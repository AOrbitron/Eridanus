"""
reply_engine.py 核心回复引擎 ——
将所有子模块串联起来，完成一次完整的拟人化回复流程

新增：
- 群聊气氛印象（group_impression）的读取与注入
- 最近发言者印象批量读取并注入 prompt
- triggered_by_llm 标记，群内 trigger_llm 触发时限制回复长度/句数
"""

import asyncio
import re
import traceback
import random
import uuid
import time

import aiohttp
from typing import Optional

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Record
from framework_common.database_util.User import get_user
from framework_common.framework_util.function_control import load_disabled
from framework_common.utils.system_logger import get_logger
from run.core_reply.service.audit_censor import AuditSystem

from run.core_reply.service.context_manager import ContextManager
from run.core_reply.service.emotion_system import EmotionSystem
from run.core_reply.service.llm_client import LLMClient
from run.core_reply.service.mcp_client import MCPManager
from run.core_reply.service.prompt_builder import PromptBuilder
from run.core_reply.service.reply_processor import ReplyProcessor
from run.core_reply.service.impression_updater import ImpressionUpdater
from run.core_reply.service.concurrency import ConcurrencyController
from run.core_reply.service.rag_memory import RAGMemory
from run.core_reply.service.message_identity import resolve_user_name

logger = get_logger(__name__)

# 不在模块级固定持有 tts_v2 的客户端实例：那样 tts_v2 热重载后，core_reply 仍握着旧实例/旧配置
# （历史 bug：“tts_v2 配置更新了，但 core_reply 这边用的还是旧变量”）。改为惰性获取——
# 每次从当前 sys.modules 取最新的 AsyncGPTSoVITSClient 类；仅当类对象本身变化（tts_v2 代码被
# 热重载）时才重建实例。配置层面再由该客户端的 property 实时读取，双重保证不会用到过期值。
_gpt_sovits_client = None
_gpt_sovits_cls = None


def _get_gpt_sovits_client():
    """惰性获取 tts_v2 客户端，兼容 tts_v2 的配置/代码热重载。失败返回 None。"""
    global _gpt_sovits_client, _gpt_sovits_cls
    try:
        from run.tts_v2.service.GPT_SoVits import AsyncGPTSoVITSClient as _Cls
    except Exception as e:
        logger.warning(f"[MaiReply] 获取 tts_v2 客户端失败: {e}")
        return None
    if _gpt_sovits_client is None or _gpt_sovits_cls is not _Cls:
        _gpt_sovits_client = _Cls()
        _gpt_sovits_cls = _Cls
    return _gpt_sovits_client


def refresh_tools():
    """在运行期新增/改动带 tool 的插件后调用：重扫 func_map 并重建已实例化 ReplyEngine 的工具缓存。

    ReplyEngine 是单例，工具在 __init__ 时缓存到 self._tools。这里先 func_map_loader.rescan()
    让新 tool 进入 func_map，再刷新单例缓存；_active_tools() 每轮已实时读取 function_control，
    故下一条对话即可用上新 tool（并可在「功能管理」里开关）。返回当前可用工具数（失败返回 -1）。
    """
    try:
        from framework_common.framework_util.func_map_loader import rescan
        rescan()
    except Exception as e:
        logger.warning(f"[MaiReply] refresh_tools: func_map rescan 失败: {e}")

    inst = ReplyEngine._instance
    if inst is None:
        return 0
    try:
        inst._tools = inst._load_tools()
        count = len(inst._tools or {})
        logger.info(f"[MaiReply] refresh_tools: 工具缓存已刷新，共 {count} 个")
        return count
    except Exception as e:
        logger.warning(f"[MaiReply] refresh_tools: 刷新工具缓存失败: {e}")
        return -1

