import traceback

import aiofiles
import httpx
import os
import asyncio
from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Image, Text, Mface
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import get_img, download_img
from run.ai_generated_art.function_collection import text2img
from run.ai_generated_art.gptimage2_meme_generator import download_img_from_url


# 假设这个函数已经在别处定义好
# from run.ai_generated_art.function_collection import gptimage2_text2img, image_edit

def main(bot: ExtendBot, config: YAMLManager):
    # 存储格式: {user_id: {"image": [path1, path2], "text": [prompt1, prompt2]}}
    user_dict = {}
    bot_name=config.common_config.basic_config["bot"]

    @bot.on(GroupMessageEvent)
    async def handle_group_message(event: GroupMessageEvent):
        nonlocal user_dict
        uid = event.user_id

        # 1. 基础生图指令
        if event.pure_text.startswith("/gpt"):
            prompt = event.pure_text.replace("/gpt", "", 1).strip()
            # 假设 gptimage2_text2img 是异步的
            await bot.send(event, "正在生成图片，请稍候...")

            asyncio.create_task(
                text2img(bot, event, config, prompt, True if bot_name in prompt else False)
            )
            return
        elif event.pure_text.startswith("/生图"):
            prompt= event.pure_text.replace("/生图","",1).strip()
            await bot.send(event, "正在生成图片，请稍候...")
            asyncio.create_task(
                text2img(bot, event, config, prompt, True if bot_name in prompt else False)
            )
            return
        # 2. 进入编辑模式
        if event.pure_text == "/图像编辑":
            user_dict[uid] = {"image": [], "text": []}
            await bot.send(event, "进入添加模式，请发送文本描述和图像（可多张）\n全部发送完成后，请发送 /end 提交任务")
            return

        # 3. 提交任务
        elif event.pure_text == "/end":
            if uid not in user_dict or (not user_dict[uid]["image"] and not user_dict[uid]["text"]):
                #await bot.send(event, "你还没有添加任何内容哦。")
                return

            await bot.send(event, "正在处理图片，请稍候...")

            # 整合 Prompt（将多次发送的文本合并）
            full_prompt = " ".join(user_dict[uid]["text"]) or "编辑图像"
            img_paths = list(user_dict[uid]["image"])
            user_dict.pop(uid)  # 立即清理用户数据，避免重复提交

            try:
                from run.ai_generated_art.service.gptimage2_client import gptimage2_draw, gptimage2_edit
                if img_paths:
                    res_path = await gptimage2_edit(img_paths, full_prompt, config)
                else:
                    res_path = await gptimage2_draw(full_prompt, config, is_about_bot=False)
                await bot.send(event, [Image(file=res_path)], True)
            except Exception as e:
                traceback.print_exc()
                await bot.send(event, f"发生错误: {str(e)}")
            finally:
                for path in img_paths:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
            return

        # 4. 收集模式：当用户在 user_dict 中时，记录他发的消息
        elif uid in user_dict:
            found_any = False
            for mes in event.message_chain:
                if isinstance(mes,Text):
                    user_dict[uid]["text"].append(mes.text.strip())
                    found_any = True
                elif isinstance(mes, Image) or isinstance(mes, Mface):
                    url = mes.url if hasattr(mes, 'url') and mes.url else mes.file
                    if url:
                        path = await download_img_from_url(url)
                        user_dict[uid]["image"].append(path)
                        found_any = True

            if found_any:
                # 可以选择不回复，或者小声提示
                await bot.send(event, "已添加")
                pass