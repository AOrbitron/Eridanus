"""国服明日方舟、终末地真实寻访记录。

终末地协议参考 BeyondUID/beyonduid_gachalog；明日方舟角色认证、分类和
游标协议补充参考 https://github.com/AceDroidX/arknights-gacha-export/blob/main/API.md 。
保留原始记录及未知字段；赠礼事件单独计数，不计入抽数。
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1] / "data" / "gacha"
CN_TIME = timezone(timedelta(hours=8))
AS_ROOT = "https://as.hypergryph.com"
BINDING_ROOT = "https://binding-api-account-prod.hypergryph.com/account/binding/v1"
ARK_ROOT = "https://ak.hypergryph.com/user/api"
EF_ROOT = "https://ef-webview.hypergryph.com/api"
CHAR_TYPES = {
    "E_CharacterGachaPoolType_Special": "特许寻访",
    "E_CharacterGachaPoolType_Rerun": "复刻寻访",
    "E_CharacterGachaPoolType_Standard": "基础寻访",
    "E_CharacterGachaPoolType_Beginner": "新手寻访",
    "E_CharacterGachaPoolType_Joint": "联合寻访",
}
MAX_PAGES = 2000
PAGE_INTERVAL = 0.12
ENDFIELD_HISTORY_DAYS = 90


class GachaError(Exception):
    """可直接向用户展示的错误，不携带 token 或请求 URL。"""


def numeric(value: Any, label: str = "UID") -> str:
    result = str(value or "")
    if not result.isascii() or not result.isdigit():
        raise GachaError(f"{label}缺失或格式错误，请重新登录森空岛")
    return result


def cache_path(game: str, uid: str, server: str = "1") -> Path:
    if game not in {"arknights", "endfield"}:
        raise GachaError("不支持的游戏")
    return ROOT / game / "players" / f"{numeric(uid)}_{numeric(server, '服务器编号')}.json"


def load_cache(game: str, uid: str, server: str = "1") -> dict:
    path = cache_path(game, uid, server)
    if not path.exists():
        return {"version": 1, "game": game, "uid": str(uid), "server_id": str(server), "streams": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("streams"), dict):
            raise ValueError
        if payload.get("game") != game or str(payload.get("uid")) != str(uid) or str(payload.get("server_id", "1")) != str(server):
            raise ValueError
        for stream in payload["streams"].values():
            if not isinstance(stream, dict) or not isinstance(stream.get("records"), list):
                raise ValueError
            for row in stream["records"]:
                record_key(game, stream.get("kind", "char"), row)
        return payload
    except (OSError, ValueError, TypeError, GachaError) as error:
        raise GachaError("本地抽卡记录读取失败，已保留原文件，请检查记录文件后重试") from error


def save_cache(payload: dict, full_refresh: bool = False) -> None:
    path = cache_path(payload["game"], payload["uid"], payload.get("server_id", "1"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if full_refresh and path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record_key(game: str, kind: str, row: dict) -> str:
    if not isinstance(row, dict):
        raise GachaError("抽卡记录格式异常")
    if game == "arknights":
        ts, pos = row.get("gachaTs"), row.get("pos")
        if ts is None or pos is None:
            raise GachaError("明日方舟记录缺少时间戳或批次位置")
        return f"{row.get('poolId', '')}:{ts}:{pos}"
    seq = row.get("seqId")
    if seq is None:
        raise GachaError("终末地记录缺少序号")
    return f"{kind}:{row.get('poolId', '')}:{seq}:{row.get('kind', 'draw')}"


def record_order(row: dict) -> tuple[int, int]:
    try:
        return int(row.get("gachaTs", 0)), int(row.get("seqId", row.get("pos", 0)))
    except (ValueError, TypeError) as error:
        raise GachaError("抽卡记录时间或序号格式异常") from error


def merge_records(game: str, kind: str, old: list[dict], new: list[dict]) -> list[dict]:
    merged = {}
    for row in [*old, *new]:
        key = record_key(game, kind, row)
        merged[key] = {**merged.get(key, {}), **row}
    return sorted(merged.values(), key=record_order, reverse=True)


def all_records(payload: dict) -> list[tuple[str, str, dict]]:
    """跨分类去重，避免兼容接口与逐池接口重复计入统计。"""
    records = {}
    for stream in payload.get("streams", {}).values():
        kind, name = stream.get("kind", "char"), stream.get("name", "寻访")
        for row in stream.get("records", []):
            records[record_key(payload["game"], kind, row)] = (kind, name, row)
    return sorted(records.values(), key=lambda item: record_order(item[2]), reverse=True)


def record_counts(payload: dict) -> tuple[int, int]:
    rows = all_records(payload)
    draws = sum(row.get("kind", "draw") == "draw" for _, _, row in rows)
    return draws, len(rows) - draws


class GachaAPI:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, method: str, url: str, action: str, **kwargs) -> Any:
        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
                raise GachaError(f"{action}授权失败，请发送“森空岛登录”重新登录") from error
            raise GachaError(f"{action}网络请求失败，请稍后重试") from error
        if not isinstance(value, dict):
            raise GachaError(f"{action}返回格式异常")
        code = value.get("status", value.get("code"))
        if code not in (0, "0"):
            if code in (1, 2, 3, 4, 10000, 10001, 10002, 401, "401"):
                raise GachaError(f"{action}授权失败，请发送“森空岛登录”重新登录")
            raise GachaError(f"{action}失败（接口返回 {code}）")
        if "data" not in value:
            raise GachaError(f"{action}未返回数据")
        return value["data"]

    async def authorize(self, game: str, user: dict, role: dict) -> tuple[str, dict]:
        token = user.get("access_token")
        if not token:
            raise GachaError("缺少鹰角登录凭据，请发送“森空岛登录”重新登录")
        body = {"token": token, "appCode": "be36d44aa36bfb5b", "type": 1}
        if user.get("device_token"):
            body["deviceToken"] = user["device_token"]
        data = await self.request("POST", f"{AS_ROOT}/user/oauth2/v2/grant", "获取抽卡授权", json=body)
        oauth = data.get("token") if isinstance(data, dict) else None
        if not oauth:
            raise GachaError("未取得抽卡授权，请重新登录森空岛")
        data = await self.request("GET", f"{BINDING_ROOT}/binding_list", "查询游戏绑定", params={"token": oauth, "appCode": game})
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise GachaError("游戏绑定列表格式异常")
        bindings = [binding for app in data.get("list", []) if app.get("appCode") == game for binding in app.get("bindingList", [])]
        selected = next((binding for binding in bindings if str(binding.get("uid")) == str(role.get("uid"))), None)
        if selected is None:
            raise GachaError("保存的游戏角色不属于当前鹰角账号，请重新登录森空岛")
        profile = {"nickname": selected.get("nickName") or role.get("nickname", ""), "level": role.get("level")}
        if game == "endfield":
            game_role = next((item for item in selected.get("roles", []) if str(item.get("roleId")) == str(role.get("roleid")) and str(item.get("serverId")) == str(role.get("serverid", "1"))), None)
            if game_role is None:
                raise GachaError("未找到保存的终末地角色，请重新登录森空岛")
            profile.update(nickname=game_role.get("nickName") or game_role.get("nickname") or profile["nickname"], level=game_role.get("level"))
        data = await self.request("POST", f"{BINDING_ROOT}/u8_token_by_uid", "获取角色授权", json={"token": oauth, "uid": str(selected["uid"])})
        u8 = data.get("token") if isinstance(data, dict) else None
        if not u8:
            raise GachaError("未取得游戏角色授权，请重新登录森空岛")
        return u8, profile

    async def pages(self, game: str, kind: str, url: str, params: dict, old: dict, full_refresh: bool, headers: dict | None = None) -> list[dict]:
        known = {record_key(game, kind, row) for row in old.get("records", [])}
        fetched, cursors = [], set()
        query = dict(params)
        for _ in range(MAX_PAGES):
            data = await self.request("GET", url, "获取寻访记录", params=query, headers=headers)
            if not isinstance(data, dict) or not isinstance(data.get("list"), list) or not isinstance(data.get("hasMore"), bool):
                raise GachaError("寻访记录分页数据异常")
            rows = data["list"]
            for row in rows:
                record_key(game, kind, row)
                record_order(row)
            fetched.extend(rows)
            # 仅完整遍历过的分类允许在已知记录处停止；全量更新始终继续翻页。
            if not full_refresh and old.get("complete") and any(record_key(game, kind, row) in known for row in rows):
                return fetched
            if not data["hasMore"]:
                return fetched
            if not rows:
                raise GachaError("接口声明还有记录但返回空页，已停止更新")
            last = rows[-1]
            cursor = (str(last["gachaTs"]), str(last["pos"])) if game == "arknights" else (str(last["seqId"]),)
            if cursor in cursors:
                raise GachaError("接口返回重复游标，已停止更新")
            cursors.add(cursor)
            if game == "arknights":
                query.update(gachaTs=cursor[0], pos=cursor[1])
            else:
                query["seq_id"] = cursor[0]
            await asyncio.sleep(PAGE_INTERVAL)
        raise GachaError("寻访记录页数超过上限，已保留本地历史")


async def refresh_records(game: str, user: dict, role: dict, cached: dict, *, proxy: str | None = None, full_refresh: bool = False) -> tuple[dict, int, int, list[str]]:
    """分类分别拉取、合并；某一分类失败时保留它的旧记录并明确报告。"""
    payload = copy.deepcopy(cached)
    before, gifts_before = record_counts(payload)
    warnings, targets = [], []
    now = datetime.now(CN_TIME).strftime("%Y-%m-%d %H:%M:%S")
    async with httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(25.0), follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as client:
        api = GachaAPI(client)
        u8, profile = await api.authorize(game, user, role)
        payload["profile"] = {**payload.get("profile", {}), **profile}
        if game == "arknights":
            headers = {"x-account-token": user["access_token"], "x-role-token": u8, "Origin": "https://ak.hypergryph.com", "Referer": "https://ak.hypergryph.com/"}
            await api.request("POST", f"{ARK_ROOT}/role/login", "登录明日方舟角色", json={"token": u8, "source_from": "", "share_type": "", "share_by": ""})
            info = await api.request("GET", f"{ARK_ROOT}/role/info", "查询明日方舟角色", params={"source_from": "", "share_type": "", "share_by": ""}, headers=headers)
            if str(info.get("uid")) != str(role["uid"]):
                raise GachaError("明日方舟角色授权不匹配，已停止更新")
            payload["profile"]["nickname"] = info.get("name") or profile["nickname"]
            categories = await api.request("GET", f"{ARK_ROOT}/inquiry/gacha/cate", "查询寻访分类", params={"uid": str(role["uid"])}, headers=headers)
            if not isinstance(categories, list):
                raise GachaError("明日方舟寻访分类格式异常")
            for category in categories:
                if not isinstance(category, dict) or not category.get("id"):
                    raise GachaError("明日方舟寻访分类缺少编号")
                key = f"ark:{category['id']}"
                targets.append((key, str(category.get("name") or category["id"]).replace("\n", " "), "char", f"{ARK_ROOT}/inquiry/gacha/history", {"uid": str(role["uid"]), "category": str(category["id"]), "size": 10}, headers))
        else:
            base = {"lang": "zh-cn", "token": u8, "server_id": str(role.get("serverid", "1"))}
            char_types = dict(CHAR_TYPES)
            try:
                meta = await api.request("GET", f"{EF_ROOT}/record/char/meta", "查询角色池类型", params=base)
                for item in meta.get("tabs", []):
                    if item.get("poolType"):
                        char_types[str(item["poolType"])] = item.get("label") or char_types.get(item["poolType"], str(item["poolType"]).split("_")[-1] + "寻访")
            except (GachaError, AttributeError, TypeError):
                warnings.append("角色池类型查询失败，已使用已知池型")
            # 旧缓存发现过的新池型也继续请求，避免下线后失去增量入口。
            for key, stream in payload.get("streams", {}).items():
                if key.startswith("char:"):
                    char_types.setdefault(key[5:], stream.get("name", "角色寻访"))
            for pool_type, name in char_types.items():
                targets.append((f"char:{pool_type}", name, "char", f"{EF_ROOT}/record/char", {**base, "pool_type": pool_type}, None))
            weapons = {}
            for key, stream in payload.get("streams", {}).items():
                if key.startswith("weapon:") and key != "weapon:all":
                    weapons[key[7:]] = stream.get("name", "武器申领")
            try:
                pools = await api.request("GET", f"{EF_ROOT}/record/weapon/pool", "查询武器池列表", params=base)
                if not isinstance(pools, list):
                    raise GachaError("武器池列表格式异常")
                for item in pools:
                    if not isinstance(item, dict) or not item.get("poolId"):
                        raise GachaError("武器池缺少编号")
                    weapons[str(item["poolId"])] = str(item.get("poolName") or item["poolId"])
            except GachaError:
                warnings.append("武器池列表查询失败，已尝试历史池及兼容接口")
            for pool_id, name in weapons.items():
                targets.append((f"weapon:{pool_id}", name, "weapon", f"{EF_ROOT}/record/weapon", {**base, "pool_id": pool_id}, None))
            # BeyondUID 始终请求不带 pool_id 的汇总接口。池目录并非历史池全集，
            # 即使目录请求成功也必须获取汇总，之后按记录键与逐池结果去重。
            targets.append(("weapon:all", "武器申领", "weapon", f"{EF_ROOT}/record/weapon", base, None))
        successful = 0
        for key, name, kind, url, params, headers in targets:
            old = payload["streams"].get(key, {})
            try:
                rows = await api.pages(game, kind, url, params, old, full_refresh, headers)
                payload["streams"][key] = {"name": name, "kind": kind, "complete": True, "updated_at": now, "records": merge_records(game, kind, old.get("records", []), rows)}
                successful += 1
            except GachaError as error:
                warnings.append(f"{name}：{error}")
        if targets and not successful:
            raise GachaError("所有寻访分类更新失败，已保留本地记录；" + "；".join(warnings))
        if not targets and payload["streams"]:
            warnings.append("当前接口未返回寻访分类，已保留本地历史")
    payload.update(initialized=True, updated_at=now, warnings=warnings)
    if game == "endfield":
        payload["coverage"] = {
            "api_history_days": ENDFIELD_HISTORY_DAYS,
            "account_history_complete": False,
            "note": "官方接口仅提供近90日记录，统计包含已存档历史，不代表账号累计抽数",
        }
    total, gifts = record_counts(payload)
    return payload, total - before, gifts - gifts_before, warnings
