"""ArknightsUID 干员/模组图鉴逻辑的原始 JSON 适配，无 gsuid_core 依赖。"""
from __future__ import annotations

import html
import re
import unicodedata

from .guide_resource import GuideError

PROFESSIONS = dict(WARRIOR="近卫", SNIPER="狙击", TANK="重装", MEDIC="医疗", SUPPORT="辅助",
                   CASTER="术师", SPECIAL="特种", PIONEER="先锋")
POSITIONS = dict(MELEE="近战", RANGED="远程", ALL="近战/远程", NONE="无")
ATTRS = dict(maxHp="生命", atk="攻击", def_="防御", magicResistance="法抗", cost="部署费用",
            blockCnt="阻挡", attackSpeed="攻击速度", baseAttackTime="攻击间隔", respawnTime="再部署时间")
ATTRS["def"] = "防御"


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).strip("\"'“”‘’").casefold()


def find_operator(tables: dict, query: str) -> tuple[str, dict]:
    name = normalize(query)
    matches = [(key, char) for key, char in tables["character_table"].items()
               if key.startswith("char_") and char.get("profession") in PROFESSIONS
               and name in {normalize(char.get("name", "")), normalize(key), normalize(char.get("appellation", ""))}]
    if not matches:
        raise GuideError(f"未找到干员“{query}”，请使用完整干员名；新干员可先发送“明日方舟更新资源”")
    if len(matches) > 1:
        choices = "、".join(f"{char['name']}（{key}）" for key, char in matches)
        raise GuideError(f"存在同名干员，请用对应 ID 查询：{choices}")
    return matches[0]


