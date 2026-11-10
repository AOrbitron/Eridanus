import copy
import email.message
import os
import uuid
from urllib.parse import parse_qs, urljoin, urlparse

import aiofiles
import httpx

from .common import filepath_init, json_init, no_draw_type


API_BASE_URL = "http://nas.manshuo.ink:5000"
PARSE_ENDPOINT = f"{API_BASE_URL}/api/link_parsing/parse"
DOWNLOAD_ENDPOINT = f"{API_BASE_URL}/api/link_parsing/download"

# Add URL substrings here to route parsing and media downloads through Manshuo API.
API_PARSE_MATCH_FIELDS = ("asmrone", "asmr.one", "asmr-")


def should_use_manshuo_api(url):
    normalized_url = str(url or "").casefold()
    return any(field.casefold() in normalized_url for field in API_PARSE_MATCH_FIELDS)


def _first_url(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return False


def _is_all_track_url(value):
    if not isinstance(value, str):
        return False
    tracks = parse_qs(urlparse(value).fragment).get("track", [])
    return any(track.strip().casefold() == "all" for track in tracks)


def _first_audio_url(audio_urls, audio_options=None):
    if isinstance(audio_options, list):
        for option in audio_options:
            if not isinstance(option, dict) or str(option.get("track") or "").casefold() == "all":
                continue
            url = _first_url(option.get("url"))
            if url and not _is_all_track_url(url):
                return url

    candidates = audio_urls if isinstance(audio_urls, list) else [audio_urls]
    for candidate in candidates:
        url = _first_url(candidate)
        if url and not _is_all_track_url(url):
            return url
    return False


async def _download_preview(client, preview, filepath):
    if not isinstance(preview, dict) or not preview.get("url"):
        return json_init["pic_path"]

    preview_url = urljoin(f"{API_BASE_URL}/", str(preview["url"]))
    parsed_preview_url = urlparse(preview_url)
    if parsed_preview_url.netloc != urlparse(API_BASE_URL).netloc:
        raise ValueError("解析 API 返回了无效的预览图片地址")

    file_name = os.path.basename(str(preview.get("filename") or parsed_preview_url.path))
    if not file_name:
        raise ValueError("解析 API 没有返回预览图片文件名")
    os.makedirs(filepath, exist_ok=True)
    preview_path = os.path.join(filepath, file_name)

    response = await client.get(preview_url)
    response.raise_for_status()
    if not response.content:
        raise ValueError("解析 API 返回了空的预览图片")
    async with aiofiles.open(preview_path, "wb") as preview_file:
        await preview_file.write(response.content)
    return preview_path


async def manshuo_api_link_prising(url, filepath=None, proxy=None, type=None):
    """Call the internal Manshuo API and adapt its result to the legacy parser shape."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("解析链接不能为空")

    parse_only = type in no_draw_type
    request_payload = {
        "url": url,
        "parse_only": parse_only,
        "use_proxy": bool(proxy),
    }
    client_timeout = httpx.Timeout(180, connect=10)
    async with httpx.AsyncClient(timeout=client_timeout, follow_redirects=True) as client:
        response = await client.post(PARSE_ENDPOINT, json=request_payload)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("解析 API 返回格式异常")

        if payload.get("code") not in (None, 0):
            raise ValueError(str(payload.get("message") or "链接解析失败"))
        result = payload.get("data", payload)
        if not isinstance(result, dict):
            raise ValueError(str(payload.get("message") or "解析 API 返回格式异常"))
        if result.get("status") is not True:
            reason = result.get("reason") or payload.get("message") or "链接解析失败"
            raise ValueError(str(reason))

        raw = result.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        legacy_result = copy.deepcopy(json_init)
        legacy_result.update(raw)

        preview_path = copy.deepcopy(json_init["pic_path"])
        if not parse_only:
            preview_path = await _download_preview(
                client,
                result.get("preview_image"),
                filepath or filepath_init,
            )

        image_urls = result.get("image_urls")
        if not isinstance(image_urls, list):
            image_urls = raw.get("pic_url_list")
        if not isinstance(image_urls, list):
            image_urls = []

        video_urls = result.get("video_urls")
        video_url = (
            (_first_url(video_urls) if isinstance(video_urls, list) else False)
            or _first_url(raw.get("video_url"))
        )
        audio_url = _first_audio_url(
            result.get("audio_url"),
            raw.get("audio_options"),
        ) or _first_audio_url(raw.get("audio_url"), raw.get("audio_options"))
        legacy_result.update({
            "status": True,
            "content": raw.get("content") or {
                "text": f"[title]{result.get('title') or ''}[/title]\n[des]{result.get('des') or ''}[/des]",
                "type": result.get("soft_type") or raw.get("soft_type") or "link",
            },
            "pic_path": preview_path,
            "url": result.get("source_url") or raw.get("url") or url,
            "video_url": video_url,
            "audio_url": audio_url,
            "soft_type": result.get("soft_type") or raw.get("soft_type") or False,
            "pic_url_list": image_urls,
            "code": raw.get("code", 0),
        })
        return legacy_result


async def download_manshuo_api_media(
    url,
    media_type,
    filepath,
    soft_type=None,
    audio_url=None,
    use_proxy=True,
):
    """Receive a media file generated by the internal API without processing it locally."""
    if media_type not in {"image", "video", "audio"}:
        raise ValueError(f"不支持的媒体类型: {media_type}")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("媒体下载地址不能为空")

    params = {
        "url": url.strip(),
        "media_type": media_type,
        "use_proxy": bool(use_proxy),
    }
    if soft_type:
        params["soft_type"] = soft_type
    if audio_url:
        params["audio_url"] = audio_url

    os.makedirs(filepath, exist_ok=True)
    timeout = httpx.Timeout(None, connect=10)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", DOWNLOAD_ENDPOINT, params=params) as response:
            if response.is_error:
                body = await response.aread()
                try:
                    error_payload = response.json()
                    detail = error_payload.get("detail") or error_payload.get("message")
                except (ValueError, AttributeError):
                    detail = body.decode("utf-8", errors="replace")
                raise RuntimeError(detail or f"API 媒体下载失败（HTTP {response.status_code}）")

            disposition = email.message.Message()
            disposition["content-disposition"] = response.headers.get("content-disposition", "")
            file_name = disposition.get_filename()
            if file_name:
                file_name = os.path.basename(file_name.replace("\\", "/"))
            if not file_name:
                extension = {
                    "image": ".jpg",
                    "video": ".mp4",
                    "audio": ".mp3",
                }[media_type]
                file_name = f"link_{media_type}_{uuid.uuid4().hex}{extension}"

            target_path = os.path.join(filepath, file_name)
            if os.path.exists(target_path):
                stem, extension = os.path.splitext(file_name)
                target_path = os.path.join(filepath, f"{stem}_{uuid.uuid4().hex[:8]}{extension}")

            try:
                async with aiofiles.open(target_path, "wb") as output:
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            await output.write(chunk)
            except BaseException:
                if os.path.exists(target_path):
                    os.remove(target_path)
                raise

    if not os.path.isfile(target_path) or os.path.getsize(target_path) <= 0:
        if os.path.exists(target_path):
            os.remove(target_path)
        raise FileNotFoundError("API 媒体下载返回了空文件")
    return target_path
