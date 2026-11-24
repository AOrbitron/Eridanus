import asyncio
import base64
import os
import re
import traceback
from typing import Optional

import aiofiles
import httpx
from PIL import Image as PILImage

from developTools.message.message_components import Image, Text
from framework_common.database_util.User import get_user
from framework_common.utils.utils import download_img, delay_recall
from run.auto_reply.main import bot_name


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
    """基于 ComfyUI / gptimage2 的图生图 / 图片编辑工具"""
    async def _image_edit_tas(bot, event, config, img_url, prompt):
        user = await get_user(event.user_id)
        permission_need = config.ai_generated_art.config.get("gptimage2", {}).get("权限要求", 0)
        if user.permission < permission_need:
            return

        backend = str(config.ai_generated_art.config.get("文生图function_calling后端", "comfyui")).strip().lower()
        if backend == "comfyui":
            from run.ai_generated_art.service.comfyui_drawer import comfyui_img2img
            try:
                msg = await bot.send(event, "正在使用 ComfyUI 进行以图生图重绘，请稍候...")
                await delay_recall(bot, msg)
                group_id = getattr(event, "group_id", getattr(event, "user_id", None))
                res_path = await comfyui_img2img(img_url, prompt, config, groupid=group_id)
                if res_path:
                    if res_path.startswith("审核api"):
                        m = await bot.send(event, res_path, True)
                        await delay_recall(bot, m)
                    else:
                        await bot.send(event, [Image(file=res_path)], True)
                    return
            except Exception as e:
                bot.logger.error(f"ComfyUI 以图生图失败: {e}\n{traceback.format_exc()}")
                await bot.send(event, f"ComfyUI 以图生图失败: {e}", True)
                return

        try:
            msg = await bot.send(event, "正在编辑图片，请稍候...")
            await delay_recall(bot, msg)
        except Exception as e:
            bot.logger.error(e)
        image_path = await download_img(img_url)
        base_url = config.ai_generated_art.config.get("gptimage2", {}).get("base_url", "http://api.apollodorus.xyz/v1").rstrip("/")
        aim_url = f"{base_url}/images/edits"

        apikey = config.ai_generated_art.config.get("gptimage2", {}).get("apikey", "")
        headers = {"Authorization": f"Bearer {apikey}"}

        aspect_ratio = get_best_aspect_ratio(image_path)

        data = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "model": config.ai_generated_art.config.get("gptimage2", {}).get("model", "gpt-image-2.5-flare"),
            "resolution": config.ai_generated_art.config.get("gptimage2", {}).get("resolution") or "1K",
        }

        max_retries = config.ai_generated_art.config.get("gptimage2", {}).get("max_retry", 5)
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                with open(image_path, "rb") as f:
                    file_objects = [("images", (os.path.basename(image_path), f, "image/png"))]
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(
                            aim_url,
                            headers=headers,
                            files=file_objects,
                            data=data
                        )

                if resp.status_code == 200:
                    res_json = resp.json()
                    result_url = res_json["data"][0]["url"]
                    await bot.send(event, [Image(file=result_url)])
                    return

                if 400 <= resp.status_code < 500:
                    await bot.send(event, f"请求失败 ({resp.status_code}): {resp.text}")
                    return

                last_error = f"HTTP {resp.status_code}: {resp.text}"

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = str(e)

            if attempt < max_retries:
                await asyncio.sleep(2 ** (attempt - 1))

        await bot.send(event, f"图片编辑失败，已重试 {max_retries} 次，最后错误：{last_error}")

    asyncio.create_task(
        _image_edit_tas(bot, event, config, img_url, prompt)
    )


