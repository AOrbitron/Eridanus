"""
core_reply/main.py
MaiReply 插件主入口

设计理念源自 MaiBot：
  "最像，而不是最好"
  不追求完美，追求真实。
  bot不是工具，她只是在这里，和大家一起聊天。

功能：
  - 高拟人化 AI 群聊/私聊回复
  - 情绪系统（随时间自然波动）
  - 多会话上下文记忆（Redis 存储）
  - 群聊旁观上下文感知
  - 跨会话用户印象记忆
  - 群聊气氛/话题印象（group_impression）
  - 群内回复时注入最近发言者 impression
  - trigger_llm 触发的回复严格限制长度/句数
  - 消息分割+打字延迟模拟
  - 错字生成
  - 概率触发 + focus持续对话
  - 高并发安全（信号量 + 会话锁 + 消息合并）
  - /clear 清除当前会话，/init 清除指定用户的全局会话
  - 函数调用（兼容 Eridanus func_calling 体系）
"""

import asyncio
import base64
import io
import re
import uuid
from framework_common.database_util.User import get_users_with_permission_above
from run.core_reply.service.proactive_service import ProactiveService
from run.core_reply.service.follow_up_service import FollowUpService
from run.core_reply.service.proactive import build_proactive_prompt, should_proactively_message

from PIL import Image as PILImage

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, LifecycleMetaEvent, Sender
from developTools.message.message_components import Text, Image, Mface, At, Reply
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import download_img, get_img

from run.core_reply.service.trigger import TriggerChecker
from run.core_reply.service.message_identity import resolve_message_text, sender_display_name
from run.core_reply.service.reply_engine import ReplyEngine


def compress_image_to_b64(file_path: str, quality: int = 70) -> str:
    """
    将本地图片用 Pillow 压缩后返回 JPEG base64 字符串。
    统一转 RGB（兼容 PNG 透明通道），quality 控制压缩质量（0-95）。
    """
    with PILImage.open(file_path) as img:
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


async def extract_message_content(event, bot, message_text=None) -> tuple:
    """
    从消息链中提取文本和图片，构建 OpenAI 多模态 content 列表。
    返回 (pure_text: str, content: str | list)
    - 若无图片，content 为纯字符串（与原逻辑兼容）
    - 若含图片，content 为 list[dict]，符合 OpenAI vision 格式

    新增：自动检测消息链中的 Reply 组件，通过 bot.get_msg() 拉取被引用消息，
    提取其中的图片一并注入 content，让 LLM 能"看到"用户引用的图。
    """
    resolved_text = message_text if message_text is not None else await resolve_message_text(event, bot)
    text_parts = [resolved_text] if resolved_text else []
    image_items = []

    # ── 第一步：检测 Reply 组件，拉取被引用消息中的图片 ──
    for msg in event.message_chain:
        if isinstance(msg, Reply):
            try:
                quoted_msg = await bot.get_msg(int(msg.id))
                # get_msg 通常返回 {"data": {"message": [...], ...}} 或直接返回事件对象
                # 兼容两种结构
                quoted_chain = None
                if isinstance(quoted_msg, dict):
                    quoted_chain = quoted_msg.get("data", {}).get("message") or quoted_msg.get("message")
                elif hasattr(quoted_msg, "message_chain"):
                    quoted_chain = quoted_msg.message_chain
                elif hasattr(quoted_msg, "message"):
                    quoted_chain = quoted_msg.message

                if not quoted_chain:
                    continue

                # 遍历引用消息的组件，只摘取图片
                for qmsg in quoted_chain:
                    # 兼容组件对象和原始 dict 两种格式
                    if isinstance(qmsg, (Image, Mface)):
                        img_url = getattr(qmsg, "url", None) or getattr(qmsg, "file", None)
                    elif isinstance(qmsg, dict):
                        qtype = qmsg.get("type", "")
                        if qtype in ("image", "mface"):
                            data = qmsg.get("data", {})
                            img_url = data.get("url") or data.get("file")
                        else:
                            continue
                    else:
                        continue

                    if not img_url:
                        continue

                    try:
                        q_path = f"data/pictures/cache/{uuid.uuid4()}.png"
                        await download_img(img_url, q_path)
                        b64 = compress_image_to_b64(q_path)
                        image_items.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                        })
                        #text_parts.append(f"[引用消息中包含图片，url：{img_url}]")
                    except Exception:
                        text_parts.append("[引用图片获取失败]")

            except Exception:
                # 拉取引用消息失败时静默跳过，不影响主流程
                pass

    # ── 第二步：处理当前消息本身的文本和图片 ──
    for msg in event.message_chain:
        if isinstance(msg, Reply):
            continue  # 已在上方处理
        if isinstance(msg, (Text, At)):
            continue  # 文本和艾特身份已统一解析，避免重复追加
        elif isinstance(msg, (Image, Mface)):
            try:
                url = await get_img(event, bot)
                path = f"data/pictures/cache/{uuid.uuid4()}.png"
                await download_img(url, path)
                b64 = compress_image_to_b64(path)
                image_items.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
                text_parts.append(f"图片url为{url}")
            except Exception:
                text_parts.append("[图片获取失败]")

    pure_text = "".join(text_parts).strip()

    if not image_items:
        return pure_text, pure_text

    content = []
    if pure_text:
        content.append({"type": "text", "text": pure_text})
    else:
        content.append({"type": "text", "text": "(发送了图片)"})
    content.extend(image_items)

    return pure_text, content


