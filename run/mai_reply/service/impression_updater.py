# -*- coding: utf-8 -*-
"""
impression_updater.py
用户印象更新器 —— 定期用 LLM 对历史对话做增量摘要，形成跨会话的压缩记忆
- 每 N 轮触发一次，融合旧印象与新对话生成新印象
- 支持双阶段强保障：阶段1 专属 Tool Calling 抽取硬事实并维护固定槽位；阶段2 生成第一人称主观情感印象
- 印象超过字数上限时自动压缩，避免无限膨胀
- 支持群聊气氛/话题印象（group_impression），每 M 条群消息触发一次
"""

import asyncio
import json
import re
import traceback
from typing import List, Dict, Optional, Any

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.simple_chat import simplified_chat

logger = get_logger(__name__)

SUMMARY_TRIGGER_TURNS = 3   # 每聊3轮触发一次用户印象更新
IMPRESSION_MAX_CHARS = 300  # 超过此字数触发压缩

GROUP_IMP_TRIGGER_MSGS = 10  # 每累计 N 条群消息触发一次群印象更新
GROUP_IMP_MAX_CHARS = 400    # 群印象最大字数

# 阶段1：专属硬事实提取与记忆槽位维护提示词（专注 Tool Calling）
MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE = """你是一个严谨客观的事实与记忆分析专家。你的唯一职责是审查对话，提取用户【{user_name}】的硬事实，并调用工具写入对应的长期记忆槽位（1-10）。

【你和TA的最新对话记录】：
{history_text}

---
【用户 {user_name} 当前的固定硬事实槽位（1-10）】：
{user_slots_text}

---
【Bot自身当前的全局独立生活经历槽位（1-10）】：
{global_slots_text}

---
【10个记忆槽位蓝图与分类规划】：
- 槽位1 [基础个人档案]：所在地/常住城市、留学地、时区/时差（例如莫斯科UTC+3、比国内慢5小时）、学校学历（如莫大、东北师大）、年龄称谓、职业等
- 槽位2 [深度喜好偏好]：饮食口味偏好、爱吃的美食、爱玩的游戏、动漫作品、音乐等生活嗜好
- 槽位3 [雷区禁忌点]：绝对忌口的食物、反感避讳的话题、容易引起冲突的雷区
- 槽位4 [日常作息规律]：早起/熬夜作息节奏、学习/打工/工作规律与生活作息
- 槽位5 [性格特质风格]：说话风格特征、标志性口头禅、鲜明性格态度
- 槽位6 [重要人际社会]：重要亲友、宠物名字（如猫狗）、身边重要的朋友伙伴社会关系
- 槽位7 [契约约定承诺]：与Bot约定好的具体事项、承诺做到的事、共同秘密
- 槽位8-9 [重大生平里程]：过往重要生平经历与转折事件（求学、考研、就业等里程碑及时间）
- 槽位10 [近期核心焦点]：近期正全力攻关或牵挂的现实大事件（考试、面试、项目推进等）

---
【执行指令】：
1. 仔细阅读最新对话。如果对话中提到了用户【{user_name}】的客观事实（例如：在莫斯科留学、比国内慢5小时、喜欢什么、讨厌什么等），必须调用工具 `set_user_memory_slot(slot_id, content)` 写入或更新对应槽位！
   - 内容要求：纯客观、事实化、精炼准确（建议30-80字），明确包含具体事实（时间/地点/学校/时差/喜好等硬事实）。切勿抒情或写主观评价！
2. 如果旧槽位信息被明确更正或失效，调用更新覆盖或调用 `clear_user_memory_slot(slot_id)` 清空。
3. 如果对话中提及了Bot自己的独立生活事件，可调用 `set_global_memory_slot(slot_id, content)` 更新Bot全局槽位。
4. 如果审查后确认本轮对话完全没有任何新的硬事实需要记录（例如纯日常寒暄、表情包、无任何新事实），不要调用工具，直接回复【无事实更新】。
"""

