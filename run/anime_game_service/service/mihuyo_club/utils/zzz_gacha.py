"""绝区零官方调频统计接口及其与本地逐抽记录的合并。"""

from bisect import bisect_left
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import httpx


STATISTICS_URL = "https://act-api-takumi.mihoyo.com/event/nap_gacha_record/api/zzz"
POOL_TYPES = {
    "音擎频段": (3, "GACHA_TYPE_WEAPON_UP"),
    "独家频段": (2, "GACHA_TYPE_CHARACTER_UP"),
    "常驻频段": (1, "GACHA_TYPE_PERMANENT"),
    "邦布频段": (5, "GACHA_TYPE_BANGBOO"),
    "独家重映": (102, "GACHA_TYPE_CHARACTER_RETURN"),
    "音擎回响": (103, "GACHA_TYPE_WEAPON_RETURN"),
}
OPTIONAL_POOLS = {"独家重映", "音擎回响"}
CN_TIMEZONE = timezone(timedelta(hours=8))


class GachaStatisticsError(ValueError):
    """官方统计未能提供完整且一致的数据。"""


def _number(value: Any, field: str) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError) as error:
        raise GachaStatisticsError(f"官方统计字段 {field} 无效") from error
    if number < 0:
        raise GachaStatisticsError(f"官方统计字段 {field} 无效")
    return number


def _pool_stat(snapshot: Dict[str, Any], pool_name: str) -> Dict[str, Any]:
    type_id, type_name = POOL_TYPES[pool_name]
    for item in (snapshot.get("index") or {}).get("type_stats") or []:
        if isinstance(item, dict) and str(item.get("gacha_type")) in {str(type_id), type_name}:
            return item
    if pool_name in OPTIONAL_POOLS:
        return {"total_count": 0, "s_count": 0, "up_count": 0, "next_s_cur_times": 0}
    raise GachaStatisticsError(f"官方统计缺少{pool_name}")


def _official_items(snapshot: Dict[str, Any], pool_name: str) -> List[Dict[str, Any]]:
    pool = (snapshot.get("pools") or {}).get(pool_name) or {}
    by_position: Dict[int, Dict[str, Any]] = {}
    default_type = "音擎" if pool_name in {"音擎频段", "音擎回响"} else "邦布" if pool_name == "邦布频段" else "角色"
    for group in list(pool.get("current") or []) + list(pool.get("history") or []):
        if not isinstance(group, dict) or not isinstance(group.get("cur_records", []), list):
            raise GachaStatisticsError(f"{pool_name}历史记录格式异常")
        for raw in group.get("cur_records") or []:
            if not isinstance(raw, dict) or not raw.get("item_id") or str(raw["item_id"]) == "0":
                raise GachaStatisticsError(f"{pool_name}历史记录格式异常")
            position = _number(raw.get("sort"), "sort")
            count = _number(raw.get("count"), "count")
            timestamp = _number(raw.get("record_time"), "record_time")
            if not position or not count or not timestamp or raw.get("rarity") != "S" or not isinstance(raw.get("is_up"), bool):
                raise GachaStatisticsError(f"{pool_name}历史记录不完整")
            try:
                time_text = datetime.fromtimestamp(timestamp, CN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError) as error:
                raise GachaStatisticsError(f"{pool_name}记录时间无效") from error
            item_type = {"ItemType_Avatar": "角色", "ItemType_Weapon": "音擎", "ItemType_Bangboo": "邦布"}.get(
                raw.get("item_type"), default_type
            )
            is_up = raw["is_up"] and pool_name != "常驻频段"
            item = dict(raw, item_id=str(raw["item_id"]), item_type=item_type, rank_type="4", time=time_text,
                        _position=position, _pull_count=count, _is_up=is_up)
            previous = by_position.get(position)
            if previous and any(previous[key] != item[key] for key in ("item_id", "time", "_pull_count", "_is_up")):
                raise GachaStatisticsError(f"{pool_name}历史记录序号冲突")
            by_position[position] = item
    return [by_position[position] for position in sorted(by_position)]


def validate_statistics(snapshot: Dict[str, Any]) -> None:
    """S 级数量、累计序号、出货间隔和垫数必须与总抽数一致。"""
    for pool_name in POOL_TYPES:
        stat = _pool_stat(snapshot, pool_name)
        total = _number(stat.get("total_count"), "total_count")
        pity = _number(stat.get("next_s_cur_times"), "next_s_cur_times")
        items = _official_items(snapshot, pool_name)
        if len(items) != _number(stat.get("s_count"), "s_count"):
            raise GachaStatisticsError(f"{pool_name}历史 S 级记录未获取完整")
        previous = 0
        for item in items:
            if item["_position"] - previous != item["_pull_count"]:
                raise GachaStatisticsError(f"{pool_name}历史抽数不连续")
            previous = item["_position"]
        if previous + pity != total:
            raise GachaStatisticsError(f"{pool_name}总抽数校验失败")


