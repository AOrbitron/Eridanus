import os
import urllib.parse
import asyncio
import traceback

from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Node, Image, Text
from framework_common.database_util.User import get_user
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str
from framework_common.utils.utils import download_img
from run.basic_plugin.service.imgae_search.eridanus_img_search_server import search_
from run.basic_plugin.service.imgae_search.image_search2 import fetch_results
from run.basic_plugin.service.imgae_search.soutubot import async_search_by_image
from run.basic_plugin.service.imgae_search.avscan import search_avscan
from run.basic_plugin.service.imgae_search.google_lens_search import search_google_lens

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


image_search = {}


async def call_image_search(bot, event, config, image_url=None):
    """
    通用图片搜索（并发调用聚合搜图、soutu.bot、eridanus搜图引擎以及 AVScan 截图搜番号）。
    支持群聊消息和 Function Calling 调用。
    始终先将图片保存到本地缓存，再统一以文件上传路径进行搜索，避免第三方或CDN反爬引发的请求异常。
    """
    user_info = await get_user(event.user_id, event.sender.nickname)
    bot.logger.info("接收来自 用户：" + str(event.sender.user_id) + " 的搜图指令")
    
    search_cfg = config.basic_plugin.config.get("搜图", {})
    if (not search_cfg.get("聚合搜图", True) and 
        not search_cfg.get("soutu_bot", True) and 
        not search_cfg.get("avscan", True) and 
        not search_cfg.get("google_lens", True) ):
        await bot.send(event, "没有开启任何搜图功能")
        return {"status": "error", "message": "没有开启任何搜图功能"}

    operate_level = search_cfg.get("search_image_resource_operate_level", 0)
    user_perm = getattr(user_info, "permission", 0) if user_info else 0
    if user_perm < operate_level:
        await bot.send(event, "权限不够呢.....")
        return {"status": "error", "message": "权限不够"}

    # 1. 提取图片来源
    if not image_url:
        images = event.get("image")
        if images and len(images) > 0:
            raw_target = images[0].get("url") or images[0].get("file")
        else:
            await bot.send(event, "未检测到图片，请提供图片URL或随消息发送图片")
            return {"status": "error", "message": "未检测到图片"}
    else:
        raw_target = image_url

    # 2. 先将图片保存到本地，然后统一走上传路径
    if is_local_file_path(raw_target):
        local_img_path = get_local_file_path(raw_target)
        if not os.path.exists(local_img_path):
            await bot.send(event, "本地图片文件不存在")
            return {"status": "error", "message": f"本地图片文件不存在: {raw_target}"}
    else:
        # 网络图片或 QQ 官方 CDN 图片：统一先下载到本地缓存
        cache_dir = "data/pictures/cache"
        os.makedirs(cache_dir, exist_ok=True)
        local_img_path = os.path.abspath(os.path.join(cache_dir, f"{random_str()}.png"))
        try:
            bot.logger.info(f"正在预下载图片到本地: {local_img_path}")
            dl_res = await download_img(raw_target, local_img_path)
            if not dl_res or not os.path.exists(local_img_path) or os.path.getsize(local_img_path) == 0:
                await bot.send(event, "图片下载失败，请稍后重试")
                return {"status": "error", "message": "图片下载失败"}
        except Exception as e:
            bot.logger.error(f"下载图片失败: {e}")
            await bot.send(event, "图片下载失败，请稍后重试")
            return {"status": "error", "message": f"图片下载失败: {e}"}

    recall_id = await bot.send(event, "正在搜索图片，请等待结果返回.....")
    
    # 3. 所有搜图引擎统一接收本地图片路径，走上传接口
    functions = [
        call_image_search1(bot, event, config, local_img_path),
        call_image_search2(bot, event, config, local_img_path),
        call_image_search3(bot, event, config, local_img_path),
    ]
    if (search_cfg.get("google_lens", True)  or search_cfg.get("谷歌识图", True) or search_cfg.get("coser搜图", True)):
        functions.append(call_image_search_google_lens(bot, event, config, local_img_path))
    nsfw_search_operate_level = config.basic_plugin.config["搜图"]["nsfw_search_operate_level"]
    user_perm = getattr(user_info, "permission", 0) if user_info else 0
    if user_perm >= nsfw_search_operate_level:
        bot.logger.info("追加av搜索")
        functions.append(call_image_search_avscan(bot, event, config, local_img_path))

    all_results = []
    for future in asyncio.as_completed(functions):
        try:
            r = await future
            if r:
                all_results.append(r)
        except Exception as e:
            bot.logger.error(f"Error in image_search: {e}")
            traceback.print_exc()

    try:
        if recall_id and isinstance(recall_id, dict) and "data" in recall_id:
            await bot.recall(recall_id['data']['message_id'])
    except Exception:
        pass

    return {
        "status": "success",
        "message": "图片搜索完成，详细信息已发送到聊天中",
        "results": all_results
    }


