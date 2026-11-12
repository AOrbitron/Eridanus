import re
import traceback
from typing import Optional
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Text, Record, Node
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from run.tts_v2.service.tts import (
    call_tts,
    get_all_speakers,
    get_breeze_tags,
    clone_voice,
    list_cloned_voices,
    TTS,
)


def _clean_audio_path(path_or_url: str) -> str:
    """清理音频路径或 URL 前缀"""
    if not path_or_url:
        return ""
    path_str = str(path_or_url).strip()
    if path_str.startswith("file:///"):
        return path_str[8:]
    elif path_str.startswith("file://"):
        return path_str[7:]
    return path_str


async def _extract_audio_from_event(bot: ExtendBot, event) -> Optional[str]:
    """
    从消息事件中提取音频文件路径或 URL：
    1. 优先提取当前消息中的 Record 组件；
    2. 其次提取被引用/回复的消息 (event.reply) 中的 Record 组件；
    3. 若引用消息中仅有 message_id，则通过 bot.get_msg(message_id) 提取。
    """
    # 1. 检查当前消息中是否有 Record
    if hasattr(event, "message_chain") and event.message_chain:
        try:
            records = event.message_chain.get(Record)
            if records:
                for r in records:
                    src = r.url or r.file
                    if src:
                        return _clean_audio_path(src)
        except Exception:
            pass

    # 2. 检查是否为引用/回复消息
    reply = getattr(event, "reply", None)
    if reply:
        # 2.1 检查 reply.message_chain
        if hasattr(reply, "message_chain") and reply.message_chain:
            try:
                records = reply.message_chain.get(Record)
                if records:
                    for r in records:
                        src = r.url or r.file
                        if src:
                            return _clean_audio_path(src)
            except Exception:
                pass

        # 2.2 检查 reply.message 原始字典列表
        if hasattr(reply, "message") and isinstance(reply.message, list):
            for seg in reply.message:
                if isinstance(seg, dict) and seg.get("type") == "record":
                    data = seg.get("data", {})
                    src = data.get("url") or data.get("file")
                    if src:
                        return _clean_audio_path(src)

        # 2.3 若未直接拿到组件，尝试通过 message_id 获取原消息
        reply_msg_id = getattr(reply, "message_id", None)
        if reply_msg_id:
            try:
                source_event = await bot.get_msg(reply_msg_id)
                if source_event and hasattr(source_event, "message_chain"):
                    records = source_event.message_chain.get(Record)
                    if records:
                        for r in records:
                            src = r.url or r.file
                            if src:
                                return _clean_audio_path(src)
                if source_event and hasattr(source_event, "message") and isinstance(source_event.message, list):
                    for seg in source_event.message:
                        if isinstance(seg, dict) and seg.get("type") == "record":
                            data = seg.get("data", {})
                            src = data.get("url") or data.get("file")
                            if src:
                                return _clean_audio_path(src)
            except Exception as e:
                bot.logger.debug(f"[TTS V2] get_msg 获取引用消息音频失败: {e}")

    return None