# 阶段2：增量更新主观印象：融合旧印象与新对话
SUMMARY_PROMPT_TEMPLATE = """你（{bot_name}）和 {user_name} 的最新对话：

{history_text}

---
你对TA的旧印象（可能为空）：
{old_impression}

请用不超过{chars}字更新你对 {user_name} 的印象记忆。要求：
- 第一人称（"我"），带主观感情色彩。
- 记下交往中的重要事件和过程
- 当前对话的场景(如果有的话)
- 融合旧印象与新对话，重点记录：TA的性格/口癖/喜好、你们聊过的重要话题、你对TA的情感态度
- 如果旧印象和新对话矛盾，以新对话为准
- 直接输出印象文字，不要任何前缀或解释"""

# 压缩：印象过长时精简
COMPRESS_PROMPT_TEMPLATE = """以下是你（{bot_name}）对 {user_name} 积累的印象记忆（当前{char_count}字，需要压缩）：

{old_impression}

请压缩到{chars}字以内，保留最重要的性格特征、你们的关系状态和你的情感态度。直接输出压缩后的文字，不要任何前缀。"""

# 群聊气氛/话题印象更新
GROUP_IMP_PROMPT_TEMPLATE = """你（{bot_name}）正在旁观一个群聊（群名：{group_name}）。

最近的群消息片段：
{window_text}

---
你对这个群的旧印象（可能为空）：
{old_impression}

请用不超过{chars}字更新你对这个群的整体印象。要求：
- 第一人称（"我"），带主观感情色彩
- 记录：这个群最近在聊什么话题、群内的整体气氛、活跃的成员和他们的风格
- 有什么有趣的梗/黑话/群内文化需要记下来
- 融合旧印象与新消息，新的覆盖旧的
- 直接输出印象文字，不要任何前缀或解释"""

GROUP_IMP_COMPRESS_TEMPLATE = """以下是你（{bot_name}）对群【{group_name}】的印象记忆（当前{char_count}字，需要压缩）：

{old_impression}

请压缩到{chars}字以内，保留最重要的群氛围、热门话题和群内文化。直接输出压缩后的文字，不要任何前缀。"""


