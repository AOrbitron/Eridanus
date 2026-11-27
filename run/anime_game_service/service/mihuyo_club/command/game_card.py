"""原神、崩坏3、崩坏：星穹铁道抽卡记录适配器。

三个游戏的米游社接口参数不同，这里只共用账号 Cookie、UID 选择、缓存和图片绘制，
每个游戏保留自己的卡池协议。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from developTools.message.message_components import At, Image as CQImage
from developTools.utils.logger import get_logger

from ..api.common import get_game_record
from ..model import PluginDataManager, UserAccount, data_path, plugin_env
from ..utils.draw_note import _fit_label
from .config import game_name_list
from .card import FONT_PATH, _account_cookies, _authkey_headers, _font, _proxy_options, _request_timeout

logger = get_logger("MiHoYo")

AUTHKEY_URL = "https://api-takumi.mihoyo.com/binding/api/genAuthKey"
GAME_RECORD_URL = "https://api-takumi-record.mihoyo.com/game_record/card/wapi/getGameRecordCard"
GAME_CONFIG = {
    "原神": {"key": "GenshinImpact", "biz": "hk4e_cn", "endpoint": "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog", "gacha_id": "fecafa7b6560db5f3182222395d88aaa6aaac1bc", "pools": (("角色祈愿", "301", "301"), ("角色祈愿", "400", "301"), ("武器祈愿", "302", "302"), ("常驻祈愿", "200", "200"), ("新手祈愿", "100", "100"), ("集录祈愿", "500", "500"))},
    "崩坏：星穹铁道": {"key": "StarRail", "biz": "hkrpg_cn", "endpoint": "https://public-operation-hkrpg.mihoyo.com/common/gacha_record/api/getGachaLog", "gacha_id": "b06a52bc37892e08837b112d28229cebca6b24a2", "pools": (("角色跃迁", "11", "11"), ("光锥跃迁", "12", "12"), ("群星跃迁", "1", "1"), ("始发跃迁", "2", "2"), ("角色联动跃迁", "21", "21"), ("光锥联动跃迁", "22", "22"))},
    "崩坏3": {"key": "HonkaiImpact3", "biz": "bh3_cn", "endpoint": "https://public-operation-common.mihoyo.com/common/bh3_self_help_query/UserGachaQuery/GetUserGacha", "menus": "https://public-operation-common.mihoyo.com/common/bh3_self_help_query/UserMenuQuery/GetMenus"},
}
ROOT = data_path / "gacha"
GENSHIN_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "utils" / "resources" / "genshin_gacha"
GENSHIN_TEXTURE_ROOT = GENSHIN_RESOURCE_ROOT / "texture2d"
GENSHIN_ASSET_ROOT = ROOT / "原神" / "assets"
_LOCKS: Dict[str, asyncio.Lock] = {}
_HI3_REGIONS: Dict[Tuple[str, str], str] = {}


def _region_for_game(game: str, uid: str) -> str:
    prefix = str(uid)[:1]
    if game == "原神":
        return "cn_qd01" if prefix == "5" else "cn_gf01"
    if game == "崩坏：星穹铁道":
        return "prod_qd_cn" if prefix == "5" else "prod_gf_cn"
    if game == "崩坏3":
        return "android01"
    return "prod_gf_cn"


def _uid_items(account: UserAccount, game: str) -> List[str]:
    values = (account.game_uids or {}).get(GAME_CONFIG[game]["key"], [])
    if isinstance(values, (str, int)):
        values = [values]
    return list(dict.fromkeys(str(v) for v in values if str(v).isdigit()))


def _cache_path(game: str, uid: str) -> Path:
    return ROOT / game / f"{uid}.json"


def _load(game: str, uid: str) -> Dict[str, Any]:
    path = _cache_path(game, uid)
    if not path.exists():
        return {"uid": uid, "data_time": None, "data": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"uid": uid, "data": {}}
    except (OSError, ValueError) as error:
        raise ValueError("本地抽卡记录损坏，请重新刷新") from error


def _save(game: str, uid: str, data: Dict[str, List[Dict[str, Any]]]) -> None:
    path = _cache_path(game, uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps({"uid": uid, "data_time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), "data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def _authkey(client: httpx.AsyncClient, account: UserAccount, game: str, uid: str) -> str:
    config = GAME_CONFIG[game]
    region = _region_for_game(game, uid)
    if game == "崩坏3":
        region = await _hi3_role_region(client, account, uid)
    response = await client.post(AUTHKEY_URL, json={"auth_appid": "webview_gacha", "game_biz": config["biz"], "game_uid": uid, "region": region}, cookies=_account_cookies(account), headers=_authkey_headers(account), timeout=_request_timeout())
    response.raise_for_status()
    payload = response.json()
    authkey = ((payload.get("data") or {}).get("authkey"))
    if payload.get("retcode", 0) not in (0, "0") or not authkey:
        raise ValueError("获取抽卡授权失败，请重新登录米游社")
    return str(authkey)


async def _hi3_role_region(client: httpx.AsyncClient, account: UserAccount, uid: str) -> str:
    """Resolve the actual HI3 server name; its UID prefix is not a server ID."""
    cache_key = (str(account.bbs_uid or ""), str(uid))
    cached = _HI3_REGIONS.get(cache_key)
    if cached:
        return cached
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": plugin_env.device_config.USER_AGENT_MOBILE,
        "Origin": "https://webstatic.mihoyo.com",
        "Referer": "https://webstatic.mihoyo.com/",
    }
    response = await client.get(
        GAME_RECORD_URL,
        params={"uid": str(account.bbs_uid)},
        headers=headers,
        cookies=_account_cookies(account),
        timeout=_request_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("retcode", 0) not in (0, "0"):
        raise ValueError("无法获取崩坏3角色服务器信息，请重新登录米游社")
    records = ((payload.get("data") or {}).get("list")) or []
    for record in records:
        if str(record.get("game_id")) == "1" and str(record.get("game_role_id")) == str(uid):
            region = str(record.get("region") or "")
            if region:
                _HI3_REGIONS[cache_key] = region
                return region
    raise ValueError("未找到该崩坏3角色的服务器信息，请重新登录米游社")


def _normal_record(row: Dict[str, Any], pool: str) -> Dict[str, Any]:
    return {"id": str(row.get("id") or row.get("time") or uuid4().hex), "name": str(row.get("name") or row.get("content") or "未知物品"), "item_type": str(row.get("item_type") or "物品"), "rank_type": str(row.get("rank_type") or row.get("rarity") or ""), "time": str(row.get("time") or ""), "pool": pool, "item_id": str(row.get("item_id") or "")}


async def _fetch_standard(client: httpx.AsyncClient, account: UserAccount, game: str, uid: str,
                         existing_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                         full_refresh: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    config = GAME_CONFIG[game]
    authkey = await _authkey(client, account, game, uid)
    result: Dict[str, List[Dict[str, Any]]] = {name: [] for name, _, _ in config["pools"]}
    headers = {"Accept": "application/json, text/plain, */*", "User-Agent": plugin_env.device_config.USER_AGENT_MOBILE, "Origin": "https://webstatic.mihoyo.com", "Referer": "https://webstatic.mihoyo.com/"}
    for pool, pool_type, default_type in config["pools"]:
        end_id = "0"
        known_ids = {str(row.get("id")) for row in (existing_data or {}).get(pool, [])}
        stop_pool = False
        for page in range(1, 1000):
            params = {"authkey_ver": "1", "sign_type": "2", "auth_appid": "webview_gacha", "gacha_id": config["gacha_id"], "timestamp": str(int(time.time())), "lang": "zh-cn", "device_type": "mobile", "plat_type": "ios", "region": _region_for_game(game, uid), "authkey": authkey, "game_biz": config["biz"], "gacha_type": pool_type, "page": page, "size": "20", "end_id": end_id}
            if game == "原神":
                params["init_type"] = pool_type
            else:
                params["default_gacha_type"] = "11"
            endpoint = config["endpoint"]
            if game == "崩坏：星穹铁道" and pool_type in {"21", "22"}:
                endpoint = endpoint.rsplit("/", 1)[0] + "/getLdGachaLog"
            try:
                response = await client.get(endpoint, params=params, headers=headers, timeout=_request_timeout())
                response.raise_for_status()
                payload = response.json()
                if payload.get("retcode", 0) not in (0, "0"):
                    raise ValueError(f"{pool}返回错误")
                rows = ((payload.get("data") or {}).get("list")) or []
            except (httpx.HTTPError, ValueError):
                if game == "崩坏：星穹铁道" and pool_type in {"21", "22"}:
                    logger.warning(f"星铁可选联动卡池暂时无法获取：{pool}")
                    result[pool] = list((existing_data or {}).get(pool, []))
                    break
                raise
            if not rows:
                break
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                record = _normal_record(raw, pool)
                if not full_refresh and record["id"] in known_ids:
                    stop_pool = True
                    break
                result[pool].append(record)
            if stop_pool:
                break
            next_id = str(rows[-1].get("id") or "0")
            if next_id == end_id or len(rows) < 20:
                break
            end_id = next_id
            await asyncio.sleep(0.25)
    return result


def _bh3_params(uid: str, authkey: str, **extra: Any) -> Dict[str, Any]:
    value = {"page_id": "5", "auth_appid": "csc", "game_biz": "bh3_cn", "lang": "zh-cn", "authkey": authkey, "authkey_ver": "1", "sign_type": "2", "community_select_uid": uid, "bbs_auth_required": "true", "bbs_game_role_required": "bh3_cn", "app_client": "bbs", "source": "service-center", "source_point": "SvcCenterSelf", "win_direction": "portrait"}
    value.update(extra)
    return value


async def _fetch_hi3(client: httpx.AsyncClient, account: UserAccount, uid: str,
                     existing_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                     full_refresh: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    authkey = await _authkey(client, account, "崩坏3", uid)
    headers = {"Accept": "application/json, text/plain, */*", "User-Agent": plugin_env.device_config.USER_AGENT_MOBILE, "Origin": "https://webstatic.mihoyo.com", "Referer": "https://webstatic.mihoyo.com/"}
    menus_response = await client.get(GAME_CONFIG["崩坏3"]["menus"], params=_bh3_params(uid, authkey, type="1"), headers=headers, cookies=_account_cookies(account), timeout=_request_timeout())
    menus_response.raise_for_status()
    menu_payload = menus_response.json()
    if menu_payload.get("retcode", 0) not in (0, "0"):
        raise ValueError("崩坏3抽卡接口未能获取卡池列表")
    menus = menu_payload.get("data") or []
    if isinstance(menus, dict):
        menus = menus.get("list") or menus.get("menus") or []
    if not isinstance(menus, list):
        raise ValueError("崩坏3抽卡接口没有返回卡池列表")
    if not menus:
        return {}
    result: Dict[str, List[Dict[str, Any]]] = {}
    for menu in menus:
        if not isinstance(menu, dict):
            continue
        pool = str(menu.get("label") or menu.get("name") or f"卡池{menu.get('type', '')}")
        pool_type = str(menu.get("type") or menu.get("id") or "")
        if not pool_type:
            continue
        rows_all: List[Dict[str, Any]] = []
        known_ids = {str(row.get("id")) for row in (existing_data or {}).get(pool, [])}
        stop_pool = False
        occurrences: Dict[Tuple[str, str], int] = {}
        for page in range(1, 1000):
            response = await client.get(GAME_CONFIG["崩坏3"]["endpoint"], params=_bh3_params(uid, authkey, type=pool_type, page=page, size="20", end_id="0"), headers=headers, cookies=_account_cookies(account), timeout=_request_timeout())
            response.raise_for_status()
            payload = response.json()
            if payload.get("retcode", 0) not in (0, "0"):
                raise ValueError(f"崩坏3卡池 {pool} 返回异常")
            data = payload.get("data") or {}
            rows = data.get("list") if isinstance(data, dict) else []
            if not rows:
                break
            for raw in rows:
                fields = {str(x.get("label")): str(x.get("value")) for x in (raw.get("item") or []) if isinstance(x, dict)}
                if fields.get("补给时间") and fields.get("补给内容"):
                    base = (fields["补给时间"], fields["补给内容"])
                    occurrences[base] = occurrences.get(base, 0) + 1
                    record = _normal_record({"id": f"{base[0]}|{base[1]}|{occurrences[base]}", "time": base[0], "content": base[1]}, pool)
                    if not full_refresh and record["id"] in known_ids:
                        stop_pool = True
                        break
                    rows_all.append(record)
            if stop_pool or len(rows) < 10:
                break
            await asyncio.sleep(0.25)
        result[pool] = rows_all
    return result


async def _refresh(game: str, account: UserAccount, uid: str, proxy: Optional[str],
                   full_refresh: bool = False) -> Tuple[int, int]:
    options = _proxy_options(proxy)
    options.update(timeout=_request_timeout())
    cached_data = _load(game, uid).get("data") or {}
    async with httpx.AsyncClient(**options) as client:
        fetched = await _fetch_hi3(client, account, uid, existing_data=cached_data, full_refresh=full_refresh) if game == "崩坏3" else await _fetch_standard(
            client, account, game, uid, existing_data=cached_data, full_refresh=full_refresh)
    merged: Dict[str, List[Dict[str, Any]]] = {}
    added = 0
    for pool, rows in fetched.items():
        previous = list(cached_data.get(pool) or [])
        # 全量仅影响分页，保留接口查询期限以外的本地历史记录。
        by_id = {str(row.get("id")): row for row in previous}
        for row in rows:
            record_id = str(row.get("id"))
            if record_id not in by_id:
                added += 1
            by_id[record_id] = row
        merged[pool] = sorted(by_id.values(), key=lambda row: str(row.get("id", "")), reverse=True)
    for pool, rows in cached_data.items():
        merged.setdefault(pool, rows if isinstance(rows, list) else [])
    _save(game, uid, merged)
    return added, sum(len(rows) for rows in merged.values())


def _record_sort_key(item: Dict[str, Any]) -> Tuple[str, str]:
    return str(item.get("time") or item.get("id") or ""), str(item.get("id") or "")


def _genshin_item_index() -> Dict[str, Dict[str, Dict[str, Any]]]:
    try:
        value = json.loads((GENSHIN_RESOURCE_ROOT / "item_index.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"characters": {}, "weapons": {}}
    except (OSError, ValueError):
        return {"characters": {}, "weapons": {}}


def _genshin_gold_items(data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    result = []
    for pool, items in data.items():
        ordered = sorted((item for item in (items or []) if isinstance(item, dict)), key=_record_sort_key)
        pity = 0
        for item in ordered:
            pity += 1
            if str(item.get("rank_type", "")) != "5":
                continue
            enriched = dict(item)
            enriched["_pool"] = pool
            enriched["_pity"] = pity
            enriched["_is_up"] = _genshin_is_up(enriched, pool)
            result.append(enriched)
            pity = 0
    result.sort(key=_record_sort_key, reverse=True)
    return result


_GENSHIN_STANDARD_ITEMS = {
    "迪卢克", "七七", "琴", "莫娜", "刻晴", "提纳里", "迪希雅", "阿莫斯之弓", "天空之翼",
    "四风原典", "天空之卷", "和璞鸢", "天空之脊", "狼的末路", "天空之傲", "风鹰剑", "天空之刃",
}
_GENSHIN_LIMITED_STANDARD_WINDOWS = {
    "刻晴": ("2021-02-17 18:00:00", "2021-03-02 15:59:59"),
    "提纳里": ("2022-08-24 09:00:00", "2022-09-09 17:59:59"),
    "迪希雅": ("2023-03-01 09:00:00", "2023-03-21 17:59:59"),
    "梦见月瑞希": ("2025-02-12 09:00:00", "2025-03-04 17:59:59"),
}


def _genshin_is_up(item: Dict[str, Any], pool: str) -> bool:
    if pool == "常驻祈愿" or pool == "新手祈愿":
        return False
    name = str(item.get("name", ""))
    if name in _GENSHIN_LIMITED_STANDARD_WINDOWS:
        try:
            pull_time = datetime.strptime(str(item.get("time", "")), "%Y-%m-%d %H:%M:%S")
            start, end = _GENSHIN_LIMITED_STANDARD_WINDOWS[name]
            return datetime.strptime(start, "%Y-%m-%d %H:%M:%S") <= pull_time <= datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
    return name not in _GENSHIN_STANDARD_ITEMS


def _genshin_mood_level(pool: str, average: float) -> int:
    limits = [54, 61, 67, 73, 80] if pool == "常驻祈愿" else [62, 75, 88, 99, 111] if pool == "武器祈愿" else [74, 87, 99, 105, 120]
    if average <= 0:
        return 3
    for index, limit in enumerate(limits):
        if average <= limit:
            return 5 - index
    return 1


_GENSHIN_MOOD_TAGS = ("非到极致", "运气不好", "平稳保底", "小欧一把", "欧狗在此")


async def _cache_genshin_icons(data: Dict[str, List[Dict[str, Any]]], proxy: Optional[str]) -> Dict[str, Path]:
    item_index = _genshin_item_index()
    result: Dict[str, Path] = {}
    pending: Dict[str, Tuple[str, str]] = {}
    for item in _genshin_gold_items(data):
        item_id = str(item.get("item_id") or "")
        item_type = str(item.get("item_type") or "")
        if item_type not in {"角色", "武器"}:
            item_type = "武器" if "武器" in str(item.get("_pool", "")) else "角色"
        kind = "weapons" if item_type == "武器" else "characters"
        metadata = item_index.get(kind, {}).get(item_id)
        if metadata is None:
            metadata = next((value for value in item_index.get(kind, {}).values()
                             if value.get("name") == item.get("name")), None)
        icon = str((metadata or {}).get("icon") or "")
        if not icon or not re.fullmatch(r"[A-Za-z0-9_]+", icon):
            continue
        safe_item_id = item_id if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", item_id) else icon
        path = GENSHIN_ASSET_ROOT / f"{item_type}_{safe_item_id}.png"
        result[str(item.get("id") or f"{item.get('name')}:{item.get('time')}")] = path
        if not path.is_file():
            pending[str(path)] = (icon, str(path))

    if not pending:
        return result
    GENSHIN_ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    options = _proxy_options(proxy)
    options.update(timeout=_request_timeout(), follow_redirects=True)
    semaphore = asyncio.Semaphore(8)

    async with httpx.AsyncClient(**options) as client:
        async def download(icon: str, path_text: str) -> None:
            async with semaphore:
                try:
                    response = await client.get(f"https://enka.network/ui/{icon}.png")
                    response.raise_for_status()
                    image = Image.open(BytesIO(response.content))
                    image.verify()
                    Path(path_text).write_bytes(response.content)
                except (httpx.HTTPError, OSError, ValueError) as error:
                    logger.debug(f"原神抽卡图标缓存失败 {icon}: {type(error).__name__}")

        await asyncio.gather(*(download(icon, path) for icon, path in pending.values()))
    return result


def _pool_stats(items: List[Dict[str, Any]], pool: str = "") -> Dict[str, Any]:
    chronological = sorted((item for item in items if isinstance(item, dict)), key=_record_sort_key)
    gold_items: List[Dict[str, Any]] = []
    pity = 0
    gaps: List[int] = []
    up_count = 0
    for item in chronological:
        pity += 1
        if str(item.get("rank_type", "")) != "5":
            continue
        enriched = dict(item)
        enriched["_pity"] = pity
        enriched["_is_up"] = _genshin_is_up(enriched, pool or str(item.get("pool", "")))
        gold_items.append(enriched)
        if len(gold_items) > 1:
            gaps.append(pity)
            if enriched["_is_up"]:
                up_count += 1
        pity = 0
    times: List[datetime] = []
    for item in chronological:
        try:
            times.append(datetime.strptime(str(item.get("time", "")), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
    short_gaps = 0
    long_gaps = 0
    for previous, current in zip(times, times[1:]):
        distance = (current - previous).total_seconds()
        if distance <= 5000:
            short_gaps += 1
        elif distance >= 86400:
            long_gaps += 1
    all_time = (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0
    if len(chronological) <= 40:
        pull_type = "佛系型"
    elif long_gaps / len(chronological) >= 0.7:
        pull_type = "随缘型"
    elif short_gaps / len(chronological) >= 0.7:
        pull_type = "规划型"
    elif all_time / 30000 <= len(chronological):
        pull_type = "规划型" if long_gaps >= short_gaps else "氪金型"
    elif all_time / 32000 >= len(chronological) * 2:
        pull_type = "仓鼠型"
    else:
        pull_type = "一般型"

    return {
        "total": len(chronological),
        "pity": pity,
        "gold": gold_items,
        "average": sum(gaps) / len(gaps) if gaps else 0,
        "average_up": sum(gaps) / up_count if up_count else 0,
        "pull_type": pull_type,
        "time_range": f"{chronological[0].get('time', '')}~{chronological[-1].get('time', '')}" if chronological else "",
    }


def _genshin_pool_columns(pools: List[str], heights: Dict[str, int]) -> Tuple[List[str], List[str]]:
    if len(pools) < 2:
        return pools, []
    best = None
    selected: Tuple[List[str], List[str]] = (pools, [])
    for mask in range(1, (1 << len(pools)) - 1):
        left = [pool for index, pool in enumerate(pools) if mask & (1 << index)]
        right = [pool for index, pool in enumerate(pools) if not mask & (1 << index)]
        left_height = sum(heights[pool] for pool in left)
        right_height = sum(heights[pool] for pool in right)
        score = (max(left_height, right_height), abs(left_height - right_height), len(left))
        if best is None or score < best:
            best, selected = score, (left, right)
    return selected


def _draw_genshin_card(
    uid: str,
    payload: Dict[str, Any],
    icon_paths: Dict[str, Path],
    avatar_data: Optional[bytes] = None,
    role: Any = None,
) -> Path:
    data = payload.get("data") or {}
    stats = {pool: _pool_stats(items or [], pool) for pool, items in data.items()}
    pools = [pool for pool, info in stats.items() if info["total"]]
    total_gold = sum(len(stats[pool]["gold"]) for pool in pools)
    card_cols, card_dx, card_row_h = 6, 138, 150
    title_h, card_y0 = 300, 275
    block_heights = {pool: title_h + ((len(stats[pool]["gold"]) + card_cols - 1) // card_cols) * card_row_h for pool in pools}
    two_columns = total_gold >= 41 and len(pools) > 1
    left_pools, right_pools = _genshin_pool_columns(pools, block_heights) if two_columns else (pools, [])
    col_width, width = 950, 1900 if right_pools else 950
    header_h, bottom_pad = 430, 80
    content_height = max(sum(block_heights[name] for name in left_pools), sum(block_heights[name] for name in right_pools), 0)
    height = header_h + content_height + bottom_pad

    canvas = Image.new("RGB", (width, height), (229, 225, 213))
    draw = ImageDraw.Draw(canvas)
    top, bottom = (242, 236, 220), (204, 218, 229)
    for y in range(header_h):
        ratio = y / max(header_h - 1, 1)
        color = tuple(round(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    header_texture = Image.open(GENSHIN_TEXTURE_ROOT / "avatar_title.png").convert("RGBA").resize(
        (950, header_h), Image.Resampling.LANCZOS)
    title_texture = Image.open(GENSHIN_TEXTURE_ROOT / "gahca_title.png").convert("RGBA")
    item_texture = Image.open(GENSHIN_TEXTURE_ROOT / "item_bg.png").convert("RGBA")
    up_texture = Image.open(GENSHIN_TEXTURE_ROOT / "up.png").convert("RGBA")
    draw_font = _font(25)
    small_font = _font(20)
    tag_font = _font(32)
    title_font = _font(34)
    latest_gold = _genshin_gold_items(data)
    fallback_avatar = icon_paths.get(
        str(latest_gold[0].get("id") or f"{latest_gold[0].get('name')}:{latest_gold[0].get('time')}")
    ) if latest_gold else None

    header_x = (width - col_width) // 2
    canvas.paste(header_texture, (header_x, 0), header_texture)
    draw.text((header_x + 475, 53), "原神祈愿记录", font=title_font, fill=(53, 46, 40), anchor="mm")
    avatar = Image.new("RGBA", (220, 220), (215, 207, 192))
    avatar_draw = ImageDraw.Draw(avatar)
    avatar_draw.ellipse((76, 39, 144, 107), fill=(155, 146, 130))
    avatar_draw.ellipse((35, 124, 185, 250), fill=(155, 146, 130))
    avatar_source = BytesIO(avatar_data) if avatar_data else fallback_avatar
    if avatar_source and (isinstance(avatar_source, BytesIO) or avatar_source.is_file()):
        try:
            with Image.open(avatar_source) as source:
                avatar = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"),
                                      (220, 220), method=Image.Resampling.LANCZOS)
        except OSError:
            pass
    mask = Image.new("L", avatar.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 219, 219), fill=255)
    canvas.paste(avatar, (header_x + 100, 125), mask)

    name_font, info_font = _font(38), _font(28)
    nickname = str(getattr(role, "nickname", None) or "旅行者")
    nickname = _fit_label(nickname, name_font, 250)
    name_x = header_x + 355
    draw.text((name_x, 190), nickname, font=name_font, fill=(53, 46, 40), anchor="lm")
    badge_x = round(name_x + draw.textlength(nickname, font=name_font) + 20)
    level = getattr(role, "level", None)
    region = str(getattr(role, "region_name", None) or ("世界树" if uid.startswith("5") else "天空岛"))
    draw.rounded_rectangle((badge_x, 171, badge_x + 100, 210), 10, (224, 187, 111))
    draw.rounded_rectangle((badge_x + 112, 171, badge_x + 266, 210), 10, (158, 193, 203))
    draw.text((badge_x + 50, 190), f"Lv.{level}" if level is not None else "Lv.?",
              font=info_font, fill=(53, 46, 40), anchor="mm")
    draw.text((badge_x + 189, 190), _fit_label(region, info_font, 144),
              font=info_font, fill=(53, 46, 40), anchor="mm")
    draw.text((name_x, 263), f"UID {uid}", font=draw_font, fill=(83, 76, 68), anchor="lm")

    for column_pools, base_x in ((left_pools, 0), (right_pools, col_width)):
        current_y = header_h
        for pool in column_pools:
            info = stats[pool]
            title = title_texture.copy()
            title_draw = ImageDraw.Draw(title)
            title_draw.text((68, 72), pool, font=_font(48), fill=(29, 29, 29), anchor="lm")
            title_draw.text((68, 122), info["time_range"] or "暂未抽过卡!", font=small_font,
                            fill=(41, 25, 0), anchor="lm")
            title_draw.text((123, 176), f"{info['average']:.2f}" if info["average"] else "0",
                            font=_font(34), fill=(29, 29, 29), anchor="mm")
            title_draw.text((272, 176), f"{info['average_up']:.2f}" if info["average_up"] else "0",
                            font=_font(34), fill=(29, 29, 29), anchor="mm")
            title_draw.text((424, 176), str(info["total"]), font=_font(34), fill=(29, 29, 29), anchor="mm")
            title_draw.text((585, 176), info["pull_type"], font=_font(30), fill=(29, 29, 29), anchor="mm")
            title_draw.text((383, 85), str(info["pity"]), font=small_font,
                            fill=(74, 189, 119), anchor="mm")
            mood_value = info["average"] if pool == "常驻祈愿" else info["average_up"]
            mood_level = _genshin_mood_level(pool, mood_value)
            mood_dir = GENSHIN_TEXTURE_ROOT / str(mood_level)
            moods = sorted(mood_dir.glob("*.png"))
            if moods:
                selector = sum(ord(char) for char in f"{uid}:{pool}") % len(moods)
                mood = Image.open(moods[selector]).convert("RGBA").resize((154, 154), Image.Resampling.LANCZOS)
                title.alpha_composite(mood, (703, 28))
            title_draw.text((778, 207), _GENSHIN_MOOD_TAGS[mood_level - 1], font=_font(27), fill=(29, 29, 29), anchor="mm")
            canvas.paste(title, (base_x, current_y), title)

            newest_items = list(reversed(info["gold"]))
            for index, item in enumerate(newest_items):
                x = base_x + 60 + (index % card_cols) * card_dx
                y = current_y + card_y0 + (index // card_cols) * card_row_h
                card = item_texture.copy()
                key = str(item.get("id") or f"{item.get('name')}:{item.get('time')}")
                icon_path = icon_paths.get(key)
                if icon_path and icon_path.is_file():
                    try:
                        icon = Image.open(icon_path).convert("RGBA").resize((108, 108), Image.Resampling.LANCZOS)
                        card.alpha_composite(icon, (1, 0))
                    except OSError:
                        pass
                card_draw = ImageDraw.Draw(card)
                pity = int(item.get("_pity", 0))
                pity_color = (255, 66, 66) if pity >= 81 else (74, 189, 119) if pity <= 55 else (41, 25, 0)
                card_draw.text((55, 124), f"{pity}抽", font=small_font, fill=pity_color, anchor="mm")
                if item.get("_is_up"):
                    card.alpha_composite(up_texture, (47, -2))
                canvas.paste(card, (x, y), card)
            current_y += block_heights[pool]

    draw = ImageDraw.Draw(canvas)
    draw.text((width // 2, height - 34), "function by manshuo", font=small_font,
              fill=(112, 105, 97), anchor="mm")
    path = data_path / "pictures" / "cache" / f"原神_gacha_{uuid4().hex}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path


async def _get_qq_avatar(user_id: str, proxy: Optional[str]) -> Optional[bytes]:
    options = _proxy_options(proxy)
    options.update(timeout=5.0, follow_redirects=True)
    try:
        async with httpx.AsyncClient(**options) as client:
            response = await client.get(
                "https://q1.qlogo.cn/g",
                params={"b": "qq", "nk": str(user_id), "s": "640"},
            )
            response.raise_for_status()
            image = Image.open(BytesIO(response.content))
            image.verify()
            return response.content
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _get_genshin_role(account: UserAccount, uid: str) -> Any:
    """仅查询抽卡 UID 对应的游戏昵称、等级和区服，不回写账号数据。"""
    try:
        status, records = await asyncio.wait_for(
            get_game_record(account, retry=False), timeout=min(_request_timeout(), 8.0))
        if status:
            return next((record for record in records or []
                         if record.game_id == 2 and str(record.game_role_id) == uid), None)
    except Exception as error:
        logger.debug(f"原神抽卡角色资料获取失败 ({type(error).__name__})")
    return None


def _render(game: str, uid: str, payload: Dict[str, Any]) -> Path:
    data = payload.get("data") or {}
    rows = [(pool, item) for pool, items in data.items() for item in (items or []) if str(item.get("rank_type", "")) in {"4", "5", "S", ""}]
    rows.sort(key=lambda value: _record_sort_key(value[1]), reverse=True)
    rows = rows[:20]
    width = 1500
    height = max(710, 205 + ((len(data) + 1) // 2) * 80 + len(rows) * 70 + 80)
    canvas = Image.new("RGB", (width, height), (29, 37, 47))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype(str(FONT_PATH), 48)
        body_font = ImageFont.truetype(str(FONT_PATH), 26)
    except OSError:
        title_font = body_font = ImageFont.load_default()
    draw.text((50, 40), f"{game} · 抽卡记录", fill=(255, 210, 92), font=title_font)
    draw.text((52, 115), f"UID {uid}    本地共 {sum(len(v) for v in data.values())} 抽    同步时间 {payload.get('data_time') or '未知'}", fill=(220, 225, 230), font=body_font)
    pool_items = list(data.items())
    card_w, card_h, gap = 680, 68, 28
    for index, (pool, items) in enumerate(pool_items):
        column, row = index % 2, index // 2
        x, y = 50 + column * (card_w + gap), 175 + row * 80
        items = list(items or [])
        five_index = next((i for i, item in enumerate(items) if str(item.get("rank_type", "")) == "5"), None)
        pity = str(five_index if five_index is not None else len(items))
        five_count = sum(str(item.get("rank_type", "")) == "5" for item in items)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=12, fill=(43, 54, 66), outline=(102, 184, 211))
        stats = f"{pool}  ·  {len(items)} 抽  ·  5星 {five_count}  ·  距5星 {pity} 抽"
        draw.text((x + 18, y + 18), stats, fill=(245, 226, 162), font=body_font)
    y = 205 + ((len(pool_items) + 1) // 2) * 80
    for pool, item in rows:
        draw.rounded_rectangle((50, y, width - 50, y + 54), radius=9, fill=(43, 54, 66), outline=(102, 184, 211))
        draw.text((75, y + 13), f"{pool}  ·  {item.get('name', '未知')}  ·  {item.get('time', '')}", fill=(245, 246, 247), font=body_font)
        y += 70
    draw.text((width // 2, height - 36), "function by manshuo", fill=(170, 180, 190), font=body_font, anchor="mm")
    path = data_path / "pictures" / "cache" / f"{game}_gacha_{uuid4().hex}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path


async def _send(bot, event, user_id: str, message: Any, recall=False) -> None:
    if bot and event:
        recall_id = await bot.send(event, message)
        if recall and recall_id:
            await asyncio.sleep(50)
            await bot.recall(recall_id['data']['message_id'])
    else:
        print(message)


def _targets(user_id: str, game: str, requested: Optional[str]) -> List[Tuple[UserAccount, str]]:
    user = (PluginDataManager.plugin_data.users or {}).get(str(user_id))
    if not user:
        return []
    accounts_by_uid: Dict[str, UserAccount] = {}
    for account in user.accounts.values():
        for uid in _uid_items(account, game):
            if requested and requested != uid:
                continue
            current = accounts_by_uid.get(uid)
            if current is None or (not current.cookies or not current.cookies.stoken) and account.cookies and account.cookies.stoken:
                accounts_by_uid[uid] = account
    return [(account, uid) for uid, account in accounts_by_uid.items()]


async def handle_game_card_command(context: str, user_id: str, target: str, bot=None, event=None, proxy: Optional[str] = None) -> bool:
    if target not in GAME_CONFIG:
        return False
    text = (context or "").strip()
    aliases = sorted(game_name_list.get(target, []), key=len, reverse=True)
    for alias in aliases:
        if text.casefold().startswith(alias.casefold()):
            text = text[len(alias):].strip()
            break
    else:
        return False
    match = re.search(r"(?<!\d)(\d{8,10})(?!\d)", text)
    requested = match.group(1) if match else None
    if match:
        text = text[:match.start()] + text[match.end():]
    text = re.sub(r"(?i)^uid[:：]?", "", text).strip()
    full_refresh = any(key in text for key in ("全量刷新抽卡记录", "全量更新抽卡记录"))
    action = "refresh" if any(key in text for key in ("刷新抽卡记录", "更新抽卡记录", "全量刷新抽卡记录", "全量更新抽卡记录")) else "show" if text in ("抽卡记录", "查看抽卡记录") else None
    if action is None:
        return False
    targets = _targets(str(user_id), target, requested)
    if not targets:
        await _send(bot, event, str(user_id), f"未找到已保存的{target}角色 UID，请重新登录米游社以更新角色数据")
        return True
    if len(targets) > 1 and not requested:
        await _send(bot, event, str(user_id), "检测到多个角色 UID，请在指令中指定 UID")
        return True
    account, uid = targets[0]
    if not account.cookies or not account.cookies.stoken:
        await _send(bot, event, str(user_id), "米游社账号缺少 Stoken，请重新登录绑定")
        return True
    lock = _LOCKS.setdefault(f"{target}:{uid}", asyncio.Lock())
    try:
        if action == "refresh" or not _cache_path(target, uid).exists():
            await _send(bot, event, str(user_id), f"正在获取{target}抽卡记录，请耐心等待喵",recall=True)
            async with lock:
                added, total = await _refresh(target, account, uid, proxy, full_refresh=full_refresh)
            if action == "refresh":
                await _send(bot, event, str(user_id), f" 抽卡记录更新完成喵：新增 {added} 条，本地共 {total} 条")
                return True
        payload = await asyncio.to_thread(_load, target, uid)
        if not any(payload.get("data", {}).values()):
            await _send(bot, event, str(user_id), f" 暂无抽卡记录")
            return True
        if target == "原神":
            icon_paths, avatar_data, role = await asyncio.gather(
                _cache_genshin_icons(payload.get("data") or {}, proxy),
                _get_qq_avatar(str(user_id), proxy),
                _get_genshin_role(account, uid),
            )
            image_path = await asyncio.to_thread(_draw_genshin_card, uid, payload, icon_paths, avatar_data, role)
        else:
            image_path = await asyncio.to_thread(_render, target, uid, payload)
        try:
            await _send(bot, event, str(user_id), [At(qq=str(user_id)), CQImage(file=str(image_path))])
        finally:
            image_path.unlink(missing_ok=True)
    except (httpx.HTTPError, ValueError, OSError) as error:
        logger.warning(f"{target}抽卡记录请求失败 UID={uid}：{type(error).__name__}")
        await _send(bot, event, str(user_id), f"获取{target}抽卡记录失败，请稍后重试")
    return True


__all__ = ["handle_game_card_command"]
