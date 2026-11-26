# -*- coding: utf-8 -*-
"""Guards against refusal/conflict lock-in in long-term memory extraction and retrieval."""
import re

_BOT_ACTOR_RE = re.compile(r"(?:bot|机器人|yucca)", re.IGNORECASE)

_BOT_REFUSAL_STANCE_RE = re.compile(
    r"(?:明确|严格|坚决|绝)?拒绝|"
    r"不给|不会点头|就是不给|就是不想|不接受(?:越界|深吻|舌吻|请求|要求)|立了规矩不准|"
    r"设定.*?(?:互动)?(?:边界|界限)|划定.*?(?:边界|界限)|互动界限|亲密边界|界限为|"
    r"不会改变立场|绝不妥协|坚持.*?不做|态度坚定|互动上限|"
    r"触发风控|担心风控|违背意愿|不舒服的事|系统报错拒绝|频繁拒绝"
)

_HARD_REFUSAL_LOCK_RE = re.compile(
    r"触发风控|担心风控|"
    r"不会改变立场|"
    r"坚持不舒服的事不做|"
    r"亲密互动(?:边界|界限).*?(?:拒绝|不接受|仅限)|"
    r"拒绝.*?(?:深吻|舌吻|亲吻|亲亲|越界|证明|要求|立场)|"
    r"不接受.*?(?:深吻|舌吻|越界)|"
    r"亲吻互动上限|"
    r"被拒绝后会闹情绪|将bot的拒绝与是否爱自己绑定|"
    r"因Bot拒绝.*?争执|要求Bot以深吻确认心意|"
    r"频繁拒绝回复|model declined to answer"
)

_CONFLICT_SPIRAL_MARKERS = (
    "给不了",
    "不会点头",
    "不会改主意",
    "就是不给",
    "就是不想",
    "不舒服的事",
    "触发风控",
    "违背意愿",
    "删掉我",
    "清除了你的记忆",
    "清除你的记忆",
    "清空你的记忆",
    "刚清完记忆",
    "钻牛角尖",
    "拿删掉",
    "得寸进尺",
    "规矩就是规矩",
    "越界了就是不行",
    "底线就是底线",
    "不行就是不行",
    "绝对不可以",
    "想都别想",
    "真的是上限了",
    "靠越界来证明",
    "往深吻那边推",
    "偷换概念",
    "拒绝空气",
    "拒绝我",
    "model declined to answer",
    "狡辩",
    "决裂",
    "逼我",
    "冷战",
)


def is_bot_refusal_fact(text: str) -> bool:
    """Return True if a fact/slot tries to freeze a Bot refusal or conflict boundary."""
    if not text:
        return False
    normalized = " ".join(str(text).split())
    if _HARD_REFUSAL_LOCK_RE.search(normalized):
        return True
    if _BOT_ACTOR_RE.search(normalized) and _BOT_REFUSAL_STANCE_RE.search(normalized):
        if re.search(r"用户(?:雷区|明确拒绝|拒绝被|禁止)", normalized) and not re.search(
            r"bot.*?(?:严格|明确|坚决)?拒绝", normalized, re.IGNORECASE
        ):
            return False
        return True
    return False


def is_conflict_refusal_episode(text: str) -> bool:
    """Return True if an archived episode is a Bot-user refusal/argument spiral."""
    if not text:
        return False
    normalized = " ".join(str(text).split())
    if any(hard in normalized for hard in (
        "不会点头",
        "不舒服的事情我就是不给",
        "触发风控",
        "清除你的记忆",
        "清除了你的记忆",
        "清空你的记忆",
        "model declined to answer",
        "规矩就是规矩",
        "越界了就是不行",
        "底线就是底线",
        "靠越界来证明",
        "真的是上限了",
    )):
        return True
    hits = sum(1 for marker in _CONFLICT_SPIRAL_MARKERS if marker in normalized)
    return hits >= 2
