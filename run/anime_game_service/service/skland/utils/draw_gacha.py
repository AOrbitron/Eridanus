"""森空岛寻访统计；按 BeyondUID 的游戏素材布局，每次生成独立的新图片。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .gacha import CN_TIME, ROOT, all_records, record_counts, record_order

PROJECT = Path(__file__).resolve().parents[5]
FONT = PROJECT / "framework_common/manshuo_draw/data/fort/LXGWWenKai-Regular.ttf"
OUTPUT_DIR = PROJECT / "data/pictures/cache"
TEXTURES = Path(__file__).resolve().parents[1] / "core/resources/images"
GAME_NAMES = {"arknights": "明日方舟", "endfield": "终末地"}
# 与参考项目的资源仓库路径一致；部分镜像尚未同步 BeyondUID，按顺序回退。
MIRRORS = (
    "https://silverwing.elysia.beauty",
    "http://lulush.microgg.cn",
    "http://cn-js-nj-1.lcf.icu:13214",
    "http://tw-taipei-1.lcf.icu:20532",
    "http://sg-1.lcf.icu:12588",
    "http://us-lax-2.lcf.icu:12588",
    "http://file.minigg.cn/sayu-bot",
    "https://gscore.focalors.com",
    "https://sg-2.qxqx.cf",
    "https://kr.qxqx.cf",
    "https://jp.qxqx.cf",
)
CARD_W, CARD_H, CARD_STEP = 180, 260, 180
HEADER_HEIGHT = 695
FOLLOWING_COLUMN_TOP = 48


def rarity(game: str, row: dict) -> int:
    # 明日方舟官网样式将 rarity=5 标作六星；终末地直接返回星数。
    value = int(row.get("rarity", 0))
    return value + 1 if game == "arknights" else value


def _group(game: str, kind: str, name: str, row: dict) -> tuple[str, str]:
    if game == "arknights":
        return name, name
    pool = str(row.get("poolId", ""))
    if kind == "weapon":
        return f"weapon:{pool}:{row.get('poolVersion') or ''}", "武器申领 · " + str(row.get("poolName") or name)
    for prefix, title in (("special_", "特许寻访"), ("standard", "基础寻访"), ("beginner", "新手寻访")):
        if pool.startswith(prefix):
            return prefix, title
    return f"char:{pool}:{row.get('poolVersion') or ''}", name + " · " + str(row.get("poolName") or "角色池")


def summaries(payload: dict) -> list[dict]:
    """赠礼不计抽；免费抽独立统计，且不改变付费抽的六星间隔。"""
    groups = OrderedDict()
    game = payload["game"]
    for kind, name, row in reversed(all_records(payload)):
        if row.get("kind", "draw") != "draw":
            continue
        key, title = _group(game, kind, name, row)
        group = groups.setdefault(key, {"name": title, "kind": kind, "rows": [], "events": [], "total": 0, "free": 0, "six": 0, "paid_six": 0, "tail": 0, "cost_sum": 0})
        group["rows"].append(row)
        group["total"] += 1
        free = bool(row.get("isFree"))
        group["free"] += free
        if not free:
            group["tail"] += 1
        if rarity(game, row) == 6:
            group["six"] += 1
            group["events"].append({"record": row, "cost": group["tail"], "free": free, "kind": kind})
            if not free:
                group["cost_sum"] += group["tail"]
                group["paid_six"] += 1
                group["tail"] = 0
    for group in groups.values():
        group["events"].reverse()
        group["average"] = group["cost_sum"] / group["paid_six"] if group["paid_six"] else None
    return sorted(groups.values(), key=lambda group: record_order(group["rows"][-1]), reverse=True)


def _asset_name(value: str) -> str | None:
    return value if re.fullmatch(r"[A-Za-z0-9_@#-]{1,100}", value) else None


def icon_path(game: str, kind: str, row: dict) -> Path | None:
    item = _asset_name(str(row.get("weaponId" if kind == "weapon" else "charId", "")))
    if not item:
        return None
    return ROOT / game / "assets" / f"{kind}_{item.replace('@', '_').replace('#', '_')}.png"


def _icon_urls(game: str, kind: str, row: dict) -> list[str]:
    item = _asset_name(str(row.get("weaponId" if kind == "weapon" else "charId", "")))
    if not item:
        return []
    if game == "arknights":
        return [f"https://web.hycdn.cn/arknights/game/assets/char/avatar/{quote(item, safe='')}.png"]
    relative = f"itemiconbig/{item}.png" if kind == "weapon" else f"charicon/icon_{item}.png"
    return [f"{base}/BeyondUID/resource/{relative}" for base in MIRRORS]


def _valid_icon(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (OSError, ValueError):
        return False


def _write_icon(path: Path, data: bytes) -> None:
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGBA")
        img.thumbnail((512, 512))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
        try:
            img.save(temporary, format="PNG")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


async def cache_icons(payload: dict, proxy: str | None = None) -> None:
    game, wanted = payload["game"], {}
    for group in summaries(payload):
        for event in group["events"]:
            path = icon_path(game, event["kind"], event["record"])
            if path is not None and path not in wanted:
                wanted[path] = (event["kind"], event["record"])
    semaphore = asyncio.Semaphore(6)
    async with httpx.AsyncClient(proxy=proxy, timeout=4.0, follow_redirects=True) as client:
        async def download(path, kind, row):
            if await asyncio.to_thread(_valid_icon, path):
                return
            async with semaphore:
                for url in _icon_urls(game, kind, row):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        await asyncio.to_thread(_write_icon, path, response.content)
                        return
                    except (httpx.HTTPError, OSError, ValueError):
                        continue
        try:
            async with asyncio.timeout(25):
                await asyncio.gather(*(download(path, kind, row) for path, (kind, row) in wanted.items()))
        except TimeoutError:
            pass  # 可用头像照常绘制，未下载到的头像显示名称，下一次查询再补。


def _font(size: int):
    return ImageFont.truetype(str(FONT), size)


def _fit(draw, text: str, size: int, width: int) -> str:
    text = str(text)
    while text and draw.textlength(text, font=_font(size)) > width:
        text = text[:-2] + "…" if len(text) > 2 else ""
    return text


def _texture(name: str) -> Image.Image:
    with Image.open(TEXTURES / f"gacha_{name}") as image:
        return image.convert("RGBA")


def _open_icon(game: str, kind: str, row: dict, size: tuple[int, int]) -> Image.Image | None:
    path = icon_path(game, kind, row)
    if path is None:
        return None
    try:
        with Image.open(path) as icon:
            return ImageOps.contain(icon.convert("RGBA"), size, Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def _draw_event(img: Image.Image, game: str, event: dict, x: int, y: int) -> None:
    row, kind = event["record"], event["kind"]
    card = _texture("sg_bg.png")
    avatar = _open_icon(game, kind, row, (156, 193))
    painter = ImageDraw.Draw(card)
    name = row.get("weaponName" if kind == "weapon" else "charName") or row.get("nameText") or "未知"
    if avatar is not None:
        card.alpha_composite(avatar, ((CARD_W - avatar.width) // 2, 9 + (193 - avatar.height) // 2))
    else:
        painter.text((90, 100), str(name)[:3], font=_font(32), fill="#343434", anchor="mm")
    if event.get("up"):
        card.alpha_composite(_texture("up_tag.png").resize((80, 80)), (100, 4))
    card.alpha_composite(_texture("sg6_fg.png"))
    painter = ImageDraw.Draw(card)
    if row.get("isNew"):
        painter.rectangle((15, 10, 60, 28), fill="#fff800")
        painter.text((37, 19), "NEW", font=_font(14), fill="#252525", anchor="mm")
    painter.rectangle((12, 187, 168, 218), fill=(245, 245, 245, 215))
    painter.text((90, 202), _fit(painter, name, 19, 148), font=_font(19), fill="#333333", anchor="mm")
    painter.text((90, 235), "欧皇" if event["free"] else f"{event['cost']}抽",
                 font=_font(30), fill="white", anchor="mm")
    img.alpha_composite(card, (x, y))


def _record_date(timestamp: int) -> str:
    seconds = timestamp / 1000 if timestamp > 100_000_000_000 else timestamp
    return datetime.fromtimestamp(seconds, tz=CN_TIME).strftime("%Y.%m.%d")


def _date_range(rows: list[dict]) -> str:
    if not rows:
        return "暂无已记录明细"
    timestamps = [record_order(row)[0] for row in rows]
    return f"{_record_date(min(timestamps))} ~ {_record_date(max(timestamps))}"


def _display_groups(payload: dict) -> list[dict]:
    groups = summaries(payload)
    if payload["game"] != "endfield":
        return groups
    # 保留每个武器池独立计算的六星间隔，视觉上与 BeyondUID 一样放在同一个武器区。
    weapons = [group for group in groups if group["kind"] == "weapon"]
    groups = [group for group in groups if group["kind"] != "weapon"]
    if weapons:
        recent = max(weapons, key=lambda group: record_order(group["rows"][-1]))
        combined = dict(recent, name="武库申领", rows=[row for group in weapons for row in group["rows"]],
                        events=sorted([event for group in weapons for event in group["events"]],
                                      key=lambda event: record_order(event["record"]), reverse=True))
        for key in ("total", "free", "six", "paid_six", "cost_sum"):
            combined[key] = sum(group[key] for group in weapons)
        combined["average"] = combined["cost_sum"] / combined["paid_six"] if combined["paid_six"] else None
        combined["pity_title"] = "最近池"
        groups.append(combined)
    priority = {"特许寻访": 0, "武库申领": 1, "基础寻访": 2, "新手寻访": 3}
    return sorted(groups, key=lambda group: priority.get(group["name"], 4))


def _draw_header(img: Image.Image, payload: dict, groups: list[dict]) -> None:
    game = payload["game"]
    if game == "endfield":
        img.alpha_composite(_texture("title.png"), (0, -87))
    else:
        # ArknightsUID 的模拟十连不提供历史统计页，沿用版式并使用方舟自己的背景。
        with Image.open(TEXTURES / "background/rogue/pic_rogue_4_47.png") as source:
            banner = ImageOps.fit(source.convert("RGBA"), (1200, 510), Image.Resampling.LANCZOS)
        banner.alpha_composite(Image.new("RGBA", banner.size, (5, 20, 27, 130)))
        img.alpha_composite(banner)
        ImageDraw.Draw(img).text((65, 85), "RHODES ISLAND / RECRUITMENT", font=_font(39), fill="white")
    painter = ImageDraw.Draw(img)
    profile = payload.get("profile", {})
    nickname = profile.get("nickname") or ("博士" if game == "arknights" else "管理员")
    level = f"  Lv.{profile['level']}" if profile.get("level") is not None else ""
    painter.rectangle((210, 352, 790, 411), fill=(15, 28, 33, 225))
    painter.text((222, 378), _fit(painter, nickname + level, 33, 555), font=_font(33), fill="white", anchor="lm")
    if game == "arknights":
        painter.rectangle((210, 412, 790, 452), fill=(230, 233, 231, 235))
    painter.text((222, 427), f"UID: {payload['uid']}  ·  {GAME_NAMES[game]}", font=_font(23), fill="#242424", anchor="lm")
    first = next((event for group in groups for event in group["events"]), None)
    if first:
        avatar = _open_icon(game, first["kind"], first["record"], (137, 137))
        if avatar is not None:
            img.alpha_composite(avatar, (55 + (137 - avatar.width) // 2, 326))
    if game == "endfield":
        img.alpha_composite(_texture("frame_fg.png"), (52, 326))
    else:
        painter.rectangle((53, 325, 195, 468), outline="#eeeeee", width=2)
        painter.rectangle((53, 325, 59, 363), fill="#fff500")
    total, gifts = record_counts(payload)
    six, free = sum(group["six"] for group in groups), sum(group["free"] for group in groups)
    for x, number, label in ((906, free, "免费次数"), (1070, gifts, "附加奖励")):
        painter.text((x, 391), str(number), font=_font(40), fill="white", anchor="mm")
        painter.text((x, 427), label, font=_font(20), fill="#ffe900", anchor="mm")
    for index, (label, value) in enumerate((("已记录", total), ("六星", six))):
        tile = _texture("yellow_card.png")
        brush = ImageDraw.Draw(tile)
        if game == "arknights":
            brush.rectangle((48, 48, 130, 118), fill="#fff500")
            brush.polygon(((63, 100), (89, 55), (115, 100)), outline="#252525", width=3)
            brush.text((89, 112), "RHODES", font=_font(12), fill="#252525", anchor="mm")
        brush.text((265, 94), label, font=_font(30), fill="#333333", anchor="rm")
        brush.text((282, 87), str(value), font=_font(46), fill="#333333", anchor="lm")
        img.alpha_composite(tile, (38 + index * 544, 485))
    painter.text((70, 654), "寻访档案 / RECRUITMENT RECORDS", font=_font(20), fill="#eeeeee")
    timestamps = [record_order(row)[0] for group in groups for row in group["rows"]]
    if timestamps:
        painter.text((1130, 654), f"记录范围：自 {_record_date(min(timestamps))} 起",
                     font=_font(24), fill="#fff500", anchor="ra")


def _draw_pool_header(img: Image.Image, payload: dict, group: dict, title: str, y: int, x_offset: int = 0) -> None:
    header = Image.new("RGBA", (1200, 300))
    representative = group["events"][0] if group["events"] else None
    if representative:
        avatar = _open_icon(payload["game"], representative["kind"], representative["record"], (380, 280))
        if avatar is not None:
            # 同上游：代表干员在斜切统计面板后露出。
            header.alpha_composite(avatar, (780 + (380 - avatar.width) // 2, 10))
    header.alpha_composite(_texture("card_bg.png"))
    painter = ImageDraw.Draw(header)
    fitted_title = _fit(painter, title, 32, 1020)
    title_width = painter.textlength(fitted_title, font=_font(32))
    if title_width > 250:
        painter.rectangle((74, 26, 94 + title_width, 64), fill="#fff500")
    painter.text((82, 46), fitted_title, font=_font(32), fill="#444444", anchor="lm")
    badge = _texture("A.png")
    badge_draw = ImageDraw.Draw(badge)
    pity_title = group.get("pity_title", "当前")
    badge_draw.text((100, 30), f"{pity_title}已", font=_font(20), fill="#252525", anchor="lm")
    badge_draw.text((210, 27), str(group["tail"]), font=_font(36), fill="#d84213", anchor="mm")
    badge_draw.text((244, 30), "抽未出六星", font=_font(20), fill="#252525", anchor="lm")
    header.alpha_composite(badge, (107, 72))
    average = f"{group['average']:.1f}" if group["average"] is not None else "—"
    for x, value, label in ((200, average, "已记录平均"), (334, group["free"], "免费次数"),
                            (468, group["total"], "记录抽数"), (602, group["six"], "六星数量")):
        painter.text((x, 190), str(value), font=_font(35), fill="#222222", anchor="mm")
        painter.text((x, 223), label, font=_font(20), fill="#444444", anchor="mm")
    painter.text((1110, 226), _date_range(group["rows"]), font=_font(24), fill="#333333", anchor="rm")
    img.alpha_composite(header, (x_offset, y))


def _panel_height(events: list) -> int:
    return 300 + max(1, (len(events) + 5) // 6) * 270


def _layout_columns(panels: list[tuple[dict, str, list]]) -> list[tuple[list, int]]:
    """Pack whole pool panels vertically, adding image columns instead of sending another image."""
    columns, current, height = [], [], 0
    for panel in panels:
        panel_height = _panel_height(panel[2])
        if current and height + panel_height > 2100:
            columns.append((current, height))
            current, height = [], 0
        current.append((panel, height))
        height += panel_height
    if current:
        columns.append((current, height))
    return columns


def draw_cards(payload: dict) -> list[Path]:
    """上游的黄黑灰配色、斜切池头和六列卡片；每次绘制新文件，不读取成品图。"""
    groups = _display_groups(payload)
    panels = []
    for group in groups:
        events = group["events"]
        chunks = [events[i:i + 36] for i in range(0, len(events), 36)] or [[]]
        for index, chunk in enumerate(chunks):
            title = group["name"] + (f" ({index + 1}/{len(chunks)})" if len(chunks) > 1 else "")
            panels.append((group, title, chunk))
    columns = _layout_columns(panels)
    if not columns:
        return []
    column_tops = [HEADER_HEIGHT if index == 0 else FOLLOWING_COLUMN_TOP for index in range(len(columns))]
    image_height = max(top + height for top, (_, height) in zip(column_tops, columns)) + 160
    image_width = 1200 * len(columns)
    paths = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    background = ImageOps.fit(_texture("bg4.jpg"), (1200, image_height), Image.Resampling.LANCZOS)
    img = Image.new("RGBA", (image_width, image_height))
    header = Image.new("RGBA", (1200, 695))
    _draw_header(header, payload, groups)
    for col in range(len(columns)):
        x = col * 1200
        img.alpha_composite(background, (x, 0))
        if col == 0:
            img.alpha_composite(header, (x, 0))
    for col, (column, _) in enumerate(columns):
        x = col * 1200
        for (group, title, events), offset in column:
            y = column_tops[col] + offset
            _draw_pool_header(img, payload, group, title, y, x)
            for index, event in enumerate(events):
                row = event["record"]
                item_id = row.get("weaponId" if event["kind"] == "weapon" else "charId")
                marked = {**event, "up": item_id in payload.get("up_map", {}).get(row.get("poolId"), [])}
                _draw_event(img, payload["game"], marked,
                            x + 60 + index % 6 * CARD_STEP, y + 280 + index // 6 * 270)
            if not events:
                ImageDraw.Draw(img).text((x + 600, y + 390), "暂无已记录的六星干员", font=_font(28), fill="#dddddd", anchor="mm")
    painter = ImageDraw.Draw(img)
    y = img.height - 140
    painter.rectangle((40, y - 10, image_width - 40, img.height - 25), fill=(18, 23, 27, 245))
    note = "官方仅提供最近90天记录，图中包含已存档历史，不代表账号累计抽数。"
    painter.text((70, y), note, font=_font(22), fill="#fff500")
    painter.text((70, y + 34), "免费抽与附加奖励单列，六星间隔仅依据已记录的非免费抽计算。", font=_font(20), fill="#eeeeee")
    painter.text((70, y + 70), f"{payload.get('updated_at', '未知')}  ·  共 {len(columns)} 列", font=_font(19), fill="#cccccc")
    painter.text((image_width - 70, y + 70), "function by manshuo", font=_font(21), fill="#eeeeee", anchor="ra")
    path = OUTPUT_DIR / f"skland_{payload['game']}_{payload['uid']}_{uuid4().hex}.png"
    img.convert("RGB").save(path)
    paths.append(path)
    return paths


async def pool_up_map(proxy: str | None = None) -> dict[str, list[str]]:
    """与 BeyondUID 一样读取游戏表标注 UP，缺失池不猜测 UP 或不歪率。"""
    result = {}
    async with httpx.AsyncClient(proxy=proxy, timeout=4.0, follow_redirects=True) as client:
        async def fetch(filename, field):
            for base in MIRRORS[:3]:
                try:
                    response = await client.get(f"{base}/BeyondUID/TableCfg/{filename}.json")
                    response.raise_for_status()
                    table = response.json()
                    return {key: value[field] for key, value in table.items()
                            if isinstance(value, dict) and isinstance(value.get(field), list)}
                except (httpx.HTTPError, ValueError, AttributeError):
                    continue
            return {}
        try:
            async with asyncio.timeout(10):
                tables = await asyncio.gather(fetch("GachaCharPoolTable", "upCharIds"), fetch("GachaWeaponPoolTable", "upWeaponIds"))
                for table in tables:
                    result.update(table)
        except TimeoutError:
            pass
    return result


async def render_cards(payload: dict, proxy: str | None = None) -> list[Path]:
    await cache_icons(payload, proxy)
    props = dict(payload)
    if payload["game"] == "endfield":
        props["up_map"] = await pool_up_map(proxy)
    return await asyncio.to_thread(draw_cards, props)
