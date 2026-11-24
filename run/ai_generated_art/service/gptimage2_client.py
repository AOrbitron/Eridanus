# -*- coding: utf-8 -*-
"""
统一 OpenAI Images API 标准的 GPTImage2 服务客户端

功能：
1. 全面遵循 OpenAI `/v1/images/generations` 与 `/v1/images/edits` 接口标准；
2. 兼容响应体中的 `b64_json`（OpenAI / 翻译网关标准）与 `url`（历史中转兼容），
   统一落盘保存至 `data/pictures/cache/` 返回本地图片路径，方便聊天发送、QQ空间上传及表情包切分；
3. 作为与 `comfyui` / `sd` 同级别的画图后端，支持 Bot 自拍与日常穿搭（融合 `bot_oc.png` 与衣橱 `WardrobeManager`）。
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import aiofiles
import httpx
from PIL import Image

from framework_common.utils.utils import download_img

try:
    from run.wardrobe.wardrobe_manager import get_wardrobe_manager
except Exception:
    get_wardrobe_manager = None


_RATIO_TO_OPENAI_SIZE: Dict[str, Tuple[str, str]] = {
    "1:1": ("1024x1024", "2048x2048"),
    "3:4": ("1024x1365", "1536x2048"),
    "4:3": ("1365x1024", "2048x1536"),
    "2:3": ("1024x1536", "1365x2048"),
    "3:2": ("1536x1024", "2048x1365"),
    "9:16": ("1024x1792", "1152x2048"),
    "16:9": ("1792x1024", "2048x1152"),
}


def get_gptimage2_config(config: Any) -> Dict[str, Any]:
    """统一读取 gptimage2 配置区块"""
    ai_cfg = getattr(getattr(config, "ai_generated_art", None), "config", None) or {}
    return ai_cfg.get("gptimage2") or {}


def resolve_openai_image_params(
    cfg: Dict[str, Any],
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    explicit_size: Optional[str] = None,
) -> Dict[str, Any]:
    """将配置中的 aspect_ratio/resolution/quality 统一映射为 OpenAI 标准生图参数"""
    ar = (aspect_ratio or cfg.get("aspect_ratio") or "1:1").strip()
    res = str(resolution or cfg.get("resolution") or "1K").strip().upper()
    raw_quality = str(cfg.get("quality") or "").strip().lower()

    size = str(explicit_size or cfg.get("size") or "").strip()
    if not size:
        pair = _RATIO_TO_OPENAI_SIZE.get(ar, ("1024x1024", "2048x2048"))
        size = pair[1] if res in ("2K", "4K") else pair[0]

    if raw_quality in ("low", "medium", "high", "standard", "hd", "auto"):
        quality = raw_quality
    else:
        quality = "high" if res in ("2K", "4K") else "medium"

    output_format = str(cfg.get("output_format") or "png").strip().lower()
    if output_format == "jpg":
        output_format = "jpeg"
    if output_format not in ("png", "jpeg", "webp"):
        output_format = "png"

    return {
        "model": str(cfg.get("model") or "gpt-image-2.5-flare").strip(),
        "size": size,
        "quality": quality,
        "output_format": output_format,
        "aspect_ratio": ar,
        "resolution": res,
    }


async def save_openai_image_response(
    res_json: Dict[str, Any],
    output_format: str = "png",
    timeout: float = 60.0,
) -> str:
    """
    统一解析 OpenAI `/v1/images/*` 响应（优先 b64_json，兼容 url），
    返回本地保存的图像文件路径。
    """
    data_list = res_json.get("data") or []
    if not data_list or not isinstance(data_list, list):
        raise RuntimeError(f"GPTImage2 未返回图像数据: {res_json}")

    first = data_list[0] or {}
    cache_dir = Path("data/pictures/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    resp_fmt = str(res_json.get("output_format") or output_format or "png").lower()
    ext = "jpg" if resp_fmt == "jpeg" else resp_fmt
    if ext not in ("png", "jpg", "webp"):
        ext = "png"
    save_path = cache_dir / f"gptimg_{uuid.uuid4().hex[:10]}.{ext}"

    b64_val = first.get("b64_json")
    if b64_val:
        if isinstance(b64_val, str) and b64_val.startswith("data:") and "," in b64_val:
            b64_val = b64_val.split(",", 1)[1]
        img_bytes = base64.b64decode(b64_val)
        async with aiofiles.open(save_path, "wb") as f:
            await f.write(img_bytes)
        return str(save_path)

    url_val = first.get("url")
    if url_val:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(str(url_val))
            r.raise_for_status()
            async with aiofiles.open(save_path, "wb") as f:
                await f.write(r.content)
        return str(save_path)

    raise RuntimeError(f"GPTImage2 响应中既无 b64_json 也无 url: {list(first.keys())}")


async def _load_image_bytes(src: Union[str, bytes, Path]) -> Tuple[str, bytes, str]:
    """将本地路径、HTTP URL、file:// 或 bytes 加载为 (filename, raw_bytes, mime_type)。"""
    if isinstance(src, (bytes, bytearray)):
        return ("image.png", bytes(src), "image/png")

    s = str(src).strip()
    if s.startswith("file:///"):
        s = s[8:]
    elif s.startswith("file://"):
        s = s[7:]

    if os.path.exists(s):
        async with aiofiles.open(s, "rb") as f:
            raw = await f.read()
        fn = os.path.basename(s) or "image.png"
        ext = os.path.splitext(fn)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/webp" if ext == ".webp" else "image/png")
        return (fn, raw, mime)

    if s.startswith(("http://", "https://")):
        local_p = await download_img(s)
        async with aiofiles.open(local_p, "rb") as f:
            raw = await f.read()
        return (os.path.basename(local_p) or "image.png", raw, "image/png")

    raise ValueError(f"无法读取参考图片路径或 URL: {src}")


