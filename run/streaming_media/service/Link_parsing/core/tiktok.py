import random

import urllib.parse
import os
import shutil
import httpx
import re
import copy
import pprint
from framework_common.utils.install_and_import import install_and_import
from .login_core import ini_login_Link_Prising
from .common import json_init,filepath_init,COMMON_HEADER,GLOBAL_NICKNAME,no_draw_type
from urllib.parse import urlparse
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from developTools.utils.logger import get_logger
logger=get_logger()
import json
from framework_common.manshuo_draw.manshuo_draw import manshuo_draw

"""以下为抖音/TikTok类型代码/Type code for Douyin/TikTok"""
URL_TYPE_CODE_DICT = {
    # 抖音/Douyin
    2: 'image',
    4: 'video',
    68: 'image',
    # TikTok
    0: 'video',
    51: 'video',
    55: 'video',
    58: 'video',
    61: 'video',
    150: 'image'
}

"""
dy视频信息
"""
DOUYIN_VIDEO = "https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={}&pc_client_type=1&version_code=190500&version_name=19.5.0&cookie_enabled=true&screen_width=1344&screen_height=756&browser_language=zh-CN&browser_platform=Win32&browser_name=Firefox&browser_version=118.0&browser_online=true&engine_name=Gecko&engine_version=109.0&os_name=Windows&os_version=10&cpu_core_num=16&device_memory=&platform=PC"

"""
今日头条 DY API
"""
DY_TOUTIAO_INFO = "https://aweme.snssdk.com/aweme/v1/play/?video_id={}&ratio=1080p&line=0"

"""
tiktok视频信息
"""
TIKTOK_VIDEO = "https://api22-normal-c-alisg.tiktokv.com/aweme/v1/feed/"

# 抖音详情接口。仅传递作品 ID 和 aid，避免依赖已经失效的固定版本参数
# 及 A-Bogus 签名；调用方式与参考解析器保持一致。
DOUYIN_DETAIL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
"""
通用请求头
"""
COMMON_HEADER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 '
                  'UBrowser/6.2.4098.3 Safari/537.36'
}


header = {
    'User-Agent': "Mozilla/5.0 (Linux; Android 8.0; Pixel 2 Build/OPD3.170816.012) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Mobile Safari/537.36 Edg/87.0.664.66"
}


def generate_x_bogus_url(url, headers):
    """
            生成抖音A-Bogus签名
            :param url: 视频链接
            :return: 包含X-Bogus签名的URL
            """
    # 调用JavaScript函数
    query = urllib.parse.urlparse(url).query
    abogus_file_path = f'{os.path.dirname(os.path.abspath(__file__))}/a-bogus.js'
    with open(abogus_file_path, 'r', encoding='utf-8') as abogus_file:
        abogus_file_path_transcoding = abogus_file.read()
    execjs=install_and_import("PyExecJS",'execjs')
    abogus = execjs.compile(abogus_file_path_transcoding).call('generate_a_bogus', query, headers['User-Agent'])
    #print('生成的A-Bogus签名为: {}'.format(abogus))
    return url + "&a_bogus=" + abogus


def generate_random_str(self, randomlength=16):
    """
    根据传入长度产生随机字符串
    param :randomlength
    return:random_str
    """
    random_str = ''
    base_str = 'ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789='
    length = len(base_str) - 1
    for _ in range(randomlength):
        random_str += base_str[random.randint(0, length)]
    return random_str


async def dou_transfer_other(dou_url):
    """
        图集临时解决方案
    :param dou_url:
    :return:
    """
    douyin_temp_data = httpx.get(f"https://api.xingzhige.com/API/douyin/?url={dou_url}").json()
    data = douyin_temp_data.get("data", { })
    item_id = data.get("jx", { }).get("item_id")
    item_type = data.get("jx", { }).get("type")

    if not item_id or not item_type:
        raise ValueError("备用 API 未返回 item_id 或 type")

    # 备用API成功解析图集，直接处理
    if item_type == "图集":
        item = data.get("item", { })
        cover = item.get("cover", "")
        images = item.get("images", [])
        # 只有在有图片的情况下才发送
        if images:
            #pprint.pprint(data)
            author = data.get("author", { }).get("name", "")
            title = data.get("item", { }).get("title", "")
            avatar_url = data.get("author", { }).get("avatar", "")
            video_time = data.get("stat", { }).get("time", "")
            dt = datetime.fromtimestamp(video_time)  # 本地时间，如果想要 UTC 时间用 utcfromtimestamp
            video_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            return cover, author, title, images ,avatar_url, video_time

    return None, None, None, None, None, None



