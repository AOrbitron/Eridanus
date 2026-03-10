import asyncio
import datetime
import random
import traceback
import base64
import io
import os
import re
import httpx
from PIL import Image as PILImage
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, At, Image
from framework_common.database_util.Group import clear_group_messages, get_last_20_and_convert_to_prompt, \
    GroupMessageManager
from framework_common.database_util.Group import get_group_messages
from framework_common.database_util.User import get_user, update_user, clear_all_user_portraits
from framework_common.database_util.llmDB import delete_user_history, clear_all_history, change_folder_chara, \
    get_folder_chara, set_all_users_chara, clear_all_users_chara, clear_user_chara, delete_latest2_history, \
    get_user_history
from framework_common.database_util.GroupSummary import (
    get_group_summary, update_group_summary, increment_group_message_count,
    clear_group_summary, should_generate_summary
)
from framework_common.framework_util.func_map_loader import build_tool_map
from framework_common.utils.GeminiKeyManager import GeminiKeyManager
from framework_common.manshuo_draw import manshuo_draw
from run.ai_llm.service.aiReplyCore import aiReplyCore, send_text, count_tokens_approximate
from run.ai_llm.service.auto_talk import check_message_similarity
from run.ai_llm.service.schemaReplyCore import schemaReplyCore
from run.ai_llm.service.utility_client import utility_request

# 图片处理相关常量和函数
BASE64_PATTERN = re.compile(r'^data:(image/\w+);base64,(.+)$')


def is_local_file_path(url: str) -> bool:
    """判断是否为本地文件路径"""
    if url.startswith("file://"):
        return True
    if os.path.isabs(url) and os.path.exists(url):
        return True
    return False


def get_local_file_path(url: str) -> str:
    """获取本地文件的实际路径"""
    if url.startswith("file://"):
        return url[7:]
    return url


async def _process_image_for_summary(url: str, client_type: str) -> dict:
    """处理图片并转换为对应client格式"""
    try:
        img_base64 = None
        base64_match = BASE64_PATTERN.match(url)
        if base64_match:
            img_base64 = base64_match.group(2)
        elif is_local_file_path(url):
            actual_path = get_local_file_path(url)
            if os.path.exists(actual_path):
                image = PILImage.open(actual_path)
                image = image.convert("RGB")
                img_byte_arr = io.BytesIO()
                quality = 85
                while True:
                    img_byte_arr.seek(0)
                    img_byte_arr.truncate()
                    image.save(img_byte_arr, format='JPEG', quality=quality)
                    if img_byte_arr.tell() / 1024 <= 400 or quality <= 10:
                        break
                    quality -= 5
                img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                image.close()
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    image = PILImage.open(io.BytesIO(res.content))
                    image = image.convert("RGB")
                    img_byte_arr = io.BytesIO()
                    quality = 85
                    while True:
                        img_byte_arr.seek(0)
                        img_byte_arr.truncate()
                        image.save(img_byte_arr, format='JPEG', quality=quality)
                        if img_byte_arr.tell() / 1024 <= 400 or quality <= 10:
                            break
                        quality -= 5
                    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    image.close()

        if not img_base64:
            return None
        if client_type == "openai":
            return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}", "detail": "auto"}}
        else:
            return {"inlineData": {"mimeType": "image/jpeg", "data": img_base64}}

    except Exception as e:
        print(f"处理图片失败: {e}")
        return None


async def _extract_images_from_messages(group_messages, client_type: str, max_images: int = 10):
    """从群消息中提取图片并转换为对应格式"""
    image_parts = []
    image_count = 0

    for msg in group_messages:
        if image_count >= max_images:
            break
        message_parts = msg.get('message', [])
        for part in message_parts:
            if image_count >= max_images:
                break
            if isinstance(part, dict):
                url = None
                # 处理 image 类型
                if part.get('type') == 'image' or 'image' in part:
                    img_data = part.get('image', part)
                    if isinstance(img_data, dict):
                        url = img_data.get('url') or img_data.get('file')
                    elif isinstance(img_data, str):
                        url = img_data
                # 处理 mface 类型（表情包）
                elif part.get('type') == 'mface' or 'mface' in part:
                    mface_data = part.get('mface', part)
                    if isinstance(mface_data, dict):
                        url = mface_data.get('url') or mface_data.get('file')

                if url:
                    try:
                        img_data = await _process_image_for_summary(url, client_type)
                        if img_data:
                            user_name = msg.get('user_name', '未知用户')
                            image_parts.append({
                                'user_name': user_name,
                                'image_data': img_data
                            })
                            image_count += 1
                    except Exception as e:
                        print(f"处理图片时出错: {e}")

    return image_parts