def main(bot: ExtendBot, config: YAMLManager):
    bot.logger.info("[TTS V2] 统一语音服务加载成功（包含 Breeze-TTS 2、语音克隆与表现力标签支持）")

    async def _handle_msg(event):
        raw_text = (event.pure_text or "").strip()
        if not raw_text:
            return

        # -------------------------------------------------------------
        # 1. 可用角色列表查询指令
        # -------------------------------------------------------------
        if raw_text in ["可用角色", "语音角色", "/可用角色", "/语音角色", "/speakers", "speakers"]:
            try:
                await get_all_speakers(bot, event, config)
            except Exception as e:
                bot.logger.error(f"[TTS V2] 获取可用角色失败: {e}", exc_info=True)
                await bot.send(event, Text("获取可用角色列表失败，请查看后台日志。"))
            return

        # -------------------------------------------------------------
        # 2. Breeze 表现力音频标签面板查询
        # -------------------------------------------------------------
        if raw_text in [
            "/breeze标签", "/breeze tags", "/breeze_tags", "breeze标签",
            "/语音标签", "语音标签", "/音频标签", "音频标签", "/breeze音频标签"
        ]:
            try:
                await get_breeze_tags(bot, event, config)
            except Exception as e:
                bot.logger.error(f"[TTS V2] 获取 Breeze 标签失败: {e}", exc_info=True)
                await bot.send(event, Text("获取 Breeze 音频标签面板失败，请查看后台日志。"))
            return

        # -------------------------------------------------------------
        # 3. 当前生效中的自定义语音克隆角色查询
        # -------------------------------------------------------------
        if raw_text in [
            "/克隆列表", "/克隆角色", "/临时角色", "克隆列表", "克隆角色", "临时角色",
            "/list_clones", "/clones", "/clone_list"
        ]:
            try:
                await list_cloned_voices(bot, event)
            except Exception as e:
                bot.logger.error(f"[TTS V2] 获取克隆角色列表失败: {e}", exc_info=True)
                await bot.send(event, Text("获取克隆角色列表失败，请查看后台日志。"))
            return

        # -------------------------------------------------------------
        # 4. 角色语音克隆指令触发 (/克隆语音 /语音克隆 /clone)
        # -------------------------------------------------------------
        clone_prefixes = ["/克隆语音", "/语音克隆", "/clone_voice", "/clone"]
        if any(raw_text.startswith(p) for p in clone_prefixes):
            matched_prefix = next(p for p in clone_prefixes if raw_text.startswith(p))
            cmd_body = raw_text[len(matched_prefix):].strip()
            parts = cmd_body.split()

            if not parts:
                usage_tip = (
                    "🎤 【Breeze 角色语音克隆使用指南】\n"
                    "1. 引用语音方式（推荐）：\n"
                    "   回复/引用一条语音消息，发送：/克隆语音 <角色名> <参考台词>\n"
                    "   例如：/克隆语音 刻晴 剑光如雨！\n\n"
                    "2. 附带链接方式：\n"
                    "   /克隆语音 <角色名> <音频URL或本地路径> <参考台词>\n\n"
                    "⏱️ 克隆成功后 1 小时内有效，使用 /<角色名>说 <内容> 即可发音！"
                )
                await bot.send(event, Text(usage_tip))
                return

            speaker_name = parts[0]
            audio_source = None
            ref_text = ""

            if len(parts) >= 3:
                # 三参数：/克隆语音 <角色名> <音频地址> <参考台词...>
                audio_source = parts[1]
                ref_text = " ".join(parts[2:])
            elif len(parts) == 2:
                # 两参数：/克隆语音 <角色名> <参考台词> (从引用消息或当前消息提取音频)
                ref_text = parts[1]
                audio_source = await _extract_audio_from_event(bot, event)
            elif len(parts) == 1:
                # 仅传了角色名，检查是否有引用音频
                audio_source = await _extract_audio_from_event(bot, event)

            if not audio_source:
                await bot.send(event, Text("❌ 未检测到参考音频！请在回复/引用语音消息时发送指令，或直接附带音频链接。\n格式：/克隆语音 <角色名> <参考台词>"))
                return

            if not ref_text:
                await bot.send(event, Text("❌ 缺少参考音频台词 (ref_text)！语音模型需要参考台词进行音素对齐。\n格式：/克隆语音 <角色名> <参考台词>"))
                return

            await bot.send(event, Text(f"⏳ 正在提取并克隆【{speaker_name}】的声线，请稍候..."))
            await clone_voice(
                speaker_name=speaker_name,
                audio_url_or_path=audio_source,
                ref_text=ref_text,
                user_id=getattr(event, "user_id", 0),
                bot=bot,
                event=event,
                config=config,
            )
            return

        # -------------------------------------------------------------
        # 5. 指令模式 A：带语气指导语 (instruction) 的纯指令触发
        # 语法：/角色名 <指导语> 说 <待发音文本>
        # 例如：/breeze 说话轻柔温和，略带怀念与感伤 说 我喜欢那些讲师温柔却难懂的课
        # 例如：/达妮娅 略带娇嗔 说 漂泊者，你就一点也不想着我吗？
        # 例如：/自定义角色 语气庄重 说 契约既成，食言者当受食岩之罚。
        # -------------------------------------------------------------
        pattern_instruct = re.match(r"^/(\S+)\s+(.+?)\s+说\s+(.+)$", raw_text, re.DOTALL)
        if pattern_instruct:
            speaker = pattern_instruct.group(1).strip()
            instruction = pattern_instruct.group(2).strip()
            tts_text = pattern_instruct.group(3).strip()

            mode = None
            if speaker.lower() in ["breeze", "breeze-tts", "breeze_tts"]:
                speaker = "达妮娅"
                mode = "breeze_tts"

            try:
                bot.logger.info(f"[TTS V2] 收到带指导语语音请求: speaker={speaker}, instruction={instruction}, text={tts_text[:30]}")
                res = await call_tts(
                    bot, event, config, tts_text,
                    speaker=speaker,
                    instruction=instruction,
                    mode=mode,
                )
                if res.get("status") != "success":
                    error_msg = res.get("error", "未知错误")
                    bot.logger.warning(f"[TTS V2] 语音合成失败: {error_msg}")
                    await bot.send(event, Text(f"语音合成失败: {error_msg}"))
            except Exception as e:
                bot.logger.error(f"[TTS V2] 处理语音请求异常: {e}", exc_info=True)
                await bot.send(event, Text(f"处理语音请求异常: {e}"))
            return

        # -------------------------------------------------------------
        # 6. 指令模式 B：标准 /角色名说<内容> 语法触发
        # 例如：/natuki说早上好
        # 例如：/达妮娅说[叹气]漂泊者，你就一点也不想着我吗？
        # 例如：/breeze说今天天气真好呀
        # 例如：/克隆角色名说你好
        # -------------------------------------------------------------
        pattern_standard = re.match(r"^/(\S+?)说\s*(.+)$", raw_text, re.DOTALL)
        if pattern_standard:
            speaker_candidate = pattern_standard.group(1).strip()
            tts_text = pattern_standard.group(2).strip()

            if not tts_text:
                await bot.send(event, Text("请输入要说的内容，例如：/达妮娅说早上好"))
                return

            mode = None
            if speaker_candidate.lower() in ["breeze", "breeze-tts", "breeze_tts"]:
                speaker_candidate = "达妮娅"
                mode = "breeze_tts"

            try:
                bot.logger.info(f"[TTS V2] 收到标准语音请求: speaker={speaker_candidate}, text={tts_text[:30]}")
                res = await call_tts(
                    bot, event, config, tts_text,
                    speaker=speaker_candidate,
                    mode=mode,
                )
                if res.get("status") != "success":
                    error_msg = res.get("error", "未知错误")
                    bot.logger.warning(f"[TTS V2] 语音合成失败: {error_msg}")
                    await bot.send(event, Text(f"语音合成失败: {error_msg}"))
            except Exception as e:
                bot.logger.error(f"[TTS V2] 处理标准语音请求异常: {e}", exc_info=True)
                await bot.send(event, Text(f"处理语音请求异常: {e}"))
            return

        # -------------------------------------------------------------
        # 7. 指令模式 C：纯 /breeze <文本> 快捷语音朗读
        # 例如：/breeze 我喜欢温暖的甜甜的食物，还有那些不知所云的参考书籍。
        # -------------------------------------------------------------
        if raw_text.startswith(("/breeze ", "/breeze-tts ")):
            tts_text = re.sub(r"^/(breeze|breeze-tts)\s+", "", raw_text).strip()
            if tts_text:
                try:
                    bot.logger.info(f"[TTS V2] 收到 /breeze 快捷语音请求: text={tts_text[:30]}")
                    res = await call_tts(
                        bot, event, config, tts_text,
                        speaker="达妮娅",
                        mode="breeze_tts",
                    )
                    if res.get("status") != "success":
                        error_msg = res.get("error", "未知错误")
                        bot.logger.warning(f"[TTS V2] 语音合成失败: {error_msg}")
                        await bot.send(event, Text(f"语音合成失败: {error_msg}"))
                except Exception as e:
                    bot.logger.error(f"[TTS V2] 处理 /breeze 语音请求异常: {e}", exc_info=True)
                    await bot.send(event, Text(f"处理语音请求异常: {e}"))
                return

    @bot.on(GroupMessageEvent)
    async def handle_group(event: GroupMessageEvent):
        await _handle_msg(event)

    @bot.on(PrivateMessageEvent)
    async def handle_private(event: PrivateMessageEvent):
        await _handle_msg(event)