def _extract_douyin_url(message):
    """从消息中提取抖音 URL。"""
    message = str(message or "").replace("&amp;", "&").replace("\\/", "/")
    match = re.search(
        r"https?://(?:v|jx)\.douyin\.com/[^\s\]）)>,，。！？!！]+"
        r"|https?://(?:www\.)?douyin\.com/[^\s\]）)>,，。！？!！]+"
        r"|https?://m\.douyin\.com/[^\s\]）)>,，。！？!！]+"
        r"|https?://jingxuan\.douyin\.com/[^\s\]）)>,，。！？!！]+"
        r"|https?://(?:www\.)?iesdouyin\.com/[^\s\]）)>,，。！？!！]+",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(0).rstrip("./,;:!?！？。，、\"'")


def _extract_aweme_id(url):
    """从抖音页面 URL 中提取作品 ID。"""
    url = str(url).strip()
    patterns = (
        r"(?:^|//)(?:www\.)?douyin\.com/(?:video|note)/(?P<id>\d+)",
        r"(?:^|//)(?:www\.)?iesdouyin\.com/share/(?:video|note)/(?P<id>\d+)",
        r"(?:^|//)m\.douyin\.com/share/(?:video|note)/(?P<id>\d+)",
        r"(?:^|//)jingxuan\.douyin\.com/m/(?:video|note)/(?P<id>\d+)",
        r"(?:^|//)(?:www\.)?douyin\.com/share/(?:video|note)/(?P<id>\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, str(url), re.IGNORECASE)
        if match:
            return match.group("id")
    return None


def _last_url(value):
    """返回抖音 URL 列表中通常最稳定的最后一项。"""
    if isinstance(value, dict):
        value = value.get("url_list")
    if isinstance(value, (list, tuple)):
        for item in reversed(value):
            if item:
                return item
    return value if isinstance(value, str) else ""


def _format_time(timestamp):
    if timestamp in (None, "", 0):
        return ""
    try:
        return (datetime.utcfromtimestamp(int(timestamp)) + timedelta(hours=8)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _format_context(text, signature=""):
    """沿用本项目绘图使用的标签格式整理文案。"""
    text = str(text or "")
    if "#" in text:
        text = text.replace("#", "\n[tag]#", 1)
        text += "[/tag]"
    if signature:
        text += f"\n--------------\n作者简介：\n{signature}"
    return text


async def _resolve_douyin_url(url, headers):
    """跟随短链重定向并返回最终 URL。"""
    async with httpx.AsyncClient(
        headers=headers,
        timeout=10,
        # 短链只取 Location，不访问重定向后的页面，避免触发页面反爬。
        follow_redirects=False,
        verify=False,
    ) as client:
        response = await client.get(url)
    if getattr(response, "status_code", 200) >= 400:
        response.raise_for_status()
    final_url = str(getattr(response, "url", "") or "")
    if final_url and final_url not in ("None", str(url)):
        return final_url
    response_headers = getattr(response, "headers", {}) or {}
    location = response_headers.get("location") or response_headers.get("Location")
    if location:
        return urllib.parse.urljoin(str(url), str(location))
    return str(final_url or url)


async def _fetch_aweme(aweme_id, headers):
    """按参考插件的参数请求作品详情。"""
    async with httpx.AsyncClient(
        headers=headers,
        timeout=10,
        follow_redirects=True,
        verify=False,
    ) as client:
        response = await client.get(
            DOUYIN_DETAIL,
            params={"aweme_id": aweme_id, "aid": "6383"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"status: {response.status_code}; {getattr(response, 'text', '')}")
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("aweme_detail"), dict):
        raise ValueError("抖音接口未返回 aweme_detail")
    return payload["aweme_detail"]


async def _draw_douyin(json_check, image_urls, avatar_url, owner_name, video_time, context, type_check):
    """生成项目现有格式的抖音卡片。"""
    if type_check in no_draw_type or not image_urls:
        return
    author_block = {
        "type": "avatar",
        "subtype": "common",
        "img": [avatar_url] if avatar_url else [],
        "upshift_extra": 20,
        "content": [f"[name]{owner_name}[/name]\n[time]{video_time}[/time]"],
        "type_software": "dy",
    }
    if len(image_urls) != 1:
        json_check["pic_path"] = await manshuo_draw(
            [{"type": "backdrop", "subtype": "one_color"}, author_block,image_urls,[context]],)
    else:
        json_check["pic_path"] = await manshuo_draw(
            [{"type": "backdrop", "subtype": "one_color"}, author_block,
             {
                 "type": "img",
                 "subtype": "common_with_des_right",
                 "img": image_urls,
                 "content": [context],
             },
             ],)


async def dy(url,filepath=None,type_check=None):
    """
        抖音解析
    :param bot:
    :param event:
    :return:
    """
    if filepath is None:
        filepath = filepath_init
    json_check = copy.deepcopy(json_init)
    json_check["status"] = True
    json_check["video_url"] = False
    json_check["soft_type"] = "dy"

    dou_url = _extract_douyin_url(url)
    if not dou_url:
        json_check["status"] = False
        json_check["reason"] = "未找到有效的抖音链接"
        return json_check
    json_check["url"] = dou_url
    logger.info(f"dou_url:{dou_url}")

    try:
        douyin_url = dou_url
        dou_id = _extract_aweme_id(douyin_url)
        headers = {
            "Origin": "https://open.douyin.com",
            "Referer": "https://open.douyin.com/",
        } | COMMON_HEADER
        if not dou_id:
            douyin_url = await _resolve_douyin_url(dou_url, headers)
            logger.info(f"dou_url_2:{douyin_url}")
            dou_id = _extract_aweme_id(douyin_url)
        if not dou_id:
            raise ValueError(f"无法从抖音链接中获取作品 ID: {douyin_url}")

        detail = await _fetch_aweme(dou_id, headers)
        author = detail.get("author") or {}
        avatar_url = _last_url(author.get("avatar_thumb"))
        owner_name = author.get("nickname") or ""
        signature = author.get("signature") or ""
        video_time = _format_time(detail.get("create_time"))

        share_info = detail.get("share_info") or {}
        share_text = share_info.get("share_desc_info") or detail.get("desc") or ""
        share_desc = share_info.get("share_desc")
        if share_desc:
            share_text = share_text.replace(f"#{share_desc}#", "", 1)
        context = _format_context(share_text, signature)

        image_urls = []
        video = detail.get("video")
        images = detail.get("images") or []
        if images:
            # 图文笔记以及实况图：沿用参考插件的 clip_type 判断。
            for image in images:
                if not isinstance(image, dict):
                    continue
                if image.get("clip_type") in (None, 2):
                    image_url = _last_url(image.get("url_list"))
                    if image_url:
                        image_urls.append(image_url)
                else:
                    image_video = image.get("video") or {}
                    image_cover = _last_url(image_video.get("cover"))
                    if image_cover:
                        image_urls.append(image_cover)
                    image_play_addr = image_video.get("play_addr") or {}
                    image_uri = image_play_addr.get("uri")
                    # json_init 只有一个 video_url 字段，实况图取第一条视频。
                    if image_uri and not json_check["video_url"]:
                        json_check["video_url"] = DY_TOUTIAO_INFO.format(image_uri)
        elif isinstance(video, dict):
            play_addr = video.get("play_addr") or {}
            video_uri = play_addr.get("uri")
            if video_uri:
                json_check["video_url"] = DY_TOUTIAO_INFO.format(video_uri)
            # 参考插件优先使用原始封面，接口缺失时回退到普通封面/动态封面。
            cover = _last_url(video.get("cover_original_scale"))
            cover = cover or _last_url(video.get("cover"))
            cover = cover or _last_url(video.get("dynamic_cover"))
            if cover:
                image_urls = [cover]

        json_check["pic_url_list"] = image_urls
        share_url = detail.get("share_url")
        if share_url:
            json_check["url"] = str(share_url).split("?", 1)[0]
        await _draw_douyin(
            json_check,
            image_urls,
            avatar_url,
            owner_name,
            video_time,
            context,
            type_check,
        )
        return json_check
    except Exception as exc:
        json_check["status"] = False
        json_check["reason"] = str(exc)
        logger.warning(f"抖音解析失败: {exc}")
        return json_check



if __name__ == '__main__':
    node_path = shutil.which("node")  # 自动查找 Node.js 可执行文件路径
    if not node_path:
        raise EnvironmentError("Node.js 未安装或未正确添加到系统 PATH 中!")

    import execjs
    # 强制使用 Node.js
    execjs._runtime = execjs.ExternalRuntime("Node.js", node_path)
    # 验证是否成功切换到 Node.js
    print(execjs.get().name)  # 应该输出 "Node.js"
