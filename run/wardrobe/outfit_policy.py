"""Shared outfit rules: one coordinated outfit, independent of scene generation."""
import re


def has_terms(text, terms):
    text = (text or "").lower()
    return any((term in text if not term.isascii() else
                re.search(r"\b" + re.escape(term) + r"\b", text)) for term in terms)


def scene_kind(hint):
    # Nighttime alone does not mean bedtime (night markets / runs are outdoors).
    if has_terms(hint, ("夜跑", "晨跑", "跑步", "健身", "workout", "jogging", "running", "gym", "tennis", "网球")):
        return "sporty"
    if has_terms(hint, ("夜市", "夜游", "逛街", "出门", "街头", "户外", "night market", "street", "outdoor", "hiking")):
        return "outdoor"
    if has_terms(hint, ("睡衣", "睡裤", "睡裙", "睡袍", "晚安", "睡觉", "睡了", "好梦", "被窝", "困了", "床上", "洗澡", "泡澡", "pajamas", "pajama", "sleep", "sleeping", "sleepwear", "bedtime", "in bed", "bathrobe", "nightdress", "nightgown")):
        return "sleepwear"
    if has_terms(hint, ("居家", "宅家", "客厅", "卧室", "沙发", "home", "indoors", "indoor", "bedroom", "sofa")):
        return "indoor"
    return "daily"


_CLOTHING = re.compile(
    r"\b(?:pajamas?|sleepwear|nightdress|nightgown|sleep pants|sleep shorts|"
    r"dress|skirt|pants|trousers|shorts|jeans|leggings|tights|pantyhose|"
    r"sweater|cardigan|hoodie|shirt|tee|blouse|camisole|top|vest|jacket|coat|"
    r"robe|uniform|outfit|clothes|clothing|loungewear|sportswear|swimsuit|bikini|"
    r"kimono|hanfu|yukata|jinbei|tutu|overalls|dungarees|sleeves?|collar|"
    r"scarf|muffler|necktie|sash|apron|capelet|cape|corset|bodice|"
    r"socks|stockings|shoes|boots|sneakers|loafers|slippers|sandals|heels|"
    r"hat|cap|beret|beanie|bonnet|headwear|headband|headdress|earmuffs|"
    r"gloves|mittens|necklace|choker|ribbon|bow|hair ornament|hair accessory)\b",
    re.I,
)


def clothing_tags(tags):
    """Only persist wearable tags, never emotions, poses or backgrounds."""
    return ", ".join(t.strip() for t in (tags or "").split(",") if _CLOTHING.search(t))


def scene_tags(tags):
    """Clothes come from the selected complete outfit, not a second LLM outfit."""
    return ", ".join(t.strip() for t in (tags or "").split(",")
                     if t.strip() and not _CLOTHING.search(t))


def normalize_outfit(tags, category=""):
    """Repair unambiguous sleep/outdoor and alternative-bottom conflicts."""
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    sleep = category == "sleepwear" or has_terms(tags, (
        "pajamas", "pajama", "sleepwear", "nightdress", "nightgown", "sleep pants",
        "pajama shorts", "睡衣", "睡裤", "睡裙"))
    if sleep:
        # Keep sleep pieces as a set; do not turn random outdoor knitwear into pajamas.
        bad = r"\b(sweater|cardigan|scarf|muffler|jacket|coat|boots|sneakers|hat|cap|beret|beanie|earmuffs|mittens)\b|毛衣|围巾|外套"
        parts = [t for t in parts if not re.search(bad, t, re.I)]
        remaining = ", ".join(parts)
        if has_terms(remaining, ("sleep pants", "pajama shorts", "睡裤")) and not has_terms(
                remaining, ("pajamas", "pajama set", "sleepwear", "shirt", "top", "camisole", "睡衣")):
            parts.insert(0, "matching cotton pajama top")
    # A dress / skirt and an unrelated pair of trousers must not compete.
    if has_terms(", ".join(parts), ("dress", "nightdress", "nightgown", "skirt", "睡裙")):
        parts = [t for t in parts if not re.search(r"\b(pants|trousers|jeans|shorts)\b|睡裤", t, re.I)]
    return ", ".join(dict.fromkeys(parts))
