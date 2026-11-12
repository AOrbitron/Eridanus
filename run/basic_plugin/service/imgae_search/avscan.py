# -*- coding: utf-8 -*-
import io
import os
import re
import urllib.parse
from typing import Optional, Dict, Any, List, Union
import httpx
from PIL import Image as PILImage

from developTools.utils.logger import get_logger

logger = get_logger()

SEARCH_URL = "https://avscan.cc/search"
BASE_URL = "https://avscan.cc"
COVER_STEM_RE = re.compile(r"^(.+)_cover_(?:full|left|right)$", re.IGNORECASE)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://avscan.cc/",
    "Origin": "https://avscan.cc",
    "Accept": "application/json, text/plain, */*",
}


def get_local_file_path(url: str) -> str:
    """解析本地 URI / 绝对路径 / 兼容反斜杠与 URL 解码"""
    if not url:
        return ""
    p = str(url).strip()
    if p.startswith("file:///"):
        p = p[8:]
    elif p.startswith("file://"):
        p = p[7:]
    try:
        p = urllib.parse.unquote(p)
    except Exception:
        pass
    if len(p) >= 3 and p[0] in ('/', '\\') and p[2] == ':' and p[1].isalpha():
        p = p[1:]
    return os.path.normpath(p)


def is_local_file_path(url: str) -> bool:
    """判断是否为本地文件路径或 file:// URI"""
    if not url:
        return False
    u = str(url).strip()
    if u.startswith("file://"):
        return True
    if u.startswith(("http://", "https://", "data:image")):
        return False
    if len(u) >= 2 and u[1] == ':' and u[0].isalpha():
        return True
    if u.startswith(('/', '\\')):
        return True
    norm = get_local_file_path(u)
    return os.path.exists(norm)


def _frame_stem(name: str) -> str:
    base = str(name).replace('\\', '/').split('/')[-1]
    return os.path.splitext(base)[0]


def parse_timestamp(name: str) -> str:
    """解析时间戳，如 IPX-917_02-23-35.jpg -> 02:23:35，封面图返回 '封面'"""
    if not name:
        return "--:--:--"
    base = _frame_stem(name)
    if COVER_STEM_RE.match(base):
        return "封面"
    idx = base.rfind('_')
    if idx == -1:
        return "--:--:--"
    raw_ts = base[idx + 1:].replace('-', ':')
    return raw_ts if raw_ts else "--:--:--"


def build_thumb_url(video_code: str, image_name: str, thumb_path: Optional[str] = None) -> str:
    """根据返回的 thumb 字段或 code/image_name 拼装完整封面/截图 URL"""
    if thumb_path:
        if thumb_path.startswith("http"):
            return thumb_path
        return BASE_URL + ("" if thumb_path.startswith("/") else "/") + thumb_path
    base = _frame_stem(image_name)
    cover_match = COVER_STEM_RE.match(base)
    if cover_match:
        return f"{BASE_URL}/thumb/covers/{urllib.parse.quote(cover_match.group(1))}.webp"
    return f"{BASE_URL}/thumb/{urllib.parse.quote(video_code)}/{urllib.parse.quote(base)}.webp"


def preprocess_image(image_bytes: bytes, max_side: int = 1024, quality: int = 85) -> bytes:
    """按前端逻辑预处理：等比例缩放最长边到 max_side，转换为 JPEG 压缩"""
    try:
        with PILImage.open(io.BytesIO(image_bytes)) as im:
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            
            w, h = im.size
            longest = max(w, h)
            if longest > max_side:
                ratio = max_side / float(longest)
                new_w = max(1, int(round(w * ratio)))
                new_h = max(1, int(round(h * ratio)))
                im = im.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
            
            out_buf = io.BytesIO()
            im.save(out_buf, format="JPEG", quality=quality)
            return out_buf.getvalue()
    except Exception as e:
        logger.warning(f"avscan preprocess_image failed, using raw bytes: {e}")
        return image_bytes