def main(bot: ExtendBot, config: YAMLManager):
    if not config.core_reply.config["enable"]:
        bot.logger.warning("[MaiReply] 功能未开启。使用旧版ai对话组件")
        bot.logger.warning("[MaiReply] 如要启用新版ai对话请在配置文件中将 core_reply.enable 设置为 true 随后重启bot")
        return
    engine = ReplyEngine(config)
    trigger = TriggerChecker(config, engine.context, engine.emotion)
    proactive_service = ProactiveService(engine)
    follow_up_service = FollowUpService(engine)
    proactive_running = False

    async def proactive_loop():
        nonlocal proactive_running
        if proactive_running:
            return
        proactive_running = True
        try:
            while True:
                cfg = proactive_service.get_proactive_config()
                if cfg.get("enable", False):
                    await proactive_service.run_scan_round(bot)
                interval_min = int(cfg.get("scan_interval_minutes") or cfg.get("interval_minutes", 30))
                await asyncio.sleep(max(interval_min, 1) * 60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            bot.logger.error(f"MaiReply proactive loop stopped: {exc}", exc_info=True)
        finally:
            proactive_running = False
    proactive_task = None
    follow_up_task = None

    @bot.on(LifecycleMetaEvent)
    async def start_proactive_loop(_event):
        nonlocal proactive_task, follow_up_task
        if engine.rag_memory.enable:
            engine.rag_memory.start()
        if proactive_task is None or proactive_task.done():
            proactive_task = asyncio.create_task(proactive_loop(), name="mai-reply-proactive")
        if follow_up_task is None or follow_up_task.done():
            follow_up_task = asyncio.create_task(follow_up_service.start_loop(bot), name="mai-reply-follow-up")
    bot.logger.info("[MaiReply] 高拟人化AI回复插件已加载")

    def is_master(user_id: int) -> bool:
        master = config.common_config.basic_config["master"]["id"]
        if isinstance(master, (list, tuple, set)):
            return str(user_id) in {str(item) for item in master}
        return str(user_id) == str(master)

    def get_command_text(event) -> str:
        if getattr(event, "message_chain", None) and event.message_chain.has(Text):
            return "".join(msg.text for msg in event.message_chain.get(Text)).strip()
        return (event.pure_text or "").strip()

    def parse_clear_target(event, command: str) -> int | None:
        if getattr(event, "message_chain", None) and event.message_chain.has(At):
            target = int(event.message_chain.get(At)[0].qq)
            if target != 0:
                return target

        text = get_command_text(event)
        patterns = [
            rf"^{re.escape(command)}\s+(\d{{5,12}})\s*$",
            rf"^{re.escape(command)}(\d{{5,12}})\s*$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def has_at_target(event) -> bool:
        if not getattr(event, "message_chain", None) or not event.message_chain.has(At):
            return False
        return int(event.message_chain.get(At)[0].qq) != 0

    def command_matches(text: str, command: str, has_at_target: bool) -> bool:
        if text == command or text.startswith(command + " "):
            return True
        if not has_at_target or not text.startswith(command):
            return False

        suffix = text[len(command):]
        if command == "/clear" and suffix.startswith("all"):
            return False
        if command == "/init" and suffix.startswith("all"):
            return False
        return True

    async def handle_clear_command(event, is_group: bool) -> bool:
        text = get_command_text(event)
        group_id = getattr(event, "group_id", None) if is_group else None
        has_target_at = has_at_target(event)

        # RAG 删除独立于旧记忆；群管理员只能清理当前群，用户可删除自己的私聊记忆。
        if text == "/clearrag" or text == "清除RAG记忆":
            if is_group:
                role = getattr(event, "permission", None) or getattr(getattr(event, "sender", None), "role", None)
                if not is_master(event.user_id) and role not in ("ADMINISTRATOR", "OWNER", "admin", "owner"):
                    await bot.send(event, "只有管理员或主人可以清空本群的RAG记忆。")
                    return True
            count = await engine.rag_memory.clear(group_id=group_id, user_id=event.user_id)
            await bot.send(event, f"已清除{'本群' if is_group else '你的私聊'}RAG记忆，共 {count} 条。")
            return True

        if text in ("/clearall", "清除全部对话", "清理全部对话"):
            if not is_master(event.user_id):
                return True
            follow_up_service.reset_all()
            count = engine.context.clear_all_sessions(group_id)
            if is_group:
                engine.context.clear_all_group_windows(group_id)
                engine.context.clear_group_impression(group_id)
                engine.context.clear_group_memory_slots(group_id)
                await bot.send(event, f"已清除本群 {count} 个用户的对话记录及群印象～")
            else:
                await bot.send(event, f"已清除全部 {count} 个会话记录～")
            return True

        if text in ("/initall", "初始化全部对话", "重置全部对话"):
            if not is_master(event.user_id):
                return True
            follow_up_service.reset_all()
            session_count = engine.context.clear_all_sessions()
            window_count = engine.context.clear_all_group_windows()
            user_imp_count = engine.context.clear_all_user_impressions()
            group_imp_count = engine.context.clear_all_group_impressions()
            await bot.send(
                event,
                f"已初始化全部记录：会话 {session_count} 条，群窗口 {window_count} 条，用户印象 {user_imp_count} 条，群印象 {group_imp_count} 条～",
            )
            return True

        clear_aliases = ("/clear", "清除对话", "清理对话")
        init_aliases = ("/init", "初始化对话", "重置对话")

        for command in clear_aliases:
            if command_matches(text, command, has_target_at):
                parsed_target_id = parse_clear_target(event, command)
                target_id = parsed_target_id or event.user_id
                if target_id != event.user_id and not is_master(event.user_id):
                    return True
                follow_up_service.reset_user(target_id)
                engine.context.clear_session(group_id, target_id)
                engine.context.clear_impression(target_id)
                if is_group:
                    await bot.send(event, f"已清除 {target_id} 在本群的对话记录和印象～")
                else:
                    await bot.send(event, "好，忘掉了～" if target_id == event.user_id else f"已清除 {target_id} 的私聊记录和印象～")
                return True

        for command in init_aliases:
            if command_matches(text, command, has_target_at):
                parsed_target_id = parse_clear_target(event, command)
                target_id = parsed_target_id or event.user_id
                if target_id != event.user_id and not is_master(event.user_id):
                    return True
                follow_up_service.reset_user(target_id)
                count = engine.context.clear_user_all_sessions(target_id)
                engine.context.clear_impression(target_id)
                await bot.send(event, f"已初始化 {target_id} 在所有群和私聊中的对话记录，共 {count} 条，并清除了用户印象～")
                return True

        # ── 长期固定事实记忆与全局生活记忆管理指令 ──
        show_mem_aliases = ("/showmemory", "/查看记忆", "查看记忆")
        for command in show_mem_aliases:
            if command_matches(text, command, has_target_at):
                parsed_target_id = parse_clear_target(event, command)
                target_id = parsed_target_id or event.user_id
                if target_id != event.user_id and not is_master(event.user_id):
                    return True
                if not getattr(engine.context, "enable_memory_slots", False):
                    await bot.send(event, "结构化记忆槽位功能当前未开启～")
                    return True
                mem = engine.context.get_user_memory(target_id)
                if not mem:
                    await bot.send(event, f"目前尚未记录 {target_id} 的固定事实记忆～")
                else:
                    await bot.send(event, f"【{target_id} 的长期事实记忆槽位】\n{mem}")
                return True

        clear_mem_aliases = ("/clearmemory", "/清除记忆", "清除记忆")
        for command in clear_mem_aliases:
            if command_matches(text, command, has_target_at):
                parsed_target_id = parse_clear_target(event, command)
                target_id = parsed_target_id or event.user_id
                if target_id != event.user_id and not is_master(event.user_id):
                    return True
                count = engine.context.clear_user_memory_slots(target_id)
                await bot.send(event, f"已清空 {target_id} 的全部事实记忆槽位（共清除 {count} 条）～")
                return True

        if text in ("/showglobalmemory", "/查看全局记忆", "查看全局记忆"):
            if not is_master(event.user_id):
                return True
            gmem = engine.context.get_global_memory()
            if not gmem:
                await bot.send(event, "目前暂无Bot全局生活记忆记录～")
            else:
                await bot.send(event, f"【Bot全局生活与经历记忆】\n{gmem}")
            return True

        if text in ("/clearglobalmemory", "/清除全局记忆", "清除全局记忆"):
            if not is_master(event.user_id):
                return True
            engine.context.clear_global_memory()
            await bot.send(event, "已清空Bot全局生活与经历记忆～")
            return True

                # ─── 群生态记忆槽位与群印象指令 ───
        show_group_mem_aliases = ("/showgroupmemory", "/查看群记忆", "查看群记忆", "#查看群记忆")
        for command in show_group_mem_aliases:
            if command_matches(text, command, has_target_at):
                target_gid = parse_clear_target(event, command) or (group_id if is_group else None)
                if not target_gid:
                    await bot.send(event, "请在群内使用该命令，或提供群号：/showgroupmemory [群号]")
                    return True
                slots_text = engine.context.get_group_memory_slots(target_gid)
                imp_text = engine.context.get_group_impression(target_gid)
                parts = []
                if slots_text:
                    parts.append(f"【群 {target_gid} 专属生态槽位记忆（10个槽位）】：\n{slots_text}")
                if imp_text:
                    parts.append(f"【群 {target_gid} 整体主观印象】：\n{imp_text}")
                if not parts:
                    await bot.send(event, f"目前尚未记录群 {target_gid} 的专属生态记忆或群印象。")
                else:
                    await bot.send(event, "\n\n".join(parts))
                return True

        clear_group_mem_aliases = ("/cleargroupmemory", "/清空群记忆", "清空群记忆", "#清空群记忆")
        for command in clear_group_mem_aliases:
            if command_matches(text, command, has_target_at):
                target_gid = parse_clear_target(event, command) or (group_id if is_group else None)
                if not target_gid:
                    await bot.send(event, "请在群内使用该命令，或提供群号：/cleargroupmemory [群号]")
                    return True
                sender_role = getattr(event, "permission", None) or getattr(getattr(event, "sender", None), "role", None)
                is_admin = sender_role in ("ADMINISTRATOR", "OWNER", "admin", "owner")
                if not is_master(event.user_id) and not is_admin:
                    await bot.send(event, "只有管理员或主人可以清空群记忆哦。")
                    return True
                slot_cnt = engine.context.clear_group_memory_slots(target_gid)
                engine.context.clear_group_impression(target_gid)
                await bot.send(event, f"已清空群 {target_gid} 的生态槽位记忆（共 {slot_cnt} 个）及群整体印象。")
                return True

        return False

    @bot.on(GroupMessageEvent)
    async def handle_group(event: GroupMessageEvent):
        text = event.pure_text or ""
        message_context_text = await resolve_message_text(
            event, bot, config.common_config.basic_config["bot"])

        # 清理指令
        if await handle_clear_command(event, is_group=True):
            return

        async def add_to_context():
            """把消息存入旁观窗口（不触发回复时仍需感知群氛围）"""
            if message_context_text.strip():
                try:
                    user_name = sender_display_name(event)
                    engine.context.push_group_window(
                        event.group_id,
                        user_name,
                        message_context_text,
                        user_id=event.user_id,  # ← 传入 user_id
                    )
                    if (engine.rag_memory.allowed(event.group_id)
                            and engine.rag_memory.cfg.get("group", {}).get("observe_untriggered", True)):
                        await engine.rag_memory.observe(
                            event.group_id, event.user_id, user_name, message_context_text,
                            message_id=getattr(event, "message_id", None),
                        )
                    # 只有在群记忆启用且该群允许时，才进行群记忆 tick
                    if engine.impression_updater.is_group_memory_enabled(event.group_id):
                        group_name_hint = str(event.group_id)  # 此处无法拿到群名，用 group_id 代替
                        bot_name_hint = config.common_config.basic_config["bot"]
                        engine.impression_updater.tick_group(
                            event.group_id, group_name_hint, bot_name_hint
                        )
                except Exception:
                    pass

        # ------------------------------------------------------------------ 触发判断
        triggered_by_llm = False  # 标记是否由 trigger_llm 语义判断触发

        if trigger._has_at(event, bot.id):
            should_reply = True
            pure_text, content = await extract_message_content(event, bot, message_text=message_context_text)
            clean_text = pure_text or "(艾特了你)"

        elif prefix_check(text, config.core_reply.config["trigger"]["prefix"]):
            should_reply = True
            pure_text, content = await extract_message_content(event, bot, message_text=message_context_text)
            clean_text = pure_text

        else:
            if not config.core_reply.config["trigger_llm"]["enable"]:
                await add_to_context()
                return
            ignore_prefixes = config.core_reply.config["trigger_llm"].get("ignore_prefixes", [])
            if any(text.strip().startswith(p) for p in ignore_prefixes if p):
                await add_to_context()
                return
            if config.core_reply.config["trigger_llm"]["whitelist_enabled"]:
                if event.group_id not in config.core_reply.config["trigger_llm"]["whitelist"]:
                    await add_to_context()
                    return
            should_reply, clean_text = await trigger.check(
                event=event,
                bot_self_id=bot.id,
                bot_name=config.common_config.basic_config["bot"],
                pure_text=text,
                message_text=message_context_text,
            )
            pure_text, content = await extract_message_content(event, bot, message_text=message_context_text)
            if should_reply:
                triggered_by_llm = True  # ← 由 LLM 语义触发，需严格限制回复长度

        bot.logger.info(
            f"[MaiReply] trigger={should_reply} triggered_by_llm={triggered_by_llm} "
            f"self_id={bot.id} text={clean_text}"
        )

        if not should_reply:
            await add_to_context()
            return

        # 异步处理，传入 triggered_by_llm 标记
        asyncio.create_task(
            engine.handle(
                bot, event, clean_text,
                multimodal_content=content,
                triggered_by_llm=triggered_by_llm,
            )
        )

    # ------------------------------------------------------------------ 私聊消息处理
    @bot.on(PrivateMessageEvent)
    async def handle_private(event: PrivateMessageEvent):
        text = event.pure_text or ""
        follow_up_service.reset_user(event.user_id)

        if await handle_clear_command(event, is_group=False):
            return

        if not config.core_reply.config.get("trigger", {}).get("private_trigger", True):
            return

        pure_text, content = await extract_message_content(event, bot)
        # 私聊不传 triggered_by_llm，不限制长度
        asyncio.create_task(engine.handle(bot, event, pure_text or text, multimodal_content=content))

    def prefix_check(message: str, prefix: list):
        for p in prefix:
            if message.startswith(p) and p != "":
                bot.logger.info(f"[MaiReply] 消息以触发前缀 {p} 开头，强制触发")
                return True
        return False