class ReplyEngine:
    _instance = None
    _initialized = False

    def __new__(cls, config=None, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ReplyEngine, cls).__new__(cls)
        return cls._instance

    def __init__(self, config=None):
        if self._initialized:
            return

        if config is None:
            raise ValueError("首次实例化 ReplyEngine 时必须传入 config 参数！")
        self.cfg = config
        self.llm = LLMClient(config)
        self.emotion = EmotionSystem(config)
        self.context = ContextManager(config)
        self.prompt_builder = PromptBuilder(config, self.emotion)
        self.processor = ReplyProcessor(config, self.context)
        self.impression_updater = ImpressionUpdater(self.llm, self.context)
        self.concurrency = ConcurrencyController(config)
        self.audit_system = AuditSystem(self.llm, self.context, config)
        self.mcp_manager = MCPManager(config)
        self.rag_memory = RAGMemory(config)

        self._name_cache: dict[str, tuple[str, float]] = {}

        self._tools = self._load_tools()
        self._last_disabled = frozenset()  # 上次过滤所用的禁用集合，仅用于变更时打日志
        self.emotion.random_drift()
        self._initialized = True

    # --------------------------------------------------
    # 名称缓存辅助
    # --------------------------------------------------

    def _cache_get(self, key: str) -> Optional[str]:
        entry = self._name_cache.get(key)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        return None

    def _cache_set(self, key: str, value: str) -> None:
        ttl = self.cfg.core_reply.config.get("concurrency", {}).get("name_cache_ttl", 300)
        now = time.monotonic()
        if len(self._name_cache) > 5000:
            self._name_cache = {k: v for k, v in self._name_cache.items() if v[1] > now}
        self._name_cache[key] = (value, now + ttl)

    # --------------------------------------------------

    def is_master(self, user_id) -> bool:
        """检查给定 user_id 是否是系统配置的管理员/主人 (master.id)"""
        if hasattr(self, "prompt_builder") and hasattr(self.prompt_builder, "is_master"):
            return self.prompt_builder.is_master(user_id)
        if user_id is None:
            return False
        try:
            cfg = getattr(self.cfg, "common_config", None)
            basic_config = getattr(cfg, "basic_config", None) if cfg else None
            if basic_config is None and isinstance(self.cfg, dict):
                basic_config = self.cfg.get("common_config", {}).get("basic_config", {})
            if not basic_config:
                return False
            master = basic_config.get("master", {})
            if isinstance(master, dict):
                master_id = master.get("id")
            else:
                master_id = master
            if isinstance(master_id, (list, tuple, set)):
                return str(user_id) in {str(item) for item in master_id}
            return master_id is not None and str(user_id) == str(master_id)
        except Exception:
            return False

    def _load_tools(self):
        tools = {}
        try:
            if self.cfg.core_reply.config.get("llm", {}).get("func_calling", False):
                from framework_common.framework_util.func_map_loader import build_tool_map, get_tool_declarations
                funcs = build_tool_map()
                # 将 Gemini 格式的 declaration 列表转成 name -> decl 的索引
                declarations = {d["name"]: d for d in get_tool_declarations() if "name" in d}
                # 将每个工具包装为 {"func": <callable>, "declaration": <gemini_decl>}
                for name, func in funcs.items():
                    tools[name] = {
                        "func": func,
                        "declaration": declarations.get(name),  # 可能为 None（没有声明的工具）
                    }
        except Exception as e:
            traceback.print_exc()

        try:
            skill_tools = self.prompt_builder.skill_loader.get_tool_map()
            if skill_tools:
                tools.update(skill_tools)
        except Exception:
            traceback.print_exc()

        try:
            mcp_tools = self.mcp_manager.get_tool_map()
            if mcp_tools:
                tools.update(mcp_tools)
        except Exception:
            traceback.print_exc()

        if tools:
            logger.info(f"[MaiReply] 已加载函数调用工具: {list(tools.keys())}")
            return tools
        return None

    def _active_tools(self):
        """发给 LLM 前按 function_control.json 的禁用列表过滤工具。

        用时读取（mtime 缓存），因此在「函数管理」界面切换开关后，下一条对话即生效，
        无需依赖整插件热重载。
        """
        if not self._tools:
            return self._tools
        try:
            disabled = load_disabled()
        except Exception:
            return self._tools

        if not disabled:
            if self._last_disabled:
                logger.info("[MaiReply] 函数开关：已恢复全部工具")
                self._last_disabled = frozenset()
            return self._tools

        active = {k: v for k, v in self._tools.items() if k not in disabled}
        snapshot = frozenset(disabled)
        if snapshot != self._last_disabled:
            removed = [k for k in self._tools if k in disabled]
            logger.info(
                f"[MaiReply] 函数开关：已禁用 {removed}，本次可用工具 {len(active)}/{len(self._tools)}"
            )
            self._last_disabled = snapshot
        return active

    async def handle(
        self,
        bot,
        event,
        clean_text: str,
        multimodal_content=None,
        triggered_by_llm: bool = False,  # 是否由 trigger_llm 触发
        include_tools: bool = True,       # 是否注入 tools（定时任务或纯问候可设为 False 节省大量 token）
        tools_override: Optional[dict] = None,  # 自定义覆盖 tools 映射（按需仅传特定工具）
        system_prompt_prefix: Optional[str] = None,  # 前置注入的系统指令提示词（明确系统定时事件来源，防抢台词误判）
        history_user_text: Optional[str] = None,  # 可选：写入历史记录的替代文本（避免系统引导词被当成用户说话写入历史）
    ) -> None:
        is_group = isinstance(event, GroupMessageEvent) or bool(getattr(event, "group_id", None))
        group_id: Optional[int] = getattr(event, "group_id", None) if is_group else None
        user_id: int = event.user_id

        # ---------- 权限检查
        perm_cfg = self.cfg.core_reply.config.get("permission", {})
        required_level = perm_cfg.get("group_reply_level" if is_group else "private_reply_level", 0)
        if required_level > 0:
            user_info = await get_user(user_id)
            if user_info.permission < required_level:
                return

        user_name = await self._get_user_name(bot, event, user_id, group_id)
        bot_name = await self._get_bot_name(bot)

        # ---------- 消息合并窗口（多条短时消息合并为一条）
        session_key = self.context.session_key_for(group_id, user_id)
        is_multimodal = isinstance(multimodal_content, list)
        if is_multimodal:
            # 多模态消息跳过合并窗口，直接处理
            final_text = clean_text
        else:
            final_text = await self.concurrency.merge_or_process(session_key, clean_text)
            if final_text is None:
                # 被合并窗口吸收，本条消息作废（更新的消息会继续处理）
                return
            multimodal_content = final_text

        # ---------- 抢占式并发控制
        # 将当前协程包装为 Task，注册到抢占器。
        # 如果该会话已有正在处理的旧 Task，旧 Task 会被 cancel()，
        # 同时旧消息文本与新消息文本合并后作为本次实际处理内容。
        current_task = asyncio.current_task()
        final_text = await self.concurrency.preempt_and_register(
            session_key, final_text, current_task
        )

        # 【修改点 1】：修复多模态消息(带图片)时，合并后的文本没有注入到 content 列表里的问题
        if not is_multimodal:
            multimodal_content = final_text
        else:
            # 如果是多模态结构（列表），需要遍历把里面 type 为 text 的部分替换成合并后的文本
            for part in multimodal_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    part["text"] = final_text
                    break

        await self.concurrency.acquire_global()
        lock_acquired = False  # 初始化锁状态变量
        rag_active = False
        rag_turn_recorded = False
        try:
            # 【关键修复 3】：恢复被误删的 Redis 锁，防止同一个用户的上下文数据库写冲突
            lock_timeout = self.cfg.core_reply.config.get("concurrency", {}).get("lock_timeout", 30)
            lock_acquired = await self.context.acquire_lock(session_key, lock_timeout)
            if not lock_acquired:
                return

            # 被旧 Task 抢占后到这里时，如果自身已被 cancel，直接退出
            if current_task.cancelled():
                return

            if is_group:
                # 传入 user_id 以便发言者追踪
                self.context.push_group_window(group_id, user_name, final_text, user_id=user_id)

            # 提取历史对话上下文：群聊被@时精简提取少量私聊/群聊上下文（默认2-3轮），把宝贵窗口留给群公屏
            max_turns = self.cfg.core_reply.config.get("context", {}).get("max_turns", 20)
            max_history_msgs = max_turns * 2

            if is_group:
                trimmed_history = self.context.get_group_user_session_context(group_id, user_id)
            else:
                history = self.context.get_session_history(group_id, user_id)
                trimmed_history = history[-max_history_msgs:] if len(history) > max_history_msgs else list(history)

            group_context = ""
            if is_group:
                group_context = self.context.build_group_context_snippet(group_id, bot_name)

            # RAG 关闭时不执行查询/归档，也不额外读取上下文；旧记忆逻辑保持原状。
            rag_memory = ""
            knowledge_context = ""
            rag_active = self.rag_memory.allowed(group_id)
            rag_replace = rag_active and self.rag_memory.replaces_legacy
            if rag_active:
                recent_context = self.context._load_group_window(group_id) if is_group else trimmed_history
                memory_recall = self.rag_memory.recall(
                    group_id, user_id, final_text, recent_context=recent_context,
                )
                knowledge = self.rag_memory.knowledge
                if knowledge is None:
                    rag_memory = await memory_recall
                else:
                    knowledge_recall = asyncio.create_task(knowledge.recall(group_id, final_text))
                    try:
                        rag_memory = await memory_recall
                        knowledge_context = await knowledge_recall
                    finally:
                        if not knowledge_recall.done():
                            knowledge_recall.cancel()
                        await asyncio.gather(knowledge_recall, return_exceptions=True)

            # 内存模式感知：按配置动态读取用户记忆（slots / impression / both）
            user_mem_mode = self.context.get_effective_user_memory_mode() if hasattr(self.context, "get_effective_user_memory_mode") else "slots"
            user_impression = self.context.get_impression(user_id) if not rag_replace and user_mem_mode in ("impression", "both") else ""
            user_memory = self.context.get_user_memory(user_id) if not rag_replace and user_mem_mode in ("slots", "both") else ""

            # 群聊专属记忆：群聊生态特征槽位(group_slots)与群整体主观印象(group_impression)，及最近发言者记忆
            group_impression = ""
            group_slots = ""
            recent_speaker_memories = []
            if is_group and group_id and not rag_replace:
                group_mem_mode = self.context.get_effective_group_memory_mode() if hasattr(self.context, "get_effective_group_memory_mode") else "slots"
                if group_mem_mode in ("impression", "both"):
                    group_impression = self.context.get_group_impression(group_id)
                if group_mem_mode in ("slots", "both"):
                    group_slots = self.context.get_group_memory_slots(group_id)

                recent_speaker_memories = self.context.get_recent_speaker_memories(group_id, exclude_user_id=user_id)

            group_name = await self._get_group_name(bot, group_id) if is_group else "私聊"
            system_prompt = self.prompt_builder.build_system_prompt(
                bot_name=bot_name,
                user_name=user_name,
                group_name=group_name,
                group_context_snippet=group_context,
                user_impression=user_impression,
                is_group=is_group,
                triggered_by_llm=triggered_by_llm,
                group_impression=group_impression,
                recent_speaker_memories=recent_speaker_memories,
                user_text=final_text,
                global_memory=self.context.get_global_memory() if not rag_replace else "",
                user_memory=user_memory,
                group_slots=group_slots,
                rag_memory=rag_memory,
                is_master=self.is_master(user_id),
                user_id=user_id,
                knowledge_context=knowledge_context,
            )
            if system_prompt_prefix:
                system_prompt = f"{system_prompt_prefix.strip()}\n\n{system_prompt}"

            messages = trimmed_history
            user_content = multimodal_content if multimodal_content is not None else clean_text
            messages.append({"role": "user", "content": user_content})

            msg_id = getattr(event, "message_id", None)
            sent_reply_parts: list[str] = []
            sent_reply_segments: list[str] = []

            async def send_intermediate_text(text: str) -> None:
                if current_task.cancelled():
                    return
                segments = self.processor.process(text)
                if triggered_by_llm and is_group:
                    segments = self._hard_truncate_segments(segments)
                if not segments:
                    return
                quote_id = None if sent_reply_segments else msg_id
                await self.processor.send_with_delay(bot, event, segments, quote_message_id=quote_id)
                sent_reply_parts.append(text)
                sent_reply_segments.extend(segments)

            if not include_tools:
                active_tools = None
            elif tools_override is not None:
                active_tools = tools_override
            else:
                active_tools = self._active_tools()
            raw_reply = await self.llm.chat(
                messages=messages,
                system_prompt=system_prompt,
                tools=active_tools,
                bot=bot,
                event=event,
                retries=3,
                on_intermediate_text=send_intermediate_text,
            )

            # LLM 调用完成后，再次确认自己没有被更新的 Task 抢占取消
            if current_task.cancelled():
                logger.info(f"[MaiReply] 任务在 LLM 返回后被抢占，丢弃本次回复（user={user_id}）")
                return

            if not raw_reply:
                bot.logger.warning("[MaiReply] LLM 返回空回复，清理上下文后重试一次")
                retry_messages = [{"role": "user", "content": user_content}]
                raw_reply = await self.llm.chat(
                    messages=retry_messages,
                    system_prompt=system_prompt,
                    tools=active_tools,
                    bot=bot,
                    event=event,
                    retries=2,
                    on_intermediate_text=send_intermediate_text,
                )
                if not raw_reply:
                    bot.logger.warning("[MaiReply] 重试后仍为空，放弃本次回复")
                    return

            sent_prefix = "".join(sent_reply_parts)
            final_reply_text = raw_reply or ""
            remaining_reply = final_reply_text
            if sent_prefix and final_reply_text.startswith(sent_prefix):
                remaining_reply = final_reply_text[len(sent_prefix):]
            elif sent_prefix and final_reply_text.startswith(sent_prefix.strip()):
                remaining_reply = final_reply_text[len(sent_prefix.strip()):]

            segments = self.processor.process(remaining_reply)
            if not segments:
                if not sent_reply_segments:
                    return
                segments = []

            # trigger_llm 触发时在处理层也做一次硬截断保险
            if triggered_by_llm and is_group:
                segments = self._hard_truncate_segments(segments)

            if segments:
                await self.processor.send_with_delay(bot, event, segments, quote_message_id=None if sent_reply_segments else msg_id)

            # TTS
            voice_cfg = self.cfg.core_reply.config["tts"]
            voice_prob = int(voice_cfg.get("voice_reply_probability", 0))
            translate_api_key = self.cfg.core_reply.config["trigger_llm"]["api_key"]
            voice_cfg["translate_api_key"] = translate_api_key
            all_sent_segments = sent_reply_segments + segments
            if voice_prob > 0 and random.randint(1, 100) <= voice_prob:
                combined_text = ".".join(all_sent_segments)
                asyncio.create_task(self._async_tts_and_send(bot, event, combined_text, voice_cfg))

            # 更新历史（只有真正发出回复才更新，被抢占的任务不写历史）
            if history_user_text is not None:
                effective_user_text = history_user_text
            elif isinstance(multimodal_content, list):
                effective_user_text = final_text + " [含图片]" if final_text else "[图片]"
            else:
                effective_user_text = final_text

            self.context.append_to_session(group_id, user_id, effective_user_text, final_reply_text)

            if is_group:
                self.context.push_group_window(group_id, bot_name, final_reply_text)

            if rag_active:
                # 只在真实发出回复后记录完整一轮；被抢占/失败的生成不伪造 Bot 发言。
                await self.rag_memory.record_turn(
                    group_id, user_id, user_name, effective_user_text,
                    "||".join(all_sent_segments), bot_name=bot_name,
                    message_id=getattr(event, "message_id", None),
                )
                rag_turn_recorded = True

            self.impression_updater.tick(user_id, group_id, user_name, bot_name)
            self.audit_system.tick(user_id, group_id, user_name, bot_name, bot)

            # 群记忆更新 tick（有群 ID 且该群启用群记忆体系时触发）
            if is_group and group_id and self.impression_updater.is_group_memory_enabled(group_id):
                self.impression_updater.tick_group(group_id, group_name, bot_name)

            current_score = self.emotion.get_score()
            current_mood = self.emotion.get_mood()
            if user_mem_mode in ("impression", "both"):
                current_imp = user_impression or "暂无，还不熟"
            else:
                current_imp = "已关闭 (当前为 slots 槽位模式)"

            panel = (
                f"\n┌──────── MaiReply 机器人状态监控 ────────┐\n"
                f"│ 👤 交互对象: {user_name} ({user_id})\n"
                f"│ 💬 最终回复: {final_reply_text}\n"
                f"│ 📊 全局心情: {current_score}分 ({current_mood})\n"
                f"│ 🧠 对TA印象: {current_imp}\n"
                f"│ 🌐 trigger_llm: {triggered_by_llm}\n"
                f"└─────────────────────────────────────────────┘"
            )
            bot.logger.info(panel)

        except asyncio.CancelledError:
            # 被新消息抢占时正常取消，不报错
            logger.info(f"[MaiReply] 任务被新消息抢占，已取消（user={user_id}）")
            raise  # 必须重新抛出，让 asyncio 正确标记任务状态
        except Exception as e:
            bot.logger.error(f"[MaiReply] 回复出错: {e}", exc_info=True)
            traceback.print_exc()
        finally:
            if rag_active and not rag_turn_recorded:
                # 回复失败/被抢占时仍保留真实用户发言，不虚构一轮已完成对话。
                try:
                    await self.rag_memory.observe(group_id, user_id, user_name, final_text,
                                                  message_id=getattr(event, "message_id", None))
                except Exception as exc:
                    logger.warning("[MaiReply RAG] 未完成对话的用户消息缓冲失败 (%s)", type(exc).__name__)
            # 任务结束（无论正常/取消/异常）时从抢占表注销自身，并释放全局信号量
            await self.concurrency.unregister_task(session_key, current_task)
            if lock_acquired:
                self.context.release_lock(session_key)
            self.concurrency.release_global()

    def _hard_truncate_segments(self, segments: list) -> list:
        """
        trigger_llm 触发时的处理层硬截断保险。
        防止 LLM 无视 prompt 约束产生过长回复。
        """
        max_segs = self.prompt_builder.trigger_max_segments
        max_chars = self.prompt_builder.trigger_max_chars

        # 截断段数
        segments = segments[:max_segs]

        # 每段字数截断
        result = []
        total = 0
        for seg in segments:
            remaining = max_chars - total
            if remaining <= 0:
                break
            if len(seg) > remaining:
                seg = seg[:remaining].rstrip()
            result.append(seg)
            total += len(seg)

        return result

    # =================================================================
    # 后台处理语音：翻译 -> TTS 合成 -> 发送
    # =================================================================
    async def _async_tts_and_send(self, bot, event, text: str, voice_cfg: dict):
        speaker = voice_cfg.get("speaker", "natuki")
        lang_type = voice_cfg.get("lang_type", "JP")
        api_key = voice_cfg.get("translate_api_key", "")
        if not api_key:
            try:
                api_key = self.cfg.core_reply.config.get("trigger_llm", {}).get("api_key", "")
            except Exception:
                api_key = ""

        try:
            from run.tts_v2.service.tts import TTS
            tts_engine = TTS()
            bot.logger.info(f"[MaiReply] 后台语音合成启动 | speaker: {speaker} | lang: {lang_type} | text: {text[:30]}")
            audio_path = await tts_engine.tts(
                text=text,
                speaker=speaker,
                config=self.cfg,
                bot=bot,
                lang_type=lang_type,
                api_key=api_key,
            )
            if audio_path:
                await bot.send(event, Record(file=audio_path))
                bot.logger.info(f"[MaiReply] 后台语音发送完成: {audio_path}")
        except Exception as e:
            bot.logger.error(f"[MaiReply] TTS语音合成或发送失败: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # 辅助：获取用户名（带缓存）
    # ------------------------------------------------------------------
    async def _get_user_name(self, bot, event, user_id: int, group_id: Optional[int]) -> str:
        cache_key = f"user:{group_id}:{user_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        name = await resolve_user_name(bot, event, user_id, group_id)

        self._cache_set(cache_key, name)
        return name

    # ------------------------------------------------------------------
    # 辅助：获取 Bot 名称
    # ------------------------------------------------------------------
    async def _get_bot_name(self, bot) -> str:
        from framework_common.framework_util.yamlLoader import YAMLManager
        globconfig = YAMLManager.get_instance()
        bot_name = globconfig.common_config.basic_config["bot"]
        return bot_name
        try:
            info = await bot.get_login_info()
            name = (info or {}).get("nickname", "")
            name = name.strip()
        except Exception:
            name = ""
        override = self.prompt_builder.get_bot_name(name)
        return override or name or "Bot"

    # ------------------------------------------------------------------
    # 辅助：获取群名称（带缓存）
    # ------------------------------------------------------------------
    async def _get_group_name(self, bot, group_id: int) -> str:
        cache_key = f"group:{group_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            info = await bot.get_group_info(group_id=group_id)
            name = info["data"]["group_name"]
            name = name.strip() or str(group_id)
        except Exception:
            name = str(group_id)

        self._cache_set(cache_key, name)
        return name