async def call_image_search1(bot, event, config, local_img_path):
    if not config.basic_plugin.config.get("搜图", {}).get("聚合搜图", True):
        return None
    bot.logger.info("调用聚合接口搜索图片")
    try:
        results = await fetch_results(config.common_config.basic_config["proxy"]["http_proxy"], local_img_path,
                                      config.basic_plugin.config["image_search"]["sauceno_api_key"])
    except Exception as e:
        bot.logger.error(f"聚合搜图异常: {e}")
        return None

    async def extract_data(name, result):
        node_list = []
        if name == "saucenao":
            for item in result:
                try:
                    path = "data/pictures/cache/" + random_str() + ".png"
                    imgpath = await download_img(item[0], path, proxy=config.common_config.basic_config["proxy"]["http_proxy"], gray_layer=True)
                    node_list.append(Node(content=[Image(file=imgpath), Text(item[1])]))
                except Exception as e:
                    bot.logger.error(f"Error in extract_data: {e}")
                    node_list.append(Node(content=[Text(item[1])]))
                    continue
        if name == "anime_trace":
            node_list.append(Node(content=[Text(f"ai创作检测：{result[2]}")]))
            node_list.append(Node(content=[Text(result[0])]))
            node_list.append(Node(content=[Text(result[1])]))
        return node_list

    forMeslist = []
    for name, result in results.items():
        if result and result[0] != "":
            bot.logger.info(f"{name} 成功返回: {result}")
            forMeslist.extend(await extract_data(name, result))
    if forMeslist:
        await bot.send(event, forMeslist)
    return {"engine": "saucenao_and_animetrace", "status": "success", "data": results}


