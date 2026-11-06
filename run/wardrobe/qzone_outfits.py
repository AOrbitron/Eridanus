"""Select a wardrobe key before generating the scene, with a custom-outfit escape hatch."""
import json
import logging

from run.wardrobe.outfit_policy import normalize_outfit, scene_kind, clothing_tags

logger = logging.getLogger(__name__)


def commit_post_outfit(manager, selection, response, date_str, has_image):
    """Consume rotation only after Qzone confirms publishing an illustrated post."""
    if not manager or not selection or not has_image:
        return False
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return False
    if not isinstance(response, dict) or response.get("code") != 0:
        return False
    first = manager.on_daily_first_post(date_str)
    manager.update_from_qzone_tags(selection["name"], selection["clothing_tags"],
                                   is_daily_default=first, no_hat=selection.get("no_hat", False))
    manager.record_qzone_outfit_usage(selection["name"])
    return True


async def select_post_outfit(manager, llm, post_text, theme_desc, season_name=""):
    candidates = manager.get_qzone_candidates(post_text, theme_desc, season_name)
    fallback = manager.pick_base_outfit_for_theme(
        theme_desc=theme_desc, post_text=post_text, season_name=season_name)
    if not llm:
        return fallback
    catalog = [{"key": key, "description": obj.get("description", ""),
                "category": obj.get("category", ""), "season": obj.get("season", "all"),
                "occasion": obj.get("occasion", ""), "clothing_tags": obj.get("clothing_tags", "")}
               for key, obj in candidates.items()]
    try:
        response = await llm.chat(
            messages=[{"role": "user", "content": (
                f"已确定的动态文案：{post_text}\n主题参考：{theme_desc}\n季节：{season_name}\n"
                f"character_anchor: {manager.get_character_anchor()}\n"
                f"art_anchor: {manager.get_art_anchor()}\n"
                f"可选衣橱：{json.dumps(catalog, ensure_ascii=False)}\n"
                "先判断实际活动和穿衣场合，再选择一套完整服装。文案优先于主题参考。"
                "主题与实际活动优先于季节；season 仅为穿搭参考，不是选择限制。"
                "允许按场景选择跨季或反季节服饰，例如夏季去雪山可以穿冬衣。"
                "躺床上睡觉、晚安应选睡衣，不得选骑行皮衣、外出服或靴子。"
                "sleepwear 候选已按使用次数轮换，优先未使用款，季节仅作室内睡衣的参考。"
                "只返回 JSON：{\"outfit_key\":\"候选中的精确key\"}。"
                "仅当衣橱确实没有合适服装时，允许返回 "
                "{\"outfit_key\":null,\"clothing_tags\":\"完整协调的新服装英文SD tags\"}，"
                "基于上述角色和画风锚点设计，只含服饰，不含人物、动作、背景或画风。"
            )}],
            system_prompt="你负责为已确定的空间动态选衣服。只输出一个合法JSON对象。")
        raw = response.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        choice = json.loads(raw)
        if not isinstance(choice, dict) or "outfit_key" not in choice:
            raise ValueError("missing outfit_key")
        key = choice["outfit_key"]
        if isinstance(key, str) and key in candidates:
            return manager.resolve_qzone_outfit(key, post_text, theme_desc)
        if key is None and isinstance(choice.get("clothing_tags"), str):
            tags = normalize_outfit(choice["clothing_tags"].strip(),
                                    "sleepwear" if scene_kind(post_text) == "sleepwear" else "")
            if clothing_tags(tags):
                return {"name": "自动设计", "clothing_tags": tags,
                        "no_hat": scene_kind(post_text) in {"sleepwear", "indoor"},
                        "matched_by": "llm_custom"}
        raise ValueError("invalid wardrobe key or empty custom outfit")
    except Exception as exc:
        logger.warning("[Qzone Wardrobe] LLM选衣失败，使用场景与轮换兜底: %s", exc)
        return fallback
