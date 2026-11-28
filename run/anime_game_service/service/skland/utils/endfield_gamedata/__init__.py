"""BeyondUID 表访问适配；运行资源由 Eridanus 统一更新。"""
from ..guide_resource import END_TABLES, read_tables


class TableCfg:
    @classmethod
    def reload(cls) -> None:
        from .i18n_text import clear_i18n_text_cache
        clear_i18n_text_cache()
        CharacterInfoTable.clear_cache()
        WeaponInfoTable.clear_cache()
        WeaponGemInfoTable.clear_cache()


def _table(name):
    return classmethod(lambda cls: read_tables("endfield").get(name, {}))


for _name in (*END_TABLES, "CharWpnSkillRecommendTable"):
    setattr(TableCfg, _name, _table(_name))

from .character_weapon_info import CharacterInfoTable, WeaponInfoTable  # noqa: E402
from .weapon_gem_info import WeaponGemInfoTable  # noqa: E402