def main(bot, config):
    apikey_check = False
    removed_keys = []
    cleanup_tasks = {}
    if config.ai_llm.config["llm"]["func_calling"]:
        tools = build_tool_map()
    else:
        tools = None

    # 设置群消息保留数量
    group_cache_size = config.ai_llm.config["llm"].get("群消息保留数量", 100)
    GroupMessageManager().set_max_messages(group_cache_size)

    global user_state, recent_interactions
    user_state = {}
    recent_interactions = {}  # 记录最近交互的用户 {user_id: group_id}
    portrait_updating = set()  # 正在更新画像的用户集合
    summary_updating = set()  # 正在更新群总结的群组集合

    @bot.on(GroupMessageEvent)
    async def aiReply(event: GroupMessageEvent):
        await check_commands(event)

        if config.ai_llm.config["llm"].get("群聊总结", {}).get("enable", False):
            await increment_group_message_count(event.group_id)
            summary_interval = config.ai_llm.config["llm"]["群聊总结"].get("总结间隔消息数", 50)
            if await should_generate_summary(event.group_id, summary_interval):
                summary_whitelist_enabled = config.ai_llm.config["llm"]["群聊总结"].get("whitelist_enabled", False)
                summary_chat_whitelist = config.ai_llm.config["llm"]["群聊总结"].get("chat_whitelist", [])
                if summary_whitelist_enabled and event.group_id not in summary_chat_whitelist:
                    pass
                elif event.group_id not in summary_updating:
                    summary_updating.add(event.group_id)
                    asyncio.create_task(auto_generate_group_summary(event.group_id, bot, config))

        if config.ai_llm.config["heartflow"]["whitelist_enabled"]:
            if event.group_id in config.ai_llm.config["heartflow"]["chat_whitelist"]:
                if event.message_chain.has(At):
                    if event.message_chain.get(At)[0].qq in [bot.id, 1000000]:
                        pass
                    else:
                        return
                else:
                    return
        """
        原有处理逻辑
        """
        if (event.message_chain.has(At) and event.message_chain.get(At)[0].qq in [bot.id, 1000000]) or prefix_check(
                str(event.pure_text), config.ai_llm.config["llm"]["prefix"]):
            bot.logger.info(f"接受消息{event.processed_message}")

            ## 权限判断
            user_info = await get_user(event.user_id, event.sender.nickname)
            bot.logger.info(f"用户：{event.user_id} 群： {event.group_id} 权限：{user_info.permission}")
            if not user_info.permission >= config.ai_llm.config["core"]["ai_reply_group"]:
                await bot.send(event, "你没有足够的权限使用该功能~")
                return
            if event.group_id in [913122269, 1050663831] and not user_info.permission >= 66:
                # await bot.send(event,"你没有足够的权限使用该功能哦~")
                return
            if not user_info.permission >= config.ai_llm.config["core"]["ai_token_limt"]:
                if user_info.ai_token_record >= config.ai_llm.config["core"]["ai_token_limt_token"]:
                    await bot.send(event, "您的ai对话token已用完，请耐心等待下一次刷新～～")
                    return
            await handle_message(event, user_info)
        elif config.ai_llm.config["llm"]["仁济模式"]["延时相关性"]["enable"]:
            global recent_interactions
            if event.user_id in recent_interactions and recent_interactions[event.user_id] == event.group_id:
                # 使用schema判断当前消息是否与bot相关
                try:
                    # 获取更多上下文消息用于准确判断
                    group_messages_bg = await get_last_20_and_convert_to_prompt(
                        event.group_id,
                        15,  # 增加消息数量获取更好的上下文
                        "gemini",
                        bot
                    )

                    # 优化schema，增加更具体的判断标准
                    schema = {
                        "type": "object",
                        "properties": {
                            "bot_related": {
                                "type": "boolean",
                                "description": "判断用户消息是否真正需要bot回复。返回true的条件：1)直接提问或寻求帮助 2)回应bot的回复内容并期待进一步交流 3)分享观点或内容并期待反馈。返回false的条件：1)明确表达结束对话意愿(如'结束对话''不聊了''再见'等) 2)纯表情、简单应答词(如'好的''嗯''哦''知道了') 3)明显与他人对话 4)无关闲聊或测试性消息 5)礼貌性结束语"
                            },
                            "confidence": {
                                "type": "number",
                                "description": "判断的置信度，0-1之间的数值",
                                "minimum": 0,
                                "maximum": 1
                            },
                            "reason": {
                                "type": "string",
                                "description": "判断理由的简短说明"
                            }
                        },
                        "required": ["bot_related", "confidence", "reason"]
                    }

                    # 构建更详细的判断提示
                    analysis_prompt = f"""
                                分析以下情况：
                                - 当前用户消息："{event.processed_message}"
                                - 用户ID：{event.user_id}
                                - 最近群聊上下文：{group_messages_bg[-3:] if group_messages_bg else "无"}

                                请严格判断该消息是否需要bot回复。重要原则：

                                **明确不需要回复的情况(返回false)：**
                                1. 用户明确表达结束对话意愿："结束对话"、"不聊了"、"再见"、"停止"、"结束吧"等
                                2. 纯表情符号或简单应答词："好"、"嗯"、"哦"、"ok"、"知道了"、"明白"等
                                3. 明显是与其他用户对话，不是对bot说话
                                4. 无意义的闲聊、测试性消息或重复内容
                                5. 礼貌性的结束语或告别

                                **需要回复的情况(返回true)：**
                                1. 直接的问题或求助
                                2. 分享观点并明显期待回应
                                3. 对bot之前回复的有意义回应，且希望继续交流
                                4. 明确的互动请求

                                注意：如果用户说要结束对话，那就是明确的结束信号，绝对不应该继续回复！
                                """

                    result = await schemaReplyCore(
                        config,
                        schema,
                        analysis_prompt,
                        keep_history=False,
                        user_id=event.user_id,
                        group_messages_bg=group_messages_bg,
                    )

                    bot.logger.info(f"延时相关性判断结果: {result}")

                    # 增加置信度阈值和更严格的判断条件
                    confidence_threshold = config.ai_llm.config["llm"]["仁济模式"]["延时相关性"]["置信度阈值"]

                    if result["bot_related"] and result.get("confidence") >= confidence_threshold:  # 排除单字符消息

                        bot.logger.info(
                            f"延时相关性判断触发 - 消息: '{event.processed_message}' | 置信度: {result.get('confidence', 0)} | 理由: {result.get('reason', 'N/A')}")

                        # 执行权限判断
                        user_info = await get_user(event.user_id, event.sender.nickname)
                        if not user_info.permission >= config.ai_llm.config["core"]["ai_reply_group"]:
                            bot.logger.debug(f"用户 {event.user_id} 权限不足，跳过回复")
                            return

                        if event.group_id in [913122269, 1050663831] and not user_info.permission >= 66:
                            bot.logger.debug(f"特定群组 {event.group_id} 权限不足，跳过回复")
                            return

                        if not user_info.permission >= config.ai_llm.config["core"]["ai_token_limt"]:
                            if user_info.ai_token_record >= config.ai_llm.config["core"]["ai_token_limt_token"]:
                                bot.logger.debug(f"用户 {event.user_id} token限制，跳过回复")
                                return

                        await handle_message(event, user_info)
                    else:
                        bot.logger.debug(
                            f"延时相关性判断未触发 - 消息: '{event.processed_message}' | bot_related: {result['bot_related']} | 置信度: {result.get('confidence', 0)} | 理由: {result.get('reason', 'N/A')}")

                except Exception as e:
                    bot.logger.error(f"延时相关性判断出错: {e}")

        elif config.ai_llm.config["llm"]["仁济模式"]["随机回复概率"] > 0:  # 仁济模式第一层(随机)
            if random.randint(1, 100) < config.ai_llm.config["llm"]["仁济模式"]["随机回复概率"]:
                bot.logger.info(f"接受消息{event.processed_message}")

                ## 权限判断
                user_info = await get_user(event.user_id, event.sender.nickname)
                if not user_info.permission >= config.ai_llm.config["core"]["ai_reply_group"]:
                    return
                if event.group_id == 913122269 and not user_info.permission >= 66:
                    return
                if not user_info.permission >= config.ai_llm.config["core"]["ai_token_limt"]:
                    if user_info.ai_token_record >= config.ai_llm.config["core"]["ai_token_limt_token"]:
                        return
                await handle_message(event, user_info)

        elif config.ai_llm.config["llm"]["仁济模式"]["算法回复"]["enable"]:  # 仁济模式第二层(算法判断)
            sentences = await get_group_messages(event.group_id, config.ai_llm.config["llm"]["可获取的群聊上下文长度"])
            if await check_message_similarity(str(event.pure_text), sentences,
                                              similarity_threshold=config.ai_llm.config["llm"]["仁济模式"]["算法回复"][
                                                  "相似度阈值"],
                                              frequency_threshold=config.ai_llm.config["llm"]["仁济模式"]["算法回复"][
                                                  "频率阈值"],
                                              min_list_size=config.ai_llm.config["llm"]["仁济模式"]["算法回复"][
                                                  "消息列表最小长度"],
                                              entropy_threshold=config.ai_llm.config["llm"]["仁济模式"]["算法回复"][
                                                  "信息熵阈值"]):
                bot.logger.info(f"接受消息{event.processed_message}")

                ## 权限判断
                user_info = await get_user(event.user_id, event.sender.nickname)
                if not user_info.permission >= config.ai_llm.config["core"]["ai_reply_group"]:
                    return
                if event.group_id == 913122269 and not user_info.permission >= 66:
                    return
                if not user_info.permission >= config.ai_llm.config["core"]["ai_token_limt"]:
                    if user_info.ai_token_record >= config.ai_llm.config["core"]["ai_token_limt_token"]:
                        return
                await handle_message(event, user_info)

    async def handle_message(event, user_info=None):
        global user_state, recent_interactions
        # 锁机制
        uid = event.user_id
        if user_info is None:
            user_info = await get_user(event.user_id, event.sender.nickname)

        if hasattr(event, 'group_id'):
            recent_interactions[event.user_id] = event.group_id
        # 初始化该用户的状态
        if uid not in user_state:
            user_state[uid] = {
                "queue": asyncio.Queue(),
                "running": False
            }

        await user_state[uid]["queue"].put(event)

        if user_state[uid]["running"]:
            bot.logger.info(f"用户{uid}正在处理中，已放入队列")
            return

        async def process_user_queue(uid):
            """同一 uid 同时只处理一个事件，避免递归 create_task 导致并发与重复执行。"""
            user_state[uid]["running"] = True
            try:
                while True:
                    current_event = await user_state[uid]["queue"].get()
                    try:
                        reply_message = await aiReplyCore(
                            current_event.processed_message,
                            current_event.user_id,
                            config,
                            tools=tools,
                            bot=bot,
                            event=current_event,
                        )

                        if reply_message is None or '' == str(reply_message) or 'Maximum recursion depth' in str(reply_message):
                            continue

                        if "call_send_mface(summary='')" in reply_message:
                            reply_message = reply_message.replace("call_send_mface(summary='')", '')

                        try:
                            tokens_total = count_tokens_approximate(
                                current_event.processed_message[1]['text'],
                                reply_message,
                                user_info.ai_token_record
                            )
                            await update_user(user_id=current_event.user_id, ai_token_record=tokens_total)
                        except Exception:
                            pass

                        await send_text(bot, current_event, config, reply_message.strip())
                    except Exception as e:
                        bot.logger.exception(f"用户 {uid} 处理出错: {e}")
                    finally:
                        user_state[uid]["queue"].task_done()

                        async def delayed_cleanup(clean_uid):
                            await asyncio.sleep(config.ai_llm.config["llm"]["仁济模式"]["延时相关性"]["有效延时"])
                            if clean_uid in recent_interactions:
                                del recent_interactions[clean_uid]
                                bot.logger.info(f"清理用户 {clean_uid} 的延时交互记录")
                            if clean_uid in cleanup_tasks:
                                del cleanup_tasks[clean_uid]

                        if current_event.user_id in cleanup_tasks:
                            cleanup_tasks[current_event.user_id].cancel()
                        cleanup_tasks[current_event.user_id] = asyncio.create_task(delayed_cleanup(current_event.user_id))

                        """
                        总结用户特征，伪长期记忆人格
                        """
                        if config.ai_llm.config["llm"]["用户画像"] and current_event.user_id not in portrait_updating:
                            should_update = False
                            if user_info.portrait_update_time == "":
                                should_update = True
                            else:
                                try:
                                    time_diff = (datetime.datetime.now() - datetime.datetime.fromisoformat(
                                        user_info.portrait_update_time)).total_seconds()
                                    should_update = time_diff > config.ai_llm.config["llm"]["用户画像更新间隔"]
                                except Exception:
                                    should_update = True

                            if should_update:
                                portrait_updating.add(current_event.user_id)
                                try:
                                    bot.logger.info(f"更新用户 {current_event.user_id} 设定")
                                    await update_user(
                                        current_event.user_id,
                                        portrait_update_time=datetime.datetime.now().isoformat()
                                    )

                                    user_history = await get_user_history(current_event.user_id)
                                    user_messages = []
                                    for msg in user_history:
                                        if msg.get("role") == "user":
                                            if "parts" in msg:  # Gemini 格式
                                                for part in msg["parts"]:
                                                    if isinstance(part, dict) and "text" in part:
                                                        user_messages.append(part["text"])
                                            elif "content" in msg:  # OpenAI 格式
                                                content = msg["content"]
                                                if isinstance(content, str):
                                                    user_messages.append(content)
                                                elif isinstance(content, list):
                                                    for item in content:
                                                        if isinstance(item, dict) and item.get("type") == "text":
                                                            user_messages.append(item.get("text", ""))

                                    if user_messages:
                                        messages_text = "\n".join(user_messages[-20:])
                                        bot_name = config.common_config.basic_config.get("bot", "Bot")
                                        user_nickname = user_info.nickname if user_info and user_info.nickname else f"用户{current_event.user_id}"
                                        portrait_prompt = [{
                                            "text": f"以下是用户「{user_nickname}」发送的消息历史（注意：你是「{bot_name}」，请勿将bot的特征混入用户画像）：\n{messages_text}\n\n请根据以上内容总结该用户「{user_nickname}」的用户画像，包括人物性格特征、兴趣爱好、语言风格等。直接给出结果，不要回复。"
                                        }]

                                        portrait_reply = await utility_request(
                                            config,
                                            portrait_prompt,
                                            system_instruction=f"你是一个用户画像分析助手。你需要分析的是用户「{user_nickname}」，而不是bot「{bot_name}」。请根据用户的消息历史总结其特征，不要把bot的特征混入用户画像。",
                                            user_id=current_event.user_id,
                                        )

                                        if portrait_reply:
                                            await update_user(current_event.user_id, user_portrait=portrait_reply.strip())
                                            bot.logger.info(f"用户 {current_event.user_id} 画像更新成功")
                                    else:
                                        bot.logger.info(f"用户 {current_event.user_id} 没有足够的消息历史来生成画像")
                                finally:
                                    portrait_updating.discard(current_event.user_id)

                    if user_state[uid]["queue"].empty():
                        break
            finally:
                user_state[uid]["running"] = False

        asyncio.create_task(process_user_queue(uid))

    async def auto_generate_group_summary(group_id, bot, config):
        """自动生成群聊总结"""
        try:
            summary_interval = config.ai_llm.config["llm"]["群聊总结"].get("总结间隔消息数", 50)
            group_messages = await get_group_messages(group_id, summary_interval)
            if not group_messages:
                bot.logger.info(f"群 {group_id} 没有足够的消息来生成总结")
                return

            # 读取图片配置
            read_images = config.ai_llm.config["llm"]["群聊总结"].get("读取图片", False)
            utility_config = config.ai_llm.config["llm"].get("utility_client", {})
            client_type = utility_config.get("type", "gemini").strip().lower()

            # 提取文本内容
            messages_text = []
            for msg in group_messages:
                user_name = msg.get('user_name', '未知用户')
                message_parts = msg.get('message', [])
                text_content = ""
                for part in message_parts:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        text_content += part.get('text', '')
                    elif isinstance(part, dict) and 'text' in part:
                        text_content += part.get('text', '')
                if text_content.strip():
                    messages_text.append(f"{user_name}: {text_content.strip()}")

            # 处理图片（如果启用）- 移到前面，先提取图片再判断是否有内容
            image_parts = []
            if read_images:
                try:
                    image_parts = await _extract_images_from_messages(group_messages, client_type, max_images=10)
                    bot.logger.info(f"群 {group_id} 总结：提取到 {len(image_parts)} 张图片")
                except Exception as e:
                    bot.logger.warning(f"提取群消息图片失败: {e}")

            # 检查是否既没有文本也没有图片
            if not messages_text and not image_parts:
                bot.logger.info(f"群 {group_id} 消息中没有文本内容" + ("也没有图片" if read_images else ""))
                return

            # 构建提示词
            group_info = await get_group_summary(group_id)
            existing_summary = group_info.get("summary", "")

            # 根据是否有图片构建不同的提示词格式
            if image_parts:
                # 有图片时，构建多模态消息
                image_desc = "\n".join([f"- {img['user_name']} 发送了一张图片" for img in image_parts])
                if messages_text:
                    base_text = f"以下是群聊的最近消息记录：\n{chr(10).join(messages_text)}\n\n群成员分享的图片：\n{image_desc}\n\n"
                else:
                    base_text = f"群成员分享的图片：\n{image_desc}\n\n"

                if existing_summary:
                    prompt_text = f"""## 现有群聊总结（必须完整保留其中的重要信息）：
{existing_summary}

## 新增消息记录：
{base_text}

## 任务要求：
请基于现有总结进行**增量更新**，生成新版本的群聊总结。

**重要规则**：
1. 【保留历史】现有总结中的话题、参与者、重要信息点必须保留，除非明确过时或被新消息否定
2. 【累积添加】将新消息中的新话题、新参与者、新信息点追加到对应分类中
3. 【合并相似】如果新旧话题相似，合并描述而非替换
4. 【标注时效】对于有时效性的内容可标注"近期"/"早期"

**输出格式**：
1. 讨论话题（按时间/重要性排列，保留历史话题）
2. 活跃参与者（累积记录）
3. 重要信息点（新旧合并）
4. 图片内容（如有意义）

请输出完整的累积总结，可适当扩展字数以保留重要历史信息，建议300-500字。"""
                else:
                    prompt_text = f"{base_text}请对以上群聊内容和图片进行总结，包括：\n1. 主要讨论的话题\n2. 活跃的参与者\n3. 重要的信息点\n4. 图片内容描述（如有意义）\n\n请用简洁的语言总结，200-300字。"

                # 构建多模态消息格式
                if client_type == "openai":
                    summary_prompt = [{
                        "role": "user",
                        "content": [{"type": "text", "text": prompt_text}] + [img['image_data'] for img in image_parts]
                    }]
                else:  # gemini
                    parts = [{"text": prompt_text}] + [img['image_data'] for img in image_parts]
                    summary_prompt = [{"role": "user", "parts": parts}]
            else:
                # 无图片时，使用原有的简单文本格式
                if existing_summary:
                    summary_prompt = [{
                        "text": f"""## 现有群聊总结（必须完整保留其中的重要信息）：
{existing_summary}

## 新增消息记录：
{chr(10).join(messages_text)}

## 任务要求：
请基于现有总结进行**增量更新**，生成新版本的群聊总结。

**重要规则**：
1. 【保留历史】现有总结中的话题、参与者、重要信息点必须保留，除非明确过时或被新消息否定
2. 【累积添加】将新消息中的新话题、新参与者、新信息点追加到对应分类中
3. 【合并相似】如果新旧话题相似，合并描述而非替换
4. 【标注时效】对于有时效性的内容可标注"近期"/"早期"

**输出格式**：
1. 讨论话题（按时间/重要性排列，保留历史话题）
2. 活跃参与者（累积记录）
3. 重要信息点（新旧合并）

请输出完整的累积总结，可适当扩展字数以保留重要历史信息，建议300-500字。"""
                    }]
                else:
                    summary_prompt = [{
                        "text": f"以下是群聊的最近消息记录：\n{chr(10).join(messages_text)}\n\n请对以上群聊内容进行总结，包括：\n1. 主要讨论的话题\n2. 活跃的参与者\n3. 重要的信息点\n\n请用简洁的语言总结，200-300字。"
                    }]

            summary = await utility_request(
                config,
                summary_prompt,
                system_instruction="你是一个群聊总结助手，请根据群聊消息生成简洁的总结。" + (
                    "消息中包含图片，请描述图片中的重要内容。" if image_parts else ""),
                user_id=0,
            )

            if summary:
                current_count = group_info.get("message_count", 0)

                await update_group_summary(
                    group_id,
                    summary=summary.strip(),
                    last_summarized_count=current_count
                )
                bot.logger.info(f"群 {group_id} 总结自动更新成功")
        except Exception as e:
            bot.logger.error(f"自动生成群总结失败: {e}")
        finally:
            summary_updating.discard(group_id)

    async def generate_and_send_group_summary(event, bot, config):
        """生成群总结并以图片形式发送"""
        try:
            group_id = event.group_id
            group_info = await get_group_summary(group_id)
            existing_summary = group_info.get("summary", "")
            update_time = group_info.get("update_time", "")
            is_refresh = event.pure_text == "/群总结 刷新"

            # /群总结，只查看现有总结，不生成
            # /群总结 刷新，重新生成总结
            if is_refresh:
                await bot.send(event, "正在生成群聊总结，请稍候...", True)
                summary_interval = config.ai_llm.config["llm"]["群聊总结"].get("总结间隔消息数", 50)
                group_messages = await get_group_messages(group_id, summary_interval)
                if not group_messages:
                    await bot.send(event, "本群暂无足够的消息记录来生成总结", True)
                    return

                # 读取图片配置
                read_images = config.ai_llm.config["llm"]["群聊总结"].get("读取图片", False)
                utility_config = config.ai_llm.config["llm"].get("utility_client", {})
                client_type = utility_config.get("type", "gemini").strip().lower()

                # 提取文本内容
                messages_text = []
                for msg in group_messages:
                    user_name = msg.get('user_name', '未知用户')
                    message_parts = msg.get('message', [])
                    text_content = ""
                    for part in message_parts:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            text_content += part.get('text', '')
                        elif isinstance(part, dict) and 'text' in part:
                            text_content += part.get('text', '')
                    if text_content.strip():
                        messages_text.append(f"{user_name}: {text_content.strip()}")

                # 处理图片（如果启用）- 移到前面，先提取图片再判断是否有内容
                image_parts = []
                if read_images:
                    try:
                        image_parts = await _extract_images_from_messages(group_messages, client_type, max_images=10)
                        bot.logger.info(f"群 {group_id} 总结刷新：提取到 {len(image_parts)} 张图片")
                    except Exception as e:
                        bot.logger.warning(f"提取群消息图片失败: {e}")

                # 检查是否既没有文本也没有图片
                if not messages_text and not image_parts:
                    await bot.send(event, "本群消息中没有可供总结的内容" + (
                        "（文本和图片均为空）" if read_images else "（无文本内容）"), True)
                    return

                # 根据是否有图片构建不同的提示词格式
                if image_parts:
                    # 有图片时，构建多模态消息
                    image_desc = "\n".join([f"- {img['user_name']} 发送了一张图片" for img in image_parts])
                    if messages_text:
                        base_text = f"以下是群聊的最近消息记录：\n{chr(10).join(messages_text)}\n\n群成员分享的图片：\n{image_desc}\n\n"
                    else:
                        base_text = f"群成员分享的图片：\n{image_desc}\n\n"

                    if existing_summary:
                        prompt_text = f"""## 现有群聊总结（必须完整保留其中的重要信息）：
{existing_summary}

## 新增消息记录：
{base_text}

## 任务要求：
请基于现有总结进行**增量更新**，生成新版本的群聊总结。

**重要规则**：
1. 【保留历史】现有总结中的话题、参与者、重要信息点必须保留，除非明确过时或被新消息否定
2. 【累积添加】将新消息中的新话题、新参与者、新信息点追加到对应分类中
3. 【合并相似】如果新旧话题相似，合并描述而非替换
4. 【标注时效】对于有时效性的内容可标注"近期"/"早期"

**输出格式**：
1. 讨论话题（按时间/重要性排列，保留历史话题）
2. 活跃的参与者及其特点（累积记录）
3. 重要的信息点和结论（新旧合并）
4. 群聊氛围和互动情况
5. 图片内容描述（如有意义）

请用清晰的格式输出完整的累积总结，可适当扩展字数以保留重要历史信息。"""
                    else:
                        prompt_text = f"{base_text}请对以上群聊内容和图片进行详细总结，包括：\n1. 主要讨论的话题（按重要性列出）\n2. 活跃的参与者及其特点\n3. 重要的信息点和结论\n4. 群聊氛围和互动情况\n5. 图片内容描述（如有意义）\n\n请用清晰的格式总结，便于阅读。"

                    # 构建多模态消息格式
                    if client_type == "openai":
                        summary_prompt = [{
                            "role": "user",
                            "content": [{"type": "text", "text": prompt_text}] + [img['image_data'] for img in
                                                                                  image_parts]
                        }]
                    else:  # gemini
                        parts = [{"text": prompt_text}] + [img['image_data'] for img in image_parts]
                        summary_prompt = [{"role": "user", "parts": parts}]
                else:
                    # 无图片时，使用原有的简单文本格式
                    if existing_summary:
                        summary_prompt = [{
                            "text": f"""## 现有群聊总结（必须完整保留其中的重要信息）：
{existing_summary}

## 新增消息记录：
{chr(10).join(messages_text)}

## 任务要求：
请基于现有总结进行**增量更新**，生成新版本的群聊总结。

**重要规则**：
1. 【保留历史】现有总结中的话题、参与者、重要信息点必须保留，除非明确过时或被新消息否定
2. 【累积添加】将新消息中的新话题、新参与者、新信息点追加到对应分类中
3. 【合并相似】如果新旧话题相似，合并描述而非替换
4. 【标注时效】对于有时效性的内容可标注"近期"/"早期"

**输出格式**：
1. 讨论话题（按时间/重要性排列，保留历史话题）
2. 活跃的参与者及其特点（累积记录）
3. 重要的信息点和结论（新旧合并）
4. 群聊氛围和互动情况

请用清晰的格式输出完整的累积总结，可适当扩展字数以保留重要历史信息。"""
                        }]
                    else:
                        summary_prompt = [{
                            "text": f"以下是群聊的最近消息记录：\n{chr(10).join(messages_text)}\n\n请对以上群聊内容进行详细总结，包括：\n1. 主要讨论的话题（按重要性列出）\n2. 活跃的参与者及其特点\n3. 重要的信息点和结论\n4. 群聊氛围和互动情况\n\n请用清晰的格式总结，便于阅读。"
                        }]

                summary = await utility_request(
                    config,
                    summary_prompt,
                    system_instruction="你是一个群聊总结助手，请根据群聊消息生成详细且有条理的总结。" + (
                        "消息中包含图片，请描述图片中的重要内容。" if image_parts else ""),
                    user_id=event.user_id,
                )

                if summary:
                    existing_summary = summary.strip()
                    current_count = group_info.get("message_count", 0)
                    await update_group_summary(
                        group_id,
                        summary=existing_summary,
                        last_summarized_count=current_count
                    )
                    update_time = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
                else:
                    await bot.send(event, "生成群聊总结失败，请稍后重试", True)
                    return
            else:
                if not existing_summary:
                    await bot.send(event, "本群暂无总结记录，请使用 /群总结 刷新 来生成总结", True)
                    return

            formatted_date = datetime.datetime.now().strftime("%Y年%m月%d日")
            summary_lines = existing_summary.split('\n')

            draw_list = [
                {'type': 'basic_set', 'img_width': 800},
                {'type': 'avatar', 'img': [f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640"], 'upshift_extra': 15,
                 'avatar_backdrop_color': (235, 239, 253, 0),
                 'content': [f"[name]群聊总结[/name]\n[time]生成时间：{formatted_date}[/time]"]},
                f'[title]群 {group_id} 的聊天总结[/title]',
            ]
            for line in summary_lines:
                if line.strip():
                    draw_list.append(line.strip())

            if update_time:
                try:
                    if 'T' in update_time:
                        update_time_obj = datetime.datetime.fromisoformat(update_time)
                        update_time_str = update_time_obj.strftime("%Y年%m月%d日 %H:%M:%S")
                    else:
                        update_time_str = update_time
                except:
                    update_time_str = update_time
                draw_list.append(f'\n[des]上次更新时间：{update_time_str}[/des]')

            bot.logger.info('开始制作群聊总结图片')
            await bot.send(event, Image(file=(await manshuo_draw(draw_list))))

        except Exception as e:
            bot.logger.error(f"生成群总结失败: {e}")
            await bot.send(event, f"生成群聊总结失败: {str(e)}", True)

    async def check_commands(event):
        if event.message_chain.has(Text):
            t = event.message_chain.get(Text)[0].text.strip()
        else:
            t = ""

        if event.pure_text == "/clear" or t == "/clear":
            await delete_user_history(event.user_id)
            await delete_user_history(int(f"{event.user_id}1024"))
            await clear_group_messages(event.group_id)
            await update_user(event.user_id, user_portrait="默认用户")
            await update_user(event.user_id, portrait_update_time=datetime.datetime.now().isoformat())
            await bot.send(event, "历史记录已清除", True)
        elif event.pure_text == "/clear group" and event.user_id == config.common_config.basic_config["master"]["id"]:
            await clear_group_messages(event.group_id)
            await clear_group_summary(event.group_id)
            await bot.send(event, "本群消息和群总结已清除", True)
        elif event.pure_text == "/clearall" and event.user_id == config.common_config.basic_config["master"]["id"]:
            await clear_all_history()
            await clear_all_user_portraits()
            await bot.send(event, "已清理所有用户的对话记录和用户画像")
        elif event.pure_text.startswith("/clear") and event.user_id == config.common_config.basic_config["master"][
            "id"] and event.get("at"):
            target_user_id = event.get("at")[0]["qq"]
            await delete_user_history(target_user_id)
            await update_user(target_user_id, user_portrait="默认用户", portrait_update_time="")
            await bot.send(event, [Text("已清理与目标用户的对话记录和用户画像")])
        elif event.pure_text.startswith("/切人设 "):
            user_info = await get_user(event.user_id)
            if user_info.permission >= config.ai_llm.config["core"]["ai_change_character"]:
                chara_file = str(event.pure_text).replace("/切人设 ", "")
                if chara_file == "0":
                    reply = await change_folder_chara(config.ai_llm.config["llm"]["chara_file_name"], event.user_id)
                else:
                    reply = await change_folder_chara(chara_file, event.user_id)
                await bot.send(event, reply, True)
        elif event.pure_text.startswith("/全切人设 ") and event.user_id == config.common_config.basic_config["master"][
            "id"]:
            chara_file = str(event.pure_text).replace("/全切人设 ", "")
            if chara_file == "0":
                reply = await set_all_users_chara(config.ai_llm.config["llm"]["chara_file_name"])
            else:
                config.ai_llm.config["llm"]["chara_file_name"] = chara_file
                config.save_yaml("config", plugin_name="ai_llm")
                reply = await set_all_users_chara(chara_file)
            await bot.send(event, reply, True)
        elif event.pure_text == "/查人设":
            chara_file = str(event.pure_text).replace("/查人设", "")
            all_chara = await get_folder_chara()
            await bot.send(event, all_chara)
        elif event.pure_text == "/群总结" or event.pure_text == "/群总结 刷新":
            await generate_and_send_group_summary(event, bot, config)

    def prefix_check(message: str, prefix: list):
        for p in prefix:
            if message.startswith(p) and p != "":
                bot.logger.info(f"消息{message}匹配到关键词{p}")
                return True
        return False

    @bot.on(PrivateMessageEvent)
    async def aiReply(event):
        # print(event.processed_message)
        # print(event.message_id,type(event.message_id))
        if event.pure_text == "/clear":
            await delete_user_history(event.user_id)
            await bot.send(event, "历史记录已清除", True)
        elif event.pure_text == "/clearall" and event.user_id == config.common_config.basic_config["master"]["id"]:
            await clear_all_history()
            await bot.send(event, "已清理所有用户的对话记录")
        else:

            bot.logger.info(f"私聊接受消息{event.processed_message}")
            user_info = await get_user(event.user_id, event.sender.nickname)
            if not user_info.permission >= config.ai_llm.config["core"]["ai_reply_private"]:
                await bot.send(event, "你没有足够的权限使用该功能哦~")
                return
            # 锁机制
            await handle_message(event, user_info)

    @bot.on(LifecycleMetaEvent)
    async def _(event: LifecycleMetaEvent):
        nonlocal apikey_check, removed_keys
        if not apikey_check and config.ai_llm.config["llm"]["自动清理无效apikey"]:
            apikey_check = True
            while True:
                try:
                    initial_keys_from_config = config.ai_llm.config["llm"]["gemini"]["api_keys"]
                    key_manager = GeminiKeyManager(initial_api_keys=initial_keys_from_config,
                                                   check_interval_seconds=60)  # 每60秒检测一次

                    await asyncio.sleep(5)
                    bot.logger.info("\n--- 检查当前 Key 状态 ---")
                    bot.logger.info(f"可用 Key ({len(key_manager._available_keys)}个): {key_manager._available_keys}")
                    bot.logger.info(
                        f"不可用 Key ({len(key_manager._unavailable_keys)}个): {list(key_manager._unavailable_keys.keys())}")

                    for k in list(key_manager._unavailable_keys.keys()):
                        if k not in removed_keys:
                            bot.logger.info(f"已移除不可用 Key {k} 失效理由: {key_manager._unavailable_keys[k]}")
                            await bot.send_friend_message(config.common_config.basic_config["master"]["id"],
                                                          f"已自动移除不可用apikey: {k}")
                            config.ai_llm.config["llm"]["gemini"]["api_keys"].remove(k)
                            removed_keys.append(k)
                    config.save_yaml("config", plugin_name="ai_llm")
                    await asyncio.sleep(5000)
                except Exception as e:
                    bot.logger.exception(f"检查 Key 状态出错: {e}")
                    traceback.print_exc()
                    await asyncio.sleep(60)
