import asyncio
import base64
import os
import re

import aiofiles
import httpx
from openai import max_retries

from developTools.message.message_components import Image
from framework_common.database_util.User import get_user
from framework_common.utils.utils import download_img, delay_recall
from run.auto_reply.main import bot_name


import asyncio
from PIL import Image as PILImage

def get_best_aspect_ratio(image_path: str) -> str:
    SUPPORTED_RATIOS = {
        "1:1":  (1, 1),
        "16:9": (16, 9),
        "9:16": (9, 16),
        "4:3":  (4, 3),
        "3:4":  (3, 4),
        "3:2":  (3, 2),
        "2:3":  (2, 3),
        "2:1":  (2, 1),
        "1:2":  (1, 2),
        "21:9": (21, 9),
        "9:21": (9, 21),
    }
    with PILImage.open(image_path) as img:
        w, h = img.size
    actual_ratio = w / h
    return min(SUPPORTED_RATIOS, key=lambda k: abs(SUPPORTED_RATIOS[k][0] / SUPPORTED_RATIOS[k][1] - actual_ratio))


async def image_edit(bot, event, config, img_url, prompt):
    async def _image_edit_tas(bot, event, config, img_url, prompt):
        user = await get_user(event.user_id)
        permission_need = config.ai_generated_art.config["gptimage2"]["权限要求"]
        if user.permission < permission_need:
            return
        try:
            msg = await bot.send(event,"正在生成，请等待")
            await delay_recall(bot, msg)
        except Exception as e:
            bot.logger.error(e)
        image_path = await download_img(img_url)
        aim_url = "http://api.apollodorus.xyz/v1/images/edits"

        apikey = config.ai_generated_art.config["gptimage2"]["apikey"]
        headers = {"Authorization": f"Bearer {apikey}"}

        #configured_ratio = config.ai_generated_art.config["gptimage2"].get("aspect_ratio")
        aspect_ratio = get_best_aspect_ratio(image_path)

        data = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "model": config.ai_generated_art.config["gptimage2"]["model"],
            "resolution": config.ai_generated_art.config["gptimage2"]["resolution"] or "1K",
        }

        max_retries = 5
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                # 每次重试都重新打开文件，避免文件流已读完
                with open(image_path, "rb") as f:
                    file_objects = [("images", (os.path.basename(image_path), f, "image/png"))]
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            aim_url,
                            headers=headers,
                            files=file_objects,
                            data=data,
                            timeout=None
                        )

                if resp.status_code == 200:
                    res_json = resp.json()
                    result_url = res_json["data"][0]["url"]
                    await bot.send(event, [Image(file=result_url)])
                    return

                # 4xx 客户端错误不重试（参数有误重试也没用）
                if 400 <= resp.status_code < 500:
                    await bot.send(event, f"请求失败 ({resp.status_code}): {resp.text}")
                    return

                last_error = f"HTTP {resp.status_code}: {resp.text}"

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = str(e)

            if attempt < max_retries:
                wait = 2 ** (attempt - 1)  # 1s, 2s, 4s, 8s
                await asyncio.sleep(wait)

        await bot.send(event, f"请求失败，已重试 {max_retries} 次，最后错误：{last_error}")

    asyncio.create_task(
        _image_edit_tas(bot, event, config, img_url, prompt)
    )


async def _send_bot_image_with_retry(bot, event, config, prompt, max_retries=5):
    """后台任务：生成bot相关图片，失败自动重试最多5次"""
    bot_name = config.common_config.basic_config["bot"]
    apikey = config.ai_generated_art.config["gptimage2"]["apikey"]
    headers = {"Authorization": f"Bearer {apikey}"}
    base_url = "http://api.apollodorus.xyz/v1"
    bot_oc = config.ai_generated_art.config["gptimage2"]["bot_oc"]
    extra_prompt = config.ai_generated_art.config["gptimage2"]["extra_prompt"]
    character_anchor = bot_name + config.ai_generated_art.config["gptimage2"]["character_anchor"]
    prompt_text = (
        f"【角色参考】附图为{bot_name}的设定图,仅作为外貌参考(发色、瞳色、发型),"
        f"请在保持角色辨识度的前提下进行完整重绘。\n"
        f"【角色特征锚点】{character_anchor}\n"
        f"【绘制任务】根据以下描述绘制{bot_name}:{prompt}。\n"
        f"必须为全新高分辨率重绘,而不是对原图进行模糊放大或局部修改。\n"
        f"【细节要求】全身清晰,服装、手部、背景细节完整且清楚。\n"
        f"【画质要求】masterpiece, best quality, ultra detailed, 4k, sharp focus。\n"
        f"【负面约束】no blur, no low resolution, no smudging, no soft focus。\n"
        f"【画风一致性】整体风格接近设定图,但允许自然细化。\n"
        f"【额外要求】{extra_prompt}"
    )

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            async with aiofiles.open(bot_oc, "rb") as f1:
                file_content = await f1.read()

            async with httpx.AsyncClient(timeout=None, headers=headers) as client:
                resp = await client.post(
                    f"{base_url}/images/edits",
                    files=[
                        ("images", (os.path.basename(bot_oc), file_content, "image/png")),
                    ],
                    data={
                        "prompt": prompt_text,
                        "aspect_ratio": config.ai_generated_art.config["gptimage2"]["aspect_ratio"],
                        "resolution": config.ai_generated_art.config["gptimage2"]["resolution"] or "1K",
                        "model": config.ai_generated_art.config["gptimage2"]["model"],
                    },
                )
            bot.logger.info(resp.json())
            await bot.send(event, Image(file=resp.json()["data"][0]["url"]),True)
            bot.logger.info(f"bot图片生成成功（第{attempt}次尝试）")
            return  # 成功则退出

        except Exception as e:
            last_exception = e
            bot.logger.warning(f"bot图片生成失败（第{attempt}/{max_retries}次）: {e}")
            if attempt < max_retries:
                await asyncio.sleep(1)  # 指数退避: 1s, 2s, 4s, 8s

    bot.logger.error(f"bot图片生成最终失败，已重试{max_retries}次，最后错误: {last_exception}")


async def text2img(bot, event, config, prompt, is_about_bot=False):
    user = await get_user(event.user_id)
    permission_need = config.ai_generated_art.config["gptimage2"]["权限要求"]
    if user.permission < permission_need:
        return
    bot.logger.info(f"用户 {event.user_id} 请求生成图片,提示词 {prompt} is_about_bot={is_about_bot}")
    max_retries=config.ai_generated_art.config["gptimage2"]["max_retry"] or 5
    if is_about_bot:
        # 丢到后台运行，不阻塞上游，无需等待结果
        asyncio.create_task(
            _send_bot_image_with_retry(bot, event, config, prompt,max_retries)
        )
        #return "genrating....please wait..."

    else:
        apikey = config.ai_generated_art.config["gptimage2"]["apikey"]
        headers = {"Authorization": f"Bearer {apikey}"}
        base_url = "http://api.apollodorus.xyz/v1/images/generations"
        payload = {
            "prompt": prompt,
            "aspect_ratio": config.ai_generated_art.config["gptimage2"]["aspect_ratio"],
            "model": config.ai_generated_art.config["gptimage2"]["model"],
            "resolution": config.ai_generated_art.config["gptimage2"]["resolution"] or "1K",
            "response_format": "url",
            "n": 1,
        }
        async with httpx.AsyncClient(timeout=None, headers=headers) as client:
            response = await client.post(base_url, json=payload)
            resp = response.json()
            img_url = resp["data"][0]["url"]
            await bot.send(event, Image(file=img_url), True)