class ImpressionUpdater:

    def __init__(self, llm_client, context_manager):
        self._llm = llm_client
        self._ctx = context_manager
        # 用户印象计数器：counter_key -> turn_count
        self._counters: Dict[str, int] = {}
        # 群印象计数器：group_id -> msg_count
        self._group_counters: Dict[int, int] = {}

        cfg = YAMLManager.get_instance()
        ccfg = cfg.mai_reply.config.get("context", {})

        # 模型解析：优先使用配置中指定的 impression_model；留空则默认使用主 LLM 模型（具备完整工具调用能力）
        imp_model = ccfg.get("impression_model")
        if imp_model and str(imp_model).strip():
            self.model = str(imp_model).strip()
        else:
            lcfg = cfg.mai_reply.config.get("llm", {})
            provider = str(lcfg.get("provider", "openai")).lower()
            if provider == "gemini":
                self.model = lcfg.get("gemini", {}).get("model")
            else:
                self.model = lcfg.get("openai", {}).get("model")

        # trigger_llm 配置作为次级回退
        trig_cfg = cfg.mai_reply.config.get("trigger_llm", {})
        self.api_key = trig_cfg.get("api_key", "")
        self.base_url = trig_cfg.get("base_url", "")

        self.max_chars = int(ccfg.get("impression_max_chars", IMPRESSION_MAX_CHARS))
        self.group_imp_trigger: int = int(ccfg.get("group_trigger_msgs", GROUP_IMP_TRIGGER_MSGS))
        self.group_imp_max_chars: int = int(ccfg.get("group_max_chars", GROUP_IMP_MAX_CHARS))

        self.enable_group_impression: bool = ccfg.get("enable_impression", True)
        self.group_impression_ttl: int = ccfg.get("impression_ttl", 604800)
        # 构建回复时，最多读取最近 N 位发言者的 impression
        self.group_reply_impression_count: int = ccfg.get("group_reply_impression_count", 3)

    def _counter_key(self, user_id: int, group_id) -> str:
        return f"{group_id or 'priv'}:{user_id}"

    async def _call_llm(self, prompt: str, tools=None, system_prompt: Optional[str] = None) -> str:
        """统一的LLM调用入口，优先走支持 Function Calling 的 LLMClient"""
        sys_p = system_prompt or "你是一个情感与记忆管理专家，负责帮助Bot记住他人的客观事实、更新自身独立生活记忆、并提炼主观情感态度。"
        if tools:
            # 携带工具调用时，必须走支持函数调用的 LLMClient
            res = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=sys_p,
                tools=tools,
                model=self.model,
            )
            return res or ""

        if self._llm:
            res = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=sys_p,
                model=self.model,
            )
            return res or ""
        elif self.base_url:
            res = await simplified_chat(
                self.base_url,
                [{"role": "user", "content": prompt}],
                self.model,
                self.api_key,
                system_prompt=sys_p,
            )
            return res or ""
        return ""

    def _parse_and_apply_fallback_slots(self, text: str, user_id: int, user_name: str) -> bool:
        """
        容错解析器：当部分模型或中转代理未走原生 tool_calls 而是以文本/JSON/函数代码输出时，
        自动提取并写入记忆槽位，确保 100% 成功率。
        """
        if not text or not text.strip() or "无事实更新" in text:
            return False

        applied = False

        # 1. 提取 XML/函数标记 (<tool_call>, <function=...>)
        xml_matches = re.finditer(r'(?:<tool_call>|<function=(?P<fn>[\w_]+)>)(.*?)(?:</tool_call>|</function>)', text, re.DOTALL)
        for xm in xml_matches:
            fn_tag = xm.group("fn") or ""
            payload_str = (xm.group(2) or "").strip()
            try:
                d = json.loads(payload_str)
                sid = d.get("slot_id") or (d.get("parameters", {}).get("slot_id") if isinstance(d.get("parameters"), dict) else None)
                cnt = d.get("content") or (d.get("parameters", {}).get("content") if isinstance(d.get("parameters"), dict) else "")
                tname = fn_tag or str(d.get("tool", "") or d.get("name", ""))
                if sid is not None and cnt:
                    sid_int = int(sid)
                    if "global" in tname:
                        self._ctx.memory_slots.set_global_slot(sid_int, str(cnt).strip())
                    else:
                        self._ctx.memory_slots.set_user_slot(user_id, sid_int, str(cnt).strip())
                    applied = True
                    logger.info(f"[MemorySlots 容错解析] 成功从XML标记解析写入槽位: {sid_int} -> {cnt}")
            except Exception:
                pass

        # 2. 提取 Markdown 代码块中的 JSON 或原生 JSON 列表/对象
        json_blocks = re.findall(r"```(?:json)?\s*([{\[].*?[}\]])\s*```", text, re.DOTALL)
        candidates = list(json_blocks)
        bare_objs = re.findall(r'(\{[^{}]*?"slot_id"[^{}]*?\})', text, re.DOTALL)
        candidates.extend(bare_objs)
        if not candidates:
            candidates = [text.strip()]

        for block in candidates:
            block_clean = block.strip()
            try:
                data = json.loads(block_clean)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        sid = item.get("slot_id")
                        content = item.get("content")
                        tool_name = str(item.get("tool", "") or item.get("name", "") or item.get("action", ""))
                        if sid is not None:
                            try:
                                sid_int = int(sid)
                                if "clear" in tool_name:
                                    if "global" in tool_name:
                                        self._ctx.memory_slots.clear_global_slot(sid_int)
                                    else:
                                        self._ctx.memory_slots.clear_user_slot(user_id, sid_int)
                                    applied = True
                                    logger.info(f"[MemorySlots 容错解析] 成功清空槽位: {tool_name} -> {sid_int}")
                                elif content:
                                    if "global" in tool_name:
                                        self._ctx.memory_slots.set_global_slot(sid_int, str(content).strip())
                                    else:
                                        self._ctx.memory_slots.set_user_slot(user_id, sid_int, str(content).strip())
                                    applied = True
                                    logger.info(f"[MemorySlots 容错解析] 成功从JSON解析写入槽位: {sid_int} -> {content}")
                            except Exception:
                                pass
            except Exception:
                pass

        # 3. 匹配函数调用形式：set_user_memory_slot(...)
        func_matches = re.finditer(
            r'(?P<fn>set_user_memory_slot|set_global_memory_slot|clear_user_memory_slot|clear_global_memory_slot)\s*\((.*?)\)',
            text,
            re.DOTALL
        )
        for m in func_matches:
            full_fn = m.group("fn")
            args_str = m.group(2)
            sid_m = re.search(r'(?:slot_id\s*=\s*)?(\d+)', args_str)
            cnt_m = re.search(r'(?:content\s*=\s*)?["\'](.*?)["\'](?:\s*[,)]|\s*$)', args_str, re.DOTALL)
            if sid_m:
                try:
                    sid = int(sid_m.group(1))
                    cnt = cnt_m.group(1).strip() if cnt_m else ""
                    if "clear" in full_fn:
                        if "global" in full_fn:
                            self._ctx.memory_slots.clear_global_slot(sid)
                        else:
                            self._ctx.memory_slots.clear_user_slot(user_id, sid)
                        applied = True
                        logger.info(f"[MemorySlots 容错解析] 成功从函数字符串解析清空槽位: {full_fn}({sid})")
                    elif cnt:
                        if "global" in full_fn:
                            self._ctx.memory_slots.set_global_slot(sid, cnt)
                        else:
                            self._ctx.memory_slots.set_user_slot(user_id, sid, cnt)
                        applied = True
                        logger.info(f"[MemorySlots 容错解析] 成功从函数字符串解析写入槽位: {full_fn}({sid}, {cnt})")
                except Exception:
                    pass

        return applied

    async def _extract_and_update_memory_slots(
        self, user_id: int, user_name: str, history_text: str
    ) -> None:
        """阶段1：专门使用 Tool Calling 分析对话并抽取硬事实，维护固定记忆槽位"""
        try:
            tools = self._ctx.memory_slots.build_updater_tools(user_id, user_name)
            user_slots_text = self._ctx.memory_slots.format_user_slots_for_updater(user_id)
            global_slots_text = self._ctx.memory_slots.format_global_slots_for_updater()

            prompt = MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE.format(
                user_name=user_name,
                history_text=history_text,
                user_slots_text=user_slots_text,
                global_slots_text=global_slots_text,
            )

            executed_calls = []
            wrapped_tools = {}
            for tname, tdict in tools.items():
                orig_func = tdict["func"]
                decl = tdict["declaration"]

                def _bind(name, func):
                    async def wrapper(*args, **kwargs):
                        executed_calls.append((name, kwargs))
                        return await func(*args, **kwargs)
                    wrapper.__doc__ = func.__doc__
                    return wrapper

                wrapped_tools[tname] = {
                    "func": _bind(tname, orig_func),
                    "declaration": decl,
                }

            result_text = await self._call_llm(
                prompt,
                tools=wrapped_tools,
                system_prompt="你是一个严谨客观的硬事实记忆提取专家，负责提取客观事实并调用工具更新记忆槽位。切忌主观抒情。",
            )

            if executed_calls:
                logger.info(f"[MaiReply] 记忆槽位更新完成，共触发 {len(executed_calls)} 次工具调用: {[c[0] for c in executed_calls]}")
            else:
                # 若模型未触发原生 tool call，尝试从回复文本做容错解析
                if result_text:
                    parsed = self._parse_and_apply_fallback_slots(result_text, user_id, user_name)
                    if not parsed and "无事实更新" not in result_text:
                        logger.debug(f"[MaiReply] 事实槽位分析无事实更新或未触发工具: {result_text[:60]}")
        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 记忆槽位事实提取失败: {e}")

    # ------------------------------------------------------------------ 用户印象

    def tick(self, user_id: int, group_id, user_name: str, bot_name: str) -> None:
        """每次对话完成后调用，达到触发轮数时异步更新用户印象与硬事实记忆"""
        key = self._counter_key(user_id, group_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        if self._counters[key] >= SUMMARY_TRIGGER_TURNS:
            self._counters[key] = 0
            asyncio.create_task(
                self._update_impression(user_id, group_id, user_name, bot_name)
            )

    async def _update_impression(
        self, user_id: int, group_id, user_name: str, bot_name: str
    ) -> None:
        try:
            history: List[Dict] = self._ctx.get_session_history(group_id, user_id)
            if not history:
                return

            recent = history[-8:]
            lines = []
            for msg in recent:
                role = user_name if msg["role"] == "user" else bot_name
                content = msg["content"]
                if isinstance(content, list):
                    content = next((p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"), "")
                content = str(content)[:200]
                lines.append(f"{role}：{content}")
            history_text = "\n".join(lines)

            old_impression = self._ctx.get_impression(user_id) or ""

            enable_slots = getattr(self._ctx, "enable_memory_slots", False) and hasattr(self._ctx, "memory_slots")

            # 阶段 1：独立提取客观硬事实并更新记忆槽位
            if enable_slots:
                await self._extract_and_update_memory_slots(
                    user_id=user_id,
                    user_name=user_name,
                    history_text=history_text,
                )

            # 阶段 2：生成第一人称主观情感印象
            prompt = SUMMARY_PROMPT_TEMPLATE.format(
                bot_name=bot_name,
                user_name=user_name,
                history_text=history_text,
                old_impression=old_impression or "（暂无，第一次聊）",
                chars=self.max_chars,
            )

            new_impression = await self._call_llm(
                prompt,
                system_prompt="你是一个情感记忆提取器，帮助机器人记住并压缩对他人的主观印象。不加任何前缀。"
            )
            if not new_impression:
                return

            new_impression = new_impression.strip()

            if len(new_impression) > self.max_chars:
                compress_prompt = COMPRESS_PROMPT_TEMPLATE.format(
                    bot_name=bot_name,
                    user_name=user_name,
                    char_count=len(new_impression),
                    old_impression=new_impression,
                    chars=self.max_chars
                )
                compressed = await self._call_llm(compress_prompt)
                if compressed and compressed.strip():
                    new_impression = compressed.strip()

            self._ctx.update_impression(user_id, new_impression)
            logger.info(f"[MaiReply] 已更新对 {user_name}({user_id}) 的印象({len(new_impression)}字): {new_impression}")

        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 用户印象更新失败: {e}")

    # ------------------------------------------------------------------ 群聊印象

    def tick_group(self, group_id: int, group_name: str, bot_name: str) -> None:
        """
        每次有群消息进入旁观窗口时调用。
        累计到 group_imp_trigger 条时，异步触发群印象更新。
        """
        if not self.enable_group_impression:
            return
        self._group_counters[group_id] = self._group_counters.get(group_id, 0) + 1
        if self._group_counters[group_id] >= self.group_imp_trigger:
            self._group_counters[group_id] = 0
            asyncio.create_task(
                self._update_group_impression(group_id, group_name, bot_name)
            )

    async def _update_group_impression(
        self, group_id: int, group_name: str, bot_name: str
    ) -> None:
        try:
            window = self._ctx._load_group_window(group_id)
            if not window:
                return

            # 取最近 N 条窗口消息作为输入
            recent = window[-self.group_imp_trigger:]
            lines = []
            for item in recent:
                sender = item.get("sender", "?")
                text = str(item.get("text", ""))[:150]
                user_id = item.get("user_id")
                sender_label = f"{sender}（用户ID: {user_id}）" if user_id is not None else sender
                lines.append(f"{sender_label}：{text}")
            window_text = "\n".join(lines)

            old_impression = self._ctx.get_group_impression(group_id) or ""

            prompt = GROUP_IMP_PROMPT_TEMPLATE.format(
                bot_name=bot_name,
                group_name=group_name,
                window_text=window_text,
                old_impression=old_impression or "（暂无，刚开始旁观这个群）",
                chars=self.group_imp_max_chars
            )
            new_impression = await self._call_llm(prompt)
            if not new_impression:
                return

            new_impression = new_impression.strip()

            if len(new_impression) > self.group_imp_max_chars:
                compress_prompt = GROUP_IMP_COMPRESS_TEMPLATE.format(
                    bot_name=bot_name,
                    group_name=group_name,
                    char_count=len(new_impression),
                    old_impression=new_impression,
                    chars=self.group_imp_max_chars
                )
                compressed = await self._call_llm(compress_prompt)
                if compressed and compressed.strip():
                    new_impression = compressed.strip()

            self._ctx.update_group_impression(group_id, new_impression)
            logger.info(
                f"[MaiReply] 已更新群 {group_name}({group_id}) 的印象"
                f"({len(new_impression)}字): {new_impression[:80]}..."
            )

        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 群印象更新失败: {e}")