async def _send_bot_image_with_retry(bot, event, config, prompt, max_retries=5):
    """后台任务：使用 gptimage2 参考图模式生成 bot 自拍/形象图"""
    bot_display_name = config.common_config.basic_config.get("bot", "Bot")
    apikey = config.ai_generated_art.config.get("gptimage2", {}).get("apikey", "")
    headers = {"Authorization": f"Bearer {apikey}"}
    base_url = config.ai_generated_art.config.get("gptimage2", {}).get("base_url", "http://api.apollodorus.xyz/v1").rstrip("/")
    bot_oc = config.ai_generated_art.config.get("gptimage2", {}).get("bot_oc", "data/system/bot_oc.png")
    extra_prompt = config.ai_generated_art.config.get("gptimage2", {}).get("extra_prompt", "")
    character_anchor = bot_display_name + config.ai_generated_art.config.get("gptimage2", {}).get("character_anchor", "")
    prompt_text = (
        f"【角色参考】附图为{bot_display_name}的设定图,仅作为外貌参考(发色、瞳色、发型),"
        f"请在保持角色辨识度的前提下进行完整重绘。\n"
        f"【角色特征锚点】{character_anchor}\n"
        f"【绘制任务】根据以下描述绘制{bot_display_name}:{prompt}。\n"
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

            async with httpx.AsyncClient(timeout=180.0, headers=headers) as client:
                resp = await client.post(
                    f"{base_url}/images/edits",
                    files=[
                        ("images", (os.path.basename(bot_oc), file_content, "image/png")),
                    ],
                    data={
                        "prompt": prompt_text,
                        "aspect_ratio": config.ai_generated_art.config.get("gptimage2", {}).get("aspect_ratio", "1:1"),
                        "resolution": config.ai_generated_art.config.get("gptimage2", {}).get("resolution") or "1K",
                        "model": config.ai_generated_art.config.get("gptimage2", {}).get("model", "gpt-image-2.5-flare"),
                    },
                )
            if resp.status_code == 200:
                img_url = resp.json()["data"][0]["url"]
                await bot.send(event, Image(file=img_url), True)
                bot.logger.info(f"bot图片生成成功（第{attempt}次尝试）")
                return

        except Exception as e:
            last_exception = e
            bot.logger.warning(f"bot图片生成失败（第{attempt}/{max_retries}次）: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** (attempt - 1))

    bot.logger.error(f"bot图片生成最终失败，已重试{max_retries}次，最后错误: {last_exception}")
    msg = await bot.send(event, f"bot图片生成失败：{last_exception}")
    await delay_recall(bot, msg)


async def _call_gptimage2_apollodorus(bot, event, config, prompt, is_about_bot=False):
    """调用 apollodorus 版本的 gptimage2 (gpt-image-2.5-flare / nano-banana-2)"""
    max_retries = config.ai_generated_art.config.get("gptimage2", {}).get("max_retry", 5)
    if is_about_bot:
        await _send_bot_image_with_retry(bot, event, config, prompt, max_retries)
        return

    apikey = config.ai_generated_art.config.get("gptimage2", {}).get("apikey", "")
    headers = {"Authorization": f"Bearer {apikey}"}
    base_url = config.ai_generated_art.config.get("gptimage2", {}).get("base_url", "http://api.apollodorus.xyz/v1").rstrip("/")
    payload = {
        "prompt": prompt,
        "aspect_ratio": config.ai_generated_art.config.get("gptimage2", {}).get("aspect_ratio", "1:1"),
        "model": config.ai_generated_art.config.get("gptimage2", {}).get("model", "gpt-image-2.5-flare"),
        "resolution": config.ai_generated_art.config.get("gptimage2", {}).get("resolution") or "1K",
        "response_format": "url",
        "n": 1,
    }
    async with httpx.AsyncClient(timeout=180.0, headers=headers) as client:
        response = await client.post(f"{base_url}/images/generations", json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"gptimage2生成失败 ({response.status_code}): {response.text}")
        resp = response.json()
        img_url = resp["data"][0]["url"]
        await bot.send(event, Image(file=img_url), True)


async def _call_gpt_official(bot, event, config, prompt):
    """调用 OpenAI 官方 DALL-E 接口 (支持 dall-e-3 / dall-e-2)"""
    gpt_cfg = config.ai_generated_art.config.get("gpt_official", {})
    base_url = (gpt_cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    apikey = gpt_cfg.get("apikey", "")
    model = gpt_cfg.get("model", "dall-e-3")
    size = gpt_cfg.get("size", "1024x1024")
    quality = gpt_cfg.get("quality", "standard")
    style = gpt_cfg.get("style", "vivid")
    timeout = float(gpt_cfg.get("timeout", 120))

    headers = {
        "Authorization": f"Bearer {apikey}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "url"
    }
    if model == "dall-e-3":
        payload["quality"] = quality
        payload["style"] = style

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/images/generations", headers=headers, json=payload)
        if resp.status_code != 200:
            err_msg = resp.text
            try:
                err_json = resp.json()
                if "error" in err_json and "message" in err_json["error"]:
                    err_msg = err_json["error"]["message"]
            except Exception:
                pass
            raise RuntimeError(f"GPT官方生图请求失败 ({resp.status_code}): {err_msg}")

        res_data = resp.json()
        data_list = res_data.get("data", [])
        if not data_list:
            raise RuntimeError(f"GPT官方生图未返回图像数据: {res_data}")

        first = data_list[0]
        if "url" in first and first["url"]:
            await bot.send(event, [Image(file=first["url"])], True)
        elif "b64_json" in first and first["b64_json"]:
            await bot.send(event, [Image(file=f"base64://{first['b64_json']}")], True)


async def _call_nano_banana(bot, event, config, prompt):
    """调用 Google 官方/第三方 nano_banana (Imagen / Gemini preview)"""
    nano_cfg = config.ai_generated_art.config.get("ai绘画", {}).get("nano_banana_config", {})
    is_native = nano_cfg.get("原生gemini接口", False)
    contents = [{"text": prompt}]

    if not is_native:
        from run.ai_generated_art.service.nano_banana.unofficial_banana import call_openrouter_api
        api_result = await call_openrouter_api(contents, config)
    else:
        from run.ai_generated_art.service.nano_banana.gemini_official_banana import call_gemini_api
        api_result = await call_gemini_api(contents, config)

    if not api_result.get("success"):
        raise RuntimeError(f"nano_banana生图失败: {api_result.get('error', '未知错误')}")

    result_path = api_result.get("result_path")
    if result_path and os.path.exists(result_path):
        await bot.send(event, [Image(file=result_path)], True)
    elif api_result.get("b64_url"):
        await bot.send(event, [Image(file=api_result["b64_url"])], True)
    elif api_result.get("text"):
        img_match = re.search(r'!\[.*?\]\((.*?)\)', api_result["text"])
        if img_match:
            img_url = img_match.group(1)
            await bot.send(event, [Image(file=img_url)], True)
        else:
            await bot.send(event, [Text(api_result["text"])], True)


async def _call_comfyui(bot, event, config, prompt, is_about_bot=False, **kwargs):
    """调用 ComfyUI 后端生图"""
    from run.ai_generated_art.service.comfyui_drawer import comfyui_draw
    group_id = getattr(event, "group_id", getattr(event, "user_id", None))
    img_path = await comfyui_draw(prompt, config, groupid=group_id, args=kwargs, is_about_bot=is_about_bot)
    if img_path:
        if img_path.startswith("审核api"):
            msg = await bot.send(event, img_path, True)
            await delay_recall(bot, msg)
        else:
            await bot.send(event, [Image(file=img_path)], True)
    else:
        raise RuntimeError("ComfyUI 未生成有效图像")


async def _call_sd(bot, event, config, prompt, is_about_bot=False, **kwargs):
    """调用 Stable Diffusion WebUI 后端生图（支持 LLM 纯 Danbooru 词条优化与 1200-1800 尺寸约束）"""
    from run.ai_generated_art.service.prompt_optimizer import optimize_prompt_for_sd
    from run.ai_generated_art.service.aiDraw import SdDraw0
    from framework_common.utils.random_str import random_str

    group_id = getattr(event, "group_id", getattr(event, "user_id", None))
    path = f"data/pictures/cache/{random_str()}.png"

    # 调用 SD 专用提示词优化器（将自然语言转为纯 Danbooru tags，对齐 1200-1800 宽高比及 28-60 步数）
    ar = kwargs.get("aspect_ratio") or kwargs.get("ar")
    optimized = await optimize_prompt_for_sd(
        user_prompt=prompt,
        config=config,
        is_about_bot=is_about_bot,
        aspect_ratio=ar
    )

    opt_prompt = optimized.get("positive_prompt") or prompt
    sd_args = {
        "w": optimized.get("width", 1280),
        "h": optimized.get("height", 1728),
        "steps": optimized.get("steps", 32),
        "cfg": optimized.get("cfg", 5.0),
        "n": optimized.get("negative_prompt", "")
    }
    if "steps" in kwargs:
        sd_args["steps"] = kwargs["steps"]
    if "width" in kwargs:
        sd_args["w"] = kwargs["width"]
    if "height" in kwargs:
        sd_args["h"] = kwargs["height"]
    if "cfg" in kwargs:
        sd_args["cfg"] = kwargs["cfg"]

    p = await SdDraw0(opt_prompt, path, config, group_id, sd_args)
    if p:
        if p.startswith("审核api"):
            msg = await bot.send(event, p, True)
            await delay_recall(bot, msg)
        else:
            await bot.send(event, [Image(file=p)], True)
    else:
        raise RuntimeError("SD 绘图未返回有效图像或已被审核屏蔽")


async def _call_novelai(bot, event, config, prompt):
    """调用 NovelAI (nai4) 后端生图"""
    from run.ai_generated_art.service.aiDraw import n4
    from framework_common.utils.random_str import random_str
    group_id = getattr(event, "group_id", getattr(event, "user_id", None))
    path = f"data/pictures/cache/{random_str()}.png"
    p = await n4(prompt, path, group_id, config, {})
    if p:
        if p.startswith("审核api"):
            msg = await bot.send(event, p, True)
            await delay_recall(bot, msg)
        else:
            await bot.send(event, [Image(file=p)], True)
    else:
        raise RuntimeError("NovelAI 绘图未返回有效图像或已被屏蔽")


async def text2img(bot, event, config, prompt: str, is_about_bot: bool = False, **kwargs):
    """
    统一文生图 Function Calling 核心入口：
    自动根据配置文件中的 `文生图function_calling后端` 选择对应后端：
    - comfyui: 本地/远程 ComfyUI 节点绘图 (支持 Anima DiT 及主回复模型控制)
    - sd: Stable Diffusion WebUI API
    - gptimage2 / gptimage2_apollodorus: apollodorus 版本的 gptimage2
    - gpt_official: OpenAI 官方 DALL-E 接口
    - nano_banana / google官方nano_banana: Google 官方或第三方 Imagen/Gemini preview
    - novelai / novel_ai: NovelAI 绘图接口
    """
    user = await get_user(event.user_id)
    # 权限检查
    draw_cfg = config.ai_generated_art.config.get("ai绘画", {})
    permission_need = draw_cfg.get("ai绘画所需权限等级", 0)
    if user.permission < permission_need:
        msg = await bot.send(event, "无绘图功能使用权限", True)
        await delay_recall(bot, msg)
        return

    # 获取选择的后端
    backend = str(config.ai_generated_art.config.get("文生图function_calling后端", "comfyui")).strip().lower()

    bot.logger.info(f"统一文生图调用: backend={backend}, user={event.user_id}, prompt={prompt}, is_about_bot={is_about_bot}")

    backend_names = {
        "comfyui": "ComfyUI",
        "sd": "Stable Diffusion",
        "gptimage2": "GPT Image 2",
        "gptimage2_apollodorus": "GPT Image 2 (Apollodorus)",
        "gpt_official": "OpenAI DALL-E",
        "nano_banana": "Google Nano Banana",
        "google官方nano_banana": "Google Nano Banana",
        "novelai": "NovelAI",
        "novel_ai": "NovelAI"
    }
    display_backend = backend_names.get(backend, backend)

    async def _execute_draw():
        try:
            wait_msg = await bot.send(event, f"正在使用 {display_backend} 进行绘制，请稍候...", True)
            await delay_recall(bot, wait_msg)
        except Exception:
            pass

        try:
            if backend == "comfyui":
                await _call_comfyui(bot, event, config, prompt, is_about_bot=is_about_bot, **kwargs)
            elif backend == "sd":
                await _call_sd(bot, event, config, prompt, is_about_bot=is_about_bot, **kwargs)
            elif backend in ("gptimage2", "gptimage2_apollodorus"):
                await _call_gptimage2_apollodorus(bot, event, config, prompt, is_about_bot=is_about_bot)
            elif backend in ("gpt_official", "openai", "dalle"):
                await _call_gpt_official(bot, event, config, prompt)
            elif backend in ("nano_banana", "google官方nano_banana"):
                await _call_nano_banana(bot, event, config, prompt)
            elif backend in ("novelai", "novel_ai", "nai"):
                await _call_novelai(bot, event, config, prompt)
            else:
                bot.logger.warning(f"未知文生图后端: {backend}，自动回退到 comfyui")
                await _call_comfyui(bot, event, config, prompt, is_about_bot=is_about_bot, **kwargs)
        except Exception as e:
            bot.logger.error(f"文生图后端 ({display_backend}) 执行失败: {e}\n{traceback.format_exc()}")
            err_msg = await bot.send(event, f"绘制失败 ({display_backend}): {e}", True)
            await delay_recall(bot, err_msg)

    # 异步非阻塞执行
    asyncio.create_task(_execute_draw())
