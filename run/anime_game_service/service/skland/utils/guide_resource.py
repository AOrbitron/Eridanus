"""图鉴/基质静态游戏表；整组下载、校验后原子替换，失败保留上一版。"""
from __future__ import annotations

import asyncio
from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

import httpx

PROJECT = Path(__file__).resolve().parents[5]
ROOT = Path(__file__).resolve().parents[1] / "data/guides"
FONT = PROJECT / "framework_common/manshuo_draw/data/fort/LXGWWenKai-Regular.ttf"
OUTPUT_DIR = PROJECT / "data/pictures/cache"
ARK_TABLES = ("character_table", "skill_table", "uniequip_table", "battle_equip_table")
END_TABLES = (
    "WeaponBasicTable", "ItemTable", "GemTable", "GemPresetTable",
    "WorldEnergyPointTable", "WorldEnergyPointGroupTable", "DomainDataTable",
    "GachaPoolWeaponPresetTable", "GachaPoolCharPresetTable",
    "CharWpnRecommendTable", "CharacterTable", "I18nTextTable_CN",
)
TABLES = {"arknights": ARK_TABLES, "endfield": END_TABLES}
ARK_BASES = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel",
    "https://cdn.jsdelivr.net/gh/Kengxxiao/ArknightsGameData@master/zh_CN/gamedata/excel",
)
END_BASES = (
    "https://silverwing.elysia.beauty/BeyondUID/TableCfg",
    "http://lulush.microgg.cn/BeyondUID/TableCfg",
    "https://gscore.focalors.com/BeyondUID/TableCfg",
)
_LOCKS: dict[str, asyncio.Lock] = {}


class GuideError(Exception):
    """可直接向用户展示的查询错误。"""


def resource_path(game: str) -> Path:
    return ROOT / game / "tables.json"


def validate_table(game: str, name: str, data: object) -> None:
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{name}: empty table")
    required = {
        "character_table": ("char_",), "skill_table": ("skchr_",),
        "uniequip_table": ("equipDict", "charEquip", "subProfDict"),
        "battle_equip_table": ("uniequip_",),
        "WeaponBasicTable": ("wpn_",), "GemTable": ("gat_",),
        "I18nTextTable_CN": (),
    }.get(name, ())
    if required and not all(any(str(key).startswith(prefix) for key in data) for prefix in required):
        raise ValueError(f"{name}: unexpected schema")
    if name == "I18nTextTable_CN" and not any(isinstance(value, str) and value for value in data.values()):
        raise ValueError("empty translations")


@lru_cache(maxsize=4)
def _read_snapshot(path: str, modified: int, size: int) -> dict:
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("invalid snapshot")
    return snapshot


def read_tables(game: str) -> dict:
    path = resource_path(game)
    try:
        stat = path.stat()
        tables = _read_snapshot(str(path), stat.st_mtime_ns, stat.st_size)
        if set(TABLES[game]) - tables.keys():
            raise ValueError("incomplete snapshot")
        return tables
    except (OSError, ValueError, TypeError) as error:
        raise GuideError("查询资源尚未就绪，请发送“明日方舟更新资源”或“终末地更新资源”") from error


def _save_tables(game: str, tables: dict) -> None:
    for name in TABLES[game]:
        validate_table(game, name, tables[name])
    path = resource_path(game)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(tables, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    _read_snapshot.cache_clear()
    if game == "endfield":
        from .endfield_gamedata import TableCfg
        TableCfg.reload()


async def ensure_guide_resources(game: str, proxy: str | None = None, *, force: bool = False) -> dict:
    if not force:
        try:
            return await asyncio.to_thread(read_tables, game)
        except GuideError:
            pass
    async with _LOCKS.setdefault(game, asyncio.Lock()):
        if not force:
            try:
                return await asyncio.to_thread(read_tables, game)
            except GuideError:
                pass
        semaphore = asyncio.Semaphore(4)
        bases = ARK_BASES if game == "arknights" else END_BASES
        async with httpx.AsyncClient(proxy=proxy, timeout=60, follow_redirects=True) as client:
            async def download(name: str) -> tuple[str, dict]:
                async with semaphore:
                    for base in bases:
                        try:
                            response = await client.get(f"{base}/{name}.json")
                            response.raise_for_status()
                            data = response.json()
                            validate_table(game, name, data)
                            return name, data
                        except (httpx.HTTPError, ValueError):
                            continue
                    raise GuideError(f"{name} 下载失败，已保留原有资源，请稍后重试")
            # return_exceptions 避免失败后仍有下载任务继续使用已关闭的 client。
            results = await asyncio.gather(*(download(name) for name in TABLES[game]), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        tables = dict(results)
        await asyncio.to_thread(_save_tables, game, tables)
        return tables
