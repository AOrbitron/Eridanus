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
    """基于 gptimage2 (OpenAI Images API 标准) 的统一图像编辑工具"""
    async def _image_edit_task(bot, event, config, img_url, prompt):
        user = await get_user(event.user_id)
        permission_need = config.ai_generated_art.config.get("gptimage2", {}).get("权限要求", 0)
        if user.permission < permission_need:
            return

        try:
            msg = await bot.send(event, "正在使用 GPTImage2 编辑图片，请稍候...")
            await delay_recall(bot, msg)
        except Exception as e:
            bot.logger.error(e)

        try:
            from run.ai_generated_art.service.gptimage2_client import gptimage2_edit
            res_path = await gptimage2_edit(img_url, prompt, config)
            await bot.send(event, [Image(file=res_path)], True)
        except Exception as e:
            bot.logger.error(f"GPTImage2 图片编辑失败: {e}\n{traceback.format_exc()}")
            await bot.send(event, f"图片编辑失败：{e}")

    asyncio.create_task(
        _image_edit_task(bot, event, config, img_url, prompt)
    )


async def _call_gptimage2(bot, event, config, prompt, is_about_bot=False, **kwargs):
    """统一调用符合 OpenAI Images API 标准的 gptimage2 后端（已合并原 gpt_official 与 gptimage2）"""
    from run.ai_generated_art.service.gptimage2_client import gptimage2_draw
    res_path = await gptimage2_draw(
        prompt=prompt,
        config=config,
        is_about_bot=is_about_bot,
        aspect_ratio=kwargs.get("aspect_ratio") or kwargs.get("ar"),
        args=kwargs,
    )
    await bot.send(event, [Image(file=res_path)], True)


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
            elif backend in ("gptimage2", "gptimage2_apollodorus", "gpt_official", "openai", "dalle"):
                await _call_gptimage2(bot, event, config, prompt, is_about_bot=is_about_bot, **kwargs)
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
