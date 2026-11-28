"""Adapted from BeyondUID 95ba169 (GPL-3.0-or-later). See ../GUIDE_SOURCES.md."""
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import TableCfg
from .i18n_text import get_i18n_text


def _normalize_query(value: str) -> str:
    return value.strip().lower()


def _collect_search_names(*values: str) -> set[str]:
    return {_normalize_query(value) for value in values if isinstance(value, str) and value.strip()}


def _get_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


class CharacterWeaponRecommendData(BaseModel):
    primary_weapon_ids: list[str] = Field(default_factory=list)
    secondary_weapon_ids: list[str] = Field(default_factory=list)
    tertiary_weapon_ids: list[str] = Field(default_factory=list)
    weapon_skill_ids: list[str] = Field(default_factory=list)


class CharacterDetailData(BaseModel):
    id: str
    name: str = ""
    eng_name: str = ""
    phonetic_name: str = ""
    profession: str = ""
    rarity: int = 0
    department: str = ""
    default_weapon_id: str = ""
    weapon_recommend: CharacterWeaponRecommendData = Field(default_factory=CharacterWeaponRecommendData)
    profile_record: list[dict[str, Any]] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class WeaponDetailData(BaseModel):
    id: str
    name: str = ""
    eng_name: str = ""
    weapon_type: str = ""
    rarity: int = 0
    max_lv: int = 0
    desc: str = ""
    weapon_desc: str = ""
    skill_list: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class BaseEntityInfoTable(ABC):
    _name_to_id: ClassVar[dict[str, str] | None] = None

    @classmethod
    @abstractmethod
    def get_by_id(cls, entity_id: str) -> BaseModel | None:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _iter_search_entries(cls) -> list[tuple[str, set[str]]]:
        raise NotImplementedError

    @classmethod
    def clear_cache(cls) -> None:
        cls._name_to_id = None
        detail_cache = getattr(cls, "_detail_cache", None)
        if isinstance(detail_cache, dict):
            detail_cache.clear()

    @classmethod
    def _build_name_index(cls) -> dict[str, str]:
        name_to_id: dict[str, str] = {}
        for entity_id, names in cls._iter_search_entries():
            for name in names:
                name_to_id.setdefault(name, entity_id)
        return name_to_id

    @classmethod
    def get_id_by_name(cls, name: str) -> str | None:
        normalized_name = _normalize_query(name)
        if not normalized_name:
            return None

        if cls._name_to_id is None:
            cls._name_to_id = cls._build_name_index()

        return cls._name_to_id.get(normalized_name)

    @classmethod
    def get_by_name(cls, name: str) -> BaseModel | None:
        entity_id = cls.get_id_by_name(name)
        if entity_id is None:
            return None
        return cls.get_by_id(entity_id)


class CharacterInfoTable(BaseEntityInfoTable):
    _detail_cache: ClassVar[dict[str, CharacterDetailData]] = {}

    @classmethod
    def _iter_search_entries(cls) -> list[tuple[str, set[str]]]:
        entries: list[tuple[str, set[str]]] = []
        for char_id, data in TableCfg.CharacterTable().items():
            entries.append(
                (
                    char_id,
                    _collect_search_names(
                        char_id,
                        get_i18n_text(data.get("name")),
                        get_i18n_text(data.get("engName")),
                        data.get("phoneticName", ""),
                    ),
                )
            )
        return entries

    @classmethod
    def _build_weapon_recommend(cls, entity_id: str) -> CharacterWeaponRecommendData:
        recommend_data = TableCfg.CharWpnRecommendTable().get(entity_id, {})
        recommend_skill_data = TableCfg.CharWpnSkillRecommendTable().get(entity_id, {})
        return CharacterWeaponRecommendData(
            primary_weapon_ids=_get_str_list(recommend_data.get("weaponIds1")),
            secondary_weapon_ids=_get_str_list(recommend_data.get("weaponIds2")),
            tertiary_weapon_ids=_get_str_list(recommend_data.get("weaponIds3")),
            weapon_skill_ids=_get_str_list(recommend_skill_data.get("weaponSkillIds")),
        )

    @classmethod
    def get_by_id(cls, entity_id: str) -> CharacterDetailData | None:
        if entity_id in cls._detail_cache:
            return cls._detail_cache[entity_id]

        data = TableCfg.CharacterTable().get(entity_id)
        if data is None:
            return None

        detail = CharacterDetailData(
            id=entity_id,
            name=get_i18n_text(data.get("name")),
            eng_name=get_i18n_text(data.get("engName")),
            phonetic_name=data.get("phoneticName", "") or "",
            profession=data.get("profession", "") or "",
            rarity=int(data.get("rarity", 0) or 0),
            department=data.get("department", "") or "",
            default_weapon_id=data.get("defaultWeaponId", "") or "",
            weapon_recommend=cls._build_weapon_recommend(entity_id),
            profile_record=data.get("profileRecord", []) or [],
            raw_data=data,
        )
        cls._detail_cache[entity_id] = detail
        return detail


class WeaponInfoTable(BaseEntityInfoTable):
    _detail_cache: ClassVar[dict[str, WeaponDetailData]] = {}

    @classmethod
    def _iter_search_entries(cls) -> list[tuple[str, set[str]]]:
        entries: list[tuple[str, set[str]]] = []
        weapon_table = TableCfg.WeaponBasicTable()
        item_table = TableCfg.ItemTable()

        for weapon_id, data in weapon_table.items():
            item_data = item_table.get(weapon_id, {})
            entries.append(
                (
                    weapon_id,
                    _collect_search_names(
                        weapon_id,
                        get_i18n_text(item_data.get("name")),
                        get_i18n_text(data.get("engName")),
                    ),
                )
            )
        return entries

    @classmethod
    def get_by_id(cls, entity_id: str) -> WeaponDetailData | None:
        if entity_id in cls._detail_cache:
            return cls._detail_cache[entity_id]

        weapon_data = TableCfg.WeaponBasicTable().get(entity_id)
        item_data = TableCfg.ItemTable().get(entity_id)
        if weapon_data is None and item_data is None:
            return None

        detail = WeaponDetailData(
            id=entity_id,
            name=get_i18n_text((item_data or {}).get("name")),
            eng_name=get_i18n_text((weapon_data or {}).get("engName")),
            weapon_type=(weapon_data or {}).get("weaponType", "") or "",
            rarity=int(((item_data or {}).get("rarity")) or ((weapon_data or {}).get("rarity")) or 0),
            max_lv=int((weapon_data or {}).get("maxLv", 0) or 0),
            desc=get_i18n_text((item_data or {}).get("desc")),
            weapon_desc=get_i18n_text((weapon_data or {}).get("weaponDesc")),
            skill_list=(weapon_data or {}).get("weaponSkillList", []) or [],
            raw_data={
                "weapon_basic": weapon_data or {},
                "item": item_data or {},
            },
        )
        cls._detail_cache[entity_id] = detail
        return detail