def _build_bot_prompt(prompt: str, config: Any, has_ref_image: bool = True) -> str:
    """结合衣橱系统（WardrobeManager）当前穿搭与人设锚点组装自然语言绘画指令"""
    bot_display_name = getattr(getattr(config, "common_config", None), "basic_config", {}).get("bot", "Bot")
    cfg = get_gptimage2_config(config)
    extra_prompt = cfg.get("extra_prompt", "")
    character_anchor = cfg.get("character_anchor", "")

    outfit_desc = ""
    try:
        wm = get_wardrobe_manager() if get_wardrobe_manager else None
        if wm:
            cur_outfit = wm.get_current_outfit() or {}
            o_name = cur_outfit.get("name", "")
            o_desc = cur_outfit.get("description") or cur_outfit.get("clothing_tags", "")
            if o_name or o_desc:
                outfit_desc = f"\n【当前着装参考（若描述未指定其他服饰则采用）】{o_name}：{o_desc}"
    except Exception:
        pass

    ref_line = (
        f"【角色参考】附图为{bot_display_name}的设定图，仅作为外貌参考（发色、瞳色、发型），请在保持角色辨识度的前提下进行完整重绘。\n"
        if has_ref_image
        else ""
    )
    return (
        f"{ref_line}"
        f"【角色特征锚点】{bot_display_name}{character_anchor}{outfit_desc}\n"
        f"【绘制任务】根据以下描述绘制{bot_display_name}：{prompt}。\n"
        f"必须为全新高分辨率绘制，而不是对原图进行模糊放大或机械拼贴。\n"
        f"【细节要求】人物比例自然、表情生动，服装、手部与背景细节完整清晰。\n"
        f"【画质要求】masterpiece, best quality, ultra detailed, sharp focus。\n"
        f"【负面约束】no blur, no low resolution, no extra fingers, no distorted anatomy。\n"
        f"【额外要求】{extra_prompt}"
    )


