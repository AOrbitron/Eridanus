"""推特解析：优先 VxTwitter，回退 xdown，保留全部图片、视频与 GIF。"""

import copy
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .common import COMMON_HEADER, json_init, no_draw_type

from .twitter_download import is_twitter_gif, twitter_gif_reference

from developTools.utils.logger import get_logger
from framework_common.manshuo_draw.manshuo_draw import manshuo_draw


logger = get_logger()


def _remote_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("//"):
        value = f"https:{value}"
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else ""
    except ValueError:
        return ""


def _original_image_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query.update({"format": ["jpg"], "name": ["orig"]})
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _twitter_quality_value(label):
    match = re.search(r"(\d+)\s*p", str(label or ""), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _twitter_media_options(html_text):
    """保留 xdown 返回的每个视频及 GIF，按画质排序并去重。"""
    soup = BeautifulSoup(html_text or "", "html.parser")
    title_node = soup.find("h3")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    image_urls = list(dict.fromkeys(
        url for node in soup.select("img[src]") if (url := _remote_url(node.get("src")))
    ))
    options = []
    seen = set()
    for link in soup.select("a[href]"):
        url = _remote_url(link.get("href"))
        label = link.get_text(" ", strip=True)
        if not url or not any(kind in label.casefold() for kind in ("mp4", "gif")):
            continue
        gif = "gif" in label.casefold() or is_twitter_gif(url)
        url = twitter_gif_reference(url) if gif else url
        if url in seen:
            continue
        seen.add(url)
        options.append({
            "url": url, "label": label, "quality": label,
            "type": "gif" if gif else "video",
            "mime_type": "image/gif" if gif else "video/mp4",
        })
    options.sort(key=lambda item: _twitter_quality_value(item["quality"]), reverse=True)
    return title, image_urls, options


def _twitter_result(data, url, depth=0):
    result = copy.deepcopy(json_init)
    handle = str(data.get("user_screen_name") or "")
    article = data.get("article")
    try:
        post_time = datetime.fromtimestamp(
            float(data.get("date_epoch")), timezone(timedelta(hours=8)),
        ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, OSError):
        post_time = ""
    result.update({
        "status": True, "soft_type": "x", "url": url,
        "user_name": data.get("user_name") or "", "user_handle": f"@{handle}" if handle else "",
        "user_avatar": _remote_url(data.get("user_profile_image_url")),
        "user_description": data.get("user_description") or "", "time": post_time,
        "title": (article.get("title") or "") if isinstance(article, dict) else str(article or ""),
        "des": data.get("text") or "", "metadata_source": "vxtwitter",
    })
    covers = []
    seen = set()
    for media in data.get("media_extended") or []:
        if not isinstance(media, dict):
            continue
        media_url = _remote_url(media.get("url"))
        if not media_url:
            continue
        kind = media.get("type")
        if kind == "image":
            result["pic_url_list"].append(_original_image_url(media_url))
        elif kind in {"video", "gif", "animated_gif"}:
            gif = kind in {"gif", "animated_gif"} or is_twitter_gif(media_url)
            if gif:
                media_url = twitter_gif_reference(media_url)
            if media_url in seen:
                continue
            seen.add(media_url)
            cover = _remote_url(media.get("thumbnail_url"))
            if cover:
                covers.append(cover)
            result["video_options"].append({
                "url": media_url, "type": "gif" if gif else "video",
                "mime_type": "image/gif" if gif else "video/mp4", "quality": "原画",
                "label": f"{'GIF' if gif else '视频'} {len(result['video_options']) + 1}",
                "cover_url": cover, "duration": (media.get("duration_millis") or 0) / 1000,
            })
    result["pic_url_list"] = list(dict.fromkeys(result["pic_url_list"] or covers))
    if depth < 2 and isinstance(data.get("qrt"), dict):
        quoted = _twitter_result(data["qrt"], _remote_url(data.get("qrtURL")) or url, depth + 1)
        result["repost"] = quoted
        result["pic_url_list"] = list(dict.fromkeys(result["pic_url_list"] + quoted["pic_url_list"]))
        for option in quoted["video_options"]:
            if option["url"] not in seen:
                result["video_options"].append(option)
                seen.add(option["url"])
    result["video_url"] = result["video_options"][0]["url"] if result["video_options"] else False
    result["content"] = {"text": result["des"] or result["title"], "type": "post"}
    return result


async def twitter(url, filepath=None, proxy=None, type_check=None):
    matched = re.search(
        r"https?://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/(\w{1,20})/status/(\d+)",
        str(url), re.IGNORECASE,
    )
    if not matched:
        result = copy.deepcopy(json_init)
        result["reason"] = "未找到有效的 X 帖子链接"
        return result
    user, post_id = matched.groups()
    canonical = f"https://x.com/{user}/status/{post_id}"
    async with httpx.AsyncClient(
        proxy=proxy, trust_env=False, follow_redirects=True,
        timeout=httpx.Timeout(30, connect=15),
    ) as client:
        try:
            response = await client.get(
                f"https://api.vxtwitter.com/{user}/status/{post_id}",
                headers={"User-Agent": f"python-httpx/{httpx.__version__}"},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not data.get("user_name"):
                raise ValueError("推特接口未返回作者信息")
            result = _twitter_result(data, canonical)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning(f"VxTwitter 解析失败，尝试 xdown: {exc}")
            response = await client.post(
                "https://xdown.app/api/ajaxSearch", data={"q": canonical, "lang": "zh-cn"},
                headers={"Origin": "https://xdown.app", "Referer": "https://xdown.app/",
                         "User-Agent": COMMON_HEADER["User-Agent"]},
            )
            response.raise_for_status()
            payload = response.json()
            title, images, options = _twitter_media_options(payload.get("data"))
            if not images and not options:
                raise ValueError("推特接口未返回图片或视频")
            result = copy.deepcopy(json_init)
            result.update({
                "status": True, "soft_type": "x", "url": canonical, "title": title,
                "des": title, "user_name": f"@{user}", "user_handle": f"@{user}",
                "user_avatar": "", "time": "", "pic_url_list": images,
                "video_options": options, "video_url": options[0]["url"] if options else False,
                "metadata_source": "xdown", "content": {"text": title, "type": "post"},
            })

    if type_check not in no_draw_type:
        author = result["user_avatar"]
        draw_json = [
            {"type": "basic_set", "proxy": proxy},
            {"type": "backdrop", "subtype": "one_color"},
            {"type": "avatar", "subtype": "common", "img": [author] if author else [],
             "upshift_extra": 20, "type_software": "x",
             "content": [f"[name]{result['user_name']} {result['user_handle']}[/name]\n[time]{result['time']}[/time]"]},
        ]
        if result["pic_url_list"]:
            draw_json.append(result["pic_url_list"])
        draw_json.append([result["content"]["text"] or "X 帖子"])
        result["pic_path"] = await manshuo_draw(draw_json)
    return result