async def fetch_gacha_statistics(
    client: httpx.AsyncClient, uid: str, region: str, cookies: Dict[str, str],
    headers: Dict[str, str], timeout: float,
) -> Dict[str, Any]:
    async def request(endpoint: str, **extra: Any) -> Dict[str, Any]:
        response = await client.get(f"{STATISTICS_URL}/{endpoint}", params={"uid": uid, "region": region, **extra},
                                    cookies=cookies, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("retcode") not in (0, "0") or not isinstance(payload.get("data"), dict):
            raise GachaStatisticsError("官方调频统计接口请求失败")
        return payload["data"]

    snapshot: Dict[str, Any] = {"index": await request("index"), "pools": {}}
    if not isinstance(snapshot["index"].get("type_stats"), list):
        raise GachaStatisticsError("官方调频统计缺少卡池统计")
    for pool_name, (type_id, _) in POOL_TYPES.items():
        stat = _pool_stat(snapshot, pool_name)
        pool: Dict[str, Any] = {"current": [], "history": []}
        snapshot["pools"][pool_name] = pool
        if not _number(stat.get("total_count"), "total_count"):
            continue
        current = await request("cur_pool_stat", gacha_type=type_id)
        if not isinstance(current.get("list"), list):
            raise GachaStatisticsError(f"{pool_name}当前记录格式异常")
        pool["current"] = current["list"]
        versions = stat.get("has_data_vers")
        if not isinstance(versions, list) or not all(isinstance(version, str) for version in versions):
            raise GachaStatisticsError(f"{pool_name}历史版本列表无效")
        versions = list(dict.fromkeys(versions))
        for start in range(0, len(versions), 8):
            history = await request("hist_pool_stat", gacha_type=type_id, vers=",".join(versions[start:start + 8]))
            if not isinstance(history.get("list"), list):
                raise GachaStatisticsError(f"{pool_name}历史记录格式异常")
            pool["history"].extend(history["list"])
    validate_statistics(snapshot)
    snapshot["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return snapshot


def _fingerprint(item: Dict[str, Any]) -> Tuple[str, str]:
    item_id = str(item.get("item_id") or "")
    return item_id or str(item.get("name") or ""), str(item.get("time") or "")


def has_statistics_overlap(
    records: List[Dict[str, Any]], pool_name: str, snapshot: Dict[str, Any],
) -> bool:
    """旧接口查询到已保存的 S 级记录后，已有足够信息合并后续抽数。"""
    if not snapshot:
        return False
    known = {_fingerprint(item) for item in _official_items(snapshot, pool_name)}
    return any(str(item.get("rank_type")) == "4" and _fingerprint(item) in known for item in records)


def merge_pool_summary(
    records: List[Dict[str, Any]], legacy: Dict[str, Any], pool_name: str, snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """用同一次 S 级出货对齐逐抽位置，保留旧接口比统计快的尾部。"""
    if not snapshot:
        return dict(legacy, warnings=[])
    stat = _pool_stat(snapshot, pool_name)
    official = _official_items(snapshot, pool_name)
    official_total = _number(stat.get("total_count"), "total_count")
    official_pity = _number(stat.get("next_s_cur_times"), "next_s_cur_times")
    if not official:
        if legacy["s_items"]:
            result = dict(legacy, total=max(legacy["total"], official_total), warnings=[])
            if legacy["total"] < official_total:
                result["s_items"] = [dict(item) for item in legacy["s_items"]]
                result["s_items"][-1]["_count_incomplete"] = True
                result.update(average=None, average_up=None,
                              warnings=[f"{pool_name}本地记录未能与官方统计对齐，未知抽数以 ? 显示"])
            return result
        if legacy["total"] > official_total:
            return dict(legacy, warnings=[])
        return dict(legacy, total=official_total, pity=official_pity, warnings=[])

    available = defaultdict(deque)
    for item in official:
        available[_fingerprint(item)].append(item)
    # legacy 的 S 列表与逐抽列表都按最新在前保存；逐条消费避免同秒同角色误去重。
    legacy_items = list(reversed(legacy["s_items"]))
    chronological = list(reversed(records))
    raw_s_indices = [index for index, item in enumerate(chronological) if str(item.get("rank_type")) == "4"]
    anchors: List[Tuple[int, int]] = []
    unmatched: List[Tuple[int, Dict[str, Any]]] = []
    for index, item in zip(raw_s_indices, legacy_items):
        candidates = available[_fingerprint(item)]
        if candidates:
            anchors.append((index, candidates.popleft()["_position"]))
        else:
            unmatched.append((index, dict(item)))

    by_position = {item["_position"]: item for item in official}
    anchor_indices = [index for index, _ in anchors]
    unresolved = []
    for index, item in unmatched:
        if not anchors:
            unresolved.append(dict(item, _count_incomplete=True))
            continue
        slot = bisect_left(anchor_indices, index)
        anchor_index, anchor_position = anchors[min(slot, len(anchors) - 1)]
        position = anchor_position + index - anchor_index
        if position <= 0 or position in by_position or (slot and position <= anchors[slot - 1][1]):
            unresolved.append(dict(item, _count_incomplete=True))
            continue
        by_position[position] = dict(item, _position=position)

    total = max(official_total, legacy["total"])
    if anchors:
        last_index, last_position = anchors[-1]
        total = max(total, last_position + len(chronological) - 1 - last_index)
    items = [by_position[position] for position in sorted(by_position)]
    previous = 0
    for item in items:
        item["_pull_count"] = item["_position"] - previous
        previous = item["_position"]
    pity = max(0, total - previous)
    up_count = sum(bool(item.get("_is_up")) for item in items)
    warnings = []
    if unresolved:
        warnings.append(f"{pool_name}部分本地 S 级记录未能对齐，总抽数暂以已确认统计为准，未知抽数以 ? 显示")
        if legacy_items and str(legacy_items[-1].get("time") or "") > str(official[-1].get("time") or ""):
            pity = legacy["pity"]
    s_items = items + unresolved
    s_items.sort(key=lambda item: (str(item.get("time") or ""), item.get("_position", 0)), reverse=True)
    times = sorted(item["time"][:10] for item in s_items if item.get("time"))
    return {
        "total": total, "pity": pity, "s_items": s_items,
        "average": round(previous / len(items), 2) if items and not unresolved else None,
        "average_up": round(previous / up_count, 2) if up_count and not unresolved else None,
        "time_range": f"S级记录 {times[0]}~{times[-1]}" if times else "",
        "warnings": warnings,
    }
