"""
mai_reply/main.py
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

from PIL import Image as PILImage

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Text, Image, Mface, At, Reply
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import download_img, get_img
from run.mai_reply.service.gei_img_description import _resolve_images

from run.mai_reply.service.trigger import TriggerChecker
from run.mai_reply.service.reply_engine import ReplyEngine


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


async def extract_message_content(event, bot) -> tuple:
    """
    从消息链中提取文本和图片，构建 OpenAI 多模态 content 列表。
    返回 (pure_text: str, content: str | list)
    - 若无图片，content 为纯字符串（与原逻辑兼容）
    - 若含图片，content 为 list[dict]，符合 OpenAI vision 格式

    新增：自动检测消息链中的 Reply 组件，通过 bot.get_msg() 拉取被引用消息，
    提取其中的图片一并注入 content，让 LLM 能"看到"用户引用的图。
    """
    text_parts = []
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
                        text_parts.append(f"[引用消息中包含图片，url：{img_url}]")
                    except Exception:
                        text_parts.append("[引用图片获取失败]")

            except Exception:
                # 拉取引用消息失败时静默跳过，不影响主流程
                pass

    # ── 第二步：处理当前消息本身的文本和图片 ──
    for msg in event.message_chain:
        if isinstance(msg, Reply):
            continue  # 已在上方处理
        if isinstance(msg, Text):
            text_parts.append(msg.text)
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
    if not config.mai_reply.config["enable"]:
        bot.logger.warning("[MaiReply] 功能未开启。使用旧版ai对话组件")
        bot.logger.warning("[MaiReply] 如要启用新版ai对话请在配置文件中将 mai_reply.enable 设置为 true 随后重启bot")
        return
    engine = ReplyEngine(config)
    trigger = TriggerChecker(config, engine.context, engine.emotion)

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

    def context_text(event, fallback: str = "") -> str:
        """保留群聊中的 @ 目标，避免 pure_text 把所有人都当成对 bot 说话。"""
        parts = []
        chain = getattr(event, "message_chain", None)
        if chain:
            for component in chain:
                if isinstance(component, Text):
                    parts.append(component.text)
                elif isinstance(component, At):
                    target = "全体成员" if int(component.qq) == 0 else f"用户{component.name}"
                    parts.append(f"[@{target}]")
        return "".join(parts).strip() or fallback.strip()

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

        if text in ("/clearall", "清除全部对话", "清理全部对话"):
            if not is_master(event.user_id):
                return True
            count = engine.context.clear_all_sessions(group_id)
            if is_group:
                engine.context.clear_all_group_windows(group_id)
                engine.context.clear_group_impression(group_id)
                await bot.send(event, f"已清除本群 {count} 个用户的对话记录及群印象～")
            else:
                await bot.send(event, f"已清除全部 {count} 个会话记录～")
            return True

        if text in ("/initall", "初始化全部对话", "重置全部对话"):
            if not is_master(event.user_id):
                return True
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
                count = engine.context.clear_user_all_sessions(target_id)
                engine.context.clear_impression(target_id)
                await bot.send(event, f"已初始化 {target_id} 在所有群和私聊中的对话记录，共 {count} 条，并清除了用户印象～")
                return True

        return False

    @bot.on(GroupMessageEvent)
    async def handle_group(event: GroupMessageEvent):
        text = event.pure_text or ""
        message_context_text = context_text(event, text)

        # 清理指令
        if await handle_clear_command(event, is_group=True):
            return

        async def add_to_context():
            """把消息存入旁观窗口（不触发回复时仍需感知群氛围）"""
            if event.message_chain.has(Image) or event.message_chain.has(Mface):
                if (
                    config.mai_reply.config["context"]["img_context"]
                    and event.group_id in config.mai_reply.config["context"]["vision_enable_group"]
                ):
                    bot.logger.info(f"[MaiReply] 消息包含图片，且已开启图片上下文，将存入旁观窗口")
                    async def img_add_to_window():
                        img_url = await get_img(event, bot)
                        path = f"data/pictures/cache/{uuid.uuid4()}.png"
                        await download_img(img_url, path)
                        window_text = await _resolve_images(path, event.message_id)
                        engine.context.push_group_window(
                            event.group_id,
                            event.sender.nickname,
                            window_text + f"url：{img_url}",
                            user_id=event.user_id,  # ← 传入 user_id
                        )
                        engine.context._load_group_window(event.group_id)
                    asyncio.create_task(img_add_to_window())
            if text.strip():
                try:
                    user_name = event.sender.nickname
                    engine.context.push_group_window(
                        event.group_id,
                        user_name,
                        message_context_text,
                        user_id=event.user_id,  # ← 传入 user_id
                    )
                    # 群印象计数 tick（即便不回复，也感知气氛）
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
            pure_text, content = await extract_message_content(event, bot)
            clean_text = pure_text or "(艾特了你)"

        elif prefix_check(text, config.mai_reply.config["trigger"]["prefix"]):
            should_reply = True
            pure_text, content = await extract_message_content(event, bot)
            clean_text = pure_text

        else:
            if not config.mai_reply.config["trigger_llm"]["enable"]:
                await add_to_context()
                return
            ignore_prefixes = config.mai_reply.config["trigger_llm"].get("ignore_prefixes", [])
            if any(text.strip().startswith(p) for p in ignore_prefixes if p):
                await add_to_context()
                return
            if config.mai_reply.config["trigger_llm"]["whitelist_enabled"]:
                if event.group_id not in config.mai_reply.config["trigger_llm"]["whitelist"]:
                    await add_to_context()
                    return
            should_reply, clean_text = await trigger.check(
                event=event,
                bot_self_id=bot.id,
                bot_name=config.common_config.basic_config["bot"],
                pure_text=text,
            )
            pure_text, content = await extract_message_content(event, bot)
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

        if await handle_clear_command(event, is_group=False):
            return

        if not config.mai_reply.config.get("trigger", {}).get("private_trigger", True):
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
