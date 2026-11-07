"""The configured LLM chooses the outfit and scene directly from the full wardrobe."""
import json
from run.wardrobe.outfit_policy import validate_outfit_prompt


def outfit_seed_catalog():
    """Expose the original seeds verbatim; the LLM chooses their suitability."""
    from run.qq_zone import qzone_themes as themes
    details = []
    for prefix, values in (("indoor", themes.OUTFIT_INDOOR_DETAILS),
                           ("general", themes.OUTFIT_GENERAL_DETAILS),
                           ("headwear", themes.OUTFIT_OUTDOOR_HEADWEAR_DETAILS)):
        details.extend({"id": f"{prefix}_{index:02d}", "tags": value}
                       for index, value in enumerate(values))
    return {"styles": [dict(value, id=f"style_{index:02d}") for index, value in enumerate(themes.OUTFIT_STYLE_SEEDS)],
            "palettes": [dict(value, id=f"palette_{index:02d}") for index, value in enumerate(themes.OUTFIT_PALETTE_SEEDS)],
            "details": details}


def parse_json_response(response):
    raw = response.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Some compatible gateways prepend status text to the JSON payload.
        decoder = json.JSONDecoder()
        for offset, character in enumerate(raw):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(raw[offset:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                result = candidate
                break
        else:
            raise ValueError("LLM response contains no complete JSON object")
    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object")
    return result


async def select_post_theme(llm, candidates, task_name, context="", recent_posts=()):
    """The scheduler offers varied candidates; the LLM makes the actual choice."""
    if not llm or not candidates:
        raise RuntimeError("主题选择需要已配置的LLM和可用主题")
    choices = {item["id"]: item for item in candidates}
    prompt = (f"动态类型：{task_name}\n当前情境：{context}\n近期动态：{json.dumps(recent_posts, ensure_ascii=False)}\n"
              f"{post_scene_instruction(task_name)}\n"
              f"候选主题（含原生sd_hint）：{json.dumps(candidates, ensure_ascii=False)}\n"
              "由你选择最适合当前时段、情绪且不同于近期动态的一个主题，之后将以它发散写正文。"
              "日常动态的候选包含晨间、日常、夜间来源，由你结合当前真实时间判断适合的活动："
              "晚上可以选择夜间主题，白天优先白天的自然活动。主题池来源不限制选择，实际时间和语义才是依据。"
              "只返回JSON：{\"theme_id\":\"候选中的精确id\"}。")
    for attempt in range(2):
        response = await llm.chat(messages=[{"role": "user", "content": prompt}],
                                  system_prompt="你负责选择空间动态主题，只输出JSON对象。")
        try:
            key = parse_json_response(response).get("theme_id")
            if isinstance(key, str) and key in choices:
                return choices[key]
            raise ValueError("unknown theme_id")
        except (ValueError, TypeError, AttributeError) as exc:
            if attempt:
                raise
            prompt += f"\n上次输出无法使用：{exc}。请严格返回候选中的精确theme_id。"


def post_scene_instruction(task_name):
    if task_name == "晚安":
        return ("本次是晚安动态。没有明确的当前活动或场景时，在室内卧室穿舒适睡裙。"
                "卧室睡前的读书、看手机、发呆也自然穿睡裙。由你理解完整文案和主题，"
                "区分当前活动与回忆、比喻、已结束的活动；明确正在外出或运动时按实际活动穿衣。"
                "卧室种子的变体保留睡前语境，不发散成夜游。")
    if task_name == "早安":
        return "本次是早安动态。由你根据起床、早餐、通勤等实际活动选择穿搭和场景，不沿用昨晚着装。"
    return "本次是日常动态。由你根据完整文案和主题选择合适穿搭和场景。"


def commit_post_outfit(manager, selection, response, has_image):
    """Record this published outfit without creating a daily outfit constraint."""
    if not manager or not selection or not has_image:
        return False
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return False
    if not isinstance(response, dict) or response.get("code") != 0:
        return False
    manager.update_from_qzone_tags(selection["name"], selection["clothing_tags"],
                                   no_hat=selection.get("no_hat", False))
    manager.record_qzone_outfit_usage(selection["name"])
    return True


async def select_post_outfit(manager, llm, post_text, theme_desc, season_name="", task_name="日常",
                             character_anchor="", art_anchor=""):
    """Choose a wardrobe blueprint and original design seeds after text divergence."""
    if not llm:
        raise RuntimeError("Qzone 穿搭决策需要已配置的 LLM")
    candidates = manager.get_qzone_candidates() if manager else {}
    counts = manager._data.get("qzone_outfit_usage", {}) if manager else {}
    catalog = [{"key": key, "description": obj.get("description", ""),
                "occasion": obj.get("occasion", ""), "season": obj.get("season", "all"),
                "clothing_tags": obj["clothing_tags"], "usage_count": counts.get(key, 0)}
               for key, obj in candidates.items()]
    if manager:
        character_anchor = manager.get_character_anchor() or character_anchor
        art_anchor = manager.get_art_anchor() or art_anchor
    seeds = outfit_seed_catalog()
    response = await llm.chat(
        messages=[{"role": "user", "content": (
            f"动态类型：{task_name}\n已确定的动态文案：{post_text}\n主题参考：{theme_desc}\n季节：{season_name}\n"
            f"character_anchor: {character_anchor}\nart_anchor: {art_anchor}\n"
            f"完整可选衣橱：{json.dumps(catalog, ensure_ascii=False)}\n"
            f"原生服饰设计种子：{json.dumps(seeds, ensure_ascii=False)}\n"
            f"{post_scene_instruction(task_name)}\n"
            "每条动态独立设计，不沿用或受限于当天首条、上一条动态的着装；使用次数仅作为多样性参考。"
            "正文已经发散完成。根据正文结果选择服饰款型，并从原生种子中选择一个最适合的style_id、"
            "一个palette_id和零到三个detail_ids，供下一步完成服饰提示词。"
            "衣橱提供服饰的款型和角色气质；style seed提供材质剪裁灵感，palette提供整套协调配色，details提供兼容的细节。"
            "选择接近服饰款型的style，不要把互斥服装拼在一起。睡裙搭配睡裙种子，不用外套或裤装种子替换。"
            "文案中的当前实际活动优先于主题参考。主题与实际活动优先于季节；允许跨季节穿搭。"
            "season只是穿搭参考，不是选择限制；不要输出场景分类标签。"
            "结合usage_count优先选合适且少用的款式，兼顾轮换；最终由你决定精确衣橱key。"
            "如果确实没有合适款式或衣橱为空，outfit_key=null，依据角色和画风设计完整服饰的clothing_tags。"
            "scene_tags只含背景、动作、表情、镜头、光照，不含服饰。no_hat由你判断是否不应戴帽子。"
            "只返回JSON：{\"outfit_key\":\"精确衣橱key或null\","
            "\"clothing_tags\":\"仅自定义服饰时填写英文SD tags\","
            "\"style_id\":\"原生style的精确id\",\"palette_id\":\"原生palette的精确id\","
            "\"detail_ids\":[\"原生detail的精确id\"],"
            "\"scene_tags\":\"英文逗号分隔的场景tags\",\"no_hat\":true或false}"
        )}], system_prompt="你负责空间动态的穿搭与配图决策。直接选服装并设计一致的场景，只输出一个JSON对象。")
    choice = parse_json_response(response)
    if not isinstance(choice, dict) or "outfit_key" not in choice:
        raise ValueError("LLM missing outfit_key")
    if (not isinstance(choice.get("scene_tags"), str) or not choice["scene_tags"].strip()
            or type(choice.get("no_hat")) is not bool):
        raise ValueError("LLM missing scene_tags or no_hat")
    key = choice["outfit_key"]
    if isinstance(key, str) and key in candidates:
        result = manager.resolve_qzone_outfit(key)
    elif key is None and isinstance(choice.get("clothing_tags"), str) and choice["clothing_tags"].strip():
        result = {"name": "自动设计", "clothing_tags": choice["clothing_tags"].strip(), "matched_by": "llm_custom"}
    else:
        raise ValueError("LLM returned unknown outfit key or empty custom outfit")
    styles = {item["id"]: item for item in seeds["styles"]}
    palettes = {item["id"]: item for item in seeds["palettes"]}
    details = {item["id"]: item for item in seeds["details"]}
    if choice.get("style_id") not in styles or choice.get("palette_id") not in palettes:
        raise ValueError("LLM returned unknown style_id or palette_id")
    detail_ids = choice.get("detail_ids")
    if not isinstance(detail_ids, list) or len(detail_ids) > 3 or any(not isinstance(key, str) or key not in details for key in detail_ids):
        raise ValueError("LLM returned invalid detail_ids")
    result["design_seeds"] = {"style": styles[choice["style_id"]], "palette": palettes[choice["palette_id"]],
                              "details": [details[key] for key in dict.fromkeys(detail_ids)]}
    result.update(scene_tags=choice["scene_tags"].strip(), no_hat=choice["no_hat"])
    return result


async def render_post_outfit(llm, selection, post_text, theme_desc, task_name="日常"):
    """Synthesize the final clothes from the chosen garment and actual seed text."""
    seeds = selection["design_seeds"]
    palette = seeds["palette"]
    template = seeds["style"]["template"].format(p=palette["primary"], s=palette["secondary"])
    prompt = (
        f"动态类型：{task_name}\n发散后的最终正文：{post_text}\n"
        f"【主要画面依据：主题原生sd_hint】：{theme_desc}\n"
        f"【已选服饰款型】：{selection['name']}\n款型参考tags：{selection['clothing_tags']}\n"
        f"【必须实际使用的原生服饰seed】：{json.dumps(seeds['style'], ensure_ascii=False)}\n"
        f"【必须实际使用的原生配色seed】：{json.dumps(palette, ensure_ascii=False)}\n"
        f"配色代入后的种子模板：{template}\n"
        f"【已选细节seeds】：{json.dumps(seeds['details'], ensure_ascii=False)}\n"
        f"【已理解的场景】：{selection['scene_tags']}\n{post_scene_instruction(task_name)}\n"
        "完成可直接提交绘图的英文逗号分隔tags，不是照抄衣橱原tags。"
        "保留已选服饰的主体款型与角色气质，用原生palette重新协调主辅色，"
        "将style的面料、剪裁、层次和兼容details融入一套完整穿搭；种子和款型有出入时自然改写种子以适配款型。"
        "每个配色都明确落到衣服或饰品上，不只写抽象色板名。不得混入另一套互斥服饰，不添加未选择的帽子。"
        "原生sd_hint是画面的主要基底：保留其地点、物件、构图、动作、光线等与正文相容的细节，"
        "在native_hint_tags中保留这些原生画面信息；补充scene_tags只写必要的情绪和发散细节。"
        "整体背景信息约70%-80%来自原生hint，补充约20%-30%，避免另起一个泛化场景。"
        "相容的原生hint片段尽量直接保留，不做无意义同义改写。scene_tags最多三个短tag，"
        "不要重复native_hint_tags，补充总长度不超过原生部分的约三分之一。"
        "正文明确改变活动时，以正文实际场景为准，自然调整冲突的原生提示；原生hint中的服装移入服饰设计或替换为已选款型，不能在背景重复塞服装。"
        "clothing_tags只写最终服饰，native_hint_tags与scene_tags只写画面环境动作。"
        "服饰搭配、背景物件、人物是否戴帽子都由你根据完整语义决定，代码不会再删词、补衣服或替换你的结果。"
        "只返回JSON：{\"clothing_tags\":\"完整且协调的最终服饰tags\","
        "\"native_hint_tags\":\"保留原生hint主要画面信息的tags\","
        "\"scene_tags\":\"少量补充tags\",\"no_hat\":true或false}"
    )
    for attempt in range(2):
        response = await llm.chat(messages=[{"role": "user", "content": prompt}],
                                  system_prompt="你负责把已选服饰与原生服饰、配色、细节种子融合为最终绘图提示词，只输出JSON。")
        try:
            rendered = parse_json_response(response)
            validate_outfit_prompt(rendered, require_native_hint=bool(theme_desc))
            extra = rendered["scene_tags"]
            if len([tag for tag in extra.split(",") if tag.strip()]) > 3:
                raise ValueError("补充scene_tags过长；最多三个简短tag，不重复原生hint")
            return dict(selection, baseline_clothing_tags=selection["clothing_tags"], **rendered)
        except (ValueError, TypeError, AttributeError) as exc:
            if attempt:
                raise
            prompt += f"\n上次输出不符合要求：{exc}。保留完整服饰设计和原生hint，缩短补充后重新输出JSON。"