def _number(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def format_description(text: str | None, board: list[dict] | None = None) -> str:
    values = {str(item.get("key", "")).casefold(): item.get("value") for item in board or []}
    def replace(match):
        key, spec = match.group(1).casefold(), match.group(2) or ""
        value = values.get(key)
        if value is None and key.startswith("-"):
            original = values.get(key[1:])
            value = -original if isinstance(original, (int, float)) else None
        if value is None:
            value = values.get(key.replace("-", "_"))
        if value is None:
            return "未公开"
        if not spec:
            return _number(value)
        try:
            # 游戏是 C# 的零占位格式，不能直接作为 Python 的宽度格式。
            custom = re.fullmatch(r"0(?:\.(0+))?(%)?", spec)
            if custom:
                precision = len(custom.group(1) or "")
                return format(value, f".{precision}{'%' if custom.group(2) else 'f'}")
            return format(value, spec)
        except (ValueError, TypeError):
            return _number(value)
    text = re.sub(r"<[^>]*>", "", text or "").replace("\\n", "\n")
    return html.unescape(re.sub(r"\{([^{}:]+)(?::([^{}]+))?\}", replace, text)).strip()


def _attrs(data: dict, *, positive: bool = False) -> str:
    return "  ·  ".join(f"{title} {'+' if positive and value > 0 else ''}{_number(value)}"
                       for key, value in data.items() if key in ATTRS and isinstance(value, (int, float))
                       and (not positive or value != 0) for title in [ATTRS[key]])


def operator_sections(tables: dict, char_id: str) -> list[tuple[str, str]]:
    char = tables["character_table"][char_id]
    rarity = char.get("rarity", 0)
    stars = int(str(rarity).split("_")[-1]) if isinstance(rarity, str) else int(rarity) + 1
    sub = tables["uniequip_table"]["subProfDict"].get(char.get("subProfessionId"), {}).get("subProfessionName", "")
    phase = char["phases"][-1]
    traits = (char.get("trait") or {}).get("candidates") or []
    trait = traits[-1] if traits else {}
    description = trait.get("overrideDescripton") or char.get("description")
    sections = [("干员资料", f"{'★' * stars}　{PROFESSIONS.get(char.get('profession'), '')} · {sub}"
                 f"　{POSITIONS.get(char.get('position'), '')}\n{format_description(description, trait.get('blackboard'))}"),
                (f"精英 {len(char['phases']) - 1} / Lv.{phase['maxLevel']} · 基础属性", _attrs(phase["attributesKeyFrames"][-1]["data"]))]
    talents = []
    for talent in char.get("talents") or []:
        candidates = talent.get("candidates") or []
        if candidates:
            item = candidates[-1]
            talents.append(f"{item.get('name', '天赋')}\n{format_description(item.get('description'), item.get('blackboard'))}")
    if talents:
        sections.append(("天赋 · 最高精英及潜能", "\n\n".join(talents)))
    potential = [f"潜能 {i + 2}：{format_description(item.get('description'))}"
                 for i, item in enumerate(char.get("potentialRanks") or [])]
    if potential:
        sections.append(("潜能加成", "\n".join(potential)))
    if char.get("favorKeyFrames"):
        sections.append(("满信赖加成", _attrs(char["favorKeyFrames"][-1]["data"], positive=True) or "无额外属性"))
    for index, entry in enumerate(char.get("skills") or [], 1):
        skill = tables["skill_table"].get(entry.get("skillId"))
        if not skill or not skill.get("levels"):
            continue
        level = skill["levels"][-1]
        sp = level.get("spData") or {}
        recovery = {1: "自动回复", 2: "攻击回复", 4: "受击回复", 8: "被动", "INCREASE_WITH_TIME": "自动回复",
                    "INCREASE_WHEN_ATTACK": "攻击回复", "INCREASE_WHEN_TAKEN_DAMAGE": "受击回复", "NONE": "被动"}.get(sp.get("spType"), "特殊回复")
        trigger = {0: "被动生效", 1: "手动触发", 2: "自动触发", "PASSIVE": "被动生效",
                   "MANUAL": "手动触发", "AUTO": "自动触发"}.get(level.get("skillType"), "特殊触发")
        duration = level.get("duration", 0)
        timing = "持续无限" if duration < 0 else f"持续 {_number(duration)} 秒"
        sections.append((f"技能 {index} · {level['name']} · 最高等级 {len(skill['levels'])}",
                         f"{recovery} / {trigger}\n初始技力 {_number(sp.get('initSp', 0))}　"
                         f"消耗 {_number(sp.get('spCost', 0))}　{timing}\n"
                         + format_description(level.get("description"), [{"key": "duration", "value": duration}]
                                              + (level.get("blackboard") or []))))
    return sections


def _part_descriptions(part: dict) -> list[str]:
    lines = []
    # 同时覆盖 TRAIT、TALENT、DISPLAY 以及两个 DATA_ONLY 形式。
    for field in ("overrideTraitDataBundle", "addOrOverrideTalentDataBundle"):
        for candidate in (part.get(field) or {}).get("candidates") or []:
            descriptions = [candidate.get(key) for key in
                            ("additionalDescription", "overrideDescripton", "overrideDescription", "upgradeDescription")]
            if not any(descriptions):
                descriptions = [candidate.get("description")]
            for text in descriptions:
                if not text:
                    continue
                desc = format_description(text, candidate.get("blackboard"))
                rank = candidate.get("requiredPotentialRank", 0)
                line = f"潜能 {rank + 1}：{desc}" if rank else desc
                if line not in lines:
                    lines.append(line)
    return lines


def module_sections(tables: dict, char_id: str) -> list[tuple[str, str]]:
    uniequip = tables["uniequip_table"]
    sections = []
    for equip_id in uniequip["charEquip"].get(char_id, []):
        equip = uniequip["equipDict"].get(equip_id, {})
        battle = tables["battle_equip_table"].get(equip_id, {})
        for phase in battle.get("phases") or []:
            attrs = {item["key"]: item["value"] for item in phase.get("attributeBlackboard") or []}
            effects = []
            for part in phase.get("parts") or []:
                effects.extend(line for line in _part_descriptions(part) if line not in effects)
            title = f"{equip.get('uniEquipName', equip_id)} · 等级 {phase['equipLevel']}"
            sections.append((title, _attrs(attrs, positive=True) + "\n\n" + ("\n\n".join(effects) or "无额外特性变化")))
    return sections or [("模组图鉴", "该干员暂无可查询模组")]
