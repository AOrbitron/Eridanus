"""Adapted from BeyondUID 95ba169 beyonduid_gem/draw_img.py (GPL-3.0-or-later).
See GUIDE_SOURCES.md for attribution and local integration changes.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from itertools import combinations

from PIL import Image, ImageDraw, ImageOps

from .guide_image import core_font, get_footer, get_ICON, save_image, load_icon

from .endfield_gamedata import TableCfg, WeaponGemInfoTable
from .endfield_gamedata.i18n_text import get_i18n_text
from .endfield_gamedata.weapon_gem_info import WeaponGemEnergyPointData, WeaponGemRecommendationData

IMG_W = 1120
PAGE_PADDING_X = 42
PAGE_PADDING_Y = 36
CARD_GAP = 22
SECTION_GAP = 28
CARD_RADIUS = 26
CARD_INNER_PADDING = 24
WEAPON_CARD_W = 220
WEAPON_CARD_H = 132
ICON_SIZE = 72
PLAN_ICON_SIZE = 76
CHAR_BADGE_SIZE = 18
LINE_GAP = 12
MAX_PLAN_COUNT = 6

BG_COLOR = (14, 18, 26, 255)
CARD_COLOR = (33, 39, 52, 255)
SECTION_CARD_COLOR = (27, 33, 45, 255)
ROW_BG_COLOR = (22, 28, 38, 255)
TITLE_COLOR = (242, 245, 250, 255)
TEXT_COLOR = (214, 220, 230, 255)
SUBTEXT_COLOR = (150, 162, 180, 255)
ACCENT_COLOR = (244, 198, 116, 255)
FULL_TAG_BG = (69, 139, 101, 255)
PARTIAL_TAG_BG = (176, 116, 67, 255)
WARN_BG = (74, 49, 38, 255)
DIVIDER_COLOR = (55, 64, 80, 255)
ICON_BG = (43, 51, 66, 255)
PLUS_TILE_BG = (58, 66, 84, 255)
WARN_TILE_BG = (103, 48, 58, 255)


@dataclass
class _MultiPointPlan:
    point: WeaponGemEnergyPointData
    locked_primary_ids: list[str] = field(default_factory=list)
    locked_lock_term_id: str | None = None
    covered_weapon_names: list[str] = field(default_factory=list)
    lock_covered_weapon_names: list[str] = field(default_factory=list)
    rank_positions: list[int] = field(default_factory=list)
    extra_weapon_names: list[str] = field(default_factory=list)
    remaining_term_hit_weapon_names: list[str] = field(default_factory=list)
    remaining_term_hit_count: int = 0


@dataclass
class _PlanRenderData:
    title: str
    plan_type: str
    plan_type_bg: tuple[int, int, int, int]
    covered_weapon_names: list[str] = field(default_factory=list)
    extra_weapon_names: list[str] = field(default_factory=list)
    remaining_weapon_names: list[str] = field(default_factory=list)
    lock_primary_text: str = ""
    lock_lock_text: str = ""
    note_text: str = ""


@dataclass
class _WeaponBestData:
    name: str
    best_point_name: str
    is_covered_by_first_plan: bool


def _get_term_name(term_id: str) -> str:
    gem_data = TableCfg.GemTable().get(term_id, {})
    return get_i18n_text(gem_data.get("tagName")) or term_id


def _get_bound_character_ids(weapon_id: str, limit: int = 3) -> list[str]:
    result: list[str] = []
    for char_id, recommend_data in TableCfg.CharWpnRecommendTable().items():
        for key in ("weaponIds1", "weaponIds2", "weaponIds3"):
            weapon_ids = recommend_data.get(key, [])
            if isinstance(weapon_ids, list) and weapon_id in weapon_ids:
                if char_id not in result:
                    result.append(char_id)
                break
        if len(result) >= limit:
            break
    return result[:limit]


def _format_point_name(point: WeaponGemEnergyPointData) -> str:
    return f"{point.domain_name}·{point.point_name.removeprefix('重度能量淤积点·')}"


def _desired_lock_term_ids(
    data: WeaponGemRecommendationData,
    point: WeaponGemEnergyPointData,
) -> list[str]:
    result: list[str] = []
    for term_id in data.recommended_secondary_term_ids:
        if term_id in point.guaranteed_secondary_term_ids:
            result.append(term_id)
    for term_id in data.recommended_skill_term_ids:
        if term_id in point.guaranteed_skill_term_ids:
            result.append(term_id)
    return result


def _pick_locked_primary_ids(
    data_list: list[WeaponGemRecommendationData],
    point: WeaponGemEnergyPointData,
) -> list[str]:
    point_primary_set = set(point.primary_term_ids)
    desired_count: dict[str, int] = {}
    for data in data_list:
        for term_id in set(data.recommended_primary_term_ids):
            if term_id in point_primary_set:
                desired_count[term_id] = desired_count.get(term_id, 0) + 1

    selected = sorted(
        desired_count,
        key=lambda term_id: (
            desired_count[term_id],
            1 if term_id == "gat_passive_attr_main" else 0,
            term_id,
        ),
        reverse=True,
    )[:3]

    filler_candidates = [
        "gat_passive_attr_main",
        *[term_id for term_id in point.primary_term_ids if term_id != "gat_passive_attr_main"],
    ]
    for term_id in filler_candidates:
        if len(selected) >= 3:
            break
        if term_id in point_primary_set and term_id not in selected:
            selected.append(term_id)
    return selected[:3]


def _pick_locked_lock_term_id(
    data_list: list[WeaponGemRecommendationData],
    point: WeaponGemEnergyPointData,
) -> str | None:
    desired_count: dict[str, int] = {}
    for data in data_list:
        for term_id in set(_desired_lock_term_ids(data, point)):
            desired_count[term_id] = desired_count.get(term_id, 0) + 1

    if not desired_count:
        return None

    return max(
        desired_count,
        key=lambda term_id: (
            desired_count[term_id],
            1 if term_id.startswith("gat_") else 0,
            term_id,
        ),
    )


def _is_weapon_covered_by_plan(data: WeaponGemRecommendationData, plan: _MultiPointPlan) -> bool:
    has_primary = bool(set(plan.locked_primary_ids).intersection(data.recommended_primary_term_ids))
    if not has_primary:
        return False
    if plan.locked_lock_term_id is None:
        return True
    return plan.locked_lock_term_id in _desired_lock_term_ids(data, plan.point)


def _has_remaining_desired_terms_in_point(
    data: WeaponGemRecommendationData,
    plan: _MultiPointPlan,
) -> bool:
    desired_term_ids = set(data.recommended_secondary_term_ids + data.recommended_skill_term_ids)
    if plan.locked_lock_term_id:
        desired_term_ids.discard(plan.locked_lock_term_id)
    point_term_ids = set(plan.point.guaranteed_secondary_term_ids + plan.point.guaranteed_skill_term_ids)
    return bool(desired_term_ids.intersection(point_term_ids))


def _is_weapon_fully_supported_by_plan(
    data: WeaponGemRecommendationData,
    plan: _MultiPointPlan,
) -> bool:
    if not _is_weapon_covered_by_plan(data, plan):
        return False

    desired_term_ids = set(data.recommended_secondary_term_ids + data.recommended_skill_term_ids)
    if plan.locked_lock_term_id:
        desired_term_ids.discard(plan.locked_lock_term_id)
    if not desired_term_ids:
        return True

    point_term_ids = set(plan.point.guaranteed_secondary_term_ids + plan.point.guaranteed_skill_term_ids)
    return bool(desired_term_ids.intersection(point_term_ids))


def _is_full_input_plan(
    plan: _MultiPointPlan,
    data_list: list[WeaponGemRecommendationData],
) -> bool:
    return all(_is_weapon_fully_supported_by_plan(data, plan) for data in data_list)


def _build_multi_point_plan(
    point: WeaponGemEnergyPointData,
    lock_data_list: list[WeaponGemRecommendationData],
    all_data_list: list[WeaponGemRecommendationData],
    rank_positions: list[int],
) -> _MultiPointPlan:
    locked_primary_ids = _pick_locked_primary_ids(lock_data_list, point)
    locked_lock_term_id = _pick_locked_lock_term_id(lock_data_list, point)

    plan = _MultiPointPlan(
        point=point,
        locked_primary_ids=locked_primary_ids,
        locked_lock_term_id=locked_lock_term_id,
        rank_positions=rank_positions,
    )
    for data in all_data_list:
        if bool(set(plan.locked_primary_ids).intersection(data.recommended_primary_term_ids)):
            plan.covered_weapon_names.append(data.weapon.name)
        if _is_weapon_covered_by_plan(data, plan):
            plan.lock_covered_weapon_names.append(data.weapon.name)
            if _has_remaining_desired_terms_in_point(data, plan):
                plan.remaining_term_hit_weapon_names.append(data.weapon.name)
                plan.remaining_term_hit_count += 1

    return plan


def _select_multi_point_plans(data_list: list[WeaponGemRecommendationData]) -> list[_MultiPointPlan]:
    if not data_list:
        return []

    point_map: dict[str, WeaponGemEnergyPointData] = {}
    point_ranks: dict[str, list[int]] = {}
    for data_index, data in enumerate(data_list):
        seen_keys: set[str] = set()
        rank = 0
        for point in data.recommended_energy_points:
            point_key = _format_point_name(point)
            if point_key in seen_keys:
                continue
            seen_keys.add(point_key)
            rank += 1

            current = point_map.get(point_key)
            if current is None or (point.world_level, point.recommend_lv) > (
                current.world_level,
                current.recommend_lv,
            ):
                point_map[point_key] = point

            point_ranks.setdefault(point_key, [999] * len(data_list))
            point_ranks[point_key][data_index] = rank

    plans: list[_MultiPointPlan] = []
    for point_key, point in point_map.items():
        for subset_size in range(len(data_list), 0, -1):
            for subset in combinations(data_list, subset_size):
                plan = _build_multi_point_plan(point, list(subset), data_list, point_ranks[point_key])
                if not plan.lock_covered_weapon_names:
                    continue
                plans.append(plan)

    plans.sort(
        key=lambda plan: (
            1 if plan.locked_lock_term_id is not None else 0,
            len(plan.lock_covered_weapon_names),
            plan.remaining_term_hit_count,
            len(plan.covered_weapon_names),
            -plan.rank_positions[0],
            -sum(plan.rank_positions),
            plan.point.world_level,
            plan.point.recommend_lv,
        ),
        reverse=True,
    )

    filtered_plans: list[_MultiPointPlan] = []
    seen_plan_keys: set[tuple[str, tuple[str, ...], tuple[str, ...], str | None]] = set()
    for plan in plans:
        plan_key = (
            plan.point.point_id,
            tuple(sorted(plan.lock_covered_weapon_names)),
            tuple(sorted(plan.locked_primary_ids)),
            plan.locked_lock_term_id,
        )
        if plan_key in seen_plan_keys:
            continue
        seen_plan_keys.add(plan_key)
        filtered_plans.append(plan)
    return filtered_plans


def _select_display_plans(
    plans: list[_MultiPointPlan],
    data_list: list[WeaponGemRecommendationData],
) -> list[_MultiPointPlan]:
    if not plans:
        return []

    full_input_plans = [plan for plan in plans if _is_full_input_plan(plan, data_list)]
    if full_input_plans:
        return full_input_plans[:MAX_PLAN_COUNT]

    weapon_names = {data.weapon.name for data in data_list}
    fully_covered_plans = [plan for plan in plans if set(plan.lock_covered_weapon_names) == weapon_names]
    if fully_covered_plans:
        return fully_covered_plans[:MAX_PLAN_COUNT]

    return plans[:MAX_PLAN_COUNT]


def _list_extra_weapon_names(
    plan: _MultiPointPlan,
    data_list: list[WeaponGemRecommendationData],
) -> list[str]:
    current_names = {data.weapon.name for data in data_list}
    extra_names: list[str] = []
    for weapon_id in TableCfg.WeaponBasicTable():
        data = WeaponGemInfoTable.get_by_weapon_id(weapon_id)
        if data is None or data.weapon.name in current_names:
            continue
        if _is_weapon_covered_by_plan(data, plan):
            extra_names.append(data.weapon.name)
    return sorted(set(extra_names))


def _format_lock_terms(
    locked_primary_ids: list[str],
    locked_lock_term_id: str | None,
) -> list[tuple[str, str]]:
    primary_names = [_get_term_name(term_id) for term_id in locked_primary_ids]
    sections = [("锁基础", " / ".join(primary_names) or "无")]
    if locked_lock_term_id:
        sections.append(("锁附加/技能", _get_term_name(locked_lock_term_id)))
    else:
        sections.append(("锁附加/技能", "无公共可锁词条"))
    return sections


def _trim_join(items: list[str], limit: int = 8) -> str:
    if not items:
        return "无"
    if len(items) <= limit:
        return " / ".join(items)
    return " / ".join(items[:limit]) + f" / +{len(items) - limit}"


def _format_combined_lock_text(plan: _PlanRenderData) -> str:
    return f"基础：{plan.lock_primary_text}  ｜  附加/技能：{plan.lock_lock_text}"


def _build_plan_render_data(
    plan: _MultiPointPlan,
    weapon_names: list[str],
    data_list: list[WeaponGemRecommendationData],
    index: int,
) -> _PlanRenderData:
    if plan.locked_lock_term_id is not None:
        covered_names = plan.lock_covered_weapon_names
    else:
        covered_names = plan.covered_weapon_names

    remaining_names = [name for name in weapon_names if name not in covered_names]
    if plan.locked_lock_term_id is not None and not remaining_names:
        plan_type = "完整共锁方案"
        plan_type_bg = FULL_TAG_BG
    elif plan.locked_lock_term_id is not None:
        plan_type = "部分共锁方案"
        plan_type_bg = PARTIAL_TAG_BG
    else:
        plan_type = "仅公共三基础方案"
        plan_type_bg = PARTIAL_TAG_BG

    extra_weapon_names = _list_extra_weapon_names(plan, data_list)
    lock_sections = _format_lock_terms(plan.locked_primary_ids, plan.locked_lock_term_id)
    lock_primary_text = lock_sections[0][1] if lock_sections else "无"
    lock_lock_text = lock_sections[1][1] if len(lock_sections) > 1 else "无"

    note_text = ""
    if plan.locked_lock_term_id is None:
        note_text = "这个方案只有三条基础属性能公共锁定，第四条附加/技能词条不共通。"
    elif remaining_names:
        note_text = "这个方案存在公共附加/技能词条，但只能覆盖部分输入武器。"

    return _PlanRenderData(
        title=f"方案{index}：{_format_point_name(plan.point)}",
        plan_type=plan_type,
        plan_type_bg=plan_type_bg,
        covered_weapon_names=covered_names,
        extra_weapon_names=extra_weapon_names,
        remaining_weapon_names=remaining_names,
        lock_primary_text=lock_primary_text,
        lock_lock_text=lock_lock_text,
        note_text=note_text,
    )


def _build_best_weapon_data(
    data_list: list[WeaponGemRecommendationData],
    first_plan: _MultiPointPlan | None,
) -> list[_WeaponBestData]:
    result: list[_WeaponBestData] = []
    covered_names = set()
    if first_plan is not None:
        covered_names = set(first_plan.lock_covered_weapon_names or first_plan.covered_weapon_names)

    for data in data_list:
        best = data.best_energy_point
        result.append(
            _WeaponBestData(
                name=data.weapon.name,
                best_point_name=_format_point_name(best) if best is not None else "未找到推荐副本",
                is_covered_by_first_plan=data.weapon.name in covered_names,
            )
        )
    return result


def _text_lines(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    wrapped = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    return wrapped or [text]


def _measure_lines(draw: ImageDraw.ImageDraw, lines: list[str], font_size: int) -> int:
    font = core_font(font_size)
    total_h = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line or "测", font=font)
        total_h += int(bbox[3] - bbox[1])
    if lines:
        total_h += LINE_GAP * (len(lines) - 1)
    return int(total_h)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    lines: list[str],
    *,
    font_size: int,
    fill: tuple[int, int, int, int],
) -> int:
    font = core_font(font_size)
    current_y = y
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), line or "测", font=font)
        current_y += int(bbox[3] - bbox[1]) + LINE_GAP
    return int(current_y - y - LINE_GAP) if lines else 0


def _wrap_text_by_pixel(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font_size: int,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    if not text:
        return [""]

    font = core_font(font_size)
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = int(bbox[2] - bbox[0])
        if current and width > max_width:
            lines.append(current)
            current = char
            if max_lines is not None and len(lines) >= max_lines:
                break
        else:
            current = candidate

    if max_lines is None or len(lines) < max_lines:
        lines.append(current)

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]

    return [line for line in lines if line] or [text]


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    lines: list[str],
    *,
    font_size: int,
    fill: tuple[int, int, int, int],
) -> int:
    font = core_font(font_size)
    current_y = y
    for line in lines:
        draw.text((center_x, current_y), line, font=font, fill=fill, anchor="ma")
        bbox = draw.textbbox((0, 0), line or "测", font=font)
        current_y += int(bbox[3] - bbox[1]) + LINE_GAP
    return int(current_y - y - LINE_GAP) if lines else 0


def _load_weapon_icon(weapon_id: str, size: int = ICON_SIZE) -> Image.Image:
    icon = load_icon("endfield", "weapon", weapon_id) or get_ICON().convert("RGBA")
    return ImageOps.fit(icon, (size, size))


def _load_character_icon(char_id: str, size: int = CHAR_BADGE_SIZE) -> Image.Image | None:
    icon = load_icon("endfield", "char", char_id)
    return ImageOps.fit(icon, (size, size)) if icon else None


def _draw_character_badges(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    weapon_id: str,
    *,
    size: int = CHAR_BADGE_SIZE,
    max_count: int = 2,
    align_right: bool = False,
) -> None:
    char_ids = _get_bound_character_ids(weapon_id, limit=max_count)
    if not char_ids:
        return

    icons = [char_icon for char_id in char_ids if (char_icon := _load_character_icon(char_id, size=size)) is not None]
    if not icons:
        return

    badge_gap = 4
    badge_w = size + 4
    total_w = len(icons) * badge_w + max(0, len(icons) - 1) * badge_gap
    start_x = x - total_w if align_right else x

    for index, char_icon in enumerate(icons):
        offset_x = start_x + index * (badge_w + badge_gap)
        draw.rounded_rectangle(
            (offset_x, y, offset_x + badge_w, y + badge_w),
            radius=10,
            fill=ICON_BG,
        )
        img.paste(char_icon, (offset_x + 2, y + 2), char_icon)


def _calc_weapon_area_height(count: int) -> int:
    if count <= 0:
        return 0
    per_row = max(1, (IMG_W - PAGE_PADDING_X * 2 + CARD_GAP) // (WEAPON_CARD_W + CARD_GAP))
    rows = (count + per_row - 1) // per_row
    return rows * WEAPON_CARD_H + (rows - 1) * CARD_GAP


def _calc_icon_row_height(item_count: int, max_width: int) -> int:
    if item_count <= 0:
        return 0
    tile_gap = 18
    max_per_row = 5
    tile_w = max(136, (max_width - tile_gap * (max_per_row - 1)) // max_per_row)
    tile_h = tile_w
    name_h = 44
    badge_row_h = 40
    row_gap = 22
    rows = (item_count + max_per_row - 1) // max_per_row
    return rows * (tile_h + 12 + name_h + 10 + badge_row_h) + max(0, rows - 1) * row_gap


def _calc_info_row_content_height(
    draw: ImageDraw.ImageDraw,
    content_width: int,
    text: str = "",
    weapon_names: list[str] | None = None,
) -> int:
    if weapon_names:
        return max(84, _calc_icon_row_height(len(weapon_names), content_width))
    return max(32, _measure_lines(draw, _text_lines(text, 44), 22))


def _calc_plan_card_height(draw: ImageDraw.ImageDraw, plan: _PlanRenderData) -> int:
    content_width = IMG_W - PAGE_PADDING_X * 2 - CARD_INNER_PADDING * 2 - 36
    height = CARD_INNER_PADDING * 2 + 56

    input_weapon_names = plan.covered_weapon_names + [
        name for name in plan.remaining_weapon_names if name not in plan.covered_weapon_names
    ]
    if input_weapon_names:
        content_h = _calc_info_row_content_height(draw, content_width, weapon_names=input_weapon_names)
        height += 46 + content_h + 16 + 12
    if plan.extra_weapon_names:
        content_h = _calc_info_row_content_height(
            draw,
            content_width,
            weapon_names=plan.extra_weapon_names,
        )
        height += 46 + content_h + 16 + 12

    lock_text = _format_combined_lock_text(plan)
    content_h = _calc_info_row_content_height(draw, content_width, text=lock_text)
    height += 46 + content_h + 16 + 12

    if plan.note_text:
        content_h = _calc_info_row_content_height(draw, content_width, text=plan.note_text)
        height += 46 + content_h + 16 + 12
    return height


def _draw_header(img: Image.Image, draw: ImageDraw.ImageDraw, weapon_names: list[str], plan_count: int) -> int:
    x0 = PAGE_PADDING_X
    y0 = PAGE_PADDING_Y
    x1 = IMG_W - PAGE_PADDING_X
    y1 = y0 + 150
    draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_RADIUS, fill=CARD_COLOR)

    draw.text((x0 + 28, y0 + 24), "基质共刷推荐", font=core_font(42), fill=TITLE_COLOR)
    sub_lines = [
        f"已查询武器：{len(weapon_names)} 把",
        f"方案数量：{plan_count}",
    ]
    current_y = y0 + 82
    for line in sub_lines:
        draw.text((x0 + 28, current_y), line, font=core_font(24), fill=SUBTEXT_COLOR)
        current_y += 32
    return y1


def _draw_weapon_cards(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    data_list: list[WeaponGemRecommendationData],
    start_y: int,
) -> int:
    if not data_list:
        return start_y

    per_row = max(1, (IMG_W - PAGE_PADDING_X * 2 + CARD_GAP) // (WEAPON_CARD_W + CARD_GAP))
    x = PAGE_PADDING_X
    y = start_y
    for index, data in enumerate(data_list):
        if index > 0 and index % per_row == 0:
            x = PAGE_PADDING_X
            y += WEAPON_CARD_H + CARD_GAP

        draw.rounded_rectangle(
            (x, y, x + WEAPON_CARD_W, y + WEAPON_CARD_H),
            radius=22,
            fill=SECTION_CARD_COLOR,
        )
        draw.rounded_rectangle(
            (x + 14, y + 14, x + 14 + ICON_SIZE, y + 14 + ICON_SIZE),
            radius=18,
            fill=ICON_BG,
        )
        icon = _load_weapon_icon(data.weapon.id)
        img.paste(icon, (x + 14, y + 14), icon)

        text_x = x + 92
        text_max_width = x + WEAPON_CARD_W - 14 - text_x
        draw.text((text_x, y + 18), data.weapon.name, font=core_font(24), fill=TITLE_COLOR)
        best_lines = _wrap_text_by_pixel(
            draw,
            f"最佳：{_format_point_name(data.best_energy_point) if data.best_energy_point else '无'}",
            font_size=18,
            max_width=text_max_width,
            max_lines=2,
        )
        _draw_lines(draw, text_x, y + 50, best_lines, font_size=18, fill=SUBTEXT_COLOR)
        _draw_character_badges(
            img,
            draw,
            x + 14,
            y + WEAPON_CARD_H - 20,
            data.weapon.id,
            size=14,
            max_count=3,
        )
        x += WEAPON_CARD_W + CARD_GAP

    return y + WEAPON_CARD_H


def _load_weapon_data_by_name(weapon_name: str) -> WeaponGemRecommendationData | None:
    return WeaponGemInfoTable.get_by_weapon_name(weapon_name)


def _draw_plus_tile(draw: ImageDraw.ImageDraw, x: int, y: int, count: int) -> None:
    draw.rounded_rectangle(
        (x, y, x + PLAN_ICON_SIZE + 12, y + PLAN_ICON_SIZE + 12),
        radius=18,
        fill=PLUS_TILE_BG,
    )
    draw.text(
        (x + (PLAN_ICON_SIZE + 12) // 2, y + (PLAN_ICON_SIZE + 12) // 2),
        f"+{count}",
        font=core_font(22),
        fill=TITLE_COLOR,
        anchor="mm",
    )


def _draw_plan_weapon_row(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    weapon_names: list[str],
    x: int,
    y: int,
    max_width: int,
    warn_weapon_names: set[str] | None = None,
) -> int:
    tile_gap = 18
    max_per_row = 5
    tile_w = max(136, (max_width - tile_gap * (max_per_row - 1)) // max_per_row)
    tile_h = tile_w
    name_h = 44
    badge_row_h = 40
    row_gap = 22
    current_y = y
    warn_weapon_names = warn_weapon_names or set()

    for row_start in range(0, len(weapon_names), max_per_row):
        row_weapon_names = weapon_names[row_start : row_start + max_per_row]
        current_x = x

        for weapon_name in row_weapon_names:
            data = _load_weapon_data_by_name(weapon_name)
            if data is None:
                current_x += tile_w + tile_gap
                continue

            tile_fill = WARN_TILE_BG if weapon_name in warn_weapon_names else ICON_BG
            draw.rounded_rectangle(
                (current_x, current_y, current_x + tile_w, current_y + tile_h),
                radius=20,
                fill=tile_fill,
            )
            icon_size = tile_w - 24
            icon = _load_weapon_icon(data.weapon.id, size=icon_size)
            img.paste(icon, (current_x + 12, current_y + 12), icon)

            name_lines = _wrap_text_by_pixel(
                draw,
                weapon_name,
                font_size=18,
                max_width=tile_w - 10,
                max_lines=2,
            )
            _draw_centered_lines(
                draw,
                current_x + tile_w // 2,
                current_y + tile_h + 8,
                name_lines,
                font_size=18,
                fill=TITLE_COLOR if weapon_name not in warn_weapon_names else (255, 230, 230, 255),
            )

            bound_count = len(_get_bound_character_ids(data.weapon.id, limit=3))
            badge_total_w = bound_count * 36 + max(0, bound_count - 1) * 4
            _draw_character_badges(
                img,
                draw,
                current_x + max(0, (tile_w - badge_total_w) // 2),
                current_y + tile_h + 12 + name_h,
                data.weapon.id,
                size=32,
                max_count=3,
            )
            current_x += tile_w + tile_gap

        current_y += tile_h + 12 + name_h + 10 + badge_row_h
        if row_start + max_per_row < len(weapon_names):
            current_y += row_gap

    return current_y


def _draw_info_row(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    label: str,
    text: str = "",
    weapon_names: list[str] | None = None,
    warn: bool = False,
    warn_weapon_names: set[str] | None = None,
) -> int:
    content_x = x0 + 18
    content_width = x1 - x0 - 36
    content_y = y + 46
    content_h = _calc_info_row_content_height(draw, content_width, text=text, weapon_names=weapon_names)
    row_h = content_y - y + content_h + 16

    row_bg = WARN_BG if warn else ROW_BG_COLOR
    draw.rounded_rectangle((x0, y, x1, y + row_h), radius=18, fill=row_bg)
    draw.text((x0 + 18, y + 14), label, font=core_font(22), fill=ACCENT_COLOR)
    draw.line((x0 + 18, y + 38, x1 - 18, y + 38), fill=DIVIDER_COLOR, width=1)

    if weapon_names:
        _draw_plan_weapon_row(img, draw, weapon_names, content_x, content_y, content_width, warn_weapon_names)
    else:
        lines = _text_lines(text, 44)
        _draw_lines(draw, content_x, content_y, lines, font_size=22, fill=TEXT_COLOR)
    return y + row_h + 12


def _draw_plan_cards(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    plans: list[_PlanRenderData],
    start_y: int,
) -> int:
    current_y = start_y
    for plan in plans:
        card_h = _calc_plan_card_height(draw, plan)
        x0 = PAGE_PADDING_X
        x1 = IMG_W - PAGE_PADDING_X
        y0 = current_y
        y1 = y0 + card_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_RADIUS, fill=SECTION_CARD_COLOR)

        draw.text((x0 + CARD_INNER_PADDING, y0 + CARD_INNER_PADDING), plan.title, font=core_font(30), fill=TITLE_COLOR)

        tag_text_bbox = draw.textbbox((0, 0), plan.plan_type, font=core_font(18))
        tag_w = int(tag_text_bbox[2] - tag_text_bbox[0]) + 34
        tag_h = 36
        tag_x1 = x1 - CARD_INNER_PADDING
        tag_x0 = tag_x1 - tag_w
        tag_y0 = y0 + CARD_INNER_PADDING + 2
        tag_y1 = tag_y0 + tag_h
        draw.rounded_rectangle((tag_x0, tag_y0, tag_x1, tag_y1), radius=18, fill=plan.plan_type_bg)
        draw.text((tag_x0 + 17, tag_y0 + 7), plan.plan_type, font=core_font(18), fill=(255, 255, 255, 255))

        section_y = y0 + CARD_INNER_PADDING + 56
        inner_x0 = x0 + CARD_INNER_PADDING
        inner_x1 = x1 - CARD_INNER_PADDING
        input_weapon_names = plan.covered_weapon_names + [
            name for name in plan.remaining_weapon_names if name not in plan.covered_weapon_names
        ]
        if input_weapon_names:
            section_y = _draw_info_row(
                img,
                draw,
                inner_x0,
                inner_x1,
                section_y,
                "当前输入武器",
                weapon_names=input_weapon_names,
                warn_weapon_names=set(plan.remaining_weapon_names),
            )
        if plan.extra_weapon_names:
            section_y = _draw_info_row(
                img,
                draw,
                inner_x0,
                inner_x1,
                section_y,
                "当前选项下还能刷的其他武器",
                weapon_names=plan.extra_weapon_names,
            )
        section_y = _draw_info_row(
            img,
            draw,
            inner_x0,
            inner_x1,
            section_y,
            "锁词条",
            text=_format_combined_lock_text(plan),
        )
        if plan.note_text:
            section_y = _draw_info_row(img, draw, inner_x0, inner_x1, section_y, "说明", text=plan.note_text, warn=True)

        current_y = y1 + CARD_GAP
    return current_y - CARD_GAP


def _draw_best_section(
    draw: ImageDraw.ImageDraw,
    best_list: list[_WeaponBestData],
    start_y: int,
) -> tuple[int, int]:
    line_height = 36
    card_h = CARD_INNER_PADDING * 2 + 50 + len(best_list) * line_height
    x0 = PAGE_PADDING_X
    y0 = start_y
    x1 = IMG_W - PAGE_PADDING_X
    y1 = y0 + card_h
    draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_RADIUS, fill=CARD_COLOR)
    draw.text((x0 + CARD_INNER_PADDING, y0 + CARD_INNER_PADDING), "各武器最佳", font=core_font(30), fill=TITLE_COLOR)

    current_y = y0 + CARD_INNER_PADDING + 48
    for best in best_list:
        status = "已被方案1覆盖" if best.is_covered_by_first_plan else "需单独处理"
        status_fill = FULL_TAG_BG if best.is_covered_by_first_plan else PARTIAL_TAG_BG
        draw.text((x0 + CARD_INNER_PADDING, current_y), best.name, font=core_font(22), fill=TITLE_COLOR)
        draw.text((x0 + 290, current_y), best.best_point_name, font=core_font(22), fill=TEXT_COLOR)
        draw.text((x1 - CARD_INNER_PADDING, current_y), status, font=core_font(18), fill=status_fill, anchor="ra")
        current_y += line_height
    return y1, card_h


def draw_gem_recommend_img(
    data_list: list[WeaponGemRecommendationData],
    not_found: list[str] | None = None,
) -> str:
    plans = _select_multi_point_plans(data_list)
    display_plans = _select_display_plans(plans, data_list)
    plan_render_list = [
        _build_plan_render_data(plan, [data.weapon.name for data in data_list], data_list, index)
        for index, plan in enumerate(display_plans, start=1)
    ]
    best_list = _build_best_weapon_data(
        data_list,
        display_plans[0] if display_plans else (plans[0] if plans else None),
    )

    weapon_area_h = _calc_weapon_area_height(len(data_list))
    temp_img = Image.new("RGBA", (IMG_W, 5000), BG_COLOR)
    temp_draw = ImageDraw.Draw(temp_img)
    plan_total_h = 0
    for plan in plan_render_list:
        plan_total_h += _calc_plan_card_height(temp_draw, plan)
    if plan_render_list:
        plan_total_h += CARD_GAP * (len(plan_render_list) - 1)

    best_card_h = CARD_INNER_PADDING * 2 + 50 + len(best_list) * 36
    not_found_h = 0
    if not_found:
        lines = _text_lines(" / ".join(not_found), 42)
        not_found_h = CARD_INNER_PADDING * 2 + 40 + _measure_lines(temp_draw, lines, 22)

    footer_img = get_footer()
    img_h = (
        PAGE_PADDING_Y
        + 150
        + SECTION_GAP
        + weapon_area_h
        + SECTION_GAP
        + plan_total_h
        + SECTION_GAP
        + best_card_h
        + (SECTION_GAP + not_found_h if not_found_h else 0)
        + footer_img.size[1]
        + 70
    )

    img = Image.new("RGBA", (IMG_W, img_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    current_y = _draw_header(img, draw, [data.weapon.name for data in data_list], len(plan_render_list)) + SECTION_GAP
    current_y = _draw_weapon_cards(img, draw, data_list, current_y) + SECTION_GAP
    current_y = _draw_plan_cards(img, draw, plan_render_list, current_y) + SECTION_GAP
    current_y, _ = _draw_best_section(draw, best_list, current_y)

    if not_found:
        current_y += SECTION_GAP
        x0 = PAGE_PADDING_X
        x1 = IMG_W - PAGE_PADDING_X
        y0 = current_y
        lines = _text_lines(" / ".join(not_found), 42)
        card_h = CARD_INNER_PADDING * 2 + 40 + _measure_lines(draw, lines, 22)
        y1 = y0 + card_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_RADIUS, fill=WARN_BG)
        draw.text(
            (x0 + CARD_INNER_PADDING, y0 + CARD_INNER_PADDING), "未识别武器", font=core_font(26), fill=TITLE_COLOR
        )
        _draw_lines(draw, x0 + CARD_INNER_PADDING, y0 + CARD_INNER_PADDING + 40, lines, font_size=22, fill=TEXT_COLOR)

    footer_x = int((img.size[0] - footer_img.size[0]) / 2)
    footer_y = img.size[1] - footer_img.size[1] - 24
    img.paste(footer_img, (footer_x, footer_y), mask=footer_img)
    return save_image(img, "skland_endfield_gem")
