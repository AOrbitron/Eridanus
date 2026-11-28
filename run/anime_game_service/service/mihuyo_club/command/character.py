"""各游戏角色攻略查询与手动资源更新。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unicodedata
from PIL import Image as PILImage, ImageDraw, ImageFont

from developTools.message.message_components import At, Image

from .config import game_name_list
from ..utils.character_resource import (
    DEFAULT_FIRST_RESOURCE, DEFAULT_RESOURCE_SOURCE, GAME_RESOURCE_UPDATERS, GUIDE_PROVIDERS,
    GENSHIN_GUIDE_PATH, HI3_GUIDE_PATH, STARRAIL_GUIDE_PATH, ZZZ_GUIDE_PATH,
    migrate_zzz_character_resources, update_game_resources,
)

__all__ = ["handle_character_command", "mys_character_guide", "mys_update_game_resources"]

ALIAS_PATH = Path(__file__).resolve().parent.parent / "utils" / "resources" / "zzz_character" / "char_alias.json"
GENSHIN_ALIAS_PATH = Path(__file__).resolve().parent.parent / "utils" / "resources" / "genshin_char_alias.json"
STARRAIL_RESOURCE_PATH = Path(__file__).resolve().parent.parent / "utils" / "resources" / "starrail_character"
STARRAIL_ALIAS_PATH = STARRAIL_RESOURCE_PATH / "char_alias.json"
STARRAIL_NAME_PATH = STARRAIL_RESOURCE_PATH / "avatarId2Name_mapping.json"
HI3_FONT_PATH = Path(__file__).resolve().parent.parent / "utils" / "resources" / "zzz_note" / "zzz_fonts.ttf"


def _normal_name(name: str) -> str:
    return "".join(unicodedata.normalize("NFKC", name).casefold().split()).strip("「」『』\"'")


def _match_alias(name: str, alias_path: Path) -> set[str]:
    normalized = _normal_name(name)
    aliases = json.loads(alias_path.read_text(encoding="utf-8")) if alias_path.is_file() else {}
    for canonical, names in aliases.items():
        if normalized in {_normal_name(value) for value in [canonical, *(names or [])]}:
            return {_normal_name(value) for value in [canonical, *(names or [])]}
    return {normalized}


def _find_guide(name: str, first_resource: str = DEFAULT_FIRST_RESOURCE) -> Path | None:
    if not name.strip() or any(char in name for char in "/\\\0") or name.strip() in {".", ".."}:
        return None
    migrate_zzz_character_resources()
    if not isinstance(first_resource, str) or first_resource not in GUIDE_PROVIDERS:
        first_resource = DEFAULT_FIRST_RESOURCE
    normalized = _normal_name(name)
    matching_names = {normalized}
    aliases = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    for canonical, names in aliases.items():
        alias_names = {_normal_name(alias) for alias in [canonical, *names]}
        if normalized in alias_names:
            matching_names = alias_names
            break
    providers = [first_resource, *(provider for provider in GUIDE_PROVIDERS if provider != first_resource)]
    for provider in providers:
        guide_path = ZZZ_GUIDE_PATH / GUIDE_PROVIDERS[provider]
        for suffix in (".jpg", ".jpeg", ".png"):
            for path in sorted(guide_path.glob("*")):
                if path.suffix.lower() == suffix and _normal_name(path.stem) in matching_names and path.is_file():
                    return path
    return None


def _find_static_guide(name: str, target: str) -> Path | None:
    if not name.strip() or any(char in name for char in "/\\\0"):
        return None
    normalized = _normal_name(name)
    if target == "原神":
        alias_data = json.loads(GENSHIN_ALIAS_PATH.read_text(encoding="utf-8")) if GENSHIN_ALIAS_PATH.is_file() else {}
        for canonical, names in alias_data.items():
            if normalized not in {_normal_name(value) for value in [canonical, *(names or [])]}:
                continue
            if canonical.startswith("旅行者") and len(canonical) >= 4:
                canonical = f"{canonical[:3]}-{canonical[-1]}"
            candidate = GENSHIN_GUIDE_PATH / f"{canonical}.png"
            if candidate.is_file():
                return candidate
        return None

    if target == "崩坏：星穹铁道":
        aliases_data = json.loads(STARRAIL_ALIAS_PATH.read_text(encoding="utf-8")) if STARRAIL_ALIAS_PATH.is_file() else {}
        names_data = json.loads(STARRAIL_NAME_PATH.read_text(encoding="utf-8")) if STARRAIL_NAME_PATH.is_file() else {}
        for char_id, values in (aliases_data.get("characters") or {}).items():
            canonical = names_data.get(char_id, "")
            if normalized in {_normal_name(value) for value in [canonical, *(values or [])]}:
                candidate = STARRAIL_GUIDE_PATH / f"{char_id}.png"
                return candidate if candidate.is_file() else None
        return None
    return None


def _render_hi3_guide(path: Path) -> Path | None:
    import html
    import re

    try:
        detail = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    width, height = 1500, 1050
    canvas = PILImage.new("RGB", (width, height), (27, 34, 45))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype(str(HI3_FONT_PATH), 54)
        heading_font = ImageFont.truetype(str(HI3_FONT_PATH), 33)
        body_font = ImageFont.truetype(str(HI3_FONT_PATH), 26)
    except OSError:
        title_font = heading_font = body_font = ImageFont.load_default()
    draw.text((55, 45), str(detail.get("title") or "崩坏3角色攻略"), font=title_font, fill=(255, 213, 112))
    draw.text((60, 125), str(detail.get("summary") or "角色评价与装备推荐"), font=body_font, fill=(209, 217, 226))
    draw.rounded_rectangle((55, 185, width - 55, 190), radius=2, fill=(255, 213, 112))

    def plain_text(value: object) -> str:
        text = str(value or "")
        text = re.sub(r"<\s*br\s*/?\s*>|</p\s*>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return " ".join(html.unescape(text).split())

    y = 225
    for item in detail.get("evaluation") or []:
        if not isinstance(item, dict):
            continue
        key, data = str(item.get("partKey") or ""), item.get("data") or {}
        if key == "basicIntroduction":
            draw.text((60, y), f"角色评级：{data.get('finalLevel') or '—'}", font=heading_font, fill=(255, 213, 112)); y += 58
            for value in data.get("subFields") or []:
                label, text = plain_text(value.get("name")), plain_text(value.get("value"))
                if label or text:
                    draw.text((65, y), f"{label}：{text[:46]}", font=body_font, fill=(236, 239, 243)); y += 44
        elif key == "equipmentRecommendation":
            draw.text((60, y), "装备推荐", font=heading_font, fill=(255, 213, 112)); y += 48
            for group in data.get("equipment") or []:
                draw.text((70, y), str(group.get("name_") or "推荐搭配"), font=body_font, fill=(175, 220, 255)); y += 38
                for equip in group.get("equips") or []:
                    title = str(equip.get("title") or "")
                    if title:
                        draw.text((88, y), f"· {title}", font=body_font, fill=(236, 239, 243)); y += 35
                reason = " ".join(str(group.get("reason") or "").split())
                reason = plain_text(reason)
                if reason:
                    draw.text((88, y), reason[:70], font=body_font, fill=(190, 200, 210)); y += 38
        if y > height - 90:
            break
    draw.text((width - 350, height - 55), "Function By manshuo", font=body_font, fill=(160, 170, 182))
    output = path.with_suffix(".png")
    canvas.save(output)
    return output


def _find_hi3_guide(name: str) -> Path | None:
    normalized = _normal_name(name)
    for item in HI3_GUIDE_PATH.glob("*.json"):
        try:
            detail = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names = [str(detail.get("title") or ""), *(detail.get("aliases") or [])]
        if any(normalized == _normal_name(value) or normalized in _normal_name(value) for value in names):
            return _render_hi3_guide(item)
    return None


async def _send(message, bot=None, event=None) -> None:
    if bot:
        await bot.send(event, message)
    else:
        print(message)


async def send_zzz_character_guide(name: str, user_id: str, bot=None, event=None,
                                   first_resource: str = DEFAULT_FIRST_RESOURCE) -> None:
    path = await asyncio.to_thread(_find_guide, name, first_resource)
    if path is None:
        await _send("找不到该角色的攻略呢\n请发送‘绝区零资源更新’", bot, event)
        return
    await _send([At(qq=user_id), Image(file=str(path))], bot, event)


async def send_character_guide(name: str, user_id: str, target: str, bot=None, event=None) -> None:
    if target == "崩坏3":
        path = await asyncio.to_thread(_find_hi3_guide, name)
    else:
        path = await asyncio.to_thread(_find_static_guide, name, target)
    if path is None:
        await _send(f"找不到「{name}」的攻略呢，请发送“{target}更新资源”", bot, event)
        return
    await _send([At(qq=user_id), Image(file=str(path))], bot, event)


GAME_CHARACTER_HANDLERS = {
    "绝区零": send_zzz_character_guide,
    "原神": send_character_guide,
    "崩坏：星穹铁道": send_character_guide,
    "崩坏3": send_character_guide,
    "崩坏学园2": None,
    "未定事件簿": None,
}


async def mys_character_guide(user_id: str, name: str, bot=None, event=None, target: str = "绝区零",
                              first_resource: str = DEFAULT_FIRST_RESOURCE) -> None:
    """按游戏分发攻略查询，其他游戏仅保留接口。"""
    handler = GAME_CHARACTER_HANDLERS.get(target)
    if handler is None:
        await _send(f"{target}角色攻略暂未接入", bot, event)
        return
    if not name.strip():
        #await _send(f"请指定角色名称，例如：{target}艾莲攻略", bot, event)
        return
    if target == "绝区零":
        await handler(name.strip(), user_id, bot, event, first_resource=first_resource)
    else:
        await handler(name.strip(), user_id, target, bot, event)


async def mys_update_game_resources(target: str, bot=None, event=None, proxy: str | None = None,
                                    source: str = DEFAULT_RESOURCE_SOURCE) -> None:
    """手动更新仅指定游戏的资源，与启动时的全游戏资源检查分开。"""
    if GAME_RESOURCE_UPDATERS.get(target) is None:
        await _send(f"{target}资源更新暂未接入", bot, event)
        return
    await _send(f"开始更新{target}资源，请稍候", bot, event)
    result = await update_game_resources(target, force=True, proxy=proxy, source=source)
    if result is None:
        await _send(f"{target}资源更新暂未接入", bot, event)
        return
    if result.checked == 0 and result.failed:
        message = f"{target}资源更新失败，暂时无法获取攻略目录，已保留原有图片，请稍后重试"
    else:
        message = f"{target}资源更新完成：检查 {result.checked} 张，更新 {result.updated} 张，失败 {result.failed} 张"
    await _send(message, bot, event)


async def handle_character_command(context: str, user_id: str, bot=None, event=None,
                                    proxy: str | None = None,
                                    source: str = DEFAULT_RESOURCE_SOURCE,
                                    first_resource: str = DEFAULT_FIRST_RESOURCE) -> bool:
    """按游戏别名前缀识别攻略和手动更新，避免不同游戏互相触发。"""
    text = context.strip()
    aliases = sorted(((alias, game) for game, names in game_name_list.items() for alias in names),
                     key=lambda item: len(item[0]), reverse=True)
    for alias, target in aliases:
        if text.casefold().startswith(alias.casefold()):
            text = text[len(alias):].strip()
            break
    else:
        return False
    if text in {"更新资源", "资源更新", "更新攻略", "攻略更新", "角色攻略更新", "下载资源", "下载全部资源"}:
        await mys_update_game_resources(target, bot, event, proxy=proxy, source=source)
        return True
    if text.startswith("角色攻略"):
        name = text[len("角色攻略"):]
    elif text.startswith("攻略"):
        name = text[len("攻略"):]
    elif text.endswith("角色攻略"):
        name = text[:-len("角色攻略")]
    elif text.endswith("攻略"):
        name = text[:-len("攻略")]
    else:
        return False
    await mys_character_guide(user_id, name.strip(" ：:，,"), bot, event, target, first_resource=first_resource)
    return True
