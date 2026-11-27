"""各游戏攻略资源下载与更新入口。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import html
from io import BytesIO
import json
from pathlib import Path
import re
import threading
from time import perf_counter
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

import httpx
from PIL import Image

from developTools.utils.logger import get_logger

__all__ = ["ZZZ_GUIDE_PATH", "ResourceUpdateResult", "update_game_resources",
           "update_all_game_resources", "schedule_all_game_resource_download"]

logger = get_logger("MiHoYo")
DATA_PATH = Path(__file__).resolve().parent.parent / "data"
ZZZ_GUIDE_PATH = DATA_PATH / "ZZZ" / "character"
GENSHIN_GUIDE_PATH = DATA_PATH / "GenshinImpact" / "character"
STARRAIL_GUIDE_PATH = DATA_PATH / "StarRail" / "character"
HI3_GUIDE_PATH = DATA_PATH / "HonkaiImpact3" / "character"
GUIDE_PROVIDERS = {"猫冬": "cat", "听雨惊花": "flower"}
DEFAULT_RESOURCE_SOURCE = "auto"
DEFAULT_FIRST_RESOURCE = "猫冬"
RESOURCE_MIRRORS = {
    "CNJS": "http://cn-js-nj-1.lcf.icu:13214",
    "TW": "http://tw-taipei-1.lcf.icu:20532",
    "SG": "http://sg-1.lcf.icu:12588",
    "US": "http://us-lax-2.lcf.icu:12588",
    "Azure SG": "https://sg-2.qxqx.cf",
    "Oracle KR": "https://kr.qxqx.cf",
    "Oracle JP": "https://jp.qxqx.cf",
    "MiniGG": "http://file.minigg.cn/sayu-bot",
    "Lulu": "http://lulush.microgg.cn",
    "TakeyaYuki": "https://gscore.focalors.com",
    "Elysia": "https://silverwing.elysia.beauty",
}
_MIGRATION_LOCK = threading.Lock()
_ZZZ_UPDATE_LOCK = asyncio.Lock()
_STARTUP_TASK: asyncio.Task | None = None
STARTUP_RESOURCE_TIMEOUT = 60


def _httpx_proxy_options(proxy: str | None) -> dict:
    """传递兼容 httpx 0.23–0.27 的代理参数。"""
    return {"proxies": {"http://": proxy, "https://": proxy}} if proxy else {}


@dataclass
class ResourceUpdateResult:
    checked: int = 0
    updated: int = 0
    failed: int = 0


@dataclass(frozen=True)
class GuideFile:
    name: str
    size: int
    modified: str


def migrate_zzz_character_resources() -> None:
    """迁移旧攻略目录，保留图片和增量更新记录，已有目标文件不覆盖。"""
    legacy = ZZZ_GUIDE_PATH.parent / "角色攻略"
    with _MIGRATION_LOCK:
        if not legacy.is_dir():
            return
        moved = 0
        old_directories = {
            "cat": (legacy, legacy / "猫冬", legacy / "cat"),
            "flower": (legacy / "听雨惊花", legacy / "flower"),
        }
        for folder, directories in old_directories.items():
            destination = ZZZ_GUIDE_PATH / folder
            for directory in directories:
                if not directory.is_dir():
                    continue
                for old_file in directory.iterdir():
                    if not old_file.is_file():
                        continue
                    if old_file.name != ".resources.json" and old_file.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                        continue
                    destination.mkdir(parents=True, exist_ok=True)
                    new_file = destination / old_file.name
                    if not new_file.exists():
                        old_file.rename(new_file)
                        moved += 1
        for directory in (legacy / "猫冬", legacy / "cat", legacy / "听雨惊花", legacy / "flower", legacy):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if moved:
            logger.info(f"绝区零旧攻略资源已迁移至 character 目录：{moved} 个文件")


def _parse_index(content: str) -> list[GuideFile]:
    """解析参考资源镜像的 Nginx 目录页，仅接受当前目录中的图片。"""
    result: dict[str, GuideFile] = {}
    pattern = re.compile(r'<a\s+href=[\"\x27]([^\"\x27]+)[\"\x27][^>]*>.*?</a>([^\r\n]*)', re.I)
    for link, detail in pattern.findall(content):
        url = urlsplit(html.unescape(link))
        name = unquote(url.path)
        if url.scheme or url.netloc or url.query or url.fragment:
            continue
        if not name or name.startswith(".") or any(char in name for char in "/\\\0"):
            continue
        if Path(name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        detail = html.unescape(re.sub(r"<[^>]+>", "", detail)).strip()
        match = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})\s+(\d+)$", detail)
        if match and int(match[2]) > 0:
            result[name] = GuideFile(name, int(match[2]), match[1])
    return list(result.values())


def _read_manifest(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _replace_file(path: Path, data: bytes, validate_image: bool = False) -> None:
    if validate_image:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("攻略资源不是 JPEG/PNG 图片")
            image.verify()
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_image_if_changed(path: Path, data: bytes) -> bool:
    with Image.open(BytesIO(data)) as image:
        if image.format not in {"JPEG", "PNG"}:
            raise ValueError("攻略资源不是 JPEG/PNG 图片")
        image.verify()
    try:
        if path.read_bytes() == data:
            return False
    except FileNotFoundError:
        pass
    _replace_file(path, data)
    return True


async def _download_one(client: httpx.AsyncClient, base_url: str, guide_path: Path, entry: GuideFile,
                        manifest: dict[str, dict], semaphore: asyncio.Semaphore, force: bool) -> bool:
    destination = guide_path / entry.name
    previous = manifest.get(entry.name)
    if not force and isinstance(previous, dict) and destination.is_file():
        if (previous.get("modified") == entry.modified and previous.get("size") == entry.size
                and destination.stat().st_size == entry.size):
            return False
    async with semaphore:
        response = await client.get(base_url + quote(entry.name, safe=""))
        response.raise_for_status()
        if len(response.content) != entry.size:
            raise ValueError(f"攻略文件大小不匹配: {entry.name}")
        return await asyncio.to_thread(_replace_image_if_changed, destination, response.content)


async def _measure_mirror(client: httpx.AsyncClient, name: str, base_url: str) -> tuple[str, str, float] | None:
    """测速只接受包含攻略图片的有效目录，防止错误页或登录页被选中。"""
    started = perf_counter()
    try:
        response = await asyncio.wait_for(client.get(f"{base_url}/ZZZeroUID/guide/cat/"), timeout=6)
        response.raise_for_status()
        if _parse_index(response.text):
            return name, base_url, perf_counter() - started
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        pass
    return None


async def _select_resource_mirror(client: httpx.AsyncClient, source: str) -> tuple[str, str] | None:
    if isinstance(source, str):
        source = source.strip().strip("[]")
        if source.casefold() == "auto":
            logger.info(f"开始自动测速绝区零资源下载源，共 {len(RESOURCE_MIRRORS)} 个节点")
            results = await asyncio.gather(*(
                _measure_mirror(client, name, url) for name, url in RESOURCE_MIRRORS.items()
            ))
            available = [result for result in results if result is not None]
            if available:
                name, url, elapsed = min(available, key=lambda result: result[2])
                logger.info(f"绝区零资源自动测速完成，选择 {name}（{elapsed:.2f} 秒）")
                return name, url
            logger.warning("绝区零资源自动测速失败，没有可用的下载源")
            return None
        for name, url in RESOURCE_MIRRORS.items():
            if name.casefold() == source.casefold():
                return name, url
    logger.warning(f"未知的绝区零资源下载源：{source!r}，请检查 mihuyo_club.zzz.resource_source 配置")
    return None


async def _update_guide_provider(client: httpx.AsyncClient, mirror_url: str, provider: str,
                                 semaphore: asyncio.Semaphore, force: bool) -> ResourceUpdateResult:
    result = ResourceUpdateResult()
    guide_path = ZZZ_GUIDE_PATH / GUIDE_PROVIDERS[provider]
    base_url = f"{mirror_url}/ZZZeroUID/guide/{GUIDE_PROVIDERS[provider]}/"
    try:
        await asyncio.to_thread(guide_path.mkdir, parents=True, exist_ok=True)
        manifest_path = guide_path / ".resources.json"
        manifest = await asyncio.to_thread(_read_manifest, manifest_path)
        response = await client.get(base_url)
        response.raise_for_status()
        files = _parse_index(response.text)
        if not files:
            raise ValueError("攻略目录没有可下载图片")
        downloads = await asyncio.gather(*(
            _download_one(client, base_url, guide_path, entry, manifest, semaphore, force)
            for entry in files
        ), return_exceptions=True)
        result.checked = len(files)
        for entry, downloaded in zip(files, downloads):
            if isinstance(downloaded, BaseException):
                result.failed += 1
                logger.warning(f"绝区零{provider}攻略下载失败（{entry.name}）：{type(downloaded).__name__}")
                continue
            result.updated += int(downloaded)
            manifest[entry.name] = {"size": entry.size, "modified": entry.modified}
        await asyncio.to_thread(_replace_file, manifest_path,
                                json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    except (httpx.HTTPError, OSError, ValueError) as error:
        logger.warning(f"绝区零攻略资源更新失败（提供方 {provider}）：{type(error).__name__}")
        result.failed += 1
    return result


async def update_zzz_character_resources(force: bool = False, proxy: str | None = None,
                                          source: str = DEFAULT_RESOURCE_SOURCE) -> ResourceUpdateResult:
    """从自动测速或指定的镜像下载两家攻略，手动更新强制下载，失败保留旧图。"""
    async with _ZZZ_UPDATE_LOCK:
        await asyncio.to_thread(migrate_zzz_character_resources)
        async with httpx.AsyncClient(**_httpx_proxy_options(proxy), timeout=httpx.Timeout(30, connect=5),
                                     follow_redirects=True) as client:
            mirror = await _select_resource_mirror(client, source)
            if mirror is None:
                return ResourceUpdateResult(failed=1)
            name, mirror_url = mirror
            logger.info(f"绝区零攻略资源更新使用下载源：{name}")
            semaphore = asyncio.Semaphore(4)
            results = await asyncio.gather(*(
                _update_guide_provider(client, mirror_url, provider, semaphore, force)
                for provider in GUIDE_PROVIDERS
            ))
        result = ResourceUpdateResult(checked=sum(item.checked for item in results),
                                      updated=sum(item.updated for item in results),
                                      failed=sum(item.failed for item in results))
        logger.info(f"绝区零攻略资源检查完成：检查 {result.checked} 张，更新 {result.updated} 张，失败 {result.failed} 张")
        return result


async def update_genshin_resources(force: bool = False, proxy: str | None = None,
                                  source: str = DEFAULT_RESOURCE_SOURCE) -> ResourceUpdateResult | None:
    """下载原神角色攻略图，源目录为 GenshinUID/wiki/guide。"""
    return await _update_static_guides("原神", "GenshinUID/wiki/guide", GENSHIN_GUIDE_PATH,
                                       force=force, proxy=proxy, source=source)


async def update_starrail_resources(force: bool = False, proxy: str | None = None,
                                   source: str = DEFAULT_RESOURCE_SOURCE) -> ResourceUpdateResult | None:
    """下载崩铁角色攻略图，源目录为 StarRailUID/guide/character_overview。"""
    return await _update_static_guides("崩坏：星穹铁道", "StarRailUID/guide/character_overview",
                                       STARRAIL_GUIDE_PATH, force=force, proxy=proxy, source=source)


async def _update_static_guides(game: str, remote_path: str, destination: Path, *,
                                force: bool, proxy: str | None,
                                source: str) -> ResourceUpdateResult:
    """复用 GSUID 资源镜像的目录格式，按变更内容统计更新数量。"""
    lock = _STATIC_UPDATE_LOCKS.setdefault(game, asyncio.Lock())
    async with lock:
        result = ResourceUpdateResult()
        options = {**_httpx_proxy_options(proxy), "timeout": httpx.Timeout(30, connect=6), "follow_redirects": True}
        async with httpx.AsyncClient(**options) as client:
            mirror = await _select_static_mirror(client, source, remote_path)
            if mirror is None:
                return ResourceUpdateResult(failed=1)
            source_name, mirror_url = mirror
            base_url = f"{mirror_url}/{remote_path.strip('/')}/"
            try:
                response = await client.get(base_url)
                response.raise_for_status()
                files = _parse_index(response.text)
                if not files:
                    raise ValueError("攻略图片目录为空")
                await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
                manifest_path = destination / ".resources.json"
                manifest = await asyncio.to_thread(_read_manifest, manifest_path)
                semaphore = asyncio.Semaphore(6)
                downloads = await asyncio.gather(*(
                    _download_one(client, base_url, destination, entry, manifest,
                                  semaphore, force)
                    for entry in files
                ), return_exceptions=True)
                result.checked = len(files)
                for entry, downloaded in zip(files, downloads):
                    if isinstance(downloaded, BaseException):
                        result.failed += 1
                        logger.warning(f"{game}角色攻略下载失败（{entry.name}）：{type(downloaded).__name__}")
                        continue
                    result.updated += int(downloaded)
                    manifest[entry.name] = {"size": entry.size, "modified": entry.modified}
                await asyncio.to_thread(_replace_file, manifest_path,
                                        json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
                logger.info(f"{game}角色攻略资源使用下载源：{source_name}")
            except (httpx.HTTPError, OSError, ValueError) as error:
                logger.warning(f"{game}攻略资源更新失败：{type(error).__name__}")
                result.failed += 1
        logger.info(f"{game}攻略资源检查完成：检查 {result.checked} 张，更新 {result.updated} 张，失败 {result.failed} 张")
        return result


_STATIC_UPDATE_LOCKS: dict[str, asyncio.Lock] = {}


async def _select_static_mirror(client: httpx.AsyncClient, source: str,
                                remote_path: str) -> tuple[str, str] | None:
    if isinstance(source, str):
        source = source.strip().strip("[]")
    if source and source.casefold() != "auto":
        for name, url in RESOURCE_MIRRORS.items():
            if name.casefold() == source.casefold():
                try:
                    response = await client.get(f"{url}/{remote_path.strip('/')}/")
                    response.raise_for_status()
                    if _parse_index(response.text):
                        return name, url
                except (httpx.HTTPError, ValueError):
                    return None
        logger.warning(f"未知或不可用的资源下载源：{source!r}")
        return None

    async def measure(name: str, url: str):
        started = perf_counter()
        try:
            response = await asyncio.wait_for(
                client.get(f"{url}/{remote_path.strip('/')}/", timeout=6), timeout=7)
            response.raise_for_status()
            if _parse_index(response.text):
                return name, url, perf_counter() - started
        except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
            return None
        return None

    results = await asyncio.gather(*(measure(name, url) for name, url in RESOURCE_MIRRORS.items()))
    available = [item for item in results if item is not None]
    if not available:
        logger.warning(f"{remote_path}自动测速失败，没有可用的资源下载源")
        return None
    name, url, elapsed = min(available, key=lambda item: item[2])
    logger.info(f"{remote_path}自动测速完成，选择 {name}（{elapsed:.2f} 秒）")
    return name, url


async def update_hi3_resources(force: bool = False, proxy: str | None = None,
                               source: str = DEFAULT_RESOURCE_SOURCE) -> ResourceUpdateResult:
    """从崩坏3官方 Wiki 刷新角色攻略详情缓存。"""
    import html
    import re
    from urllib.parse import unquote

    base = "https://api-takumi-static.mihoyo.com/common/blackboard/bh3_wiki"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://bbs.mihoyo.com/"}
    result = ResourceUpdateResult()
    options = {**_httpx_proxy_options(proxy), "timeout": httpx.Timeout(20, connect=6), "follow_redirects": True}
    async with httpx.AsyncClient(**options, headers=headers) as client:
        try:
            response = await client.get(f"{base}/v1/home/content/list",
                                        params={"app_sn": "bh3_wiki", "channel_id": 18})
            response.raise_for_status()
            data = response.json().get("data") or {}
            sections = data.get("list") or []
            entries = sections[0].get("list", []) if sections else []
            if not entries:
                raise ValueError("官方 Wiki 没有返回角色目录")
            await asyncio.to_thread(HI3_GUIDE_PATH.mkdir, parents=True, exist_ok=True)
            semaphore = asyncio.Semaphore(5)

            async def update_one(entry):
                cid = str(entry.get("content_id") or "")
                if not cid.isdigit():
                    return False
                path = HI3_GUIDE_PATH / f"{cid}.json"
                async with semaphore:
                    detail_response = await client.get(f"{base}/v1/content/info",
                                                       params={"app_sn": "bh3_wiki", "content_id": cid})
                    detail_response.raise_for_status()
                    detail_data = detail_response.json().get("data") or {}
                content = detail_data.get("content") or {}
                sections = content.get("contents") or []
                evaluation = []
                aliases = []
                for section in sections:
                    if section.get("name") in ("角色评价", "角色介绍"):
                        for raw in re.findall(r'data-data="([^"]*)"', section.get("text", "")):
                            try:
                                parsed_items = json.loads(unquote(html.unescape(raw)))
                                evaluation.extend(parsed_items)
                                for parsed_item in parsed_items:
                                    if parsed_item.get("tmplKey") != "valkyrie" or parsed_item.get("partKey") != "basicIntroduction":
                                        continue
                                    for field in (parsed_item.get("data") or {}).get("mainFields", []):
                                        for label_key, value_key in (("nameL", "valueL"), ("nameR", "valueR")):
                                            label = str(field.get(label_key) or "")
                                            if "别名" in label or "昵称" in label:
                                                aliases.extend(name.strip() for name in str(field.get(value_key) or "").replace("，", "、").split("、") if name.strip())
                            except (ValueError, TypeError):
                                continue
                payload = {"id": cid, "title": content.get("title") or entry.get("title"),
                           "icon": content.get("icon") or entry.get("icon"), "summary": content.get("summary", ""),
                           "sections": sections, "evaluation": evaluation, "aliases": list(dict.fromkeys(aliases))}
                serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                if path.is_file():
                    try:
                        if path.read_bytes() == serialized:
                            return False
                    except OSError:
                        pass
                await asyncio.to_thread(_replace_file, path,
                                        serialized)
                return True

            outcomes = await asyncio.gather(*(update_one(entry) for entry in entries), return_exceptions=True)
            result.checked = len(entries)
            for item in outcomes:
                if isinstance(item, BaseException):
                    result.failed += 1
                else:
                    result.updated += int(item)
        except (httpx.HTTPError, OSError, ValueError, KeyError, IndexError) as error:
            logger.warning(f"崩坏3角色攻略更新失败：{type(error).__name__}")
            result.failed += 1
    logger.info(f"崩坏3攻略资源检查完成：检查 {result.checked} 份，更新 {result.updated} 份，失败 {result.failed} 份")
    return result


GAME_RESOURCE_UPDATERS: dict[str, Callable[..., Awaitable[ResourceUpdateResult | None]] | None] = {
    "原神": update_genshin_resources,
    "崩坏：星穹铁道": update_starrail_resources,
    "绝区零": update_zzz_character_resources,
    "崩坏3": update_hi3_resources,
    "崩坏学园2": None,
    "未定事件簿": None,
}


async def update_game_resources(target: str, force: bool = False,
                                proxy: str | None = None,
                                source: str = DEFAULT_RESOURCE_SOURCE) -> ResourceUpdateResult | None:
    """单个游戏的独立资源更新接口；尚未接入的游戏返回 None。"""
    updater = GAME_RESOURCE_UPDATERS.get(target)
    return await updater(force=force, proxy=proxy, source=source) if updater else None


async def update_all_game_resources(proxy: str | None = None,
                                    source: str = DEFAULT_RESOURCE_SOURCE) -> None:
    """启动时后台检查所有游戏资源，超过总时限时取消并等待全部下载。"""
    logger.info(f"开始在后台更新米游社游戏资源，超时限制 {STARTUP_RESOURCE_TIMEOUT} 秒")
    games = list(GAME_RESOURCE_UPDATERS)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(update_game_resources(game, proxy=proxy, source=source) for game in games),
                           return_exceptions=True),
            timeout=STARTUP_RESOURCE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.info(f"米游社游戏资源后台更新超过 {STARTUP_RESOURCE_TIMEOUT} 秒，已停止更新")
        return
    for game, result in zip(games, results):
        if isinstance(result, BaseException):
            logger.warning(f"{game} 后台资源检查失败：{type(result).__name__}")
    logger.info("米游社游戏资源后台更新完成")


def schedule_all_game_resource_download(loop: asyncio.AbstractEventLoop | None = None,
                                        proxy: str | None = None,
                                        source: str = DEFAULT_RESOURCE_SOURCE) -> bool:
    """优先使用指定的机器人主循环，避免把后台任务留在插件的临时循环中。"""
    global _STARTUP_TASK
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    target_loop = loop if loop is not None else running_loop
    if target_loop is None or target_loop.is_closed() or not target_loop.is_running():
        return False
    if target_loop is not running_loop:
        try:
            target_loop.call_soon_threadsafe(schedule_all_game_resource_download, target_loop, proxy, source)
        except RuntimeError:
            return False
        return True
    if _STARTUP_TASK is not None:
        if not _STARTUP_TASK.cancelled():
            if not _STARTUP_TASK.done() or _STARTUP_TASK.exception() is None:
                return True
    _STARTUP_TASK = target_loop.create_task(update_all_game_resources(proxy=proxy, source=source),
                                          name="mihuyo-game-resources")
    return True


async def plugin_cleanup() -> None:
    """插件卸载时取消并等待后台下载，防止模块回收时仍残留挂起任务。"""
    global _STARTUP_TASK
    task = _STARTUP_TASK
    if task is None:
        return

    async def cancel_download() -> None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    if task.get_loop() is asyncio.get_running_loop():
        await cancel_download()
    elif task.get_loop().is_running():
        future = asyncio.run_coroutine_threadsafe(cancel_download(), task.get_loop())
        await asyncio.wrap_future(future)
    elif not task.done():
        return
    if _STARTUP_TASK is task:
        _STARTUP_TASK = None