async def call_image_search2(bot, event, config, local_img_path):
    if not config.basic_plugin.config.get("搜图", {}).get("soutu_bot", True):
        return None
    bot.logger.info("调用soutu.bot搜索图片")
    proxy_cfg = config.common_config.basic_config.get("proxy", {}) or {}
    proxy = proxy_cfg.get("http_proxy") or proxy_cfg.get("socks_proxy")
    if proxy and not str(proxy).strip():
        proxy = None
    forMeslist = []
    try:
        r = await async_search_by_image(local_img_path, proxy=proxy)
    except Exception as e:
        bot.logger.warning(f"soutu.bot 搜索异常(可能接口已调整): {e}")
        return None
    bot.logger.info(f"soutu.bot 搜索结果：{r}")
    if not r:
        return None
    forMeslist.append(Node(content=[Text("图片已经过处理，但不保证百分百不被吞。")]))
    first_img = None
    for item in r[:5]:
        try:
            sst = f"标题:{item['title']}\n相似度:{item['similarity']}\n页码:{item['page']}"
            sst_img = f"data/pictures/cache/{random_str()}.png"
            if not first_img:
                first_img = sst_img
            await download_img(item['previewImageUrl'], sst_img, True,
                               proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            forMeslist.append(Node(content=[Text(sst), Image(file=sst_img)]))
        except Exception:
            bot.logger.error("图片下载失败")
            forMeslist.append(Node(content=[Text(sst)]))
    await bot.send(event, forMeslist)
    await bot.send(event, [Text(f"最高相似度:{r[0]['similarity']}\n标题：{r[0]['title']}\n页码：{r[0]['page']}\n\n")], True)
    return {"engine": "soutu_bot", "status": "success", "data": r[:5]}


async def call_image_search3(bot, event, config, local_img_path):
    try:
        r = await search_(local_img_path)
    except Exception as e:
        bot.logger.error(f"Error in eridanus_img_search: {e}")
        return None
    if not r:
        return None
    forMeslist = []
    for item in r:
        if item.get("status") == "success":
            try:
                sst = f"搜图引擎：{item['engine']}\n标题：{item['title']}\n相似度：{item['similarity']}\n作者：{item['author']}\n链接：{item['url']}"
                sst_img = f"data/pictures/cache/{random_str()}.png"
                await download_img(item['thumbnail'], sst_img, True,
                                   proxy=config.common_config.basic_config["proxy"]["http_proxy"])
                forMeslist.append(Node(content=[Text(sst), Image(file=sst_img)]))
            except Exception:
                bot.logger.error("图片下载失败")
                forMeslist.append(Node(content=[Text(sst)]))
    if forMeslist:
        await bot.send(event, forMeslist)
    return {"engine": "eridanus_img_server", "status": "success", "data": r}


async def call_image_search_avscan(bot, event, config, local_img_path):
    """
    调用 AVScan (avscan.cc) 搜索番号并发送识别卡片。
    使用已经保存到本地的图片文件走表单上传路径。
    """
    search_cfg = config.basic_plugin.config.get("搜图", {})
    if not search_cfg.get("avscan", True):
        return None

    bot.logger.info("调用 AVScan 搜索番号 (本地文件上传模式)")
    proxy_cfg = config.common_config.basic_config.get("proxy", {}) or {}
    proxy = proxy_cfg.get("http_proxy") or proxy_cfg.get("socks_proxy")
    if proxy and not str(proxy).strip():
        proxy = None

    try:
        res = await search_avscan(local_img_path, proxy=proxy)
    except Exception as e:
        bot.logger.error(f"AVScan 搜索发生异常: {e}")
        return {"engine": "avscan", "status": "error", "message": str(e)}

    if not res or res.get("status") != "success" or not res.get("results"):
        bot.logger.info("AVScan 未搜索到相关番号")
        return {"engine": "avscan", "status": "not_found", "results": []}

    results = res.get("results", [])
    top = results[0]
    best_sim = top.get("best_similarity", 0)

    forMeslist = [
        Node(content=[Text(
            f"🔍【AVScan 番号识别结果】\n"
            f"共找到 {len(results)} 部候选影片，最高相似度: {best_sim:.1f}%\n"
            f"（缩略图已进行安全处理）"
        )])
    ]

    gray_layer = config.basic_plugin.config.get("setu", {}).get("gray_layer", True)
    headers = {"Referer": "https://avscan.cc/", "User-Agent": "Mozilla/5.0"}

    # 取前 5 个匹配项生成消息卡片
    for item in results[:5]:
        code = item.get("video_code", "")
        sim = item.get("best_similarity", 0)
        ts = item.get("best_timestamp", "--:--:--")
        watch = item.get("watch_urls", {})
        missav = watch.get("missav", "")
        javdb = watch.get("javdb", "")
        javbus = watch.get("javbus", "")

        card_text = (
            f"🏷️【番号】: {code}\n"
            f"🎯【匹配度】: {sim:.1f}%\n"
            f"⏱️【时间点】: {ts}\n"
            f"▶️【MissAV】: {missav}\n"
            f"🌐【JAVDB】: {javdb}\n"
            f"🔗【JAVBus】: {javbus}"
        )

        thumb_url = item.get("best_thumb")
        if thumb_url:
            sst_img = f"data/pictures/cache/{random_str()}.webp"
            try:
                await download_img(thumb_url, sst_img, gray_layer=gray_layer, proxy=proxy, headers=headers)
                forMeslist.append(Node(content=[Text(card_text), Image(file=sst_img)]))
            except Exception as e:
                bot.logger.error(f"AVScan 缩略图下载失败: {e}")
                forMeslist.append(Node(content=[Text(card_text)]))
        else:
            forMeslist.append(Node(content=[Text(card_text)]))

    await bot.send(event, forMeslist)

    # 如果相似度达到 70% 以上，直接在聊天中高亮提示最匹配项
    if best_sim >= 70.0:
        await bot.send(
            event,
            [Text(
                f"🎯【AVScan 识别到高匹配番号】\n"
                f"番号：{top['video_code']}\n"
                f"相似度：{top['best_similarity']:.1f}%\n"
                f"时间点：{top['best_timestamp']}\n"
                f"在线播放：{top['watch_urls']['missav']}"
            )],
            True
        )

    return {
        "engine": "avscan",
        "status": "success",
        "best_match": {
            "video_code": top["video_code"],
            "similarity": top["best_similarity"],
            "timestamp": top["best_timestamp"],
            "missav": top["watch_urls"]["missav"],
        },
        "results": results[:5]
    }



async def call_image_search_google_lens(bot, event, config, local_img_path):
    """
    调用 Google Lens Search (谷歌识图/Google Lens 反向识别 Coser 及推特社媒账号)
    """
    search_cfg = config.basic_plugin.config.get("搜图", {})
    if (not search_cfg.get("google_lens", True) and
            not 
            not search_cfg.get("谷歌识图", True) and
            not search_cfg.get("coser搜图", True)):
        return None

    bot.logger.info("调用 Google Lens Search 反查推特/Coser社媒账号")
    proxy_cfg = config.common_config.basic_config.get("proxy", {}) or {}
    proxy = proxy_cfg.get("http_proxy") or proxy_cfg.get("socks_proxy")
    if proxy and not str(proxy).strip():
        proxy = None

    timeout = int(search_cfg.get("google_lens_timeout", 75))
    strict = bool(search_cfg.get("google_lens_strict", True))
    engines = search_cfg.get("google_lens_engines", None)

    try:
        res = await search_google_lens(
            image_path=local_img_path,
            proxy=proxy,
            engines=engines,
            timeout=timeout,
            strict=strict
        )
    except Exception as e:
        bot.logger.error(f"Google Lens 搜索发生异常: {e}")
        return {"engine": "google_lens", "status": "error", "message": str(e)}

    if not res or res.get("status") != "success":
        bot.logger.info(f"Google Lens 搜索未成功: {res.get('message', '未知原因') if res else 'None'}")
        return {"engine": "google_lens", "status": "not_found", "message": res.get("message") if res else ""}

    accounts = res.get("accounts", [])
    web_results = res.get("web_results", [])

    if not accounts and not web_results:
        bot.logger.info(f"Google Lens 未识别到有效账号或匹配网页: {res.get('message', '空结果')}")
        return {"engine": "google_lens", "status": "not_found", "message": res.get("message") if res else ""}

    forMeslist = []
    if accounts:
        forMeslist.append(Node(content=[Text(
            f"🎯【Google Lens 图像反向识别】\n"
            f"共识别到 {len(accounts)} 个匹配社媒账号：\n"
            f"（优先锁定原帖发布者与主轴人名）"
        )]))
        for acc in accounts:
            platform = acc.get("platform", "unknown")
            p_name = {
                "twitter": "Twitter / X",
                "weibo": "微博",
                "bilibili": "哔哩哔哩",
                "instagram": "Instagram",
                "pixiv": "Pixiv（画作平台）"
            }.get(platform, platform)

            name = acc.get("authorName") or acc.get("handle") or "未知"
            handle = acc.get("handle", "")
            url = acc.get("url", "")
            conf = acc.get("confidence", "")
            conf_str = "【精准出处】" if conf == "direct" else ("【推断关联】" if conf == "inferred" else "【相似图】")

            ev = acc.get("evidence", {}) or {}
            engine_source = ev.get("engine", "")
            src_url = ev.get("sourceUrl", "")

            card_text = (
                f"🌐【平台】：{p_name}\n"
                f"👤【名字/作者】：{name}\n"
                f"🆔【账号】：{handle}\n"
                f"🔗【主页链接】：{url}\n"
                f"✨【置信度】：{conf_str}"
            )
            if engine_source:
                card_text += f"\n🔍【来源引擎】：{engine_source}"
            if src_url:
                card_text += f"\n📌【原帖/出处】：{src_url}"

            forMeslist.append(Node(content=[Text(card_text)]))

    if web_results:
        web_lines = [f"🌐【Google Lens 相似网页出处】(共 {len(web_results)} 条)："]
        for idx, item in enumerate(web_results[:5], 1):
            w_title = item.get("title", "").strip() or "网页出处"
            w_url = item.get("url", "").strip()
            web_lines.append(f"{idx}. {w_title}\n🔗 {w_url}")
        forMeslist.append(Node(content=[Text("\n\n".join(web_lines))]))

    if forMeslist:
        await bot.send(event, forMeslist)

    return {
        "engine": "google_lens",
        "status": "success",
        "accounts": accounts,
        "web_results": web_results,
        "text": res.get("text", "")
    }

# 兼容保留原有名称引用

def main(bot: ExtendBot, config: YAMLManager):
    @bot.on(GroupMessageEvent)
    async def search_image(event):
        text = str(event.pure_text).strip()
        commands = {"搜图", "搜番号", "查番号", "avscan", "搜车牌", "搜coser", "反查coser", "福利姬", "查推特", "推特搜图", "lens", "google lens", "谷歌识图"}

        is_search_command = text in commands or (
                event.get("at")
                and str(event.get("at")[0]["qq"]) == str(bot.id)
                and event.get("text")
                and any(k == str(event.get("text")[0]).strip() for k in {"搜图", "搜番号"})
        )

        try:
            if is_search_command and not event.get('image'):
                recall_id = await bot.send(event, "请发送要搜索的图片（支持插画搜源或截图搜番号），nsfw图片可能无法发送到qq，建议自行打码后发送。")
                image_search[event.sender.user_id] = recall_id
                return
        except Exception:
            pass

        if (is_search_command or event.sender.user_id in image_search) and event.get('image'):
            if event.sender.user_id in image_search:
                recall_id = image_search.pop(event.sender.user_id)
                try:
                    if recall_id and isinstance(recall_id, dict) and "data" in recall_id:
                        await bot.recall(recall_id['data']['message_id'])
                except Exception:
                    pass

            try:
                await call_image_search(bot, event, config)
            finally:
                image_search.pop(event.sender.user_id, None)
