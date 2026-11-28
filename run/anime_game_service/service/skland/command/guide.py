"""沿用米游社攻略的游戏前缀、关键词前/后置及按游戏更新资源入口。"""
from __future__ import annotations

import asyncio
import re
import shlex
import unicodedata

from developTools.message.message_components import At, Image
from developTools.utils.logger import get_logger

from .card import GAME_ALIASES
from ..utils.arknights_wiki import find_operator, module_sections, operator_sections
from ..utils.guide_resource import GuideError, ensure_guide_resources, resource_path

logger = get_logger("skland")
KEYWORDS = {
    "arknights": {f"{category}{action}": kind
                  for category, kind in (("干员", "operator"), ("模组", "module"))
                  for action in ("图鉴", "攻略")},
    "endfield": {f"武器{action}": "gem" for action in ("图鉴", "攻略")},
}
UPDATE_WORDS = {"更新资源", "资源更新", "更新攻略", "攻略更新", "下载资源"}


def parse_guide_command(context: str) -> tuple[str, str, str] | None:
    text = unicodedata.normalize("NFKC", context or "").strip()
    aliases = sorted(((unicodedata.normalize("NFKC", alias), game) for game, names in GAME_ALIASES.items()
                      for alias in names), key=lambda item: len(item[0]), reverse=True)
    for alias, game in aliases:
        if text.casefold().startswith(alias.casefold()):
            text = text[len(alias):].strip(" :")
            break
    else:
        return None
    if re.sub(r"\s+", "", text) in UPDATE_WORDS:
        return game, "update", ""
    for keyword, kind in sorted(KEYWORDS[game].items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.escape(keyword[:-2]) + r"\s*" + re.escape(keyword[-2:])
        prefix = re.match(pattern, text)
        if prefix:
            return game, kind, text[prefix.end():].strip(" :")
        suffix = re.search(pattern + r"$", text)
        if suffix:
            return game, kind, text[:suffix.start()].strip(" :")
    return None


def query_gems(query: str):
    from ..utils.endfield_gamedata import WeaponGemInfoTable
    whole = WeaponGemInfoTable.get_by_weapon_name(query)
    if whole and whole.best_energy_point:
        return [whole], []
    try:
        names = shlex.split(re.sub(r"[,，、/;；\n]+", " ", query))
    except ValueError as error:
        raise GuideError("武器名称引号不完整，请用空格分隔多个完整武器名") from error
    names = list(dict.fromkeys(names))
    if len(names) > 8:
        raise GuideError("每次最多查询 8 把武器，请分批查询")
    data, missing, seen = [], [], set()
    for name in names:
        item = WeaponGemInfoTable.get_by_weapon_name(name)
        if item is None or item.best_energy_point is None:
            missing.append(name)
        elif item.weapon.id not in seen:
            data.append(item)
            seen.add(item.weapon.id)
    if not data:
        raise GuideError("未找到对应武器的基质推荐，请使用完整武器名；新武器可先发送“终末地更新资源”")
    return data, missing


def gem_icon_requests(data) -> list[tuple[str, str]]:
    from ..utils.draw_gem import _get_bound_character_ids, _list_extra_weapon_names, _select_display_plans, _select_multi_point_plans
    from ..utils.endfield_gamedata import WeaponInfoTable
    weapons = {item.weapon.id for item in data}
    for plan in _select_display_plans(_select_multi_point_plans(data), data):
        for name in _list_extra_weapon_names(plan, data):
            item = WeaponInfoTable.get_by_name(name)
            if item:
                weapons.add(item.id)
    icons = [("weapon", item) for item in weapons]
    icons.extend(("char", char) for weapon in weapons for char in _get_bound_character_ids(weapon, limit=3))
    return icons


async def handle_skland_guide_command(context: str, user_id: str, bot=None, event=None,
                                      proxy: str | None = None) -> bool:
    parsed = parse_guide_command(context)
    if parsed is None:
        return False
    game, kind, query = parsed
    async def send(message):
        if bot is not None and event is not None:
            await bot.send(event, [At(qq=str(user_id)), message])
        else:
            print(message)
    try:
        if kind != "update" and not query:
            await send("用法：明日方舟/方舟 + 干员/模组 + 图鉴/攻略 + 干员名；"
                       "终末地 + 武器 + 图鉴/攻略 + 武器名。"
                       "例如：方舟干员攻略能天使、明日方舟模组图鉴能天使、终末地武器攻略落草 不知归")
            return True
        if kind == "update" or not resource_path(game).exists():
            await send(f"正在{'更新' if kind == 'update' else '首次下载'}{'明日方舟' if game == 'arknights' else '终末地'}查询资源，请稍候")
        async with asyncio.timeout(300):
            tables = await ensure_guide_resources(game, proxy, force=kind == "update")
        if kind == "update":
            await send(f"{'明日方舟' if game == 'arknights' else '终末地'}查询资源更新完成，共 {len(tables)} 张游戏表")
            return True
        from ..utils.guide_image import ensure_icons
        if game == "arknights":
            char_id, char = await asyncio.to_thread(find_operator, tables, query)
            sections = await asyncio.to_thread(module_sections if kind == "module" else operator_sections, tables, char_id)
            await ensure_icons(game, [("char", char_id)], proxy)
            from ..utils.draw_wiki import render_wiki
            paths = await asyncio.to_thread(render_wiki, char_id, char["name"], "模组图鉴" if kind == "module" else "干员图鉴", sections)
        else:
            data, missing = await asyncio.to_thread(query_gems, query)
            await ensure_icons(game, await asyncio.to_thread(gem_icon_requests, data), proxy)
            from ..utils.draw_gem import draw_gem_recommend_img
            paths = [await asyncio.to_thread(draw_gem_recommend_img, data, missing)]
        for path in paths:
            await send(Image(file=str(path)))
    except GuideError as error:
        await send(str(error))
    except TimeoutError:
        await send("查询资源下载超时，请稍后重试；已保留原有资源")
    except Exception as error:
        logger.warning(f"森空岛图鉴查询失败：{type(error).__name__}")
        await send("查询或绘图失败，请稍后重试；可发送对应游戏的“更新资源”刷新游戏表")
    return True