async def search_avscan(
    image_input: Union[str, bytes],
    proxy: Optional[str] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    通过 avscan.cc 进行以图搜番号。
    优先读取本地图片文件走上传路径；若为网络URL，先下载到内存后再以二进制POST上传。
    :param image_input: 本地图片路径、图片网络 URL 或 图片二进制 bytes
    :param proxy: HTTP 代理 URL（如 http://127.0.0.1:7890），仅用于访问 avscan.cc，为空则直连
    :param timeout: 超时时间（秒）
    :return: 包含识别结果列表的字典
    """
    client_kwargs = {
        "timeout": timeout,
        "follow_redirects": True,
    }
    if proxy and str(proxy).strip():
        client_kwargs["proxy"] = proxy.strip()

    raw_bytes: Optional[bytes] = None

    if isinstance(image_input, bytes):
        raw_bytes = image_input
    elif isinstance(image_input, str):
        # 1. 本地文件判断与直接读取
        if os.path.exists(image_input) and os.path.isfile(image_input):
            with open(image_input, "rb") as f:
                raw_bytes = f.read()
        elif is_local_file_path(image_input):
            norm_path = get_local_file_path(image_input)
            if not os.path.exists(norm_path):
                return {"status": "error", "message": f"本地文件不存在: {image_input}", "results": []}
            with open(norm_path, "rb") as f:
                raw_bytes = f.read()
        # 2. 网络 URL 下载（国内腾讯 CDN 等域名不走代理，避免被拦截报 400）
        elif image_input.startswith(("http://", "https://")):
            dl_kwargs = {"timeout": timeout, "follow_redirects": True}
            parsed_u = urllib.parse.urlparse(image_input)
            host = parsed_u.netloc.lower()
            # QQ/腾讯等国内服务直连下载，不走代理
            if not any(dom in host for dom in ["qq.com", "qpic.cn", "tencent.com"]):
                if proxy and str(proxy).strip():
                    dl_kwargs["proxy"] = proxy.strip()
            
            dl_headers = {
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Accept": "*/*",
            }
            async with httpx.AsyncClient(**dl_kwargs) as dl_client:
                resp = await dl_client.get(image_input, headers=dl_headers)
                resp.raise_for_status()
                raw_bytes = resp.content
        else:
            return {"status": "error", "message": f"无法识别的图片输入: {image_input}", "results": []}

    if not raw_bytes or len(raw_bytes) < 50:
        return {"status": "error", "message": "图片数据过小或为空", "results": []}

    # 预处理图片为符合 avscan 要求的 JPEG
    compressed_bytes = preprocess_image(raw_bytes, max_side=1024, quality=85)

    files = {
        "file": ("image.jpg", compressed_bytes, "image/jpeg")
    }

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(SEARCH_URL, headers=DEFAULT_HEADERS, files=files)
            if resp.status_code == 429:
                return {"status": "rate_limited", "message": "AVScan 请求频率超限，请稍后再试", "results": []}
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"AVScan 请求失败: {e}")
        return {"status": "error", "message": str(e), "results": []}

    raw_results = data.get("results") or []
    parsed_results = []

    for item in raw_results:
        video_code = str(item.get("video_code") or "").strip()
        best_sim = float(item.get("best_similarity") or 0.0)
        raw_frames = item.get("frames") or []
        
        frames = []
        for f in raw_frames:
            img_name = f.get("image_name") or ""
            sim = float(f.get("similarity") or 0.0)
            thumb = f.get("thumb") or ""
            ts = parse_timestamp(img_name)
            t_url = build_thumb_url(video_code, img_name, thumb)
            frames.append({
                "image_name": img_name,
                "similarity": sim,
                "timestamp": ts,
                "thumb_url": t_url,
            })

        best_thumb = ""
        best_ts = "--:--:--"
        if frames:
            frames.sort(key=lambda x: x["similarity"], reverse=True)
            best_thumb = frames[0]["thumb_url"]
            best_ts = frames[0]["timestamp"]

        code_lower = video_code.lower()
        watch_urls = {
            "missav": f"https://missav.ai/cn/{code_lower}",
            "javdb": f"https://javdb.com/search?q={urllib.parse.quote(video_code)}&f=all",
            "javbus": f"https://www.javbus.com/{urllib.parse.quote(video_code)}",
            "avscan_direct": f"{BASE_URL}/go/m/zh/{code_lower}?s=r",
        }

        parsed_results.append({
            "video_code": video_code,
            "best_similarity": best_sim,
            "best_timestamp": best_ts,
            "best_thumb": best_thumb,
            "frames": frames,
            "watch_urls": watch_urls,
        })

    parsed_results.sort(key=lambda x: x["best_similarity"], reverse=True)

    return {
        "status": "success",
        "count": len(parsed_results),
        "results": parsed_results,
    }
