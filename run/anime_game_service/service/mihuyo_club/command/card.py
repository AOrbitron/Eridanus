"""绝区零国服抽卡记录查询与绘制。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import httpx
from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from developTools.message.message_components import At, Image
from developTools.utils.logger import get_logger

from ..api.common import get_game_record
from ..model import PluginDataManager, UserAccount, data_path, plugin_config, plugin_env
from ..utils import generate_device_id, generate_ds
from ..utils.zzz_gacha import fetch_gacha_statistics, has_statistics_overlap, merge_pool_summary
from .config import game_name_list

__all__ = ["handle_card_command"]

logger = get_logger("MiHoYo")

AUTHKEY_URL = "https://api-takumi.mihoyo.com/binding/api/genAuthKey"
GACHA_LOG_URL = "https://public-operation-nap.mihoyo.com/common/gacha_record/api/getGachaLog"
GACHA_ID = "2c1f5692fdfbb733a08733f9eb69d32aed1d37"
PAGE_SIZE = 20
MAX_PAGES_PER_POOL = 999
PAGE_INTERVAL = 0.9

POOL_CONFIG: Tuple[Tuple[str, str, str], ...] = (
    ("音擎频段", "3001", "3"),
    ("独家频段", "2001", "2"),
    ("常驻频段", "1001", "1"),
    ("邦布频段", "5001", "5"),
    ("独家重映", "12002", "102"),
    ("音擎回响", "13002", "103"),
)
OPTIONAL_POOLS = {"独家重映", "音擎回响"}
SERVER_BY_UID_PREFIX = {
    "10": "prod_gf_us",
    "13": "prod_gf_jp",
    "15": "prod_gf_eu",
    "17": "prod_gf_sg",
}

GACHA_ROOT = data_path / "ZZZ" / "gacha"
PLAYER_ROOT = GACHA_ROOT / "players"
ASSET_ROOT = GACHA_ROOT / "assets"
CARD_ROOT = GACHA_ROOT / "cards"
NOTE_ASSET_ROOT = Path(__file__).resolve().parents[1] / "utils" / "resources" / "zzz_note"
GACHA_ASSET_ROOT = Path(__file__).resolve().parents[1] / "utils" / "resources" / "zzz_gacha"
GACHA_TEXTURE_ROOT = GACHA_ASSET_ROOT / "texture2d"
FONT_PATH = NOTE_ASSET_ROOT / "zzz_fonts.ttf"

# Nanoka 的国服绝区零数据接口同时提供邦布和音擎的图标索引。版本号与
# 上游 ZZZeroUID 的资源版本保持一致，更新资源时只需调整这一处。
NANOKA_DATA_VERSION = "3.4.3+20291004"
NANOKA_ZH_ROOT = f"https://static.nanoka.cc/zzz/{NANOKA_DATA_VERSION}/zh"
NANOKA_ASSET_ROOT = "https://static.nanoka.cc/assets/zzz"
NORMAL_ZZZ_S_ITEMS = {"「11号」", "猫又", "莱卡恩", "丽娜", "格莉丝", "珂蕾妲",
                      "拘缚者", "燃狱齿轮", "嵌合编译器", "钢铁肉垫", "硫磺石", "啜泣摇篮"}

_UID_LOCKS: Dict[str, asyncio.Lock] = {}


class GachaRequestError(Exception):
    """An upstream response cannot be used as gacha data."""


def _proxy_options(proxy: Optional[str]) -> Dict[str, Any]:
    if not proxy:
        return {}
    return {"proxies": {"http://": proxy, "https://": proxy}}


def _request_timeout() -> float:
    return float(plugin_config.preference.timeout or 15)


def _region_for_uid(uid: str) -> str:
    if len(uid) < 10:
        return "prod_gf_cn"
    return SERVER_BY_UID_PREFIX.get(uid[:2], "prod_gf_cn")


def _account_cookies(account: UserAccount) -> Dict[str, str]:
    cookies = account.cookies
    if not cookies or not cookies.stoken:
        raise GachaRequestError("米游社账号缺少 Stoken，请重新登录绑定")
    cookie_data = {
        str(key): str(value)
        for key, value in cookies.dict(v2_stoken=True, cookie_type=True).items()
        if value
    }
    if cookies.bbs_uid:
        for key in ("stuid", "ltuid", "account_id", "login_uid", "ltuid_v2", "account_id_v2"):
            cookie_data.setdefault(key, str(cookies.bbs_uid))
    if cookies.stoken_v2:
        cookie_data.setdefault("stoken_v2", str(cookies.stoken_v2))
    if cookies.stoken_v1:
        cookie_data.setdefault("stoken_v1", str(cookies.stoken_v1))
    if cookies.cookie_token_v2 or cookies.cookie_token:
        selected_cookie_token = str(cookies.cookie_token_v2 or cookies.cookie_token)
        cookie_data.setdefault("cookie_token", selected_cookie_token)
        cookie_data.setdefault("cookie_token_v2", selected_cookie_token)
    if cookies.mid:
        cookie_data.setdefault("account_mid_v2", str(cookies.mid))
        cookie_data.setdefault("ltmid_v2", str(cookies.mid))
    if cookies.ltoken_v2 or cookies.ltoken:
        selected_ltoken = str(cookies.ltoken_v2 or cookies.ltoken)
        cookie_data.setdefault("ltoken", selected_ltoken)
        cookie_data.setdefault("ltoken_v2", selected_ltoken)
    return cookie_data


def _authkey_headers(account: UserAccount) -> Dict[str, str]:
    device = account.device_id_ios or account.device_id_android or generate_device_id()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=utf-8",
        "User-Agent": plugin_env.device_config.USER_AGENT_OTHER,
        "Origin": "https://app.mihoyo.com",
        "Referer": "https://app.mihoyo.com/",
        "x-rpc-app_version": plugin_env.device_config.X_RPC_APP_VERSION,
        "x-rpc-channel": "mihoyo",
        "x-rpc-client_type": "5",
        "x-rpc-device_id": device,
        "x-rpc-device_model": plugin_env.device_config.X_RPC_DEVICE_MODEL_MOBILE,
        "x-rpc-device_name": plugin_env.device_config.X_RPC_DEVICE_NAME_MOBILE,
        "x-rpc-platform": "ios",
        "x-rpc-sys_version": plugin_env.device_config.X_RPC_SYS_VERSION,
        "x-rpc-app_id": "bll8iq97cem8",
        "x-rpc-game_biz": "bbs_cn",
        "DS": generate_ds(),
    }
    if account.device_fp:
        headers["x-rpc-device_fp"] = account.device_fp
    return headers


def _raise_for_api_error(payload: Dict[str, Any], action: str) -> None:
    retcode = payload.get("retcode", 0)
    if retcode in (0, "0"):
        return
    if retcode in (-100, 10001, "-100", "10001"):
        raise GachaRequestError("米游社登录凭据已失效，请重新登录绑定")
    raise GachaRequestError(f"{action}失败（米游社返回 {retcode}）")


async def _get_authkey(client: httpx.AsyncClient, account: UserAccount, uid: str) -> str:
    body = {
        "auth_appid": "webview_gacha",
        "game_biz": "nap_cn",
        "game_uid": uid,
        "region": _region_for_uid(uid),
    }
    response = await client.post(
        AUTHKEY_URL,
        json=body,
        cookies=_account_cookies(account),
        headers=_authkey_headers(account),
        timeout=_request_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise GachaRequestError("米游社授权接口返回格式异常")
    _raise_for_api_error(payload, "获取抽卡授权")
    authkey = ((payload.get("data") or {}).get("authkey"))
    if not authkey:
        raise GachaRequestError("米游社未返回抽卡授权，请重新登录后再试")
    return str(authkey)


async def _get_gacha_page(
    client: httpx.AsyncClient,
    uid: str,
    authkey: str,
    gacha_type: str,
    base_type: str,
    page: int,
    end_id: str,
) -> List[Dict[str, Any]]:
    params = {
        "authkey_ver": "1",
        "sign_type": "2",
        "auth_appid": "webview_gacha",
        "init_log_gacha_type": gacha_type,
        "init_log_gacha_base_type": base_type,
        "gacha_id": GACHA_ID,
        "timestamp": str(int(time.time())),
        "lang": "zh-cn",
        "device_type": "mobile",
        "plat_type": "ios",
        "region": _region_for_uid(uid),
        "authkey": authkey,
        "game_biz": "nap_cn",
        "gacha_type": gacha_type,
        "real_gacha_type": base_type,
        "page": page,
        "size": PAGE_SIZE,
        "end_id": end_id,
    }
    response = await client.get(
        GACHA_LOG_URL,
        params=params,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": plugin_env.device_config.USER_AGENT_MOBILE,
            "Origin": "https://public-operation-nap.mihoyo.com",
            "Referer": "https://webstatic.mihoyo.com/",
        },
        timeout=_request_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise GachaRequestError("抽卡记录接口返回格式异常")
    _raise_for_api_error(payload, "拉取抽卡记录")
    rows = ((payload.get("data") or {}).get("list")) or []
    if not isinstance(rows, list):
        raise GachaRequestError("抽卡记录列表格式异常")
    return [dict(row) for row in rows if isinstance(row, dict)]


def _record_id(item: Dict[str, Any]) -> str:
    value = item.get("id")
    return str(value) if value is not None else ""


def _sort_records(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]) -> Tuple[int, str]:
        value = _record_id(item)
        try:
            return int(value), value
        except ValueError:
            return 0, value

    return sorted(items, key=key, reverse=True)


async def _fetch_and_merge(
    client: httpx.AsyncClient,
    uid: str,
    authkey: str,
    existing_data: Dict[str, List[Dict[str, Any]]],
    full_refresh: bool,
    statistics: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, List[Dict[str, Any]]], int, List[str]]:
    merged: Dict[str, List[Dict[str, Any]]] = {
        name: _sort_records(list(items or []))
        for name, items in existing_data.items()
        if isinstance(items, list)
    }
    for name, _, _ in POOL_CONFIG:
        merged.setdefault(name, [])
    added_count = 0
    warnings: List[str] = []

    for pool_name, gacha_type, base_type in POOL_CONFIG:
        by_id = {
            _record_id(item): dict(item)
            for item in merged[pool_name]
            if _record_id(item)
        }
        end_id = "0"
        try:
            for page in range(1, MAX_PAGES_PER_POOL + 1):
                rows = await _get_gacha_page(
                    client, uid, authkey, gacha_type, base_type, page, end_id
                )
                await asyncio.sleep(PAGE_INTERVAL)
                if not rows:
                    break

                reached_cached_record = False
                for row in rows:
                    row_id = _record_id(row)
                    if not row_id:
                        continue
                    if row_id in by_id:
                        current = by_id[row_id]
                        current.update(row)
                        reached_cached_record = True
                    else:
                        by_id[row_id] = row
                        added_count += 1

                next_end_id = _record_id(rows[-1])
                if not next_end_id or next_end_id == end_id:
                    break
                if reached_cached_record and not full_refresh:
                    break
                if statistics and not full_refresh:
                    try:
                        if has_statistics_overlap(rows, pool_name, statistics):
                            break
                    except (ValueError, TypeError, KeyError):
                        # 无法识别的统计缓存不应截断旧接口分页。
                        pass
                end_id = next_end_id
            else:
                warnings.append(f"{pool_name}已达到单卡池分页上限")
        except (httpx.HTTPError, GachaRequestError, ValueError) as error:
            if pool_name in OPTIONAL_POOLS:
                merged[pool_name] = _sort_records(list(by_id.values()))
                warnings.append(f"{pool_name}暂时无法获取")
                logger.warning(f"绝区零抽卡记录可选卡池失败：{pool_name} ({type(error).__name__})")
                continue
            raise
        merged[pool_name] = _sort_records(list(by_id.values()))

    return merged, added_count, warnings


def _cache_path(uid: str) -> Path:
    return PLAYER_ROOT / f"{uid}.json"


def _load_cache_sync(uid: str) -> Dict[str, Any]:
    path = _cache_path(uid)
    if not path.exists():
        return {"uid": uid, "data_time": None, "data": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GachaRequestError("本地抽卡记录读取失败，请删除损坏的记录后重新更新") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data", {}), dict):
        raise GachaRequestError("本地抽卡记录格式错误，请重新更新")
    return payload


def _write_cache_sync(uid: str, payload: Dict[str, Any], full_refresh: bool) -> None:
    path = _cache_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    if full_refresh and path.exists():
        backup_dir = path.parent / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, backup_dir / f"{uid}_{stamp}.json")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def refresh_zzz_gacha_records(
    account: UserAccount,
    uid: str,
    proxy: Optional[str] = None,
    full_refresh: bool = False,
    statistics_only: bool = False,
) -> Tuple[int, int, List[str]]:
    old_payload = await asyncio.to_thread(_load_cache_sync, uid)
    old_data = old_payload.get("data") or {}
    if not isinstance(old_data, dict):
        raise GachaRequestError("本地抽卡记录格式错误，请重新更新")
    previous_summaries = _gacha_summaries(old_payload)
    payload = dict(old_payload)
    warnings: List[str] = []
    updated = False
    request_statistics = full_refresh or statistics_only
    request_legacy = full_refresh or not statistics_only

    client_options = _proxy_options(proxy)
    client_options.update(timeout=_request_timeout())
    async with httpx.AsyncClient(**client_options) as client:
        if request_statistics:
            try:
                payload["statistics"] = await fetch_gacha_statistics(
                    client, uid, _region_for_uid(uid), _account_cookies(account),
                    {"Accept": "application/json, text/plain, */*",
                     "User-Agent": plugin_env.device_config.USER_AGENT_MOBILE,
                     "Origin": "https://act.mihoyo.com", "Referer": "https://act.mihoyo.com/"},
                    _request_timeout(),
                )
                updated = True
            except (httpx.HTTPError, GachaRequestError, ValueError) as error:
                logger.warning(f"绝区零调频统计接口失败，保留历史统计 ({type(error).__name__})")
                warnings.append("新接口暂时不可用，已保留历史统计")

        if request_legacy:
            try:
                authkey = await _get_authkey(client, account, uid)
                data, _, legacy_warnings = await _fetch_and_merge(
                    client, uid, authkey, old_data,
                    full_refresh, statistics=payload.get("statistics"),
                )
                payload["data"] = data
                payload["legacy_data_time"] = datetime.now().astimezone().isoformat(timespec="seconds")
                warnings.extend(legacy_warnings)
                updated = True
            except (httpx.HTTPError, GachaRequestError, ValueError) as error:
                logger.warning(f"绝区零逐抽记录接口失败，保留已有记录 ({type(error).__name__})")
                warnings.append("旧接口暂时不可用，已保留本地逐抽记录")

    if not updated:
        source = "新旧抽卡接口均" if request_statistics and request_legacy else "调频统计接口" if request_statistics else "逐抽记录接口"
        raise GachaRequestError(f"{source}未更新成功，已保留本地数据，请稍后重试")
    payload.update(uid=uid, data_time=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
    payload.setdefault("data", old_data)
    summaries = _gacha_summaries(payload)
    for summary in summaries.values():
        warnings.extend(summary["warnings"])
    await asyncio.to_thread(_write_cache_sync, uid, payload, full_refresh)
    added_count = sum(max(0, summary["total"] - previous_summaries[name]["total"])
                      for name, summary in summaries.items())
    new_count = sum(summary["total"] for summary in summaries.values())
    return added_count, new_count, list(dict.fromkeys(warnings))


def _uid_items(account: UserAccount) -> List[str]:
    values = (account.game_uids or {}).get("ZenlessZoneZero", [])
    if isinstance(values, (str, int)):
        values = [values]
    return list(dict.fromkeys(str(value) for value in values if str(value).isdigit()))


def _parse_card_action(text: str) -> Tuple[Optional[str], Optional[str], bool]:
    normalized = re.sub(r"\s+", "", text)
    uid_match = re.search(r"(?<!\d)(\d{8,10})(?!\d)", normalized)
    uid = uid_match.group(1) if uid_match else None
    if uid_match:
        normalized = normalized[:uid_match.start()] + normalized[uid_match.end():]
    normalized = re.sub(r"(?i)^uid[:：]?", "", normalized)
    actions = {
        "抽卡记录": ("show", False),
        "查看抽卡记录": ("show", False),
        "刷新抽卡记录": ("refresh", False),
        "更新抽卡记录": ("refresh", False),
        "全量刷新抽卡记录": ("refresh", True),
        "全量更新抽卡记录": ("refresh", True),
    }
    action = actions.get(normalized)
    return (action[0], uid, action[1]) if action else (None, uid, False)


def _summary(records: List[Dict[str, Any]], pool_name: str = "") -> Dict[str, Any]:
    chronological = list(reversed(_sort_records(records)))
    pulls_since_s = 0
    s_items: List[Dict[str, Any]] = []
    up_items: List[Dict[str, Any]] = []
    for item in chronological:
        pulls_since_s += 1
        if str(item.get("rank_type", "")) == "4":
            entry = dict(item)
            entry["_pull_count"] = pulls_since_s
            entry["_is_up"] = pool_name != "常驻频段" and str(item.get("name") or "") not in NORMAL_ZZZ_S_ITEMS
            s_items.append(entry)
            if entry["_is_up"]:
                up_items.append(entry)
            pulls_since_s = 0
    pull_counts = [item["_pull_count"] for item in s_items]
    first_time = str(chronological[0].get("time") or "") if chronological else ""
    last_time = str(chronological[-1].get("time") or "") if chronological else ""
    if first_time:
        try:
            first_time = datetime.fromisoformat(first_time).strftime("%Y-%m-%d")
            last_time = datetime.fromisoformat(last_time).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return {
        "total": len(records),
        "pity": pulls_since_s,
        "s_items": list(reversed(s_items)),
        "average": round(sum(pull_counts) / len(pull_counts), 2) if pull_counts else None,
        "average_up": round(sum(pull_counts) / len(up_items), 2) if up_items else None,
        "time_range": f"{first_time}~{last_time}" if first_time else "",
    }


def _gacha_summaries(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    data = payload.get("data") or {}
    snapshot = payload.get("statistics") or {}
    summaries = {}
    for name, _, _ in POOL_CONFIG:
        records = _sort_records(list(data.get(name) or []))
        legacy = _summary(records, name)
        try:
            summaries[name] = merge_pool_summary(records, legacy, name, snapshot)
        except (ValueError, TypeError, KeyError):
            summaries[name] = dict(legacy, warnings=[f"{name}本地统计数据无效，已使用逐抽记录"])
    return summaries


def _item_asset(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    item_id = str(item.get("item_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", item_id):
        return None, None
    item_type = str(item.get("item_type") or "")
    if item_type == "音擎":
        return f"weapon_{item_id}", item_id
    if item_type == "邦布":
        return f"bangboo_{item_id}", item_id
    return f"agent_{item_id}", item_id


def _valid_icon(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with PILImage.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, PILImage.DecompressionBombError):
        path.unlink(missing_ok=True)
        return False


def _image_as_png(content: bytes) -> bytes:
    with PILImage.open(BytesIO(content)) as image:
        image.load()
        output = BytesIO()
        image.convert("RGBA").save(output, format="PNG", optimize=True)
        return output.getvalue()


def _safe_asset_name(value: Any) -> Optional[str]:
    name = Path(str(value or "")).name.rsplit(".", 1)[0]
    return name if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", name) else None


async def _nanoka_item_icon_urls(
    client: httpx.AsyncClient,
    kind: str,
    item_id: str,
) -> List[str]:
    """通过 Nanoka 的国服索引解析音擎/邦布静态图标地址。"""
    try:
        response = await client.get(
            f"{NANOKA_ZH_ROOT}/{kind}/{item_id}.json",
            timeout=_request_timeout(),
        )
        if response.status_code != 200:
            return []
        detail = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(detail, dict):
        return []

    names: List[str] = []
    if kind == "bangboo":
        icon_name = _safe_asset_name(detail.get("icon"))
        if icon_name:
            names.append(icon_name)
    else:
        code_name = _safe_asset_name(detail.get("code_name"))
        if code_name:
            # 音擎抽卡图使用上游与参考项目相同的高清立绘，失败时退回小图。
            names.extend((f"{code_name}Big", code_name))
        icon_name = _safe_asset_name(detail.get("icon"))
        if icon_name:
            names.append(icon_name)
    return [f"{NANOKA_ASSET_ROOT}/{name}.webp" for name in dict.fromkeys(names)]


async def _cache_item_icons(
    client: httpx.AsyncClient,
    summaries: Dict[str, Dict[str, Any]],
) -> Dict[str, Path]:
    icons: Dict[str, Path] = {}
    candidates: Dict[str, Tuple[str, str]] = {}
    provided_icons: Dict[str, List[str]] = {}
    for summary in summaries.values():
        for item in summary["s_items"]:
            key, item_id = _item_asset(item)
            if key and item_id:
                kind = "bangboo" if key.startswith("bangboo_") else (
                    "weapon" if key.startswith("weapon_") else "agent"
                )
                candidates[key] = (kind, item_id)
                icon = item.get("icon")
                if isinstance(icon, str) and icon.startswith("https://"):
                    provided_icons.setdefault(key, []).append(icon)

    semaphore = asyncio.Semaphore(5)

    async def save_icon(key: str, kind: str, item_id: str) -> None:
        path = ASSET_ROOT / f"{key}.png"
        if _valid_icon(path):
            icons[key] = path
            return
        resource = "bangboo_rectangle_avatar" if kind == "bangboo" else "role_square_avatar"
        urls: List[str] = []
        official_urls: List[str] = []
        if kind in {"agent", "bangboo"}:
            filename = f"{resource}_{item_id}.png"
            official_urls.extend((
                f"https://act-webstatic.mihoyo.com/game_record/zzzv2/{resource}/{filename}",
                f"https://act-webstatic.mihoyo.com/game_record/zzz/{resource}/{filename}",
            ))
        async with semaphore:
            if kind in {"weapon", "bangboo"}:
                nanoka_urls = await _nanoka_item_icon_urls(client, kind, item_id)
                urls.extend(nanoka_urls)
            if kind == "agent":
                urls.extend(official_urls)
            elif kind == "bangboo":
                urls.extend(official_urls)
            urls.extend(provided_icons.get(key, []))
            for url in dict.fromkeys(urls):
                try:
                    response = await client.get(url, timeout=_request_timeout())
                    if response.status_code != 200:
                        continue
                    png_data = await asyncio.to_thread(_image_as_png, response.content)
                    await asyncio.to_thread(_write_icon_sync, path, png_data)
                    icons[key] = path
                    return
                except (
                    httpx.HTTPError,
                    OSError,
                    UnidentifiedImageError,
                    PILImage.DecompressionBombError,
                    ValueError,
                ):
                    continue

    await asyncio.gather(*(save_icon(key, kind, item_id) for key, (kind, item_id) in candidates.items()))
    return icons


def _write_icon_sync(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    value = str(text)
    while value and draw.textlength(value, font=font) > width:
        value = value[:-1]
    return value + "…" if value != str(text) and width > 16 else value


def _pack_two_columns(pools: List[str], heights: Dict[str, int]) -> Tuple[List[str], List[str]]:
    """按参考项目的做法分配卡池，尽可能平衡左右两列高度。"""
    if not pools:
        return [], []
    if len(pools) == 1:
        return [pools[0]], []
    tallest = max(range(len(pools)), key=lambda index: (heights[pools[index]], -index))
    best_score = None
    best_left: List[str] = []
    best_right: List[str] = []
    for mask in range(1, (1 << len(pools)) - 1):
        left = [pool for index, pool in enumerate(pools) if mask & (1 << index)]
        right = [pool for index, pool in enumerate(pools) if not mask & (1 << index)]
        left_height = sum(heights[pool] for pool in left)
        right_height = sum(heights[pool] for pool in right)
        score = (max(left_height, right_height), abs(left_height - right_height),
                 0 if mask & (1 << tallest) else 1, len(left))
        if best_score is None or score < best_score:
            best_score, best_left, best_right = score, left, right
    return best_left, best_right


def _pool_level(summary: Dict[str, Any], pool_name: str) -> int:
    average = summary["average"]
    average_up = summary["average_up"]
    if average is None and average_up is None:
        return 2
    weapon_pool = pool_name in {"音擎频段", "邦布频段", "音擎回响"}
    if average_up is not None:
        thresholds = [62, 75, 88, 99, 111] if weapon_pool else [74, 87, 99, 105, 120]
        value = average_up
    else:
        thresholds = [51, 55, 61, 68, 70] if weapon_pool else [53, 60, 68, 73, 75]
        value = average or 0
    for index, threshold in enumerate(thresholds):
        if value <= threshold:
            return 4 - index
    return 0


async def _fetch_qq_avatar(client: httpx.AsyncClient, user_id: str) -> Optional[bytes]:
    if not str(user_id).isdigit():
        return None
    try:
        response = await client.get(
            "https://q1.qlogo.cn/g",
            params={"b": "qq", "nk": str(user_id), "s": "640"},
            timeout=_request_timeout(),
        )
        if response.status_code == 200:
            with PILImage.open(BytesIO(response.content)) as avatar:
                avatar.verify()
            return response.content
    except (httpx.HTTPError, OSError, UnidentifiedImageError, PILImage.DecompressionBombError):
        pass
    return None


def _round_avatar(data: Optional[bytes]) -> PILImage.Image:
    avatar = None
    if data:
        try:
            with PILImage.open(BytesIO(data)) as source:
                avatar = ImageOps.fit(source.convert("RGBA"), (129, 129))
        except (OSError, UnidentifiedImageError, PILImage.DecompressionBombError):
            pass
    if avatar is None:
        avatar = PILImage.new("RGBA", (129, 129), (46, 46, 46, 255))
        draw = ImageDraw.Draw(avatar)
        draw.ellipse((44, 23, 85, 64), fill=(145, 145, 145, 255))
        draw.ellipse((20, 73, 109, 150), fill=(145, 145, 145, 255))
    mask = PILImage.new("L", (129, 129), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 128, 128), fill=255)
    avatar.putalpha(mask)
    return avatar


def _draw_player_card(
    canvas: PILImage.Image,
    uid: str,
    avatar_data: Optional[bytes],
    role: Any,
    fallback_name: str,
) -> None:
    with PILImage.open(NOTE_ASSET_ROOT / "player_card_min.png") as source:
        player_card = source.convert("RGBA")
    player_card.alpha_composite(_round_avatar(avatar_data), (105, 30))
    draw = ImageDraw.Draw(player_card)
    name_font = _font(38)
    info_font = _font(28)
    role_name = str(getattr(role, "nickname", None) or fallback_name or "绳匠")
    role_name = _fit_text(draw, role_name, name_font, 360)
    draw.text((290, 64), role_name, font=name_font, fill="white", anchor="lm")
    draw.text((290, 120), f"UID {uid}", font=_font(30), fill=(216, 216, 216, 255), anchor="lm")
    name_end = 290 + min(draw.textlength(role_name, font=name_font), 360) + 20
    level = getattr(role, "level", None)
    region = str(getattr(role, "region_name", None) or "新艾利都")
    draw.rounded_rectangle((name_end, 45, name_end + 90, 80), radius=10, fill=(255, 200, 1, 255))
    draw.rounded_rectangle((name_end + 102, 45, name_end + 246, 80), radius=10, fill=(1, 183, 255, 255))
    draw.text((name_end + 45, 62), f"Lv.{level}" if level is not None else "Lv.?", font=info_font,
              fill=(40, 40, 40, 255), anchor="mm")
    draw.text((name_end + 174, 62), _fit_text(draw, region, info_font, 132), font=info_font,
              fill=(40, 40, 40, 255), anchor="mm")
    canvas.alpha_composite(player_card, (25, 80))


def _make_s_item(
    item: Dict[str, Any],
    icons: Dict[str, Path],
    item_mask: PILImage.Image,
    item_fg: PILImage.Image,
    up_icon: PILImage.Image,
    s_rank: PILImage.Image,
) -> PILImage.Image:
    item_bg = PILImage.new("RGBA", (186, 130), (0, 0, 0, 0))
    item_bg.paste(item_mask, (0, 0), item_mask)
    item_temp = PILImage.new("RGBA", (186, 130), (0, 0, 0, 0))
    key, _ = _item_asset(item)
    icon_path = icons.get(key or "")
    if icon_path and _valid_icon(icon_path):
        try:
            with PILImage.open(icon_path) as source:
                icon = source.convert("RGBA")
            kind = str(item.get("item_type") or "")
            if kind == "音擎":
                icon = ImageOps.contain(icon, (160, 160))
                item_temp.paste(icon, ((186 - icon.width) // 2, -18 + (160 - icon.height) // 2), icon)
            elif kind == "邦布":
                icon = ImageOps.contain(icon, (152, 186))
                item_temp.paste(icon, ((186 - icon.width) // 2, -19), icon)
            else:
                icon = ImageOps.fit(icon, (175, 214))
                item_temp.paste(icon, (10, -24), icon)
            item_bg.paste(item_temp, (0, 0), item_mask)
        except (OSError, UnidentifiedImageError, PILImage.DecompressionBombError):
            pass
    item_bg.paste(item_fg, (0, 0), item_fg)
    draw = ImageDraw.Draw(item_bg)
    pull_count = int(item.get("_pull_count", 0) or 0)
    if pull_count >= 80:
        pull_color = (255, 20, 20, 255)
    elif pull_count <= 60:
        pull_color = (63, 255, 0, 255)
    else:
        pull_color = (255, 255, 255, 255)
    pull_text = "?抽" if item.get("_count_incomplete") else f"{pull_count}抽"
    draw.text((42, 102), pull_text, font=_font(20), fill=pull_color, anchor="mm")
    item_bg.alpha_composite(s_rank.resize((50, 50), PILImage.Resampling.LANCZOS), (122, 18))
    if item.get("_is_up"):
        item_bg.alpha_composite(up_icon, (9, 14))
    return item_bg


def _draw_gacha_card_sync(
    uid: str,
    payload: Dict[str, Any],
    icons: Dict[str, Path],
    avatar_data: Optional[bytes],
    role: Any,
    fallback_name: str,
) -> bytes:
    summaries = _gacha_summaries(payload)
    pools = [name for name, _, _ in POOL_CONFIG if name not in OPTIONAL_POOLS or summaries[name]["total"]]
    pool_heights = {name: 260 + ((len(summaries[name]["s_items"]) + 3) // 4) * 130 for name in pools}
    left_pools, right_pools = _pack_two_columns(pools, pool_heights)
    content_height = max(sum(pool_heights[name] for name in left_pools),
                         sum(pool_heights[name] for name in right_pools), 0)
    width = 1900
    with PILImage.open(GACHA_TEXTURE_ROOT / "bg.jpg") as source:
        background = source.convert("RGBA")
    height = 257 + content_height + 60 + 55
    canvas = ImageOps.fit(background, (width, height))
    draw = ImageDraw.Draw(canvas)
    _draw_player_card(canvas, uid, avatar_data, role, fallback_name)

    texture_cache: Dict[str, PILImage.Image] = {}
    for asset in ("char_bg_and_mask.png", "char_fg.png", "up.png", "SRANK.png"):
        with PILImage.open(GACHA_TEXTURE_ROOT / asset) as source:
            texture_cache[asset] = source.convert("RGBA")
    item_mask = texture_cache["char_bg_and_mask.png"]
    item_fg = texture_cache["char_fg.png"]
    up_icon = texture_cache["up.png"]
    s_rank = texture_cache["SRANK.png"]
    body_font = _font(18)
    tag_font = _font(32)
    tags = ("非到极致", "运气不好", "平稳保底", "小欧一把", "欧狗在此")

    for column_pools, base_x in ((left_pools, 25), (right_pools, 925)):
        current_y = 257
        for pool_name in column_pools:
            with PILImage.open(GACHA_TEXTURE_ROOT / f"{pool_name}.png") as source:
                title = source.convert("RGBA")
            summary = summaries[pool_name]
            title_draw = ImageDraw.Draw(title)
            time_range = summary["time_range"] or "暂未抽过卡!"
            title_draw.text((163, 132), _fit_text(title_draw, time_range, body_font, 490),
                            font=body_font, fill=(220, 220, 220, 255), anchor="lm")
            average = summary["average"]
            average_up = summary["average_up"]
            title_draw.text((253, 182), f"{average:.2f}" if average is not None else "-",
                            font=tag_font, fill="white", anchor="mm")
            title_draw.text((373, 182), f"{average_up:.2f}" if average_up is not None else "-",
                            font=tag_font, fill="white", anchor="mm")
            title_draw.text((492, 182), str(summary["total"]), font=tag_font, fill="white", anchor="mm")
            title_draw.text((398, 106), str(summary["pity"]), font=body_font,
                            fill=(63, 255, 0, 255), anchor="mm")

            level = _pool_level(summary, pool_name)
            level_images = sorted((GACHA_TEXTURE_ROOT / str(level)).glob("*.png"))
            if level_images:
                selector = sum(ord(char) for char in f"{uid}:{pool_name}") % len(level_images)
                with PILImage.open(level_images[selector]) as source:
                    level_icon = ImageOps.contain(source.convert("RGBA"), (140, 140))
                title.alpha_composite(level_icon, (684, 51))
            ImageDraw.Draw(title).text((757, 222), tags[level], font=tag_font, fill="white", anchor="mm")
            canvas.alpha_composite(title, (base_x, current_y))

            s_items = summary["s_items"]
            for index, item in enumerate(s_items):
                tile = _make_s_item(item, icons, item_mask, item_fg, up_icon, s_rank)
                x = base_x + 88 + 186 * (index % 4)
                y = current_y + 283 + 130 * (index // 4)
                canvas.alpha_composite(tile, (x, y))
            if not s_items:
                draw.text((base_x + 475, current_y + 278), "当前该卡池暂未有S_Rank数据噢!",
                          font=body_font, fill=(157, 157, 157, 255), anchor="mm")
            current_y += pool_heights[pool_name]

    draw.text((width // 2, height - 27), "function by manshuo", font=_font(20),
              fill=(190, 190, 190, 255), anchor="mm")
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


async def _get_zzz_role(account: UserAccount, uid: str) -> Any:
    try:
        status, records = await get_game_record(account, retry=False)
        if not status or not records:
            return None
        return next((record for record in records
                     if record.game_id == 8 and str(record.game_role_id) == uid), None)
    except Exception as error:
        logger.debug(f"获取绝区零抽卡卡片角色资料失败 UID={uid} ({type(error).__name__})")
        return None


async def _render_gacha_card(
    uid: str,
    payload: Dict[str, Any],
    proxy: Optional[str],
    user_id: str,
    account: UserAccount,
) -> Path:
    summaries = _gacha_summaries(payload)
    client_options = _proxy_options(proxy)
    client_options.update(timeout=_request_timeout())
    async with httpx.AsyncClient(**client_options) as client:
        icons, avatar_data = await asyncio.gather(
            _cache_item_icons(client, summaries),
            _fetch_qq_avatar(client, user_id),
        )
    try:
        role = await asyncio.wait_for(_get_zzz_role(account, uid), timeout=min(_request_timeout(), 8.0))
    except Exception:
        role = None
    image_data = await asyncio.to_thread(
        _draw_gacha_card_sync, uid, payload, icons, avatar_data, role, account.display_name
    )
    CARD_ROOT.mkdir(parents=True, exist_ok=True)
    path = CARD_ROOT / f"{uid}_{uuid4().hex}.png"
    await asyncio.to_thread(path.write_bytes, image_data)
    return path

async def _send_text(bot, event, user_id: str, text: str, recall=False) -> None:
    if bot and event:
        recall_id = await bot.send(event, [At(qq=str(user_id)), text])
        if recall and recall_id:
            await asyncio.sleep(50)
            await bot.recall(recall_id['data']['message_id'])
    else:
        print(text)


def _resolve_targets(user_id: str, uid: Optional[str]) -> List[Tuple[UserAccount, str]]:
    plugin_data = PluginDataManager.plugin_data
    user = (plugin_data.users or {}).get(str(user_id)) if plugin_data else None
    if not user:
        return []
    accounts_by_uid: Dict[str, UserAccount] = {}
    for account in (user.accounts or {}).values():
        for game_uid in _uid_items(account):
            if uid is not None and game_uid != uid:
                continue
            current = accounts_by_uid.get(game_uid)
            if current is None or (
                (not current.cookies or not current.cookies.stoken)
                and account.cookies and account.cookies.stoken
            ):
                accounts_by_uid[game_uid] = account
    return [(account, game_uid) for game_uid, account in accounts_by_uid.items()]


async def _handle_action(
    action: str,
    uid: str,
    account: UserAccount,
    user_id: str,
    bot,
    event,
    proxy: Optional[str],
    full_refresh: bool,
) -> None:
    lock = _UID_LOCKS.setdefault(uid, asyncio.Lock())
    if action == "refresh" and lock.locked():
        await _send_text(bot, event, user_id, f"的抽卡记录正在更新，请稍后再试",recall=True)
        return

    payload = await asyncio.to_thread(_load_cache_sync, uid)
    needs_initial_fetch = not payload.get("statistics") and not any((payload.get("data") or {}).values())
    if action == "refresh" or needs_initial_fetch:
        await _send_text(bot, event, user_id, "正在获取抽卡记录，请耐心等待喵")
        try:
            async with lock:
                added, total, warnings = await refresh_zzz_gacha_records(
                    account, uid, proxy=proxy, full_refresh=full_refresh,
                    statistics_only=action == "show",
                )
        except GachaRequestError:
            cached_total = sum(summary["total"] for summary in _gacha_summaries(payload).values())
            if action == "refresh" or not cached_total:
                raise
            added, total = 0, cached_total
            warnings = ["接口暂时不可用，本次使用已保存的数据绘制"]
        result_text = f"抽卡记录更新完成：新增 {added} 抽，合并统计共 {total} 抽"
        if warnings:
            result_text += "\n部分数据未能获取：" + "、".join(warnings)
        if action == "refresh":
            await _send_text(bot, event, user_id, result_text)
            return
        if warnings:
            await _send_text(bot, event, user_id, "部分卡池暂时无法获取：" + "、".join(warnings))

    payload = await asyncio.to_thread(_load_cache_sync, uid)
    summaries = _gacha_summaries(payload)
    if not any(summary["total"] for summary in summaries.values()):
        await _send_text(bot, event, user_id, f"暂无抽卡记录")
        return
    merge_warnings = list(dict.fromkeys(warning for summary in summaries.values() for warning in summary["warnings"]))
    if merge_warnings:
        await _send_text(bot, event, user_id, "、".join(merge_warnings))
    image_path = await _render_gacha_card(uid, payload, proxy, user_id, account)
    if bot and event:
        try:
            await bot.send(event, [At(qq=str(user_id)), Image(file=str(image_path))])
        finally:
            image_path.unlink(missing_ok=True)
    else:
        print(image_path)


async def handle_card_command(
    context: str,
    user_id: str,
    bot=None,
    event=None,
    proxy: Optional[str] = None,
) -> bool:
    """按绝区零别名前缀处理抽卡记录查询和刷新指令。"""
    text = (context or "").strip()
    aliases = sorted(game_name_list.get("绝区零", []), key=len, reverse=True)
    for alias in aliases:
        if text.casefold().startswith(alias.casefold()):
            text = text[len(alias):].strip()
            break
    else:
        return False

    action, requested_uid, full_refresh = _parse_card_action(text)
    if not action:
        return False

    targets = _resolve_targets(str(user_id), requested_uid)
    if not targets:
        plugin_data = PluginDataManager.plugin_data
        user = (plugin_data.users or {}).get(str(user_id)) if plugin_data else None
        if not user or not user.accounts:
            await _send_text(bot, event, str(user_id), "此用户还未绑定米游社账号，请先发送‘米游社登录’")
        elif requested_uid:
            await _send_text(bot, event, str(user_id), f"当前绑定账号中没有绝区零 UID {requested_uid}")
        else:
            await _send_text(bot, event, str(user_id), "未找到已保存的绝区零角色 UID，请重新登录米游社以更新角色数据")
        return True
    if len(targets) > 1:
        uid_list = "、".join(uid for _, uid in targets)
        await _send_text(
            bot, event, str(user_id),
            f"检测到多个绝区零 UID：{uid_list}\n请指定 UID，例如：绝区零{targets[0][1]}抽卡记录",
        )
        return True

    account, uid = targets[0]
    if not account.cookies or not account.cookies.stoken:
        await _send_text(bot, event, str(user_id), "米游社账号缺少 Stoken，请重新登录绑定")
        return True
    try:
        await _handle_action(action, uid, account, str(user_id), bot, event, proxy, full_refresh)
    except GachaRequestError as error:
        await _send_text(bot, event, str(user_id), str(error))
    except (httpx.HTTPError, ValueError, OSError) as error:
        logger.error(f"绝区零抽卡记录请求失败 UID={uid} ({type(error).__name__})")
        await _send_text(bot, event, str(user_id), "获取绝区零抽卡记录失败，请稍后重试喵")
    except Exception as error:
        logger.error(f"绝区零抽卡记录处理异常 UID={uid} ({type(error).__name__})")
        await _send_text(bot, event, str(user_id), "处理绝区零抽卡记录失败，请稍后重试喵")
    return True
