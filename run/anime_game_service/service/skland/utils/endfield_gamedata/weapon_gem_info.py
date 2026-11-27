"""Adapted from BeyondUID 95ba169 (GPL-3.0-or-later). See ../GUIDE_SOURCES.md."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import TableCfg
from .character_weapon_info import WeaponDetailData, WeaponInfoTable
from .i18n_text import get_i18n_text


def _item_name(item_id: str) -> str:
    if not item_id:
        return ""
    item_data = TableCfg.ItemTable().get(item_id, {})
    return get_i18n_text(item_data.get("name"))


class GemTermData(BaseModel):
    term_id: str
    term_name: str = ""
    term_desc: str = ""
    term_type: str = ""
    level: int = 0


class WeaponGemPresetData(BaseModel):
    gem_id: str
    domain_id: str = ""
    rarity: int = 0
    primary_terms: list[GemTermData] = Field(default_factory=list)
    secondary_terms: list[GemTermData] = Field(default_factory=list)
    skill_terms: list[GemTermData] = Field(default_factory=list)


class WeaponGemEnergyPointData(BaseModel):
    point_id: str
    point_name: str = ""
    game_group_id: str = ""
    reward_id: str = ""
    domain_id: str = ""
    domain_name: str = ""
    level_id: str = ""
    recommend_lv: int = 0
    world_level: int = 0
    cost_stamina: int = 0
    coupon_item_id: str = ""
    coupon_name: str = ""
    primary_term_ids: list[str] = Field(default_factory=list)
    primary_term_names: list[str] = Field(default_factory=list)
    guaranteed_secondary_term_ids: list[str] = Field(default_factory=list)
    guaranteed_secondary_term_names: list[str] = Field(default_factory=list)
    guaranteed_skill_term_ids: list[str] = Field(default_factory=list)
    guaranteed_skill_term_names: list[str] = Field(default_factory=list)


class WeaponGemRecommendationData(BaseModel):
    weapon: WeaponDetailData
    perfect_gem: WeaponGemPresetData
    recommended_primary_term_ids: list[str] = Field(default_factory=list)
    recommended_primary_term_names: list[str] = Field(default_factory=list)
    recommended_secondary_term_ids: list[str] = Field(default_factory=list)
    recommended_secondary_term_names: list[str] = Field(default_factory=list)
    recommended_skill_term_ids: list[str] = Field(default_factory=list)
    recommended_skill_term_names: list[str] = Field(default_factory=list)
    recommended_energy_points: list[WeaponGemEnergyPointData] = Field(default_factory=list)
    best_energy_point: WeaponGemEnergyPointData | None = None
    reasoning: list[str] = Field(default_factory=list)


class WeaponGemInfoTable:
    _KNOWN_WEAPON_GROUP_HINTS: dict[str, str] = {
        "wpn_pistol_0011": "world_energy_point_group01",
        "wpn_sword_0016": "world_energy_point_group05",
    }
    _energy_point_cache: dict[str, WeaponGemEnergyPointData] = {}
    _recommendation_cache: dict[str, WeaponGemRecommendationData] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._energy_point_cache.clear()
        cls._recommendation_cache.clear()

    @classmethod
    def _get_term_data(cls, term_id: str, level: int = 0) -> GemTermData:
        gem_data = TableCfg.GemTable().get(term_id, {})
        return GemTermData(
            term_id=term_id,
            term_name=get_i18n_text(gem_data.get("tagName")),
            term_desc=get_i18n_text(gem_data.get("tagDesc")),
            term_type=gem_data.get("termType", "") or "",
            level=level,
        )

    @classmethod
    def _resolve_domain_id_from_level(cls, level_id: str) -> str:
        if level_id.startswith("map01_"):
            return "domain_1"
        if level_id.startswith("map02_"):
            return "domain_2"
        return ""

    @classmethod
    def _resolve_coupon_item_id(cls, domain_id: str) -> str:
        coupon_item_id_map = {
            "domain_1": "item_domain_tundra_coupon",
            "domain_2": "item_domain_jinlong_coupon",
        }
        return coupon_item_id_map.get(domain_id, "")

    @classmethod
    def _build_energy_point_data(cls, point_id: str, point_data: dict[str, Any]) -> WeaponGemEnergyPointData:
        cached = cls._energy_point_cache.get(point_id)
        if cached is not None:
            return cached

        level_id = point_data.get("levelId", "") or ""
        domain_id = cls._resolve_domain_id_from_level(level_id)
        domain_data = TableCfg.DomainDataTable().get(domain_id, {}) if domain_id else {}
        game_group_id = point_data.get("gameGroupId", "") or ""
        group_data = TableCfg.WorldEnergyPointGroupTable().get(game_group_id, {})
        coupon_item_id = cls._resolve_coupon_item_id(domain_id)

        primary_term_ids = [term_id for term_id in group_data.get("primAttrTermIds", []) if isinstance(term_id, str)]
        secondary_term_ids = [term_id for term_id in group_data.get("secAttrTermIds", []) if isinstance(term_id, str)]
        skill_term_ids = [term_id for term_id in group_data.get("skillTermIds", []) if isinstance(term_id, str)]

        primary_terms = [cls._get_term_data(term_id) for term_id in primary_term_ids]
        secondary_terms = [cls._get_term_data(term_id) for term_id in secondary_term_ids]
        skill_terms = [cls._get_term_data(term_id) for term_id in skill_term_ids]

        result = WeaponGemEnergyPointData(
            point_id=point_id,
            point_name=get_i18n_text(point_data.get("gameName")),
            game_group_id=game_group_id,
            reward_id=point_data.get("rewardId", "") or "",
            domain_id=domain_id,
            domain_name=get_i18n_text(domain_data.get("domainName")),
            level_id=level_id,
            recommend_lv=int(point_data.get("recommendLv", 0) or 0),
            world_level=int(point_data.get("worldLevel", 0) or 0),
            cost_stamina=int(point_data.get("costStamina", 0) or 0),
            coupon_item_id=coupon_item_id,
            coupon_name=_item_name(coupon_item_id),
            primary_term_ids=primary_term_ids,
            primary_term_names=[term.term_name for term in primary_terms],
            guaranteed_secondary_term_ids=secondary_term_ids,
            guaranteed_secondary_term_names=[term.term_name for term in secondary_terms],
            guaranteed_skill_term_ids=skill_term_ids,
            guaranteed_skill_term_names=[term.term_name for term in skill_terms],
        )
        cls._energy_point_cache[point_id] = result
        return result

    @classmethod
    def _iter_energy_points(cls) -> list[WeaponGemEnergyPointData]:
        result: list[WeaponGemEnergyPointData] = []
        for point_id, point_data in TableCfg.WorldEnergyPointTable().items():
            point_name = get_i18n_text(point_data.get("gameName"))
            if not point_name.startswith("重度能量淤积点·"):
                continue
            result.append(cls._build_energy_point_data(point_id, point_data))
        return result

    @classmethod
    def _get_perfect_gem_id(cls, weapon_id: str) -> str:
        preset = TableCfg.GachaPoolWeaponPresetTable().get(weapon_id, {})
        perfect_gem_id = preset.get("perfectGemId", "") or ""
        if perfect_gem_id:
            return perfect_gem_id

        char_presets = TableCfg.GachaPoolCharPresetTable().values()
        for data in char_presets:
            if data.get("perfectWeaponId") == weapon_id:
                return data.get("perfectWeaponGemId", "") or ""
        return ""

    @classmethod
    def _get_perfect_gem(cls, gem_id: str) -> WeaponGemPresetData | None:
        gem_data = TableCfg.GemPresetTable().get(gem_id)
        if gem_data is None:
            return None

        primary_terms: list[GemTermData] = []
        secondary_terms: list[GemTermData] = []
        skill_terms: list[GemTermData] = []
        for term in gem_data.get("termList", []):
            term_id = term.get("termId", "") or ""
            term_level = int(term.get("level", 0) or 0)
            term_data = cls._get_term_data(term_id, term_level)
            if term_data.term_type == "PrimAttrTerm":
                primary_terms.append(term_data)
            elif term_data.term_type == "SecAttrTerm":
                secondary_terms.append(term_data)
            elif term_data.term_type == "SkillTerm":
                skill_terms.append(term_data)

        return WeaponGemPresetData(
            gem_id=gem_id,
            domain_id=gem_data.get("domainId", "") or "",
            rarity=int(gem_data.get("rarity", 0) or 0),
            primary_terms=primary_terms,
            secondary_terms=secondary_terms,
            skill_terms=skill_terms,
        )

    @classmethod
    def _score_energy_point(
        cls,
        weapon_id: str,
        energy_point: WeaponGemEnergyPointData,
        perfect_gem: WeaponGemPresetData,
    ) -> tuple[int, int, int, int]:
        secondary_hit = len(
            set(energy_point.guaranteed_secondary_term_ids).intersection(
                term.term_id for term in perfect_gem.secondary_terms
            )
        )
        skill_hit = len(
            set(energy_point.guaranteed_skill_term_ids).intersection(term.term_id for term in perfect_gem.skill_terms)
        )
        primary_hit = len(
            set(energy_point.primary_term_ids).intersection(term.term_id for term in perfect_gem.primary_terms)
        )
        known_group_hint = int(energy_point.game_group_id == cls._KNOWN_WEAPON_GROUP_HINTS.get(weapon_id, ""))
        return (secondary_hit + skill_hit, known_group_hint, skill_hit, primary_hit)

    @classmethod
    def get_by_weapon_id(cls, weapon_id: str) -> WeaponGemRecommendationData | None:
        if weapon_id in cls._recommendation_cache:
            return cls._recommendation_cache[weapon_id]

        weapon = WeaponInfoTable.get_by_id(weapon_id)
        if weapon is None:
            return None

        perfect_gem_id = cls._get_perfect_gem_id(weapon_id)
        if not perfect_gem_id:
            return None

        perfect_gem = cls._get_perfect_gem(perfect_gem_id)
        if perfect_gem is None:
            return None

        energy_points = cls._iter_energy_points()
        sorted_energy_points = sorted(
            energy_points,
            key=lambda point: (
                cls._score_energy_point(weapon_id, point, perfect_gem),
                point.world_level,
                point.recommend_lv,
            ),
            reverse=True,
        )
        best_energy_point = sorted_energy_points[0] if sorted_energy_points else None

        reasoning = [
            "优先使用武器完美基质中的基础/附加/技能词条作为推荐目标。",
            "基础属性按预刻写规则作为候选集合返回；附加属性或技能属性使用重度能量淤积点组配置中的词条池进行匹配。",
            "最优点位按命中完美基质的附加属性/技能属性优先，再按已验证样本校准同分候选，最后按世界等级排序。",
        ]

        result = WeaponGemRecommendationData(
            weapon=weapon,
            perfect_gem=perfect_gem,
            recommended_primary_term_ids=[term.term_id for term in perfect_gem.primary_terms],
            recommended_primary_term_names=[term.term_name for term in perfect_gem.primary_terms],
            recommended_secondary_term_ids=[term.term_id for term in perfect_gem.secondary_terms],
            recommended_secondary_term_names=[term.term_name for term in perfect_gem.secondary_terms],
            recommended_skill_term_ids=[term.term_id for term in perfect_gem.skill_terms],
            recommended_skill_term_names=[term.term_name for term in perfect_gem.skill_terms],
            recommended_energy_points=sorted_energy_points,
            best_energy_point=best_energy_point,
            reasoning=reasoning,
        )
        cls._recommendation_cache[weapon_id] = result
        return result

    @classmethod
    def get_by_weapon_name(cls, weapon_name: str) -> WeaponGemRecommendationData | None:
        weapon_id = WeaponInfoTable.get_id_by_name(weapon_name)
        if weapon_id is None:
            return None
        return cls.get_by_weapon_id(weapon_id)
