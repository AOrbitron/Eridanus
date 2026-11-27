"""使用 Pillow 绘制原神、崩铁、绝区零便签，布局和素材参考 ZZZeroUID。

上游：https://github.com/ZZZure/ZZZeroUID（AGPL-3.0）
素材来源与许可证见 resources/zzz_note/README.md。
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

if TYPE_CHECKING:
    from ..model.common import GameRecord, GenshinNote, StarRailNote, ZZZNote


RESOURCE_PATH = Path(__file__).resolve().parent / "resources" / "zzz_note"
CACHE_PATH = Path(__file__).resolve().parents[5] / "data" / "pictures" / "cache"
YELLOW = (255, 200, 1)
GREY = (216, 216, 216)


def _load_asset(name: str) -> Image.Image:
    with Image.open(RESOURCE_PATH / name) as image:
        return image.convert("RGBA")


async def _fetch_qq_avatar(user_id: Optional[str]) -> Optional[bytes]:
    if user_id is None or not str(user_id).isdigit():
        return None
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            response = await client.get("https://q1.qlogo.cn/g", params={"b": "qq", "nk": str(user_id), "s": "640"})
            response.raise_for_status()
            return response.content
    except httpx.HTTPError:
        return None


def _avatar_image(data: Optional[bytes]) -> Image.Image:
    avatar = None
    if data:
        try:
            with Image.open(BytesIO(data)) as source:
                avatar = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"), (129, 129))
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            pass
    if avatar is None:
        avatar = Image.new("RGBA", (129, 129), (46, 46, 46))
        draw = ImageDraw.Draw(avatar)
        draw.ellipse((44, 23, 85, 64), fill=(145, 145, 145))
        draw.ellipse((20, 73, 109, 150), fill=(145, 145, 145))
    mask = Image.new("L", (516, 516))
    ImageDraw.Draw(mask).ellipse((0, 0, 515, 515), fill=255)
    avatar.putalpha(mask.resize((129, 129), Image.Resampling.LANCZOS))
    return avatar


def _pending_icon() -> Image.Image:
    icon = Image.new("RGBA", (320, 320))
    draw = ImageDraw.Draw(icon)
    draw.ellipse((24, 24, 296, 296), outline=(112, 112, 112), width=16)
    draw.ellipse((108, 108, 212, 212), fill=(160, 160, 160))
    return icon.resize((80, 80), Image.Resampling.LANCZOS)


def _background(width: int, height: int) -> Image.Image:
    image = ImageOps.fit(_load_asset("background.jpg"), (width, height))
    frame = _load_asset("bg.png")
    # 保留原素材的边框和圆角，只拉伸中间纹理以适配双列。
    sx, sy = (0, 100, 850, 950), (0, 180, 1580, 1700)
    dx, dy = (0, 100, width - 100, width), (0, 180, height - 120, height)
    for row in range(3):
        for column in range(3):
            tile = frame.crop((sx[column], sy[row], sx[column + 1], sy[row + 1]))
            tile = tile.resize((dx[column + 1] - dx[column], dy[row + 1] - dy[row]), Image.Resampling.LANCZOS)
            image.alpha_composite(tile, (dx[column], dy[row]))
    return image


def _fit_label(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    text = " ".join(text.split())
    while font.getlength(text) > width:
        text = text[:-2] + "…"
    return text


def _player_card(fonts, avatar_data, game_uid, role, account_name, default_name, default_region,
                 game_name):
    player_card = _load_asset("player_card_min.png")
    player_card.alpha_composite(_avatar_image(avatar_data), (105, 30))
    draw = ImageDraw.Draw(player_card)
    role_name = role.nickname if role and role.nickname else account_name or default_name
    name = _fit_label(role_name, fonts[38], 360)
    draw.text((290, 64), name, "white", fonts[38], "lm")
    role_uid = role.game_role_id if role else game_uid
    uid_text = f"UID {role_uid}" if role_uid else "UID 未获取"
    draw.text((290, 120), uid_text, GREY, fonts[30], "lm")
    # UID 装饰框的右缘约为 x=562，标签需留出圆角外侧的空隙。
    game_x = round(max(580, 290 + draw.textlength(uid_text, fonts[30]) + 32))
    game_width = round(draw.textlength(game_name, fonts[28]) + 24)
    draw.rounded_rectangle((game_x, 101, game_x + game_width, 136), 10, (1, 183, 255))
    draw.text((game_x + game_width / 2, 118), game_name, (40, 40, 40), fonts[28], "mm")
    name_end = 290 + min(draw.textlength(name, fonts[38]), 360) + 20
    level = str(role.level) if role else "未知"
    region = role.region_name if role and role.region_name else default_region
    draw.rounded_rectangle((name_end, 45, name_end + 90, 80), 10, YELLOW)
    draw.rounded_rectangle((name_end + 102, 45, name_end + 246, 80), 10, (1, 183, 255))
    draw.text((name_end + 45, 62), f"Lv.{level}", (40, 40, 40), fonts[28], "mm")
    draw.text((name_end + 174, 62), _fit_label(region, fonts[28], 132), (40, 40, 40), fonts[28], "mm")
    return player_card


def _draw_zzz_note(note: ZZZNote, account_name: str, avatar_data: Optional[bytes] = None,
                   game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    fonts = {
        size: ImageFont.truetype(str(RESOURCE_PATH / "zzz_fonts.ttf"), size)
        for size in (24, 26, 28, 30, 36, 38, 40, 50)
    }
    image = _background(1900, 1100)
    draw = ImageDraw.Draw(image)
    player_card = _player_card(fonts, avatar_data, game_uid, role, account_name, "绳匠", "新艾利都", "绝区零")
    image.alpha_composite(player_card, (0, 200))

    for name, position in (("battery_banner.png", (0, 402)), ("active_banner.png", (950, 200)),
                           ("abyss_banner.png", (950, 628))):
        image.alpha_composite(_load_asset(name), position)

    battery = _load_asset("battery_card.png")
    battery_draw = ImageDraw.Draw(battery)
    current, maximum = note.current_energy, note.max_energy
    battery_draw.text((565, 111), f"/{maximum if maximum is not None else '-'}", GREY, fonts[36], "lm")
    battery_draw.text((517, 108), str(current) if current is not None else "-", YELLOW, fonts[50], "mm")
    if current is not None and maximum is not None and current >= maximum > 0:
        recovery = "电量已满"
    elif note.energy_restore_time is None:
        recovery = "恢复时间未提供"
    else:
        seconds = max(0, note.energy_restore_time)
        recovery = f"{seconds // 3600}小时{seconds % 3600 // 60}分钟"
    battery_draw.text((454, 152), recovery, "white", fonts[26], "lm")
    if current is not None and maximum is not None and maximum > 0:
        length = int(386 * max(0, min(1, current / maximum)))
        if length > 0:
            battery_draw.rounded_rectangle((415, 230, 415 + length, 246), radius=min(8, length // 2), fill=YELLOW)
    image.alpha_composite(battery, (0, 511))

    yes, pending = _load_asset("yes.png"), _pending_icon()

    def draw_row(title: str, y: int, completed: bool, current: Optional[int] = None,
                 maximum: Optional[int] = None, text: Optional[str] = None):
        bar = _load_asset("bar.png")
        bar.alpha_composite(yes if completed else pending, (93, 10))
        row_draw = ImageDraw.Draw(bar)
        row_draw.text((188, 51), title, GREY, fonts[40], "lm")
        if text is not None:
            row_draw.text((826, 50), text, YELLOW, fonts[50], "rm")
        else:
            row_draw.text((716, 56), f"/{maximum if maximum is not None else '-'}", GREY, fonts[40], "lm")
            row_draw.text((708, 54), str(current) if current is not None else "-", YELLOW, fonts[50], "rm")
        image.alpha_composite(bar, (950, y))

    def is_complete(current: Optional[int], maximum: Optional[int]) -> bool:
        return current is not None and maximum is not None and maximum > 0 and current >= maximum

    draw_row("今日活跃度", 314, is_complete(note.current_vitality, note.max_vitality),
             note.current_vitality, note.max_vitality)
    sale = bool(note.vhs_sale_state and "Doing" in note.vhs_sale_state)
    card = bool(note.card_sign and "Done" in note.card_sign)
    draw_row("录像店经营", 415, sale, text=note.vhs_sale_text if note.vhs_sale_state else "未提供")
    draw_row("刮刮卡", 516, card, text=note.card_sign_text if note.card_sign else "未提供")
    draw_row("悬赏委托", 740, is_complete(note.bounty_num, note.bounty_total),
             note.bounty_num, note.bounty_total)
    draw_row("丽都周纪", 841, is_complete(note.weekly_num, note.weekly_total),
             note.weekly_num, note.weekly_total)

    draw.text((950, 1055), "Function By manshuo", GREY, fonts[24], "mm")
    CACHE_PATH.mkdir(parents=True, exist_ok=True)
    path = CACHE_PATH / f"zzz_note_{uuid4().hex}.png"
    image.convert("RGB").save(path)
    return str(path)


async def draw_zzz_note(note: ZZZNote, account_name: str = "", *, user_id: Optional[str] = None,
                        game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    """使用已有便签和角色 UID 绘图；可获取 QQ 头像，绘制在线程中完成。"""
    avatar_data = await _fetch_qq_avatar(user_id)
    return await asyncio.to_thread(_draw_zzz_note, note, account_name, avatar_data, game_uid, role)


def _note_section(image, fonts, title, x, y):
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x, y, x + 710, y + 58), 12, (22, 22, 22))
    draw.rounded_rectangle((x + 12, y + 13, x + 20, y + 45), 4, YELLOW)
    draw.text((x + 44, y + 30), title, "white", fonts[36], "lm")


def _note_resource(image, fonts, title, current, maximum, seconds, y, accent, *, coin=False, height=220):
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, y, 850, y + height), 24, (25, 25, 25), (100, 100, 100), 3)
    y += (height - 220) // 2
    draw.ellipse((132, y + 39, 274, y + 181), fill=(14, 14, 14), outline=(72, 72, 72), width=4)
    if coin:
        draw.ellipse((166, y + 70, 240, y + 144), fill=accent)
        draw.ellipse((179, y + 83, 227, y + 131), outline=(65, 53, 25), width=4)
        draw.polygon(((203, y + 90), (218, y + 107), (203, y + 124), (188, y + 107)), fill=(65, 53, 25))
    else:
        draw.polygon(((203, y + 62), (242, y + 114), (220, y + 151),
                      (184, y + 151), (163, y + 114)), fill=accent)
        draw.line(((204, y + 85), (183, y + 118), (194, y + 137)), fill="white", width=5)
    draw.text((310, y + 43), title, GREY, fonts[30], "lm")
    number = str(current) if current is not None else "-"
    limit = str(maximum) if maximum is not None else "-"
    draw.text((310, y + 96), f"{number} / {limit}", accent, fonts[50], "lm")
    if current is not None and maximum is not None and maximum > 0 and current >= maximum:
        recovery = "已回满"
    elif seconds is None:
        recovery = "恢复时间未提供"
    elif seconds <= 0:
        recovery = "已回满"
    else:
        minutes = (seconds + 59) // 60
        recovery = f"距回满 {minutes // 60}小时{minutes % 60}分钟"
    draw.text((310, y + 146), recovery, "white", fonts[26], "lm")
    draw.rounded_rectangle((310, y + 183, 800, y + 195), 6, (5, 5, 5))
    if current is not None and maximum is not None and maximum > 0:
        length = round(490 * max(0, min(1, current / maximum)))
        if length:
            draw.rounded_rectangle((310, y + 183, 310 + length, y + 195), min(6, length // 2), accent)


def _note_row(image, fonts, title, y, completed, current=None, maximum=None, text=None):
    bar = _load_asset("bar.png")
    bar.alpha_composite(_load_asset("yes.png") if completed else _pending_icon(), (93, 10))
    draw = ImageDraw.Draw(bar)
    draw.text((188, 51), title, GREY, fonts[40], "lm")
    if text is not None:
        draw.text((826, 51), _fit_label(text, fonts[36], 280), YELLOW, fonts[36], "rm")
    else:
        draw.text((716, 56), f"/{maximum if maximum is not None else '-'}", GREY, fonts[40], "lm")
        draw.text((708, 54), str(current) if current is not None else "-", YELLOW, fonts[50], "rm")
    image.alpha_composite(bar, (950, y))


def _is_complete(current, maximum):
    return current is not None and maximum is not None and maximum > 0 and current >= maximum


def _draw_genshin_note(note: GenshinNote, account_name: str, avatar_data: Optional[bytes] = None,
                       game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    fonts = {
        size: ImageFont.truetype(str(RESOURCE_PATH / "zzz_fonts.ttf"), size)
        for size in (24, 26, 28, 30, 36, 38, 40, 50)
    }
    image = _background(1900, 1100)
    draw = ImageDraw.Draw(image)
    player_card = _player_card(fonts, avatar_data, game_uid, role, account_name, "旅行者", "提瓦特", "原神")
    image.alpha_composite(player_card, (0, 200))

    _note_section(image, fonts, "树脂与洞天", 110, 410)
    _note_section(image, fonts, "每日情况", 1060, 232)
    _note_section(image, fonts, "周期情况", 1060, 664)
    _note_resource(image, fonts, "原粹树脂", note.current_resin, note.max_resin,
                   note.resin_recovery_time, 492, (77, 198, 236))
    _note_resource(image, fonts, "洞天宝钱", note.current_home_coin, note.max_home_coin,
                   note.home_coin_recovery_time, 752, YELLOW, coin=True)

    _note_row(image, fonts, "每日委托", 320, _is_complete(note.finished_task_num, note.total_task_num),
              note.finished_task_num, note.total_task_num)
    reward = note.is_extra_task_reward_received
    _note_row(image, fonts, "委托奖励", 425, reward is True,
              text="已领取" if reward is True else "未领取" if reward is False else "未提供")
    _note_row(image, fonts, "探索派遣", 530, _is_complete(note.current_expedition_num, note.max_expedition_num),
              note.current_expedition_num, note.max_expedition_num)

    transformer = note.transformer or {}
    recovery = transformer.get("recovery_time") or {}
    ready = bool(transformer.get("obtained") and recovery.get("reached"))
    if not transformer:
        transformer_text = "未提供"
    elif not transformer.get("obtained"):
        transformer_text = "未获得"
    elif ready:
        transformer_text = "已就绪"
    elif recovery:
        days, hours, minutes = (recovery.get(key, 0) for key in ("Day", "Hour", "Minute"))
        transformer_text = f"{days}天{hours}小时" if days else f"{hours}小时{minutes}分钟"
    else:
        transformer_text = "未提供"
    _note_row(image, fonts, "参量质变仪", 750, ready, text=transformer_text)
    remaining, limit = note.remain_resin_discount_num, note.resin_discount_num_limit
    used = max(0, limit - remaining) if remaining is not None and limit is not None else None
    _note_row(image, fonts, "周本减半", 855, _is_complete(used, limit), used, limit)

    draw.text((950, 1055), "Function By manshuo", GREY, fonts[24], "mm")
    CACHE_PATH.mkdir(parents=True, exist_ok=True)
    path = CACHE_PATH / f"genshin_note_{uuid4().hex}.png"
    image.convert("RGB").save(path)
    return str(path)


async def draw_genshin_note(note: GenshinNote, account_name: str = "", *, user_id: Optional[str] = None,
                            game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    """绘制原神便签，角色资料复用便签请求结果，绘图在线程中完成。"""
    avatar_data = await _fetch_qq_avatar(user_id)
    return await asyncio.to_thread(_draw_genshin_note, note, account_name, avatar_data,
                                    game_uid, role or note.game_role)


def _draw_starrail_note(note: StarRailNote, account_name: str, avatar_data: Optional[bytes] = None,
                        game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    fonts = {
        size: ImageFont.truetype(str(RESOURCE_PATH / "zzz_fonts.ttf"), size)
        for size in (24, 26, 28, 30, 36, 38, 40, 50)
    }
    image = _background(1900, 1100)
    player_card = _player_card(fonts, avatar_data, game_uid, role, account_name,
                               "开拓者", "星穹列车", "崩坏：星穹铁道")
    image.alpha_composite(player_card, (0, 200))
    _note_section(image, fonts, "开拓力情况", 110, 410)
    _note_section(image, fonts, "每日情况", 1060, 232)
    _note_section(image, fonts, "周期情况", 1060, 664)
    _note_resource(image, fonts, "开拓力", note.current_stamina, note.max_stamina,
                   note.stamina_recover_time, 492, (77, 198, 236), height=350)
    _note_row(image, fonts, "每日实训", 320, _is_complete(note.current_train_score, note.max_train_score),
              note.current_train_score, note.max_train_score)
    _note_row(image, fonts, "委托派遣", 425, _is_complete(note.accepted_expedition_num, note.total_expedition_num),
              note.accepted_expedition_num, note.total_expedition_num)
    signed = note.has_signed
    _note_row(image, fonts, "米游社签到", 530, signed is True,
              text="已签到" if signed is True else "未签到" if signed is False else "未提供")
    _note_row(image, fonts, "模拟宇宙", 750, _is_complete(note.current_rogue_score, note.max_rogue_score),
              note.current_rogue_score, note.max_rogue_score)

    ImageDraw.Draw(image).text((950, 1055), "Function By manshuo", GREY, fonts[24], "mm")
    CACHE_PATH.mkdir(parents=True, exist_ok=True)
    path = CACHE_PATH / f"starrail_note_{uuid4().hex}.png"
    image.convert("RGB").save(path)
    return str(path)


async def draw_starrail_note(note: StarRailNote, account_name: str = "", *, user_id: Optional[str] = None,
                             game_uid: Optional[str] = None, role: Optional[GameRecord] = None) -> str:
    """绘制崩铁便签，复用本次查询的角色资料，不依赖 manshuo_draw。"""
    avatar_data = await _fetch_qq_avatar(user_id)
    return await asyncio.to_thread(_draw_starrail_note, note, account_name, avatar_data,
                                    game_uid, role or note.game_role)