async def gptimage2_edit(
    image_sources: Union[str, bytes, Path, Sequence[Union[str, bytes, Path]]],
    prompt: str,
    config: Any,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    max_retries: Optional[int] = None,
) -> str:
    """
    调用遵循 OpenAI `/v1/images/edits` 标准的 gptimage2 图像编辑接口，
    返回本地保存的结果图片路径。
    """
    cfg = get_gptimage2_config(config)
    base_url = (cfg.get("base_url") or "http://api.apollodorus.xyz/v1").rstrip("/")
    apikey = str(cfg.get("apikey") or "").strip()
    timeout = float(cfg.get("timeout", 180))
    retries = int(max_retries if max_retries is not None else (cfg.get("max_retry") or 5))
    params = resolve_openai_image_params(cfg, aspect_ratio=aspect_ratio, resolution=resolution)

    if isinstance(image_sources, (str, bytes, bytearray, Path)):
        src_list = [image_sources]
    else:
        src_list = list(image_sources)

    loaded_files: List[Tuple[str, bytes, str]] = []
    for src in src_list:
        loaded_files.append(await _load_image_bytes(src))
    if not loaded_files:
        raise ValueError("图像编辑至少需要提供 1 张有效图片")

    field_name = "image" if len(loaded_files) == 1 else "image[]"
    headers = {"Authorization": f"Bearer {apikey}"} if apikey else {}
    form_data = {
        "prompt": prompt or "编辑图像",
        "model": params["model"],
        "size": params["size"],
        "quality": params["quality"],
        "output_format": params["output_format"],
        "n": "1",
    }

    last_err: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            multipart_files = [
                (field_name, (fn, io.BytesIO(raw), mime))
                for fn, raw, mime in loaded_files
            ]
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                resp = await client.post(
                    f"{base_url}/images/edits",
                    files=multipart_files,
                    data=form_data,
                )
            if resp.status_code == 200:
                return await save_openai_image_response(resp.json(), output_format=params["output_format"], timeout=timeout)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise RuntimeError(f"GPTImage2 编辑请求被拒绝 ({resp.status_code}): {resp.text}")
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            last_err = e
            if isinstance(e, RuntimeError) and "请求被拒绝" in str(e):
                raise
        if attempt < retries:
            await asyncio.sleep(min(8, 2 ** (attempt - 1)))

    raise RuntimeError(f"GPTImage2 图像编辑失败（已重试 {retries} 次）: {last_err}")


async def gptimage2_draw(
    prompt: str,
    config: Any,
    is_about_bot: bool = False,
    aspect_ratio: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
) -> str:
    """
    与 comfyui_draw / SdDraw0 同级的统一 GPTImage2 文生图/Bot自拍入口：
    - 当 `is_about_bot=True` 且存在 `bot_oc` 参考设定图时，自动走 `/v1/images/edits` 融合设定图与衣橱穿搭；
    - 否则调用标准 OpenAI `/v1/images/generations` JSON 接口。
    - 统一返回本地图片缓存路径。
    """
    cfg = get_gptimage2_config(config)
    base_url = (cfg.get("base_url") or "http://api.apollodorus.xyz/v1").rstrip("/")
    apikey = str(cfg.get("apikey") or "").strip()
    timeout = float(cfg.get("timeout", 180))
    retries = int(cfg.get("max_retry") or 5)

    explicit_size = args.get("size") if isinstance(args, dict) else None
    ar = (args.get("aspect_ratio") or args.get("ar")) if isinstance(args, dict) else aspect_ratio
    res_override = args.get("resolution") if isinstance(args, dict) else None
    params = resolve_openai_image_params(cfg, aspect_ratio=ar, resolution=res_override, explicit_size=explicit_size)

    if is_about_bot:
        bot_oc = cfg.get("bot_oc", "data/system/bot_oc.png")
        has_oc = bool(bot_oc and os.path.exists(bot_oc))
        full_prompt = _build_bot_prompt(prompt, config, has_ref_image=has_oc)
        if has_oc:
            return await gptimage2_edit(
                bot_oc,
                full_prompt,
                config,
                aspect_ratio=params["aspect_ratio"],
                resolution=params["resolution"],
                max_retries=retries,
            )
    else:
        full_prompt = prompt

    headers = {
        "Authorization": f"Bearer {apikey}",
        "Content-Type": "application/json",
    } if apikey else {"Content-Type": "application/json"}

    payload: Dict[str, Any] = {
        "model": params["model"],
        "prompt": full_prompt,
        "n": 1,
        "size": params["size"],
        "quality": params["quality"],
        "output_format": params["output_format"],
    }

    last_err: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                resp = await client.post(f"{base_url}/images/generations", json=payload)
            if resp.status_code == 200:
                return await save_openai_image_response(resp.json(), output_format=params["output_format"], timeout=timeout)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise RuntimeError(f"GPTImage2 生图请求被拒绝 ({resp.status_code}): {resp.text}")
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            last_err = e
            if isinstance(e, RuntimeError) and "请求被拒绝" in str(e):
                raise
        if attempt < retries:
            await asyncio.sleep(min(8, 2 ** (attempt - 1)))

    raise RuntimeError(f"GPTImage2 生图失败（已重试 {retries} 次）: {last_err}")
