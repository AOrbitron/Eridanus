import json
import logging
import math
import re
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("prompt_optimizer")


def get_llm_config(config: Any) -> Dict[str, Any]:
    """
    统一获取生图提示词优化与参数控制的 LLM 配置。
    优先读取根级 `llm_config`，向后兼容 `comfyui.llm_config`，最后回退内置默认。
    """
    cfg_dict = {}
    if hasattr(config, "ai_generated_art") and hasattr(config.ai_generated_art, "config"):
        cfg_dict = config.ai_generated_art.config
    elif isinstance(config, dict):
        cfg_dict = config

    llm_cfg = cfg_dict.get("llm_config")
    if not llm_cfg or not isinstance(llm_cfg, dict):
        llm_cfg = cfg_dict.get("comfyui", {}).get("llm_config", {})

    return {
        "base_url": (llm_cfg.get("base_url") or "http://magpieapi.apollodorus.xyz/v1").rstrip("/"),
        "apikey": llm_cfg.get("apikey") or "sk-magpie-key-26c4f8a10ac45417acb09cd303e920a8ada9c458670a4006",
        "model": llm_cfg.get("model") or "gemini-3.8-flash",
        "temperature": float(llm_cfg.get("temperature", 0.7)),
    }


def normalize_resolution_bounds(
    min_dim: int = 1100,
    max_dim: int = 1600
) -> Tuple[int, int]:
    """将配置的最小/最大边长对齐到 64 的整数倍，并保证 min_aligned <= max_aligned。"""
    lo = max(256, int(min_dim))
    hi = max(lo, int(max_dim))
    min_aligned = int(math.ceil(lo / 64) * 64)
    max_aligned = int(math.floor(hi / 64) * 64)
    if max_aligned < 256:
        max_aligned = int(round(hi / 64) * 64)
    if min_aligned > max_aligned:
        min_aligned = max_aligned
    return (min_aligned, max_aligned)


def clamp_resolution_to_bounds(
    width: int,
    height: int,
    min_dim: int = 1100,
    max_dim: int = 1600
) -> Tuple[int, int]:
    """将宽高对齐 64 倍数并限制在配置的映射区间内。"""
    min_aligned, max_aligned = normalize_resolution_bounds(min_dim, max_dim)
    w = max(min_aligned, min(max_aligned, int(round(int(width) / 64) * 64)))
    h = max(min_aligned, min(max_aligned, int(round(int(height) / 64) * 64)))
    return (w, h)


def map_aspect_ratio_to_resolution(
    ar: Any,
    default_w: int = 1152,
    default_h: int = 1536,
    min_dim: int = 1100,
    max_dim: int = 1600
) -> Tuple[int, int]:
    """
    将宽高比 (aspect_ratio) 自适应映射到分辨率。
    根据 min_dim ~ max_dim 区间按目标像素面积自适应计算宽高，并对齐 64 的整数倍。
    """
    min_aligned, max_aligned = normalize_resolution_bounds(min_dim, max_dim)
    if not ar:
        return clamp_resolution_to_bounds(default_w, default_h, min_dim, max_dim)

    ar_str = str(ar).strip().lower()
    if ":" in ar_str:
        try:
            parts = ar_str.split(":", 1)
            rw, rh = float(parts[0]), float(parts[1])
            if rw > 0 and rh > 0:
                mid = (min_aligned + max_aligned) / 2.0
                base_pixels = mid * mid
                calc_w = int(round((base_pixels * (rw / rh)) ** 0.5 / 64) * 64)
                calc_h = int(round((base_pixels * (rh / rw)) ** 0.5 / 64) * 64)
                return clamp_resolution_to_bounds(calc_w, calc_h, min_dim, max_dim)
        except Exception:
            pass

    return clamp_resolution_to_bounds(default_w, default_h, min_dim, max_dim)


DEFAULT_NEGATIVE_PROMPT_FALLBACK = (
    "lowres, bad anatomy, bad proportions, bad hands, poorly drawn hands, mutated hands, malformed hands, "
    "extra fingers, too many fingers, extra digit, fewer digits, missing fingers, fused fingers, "
    "extra arms, extra legs, extra limbs, missing arms, missing legs, fused limbs, malformed limbs, "
    "disconnected limbs, floating limbs, long neck, poorly drawn face, asymmetric eyes, cross-eyed, "
    "duplicate, clone, multiple views, text, error, cropped, worst quality, low quality, normal quality, "
    "jpeg artifacts, scan artifacts, film grain, chromatic aberration, signature, watermark, username, "
    "logo, dated, blurry, out of focus"
)


def build_wardrobe_context(wm: Any, is_about_bot: bool = False) -> Dict[str, str]:
    """提取衣橱锚点、当前着装与完整可选套装目录摘要，供 LLM 语义选装。"""
    ctx = {
        "char_anchor": "",
        "art_anchor": "",
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT_FALLBACK,
        "current_outfit_name": "",
        "current_outfit_tags": "",
        "wardrobe_catalog": "",
    }
    if not wm:
        return ctx

    ctx["negative_prompt"] = wm.get_negative_prompt() or DEFAULT_NEGATIVE_PROMPT_FALLBACK
    if not is_about_bot:
        return ctx

    ctx["char_anchor"] = wm.get_character_anchor() or ""
    ctx["art_anchor"] = wm.get_art_anchor() or ""
    outfit_info = wm.get_current_outfit() or {}
    ctx["current_outfit_name"] = outfit_info.get("name", "") or ""
    ctx["current_outfit_tags"] = outfit_info.get("clothing_tags", "") or ""

    outfits = wm.get_outfits() if hasattr(wm, "get_outfits") else {}
    catalog_lines = []
    for key, obj in (outfits or {}).items():
        if not isinstance(obj, dict):
            continue
        tags = (obj.get("clothing_tags") or "").strip()
        if not tags:
            continue
        cat = (obj.get("category") or "").strip()
        desc = (obj.get("description") or "").strip()
        catalog_lines.append(f"- {key} [{cat}]: {desc} | tags: {tags}")
    ctx["wardrobe_catalog"] = "\n".join(catalog_lines)
    return ctx


async def optimize_prompt_for_sd(
    user_prompt: str,
    config: Any,
    is_about_bot: bool = False,
    aspect_ratio: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    针对 Stable Diffusion (SD/SDXL) 后端的提示词优化器：
    1. SD 无法识别中文或自然语言叙述，必须转换为纯英文逗号分隔的 Danbooru tag 词条；
    2. 自动载入衣橱管理系统的角色锚点、服装设定与负向提示词；
    3. 严格将分辨率约束在 1100 - 1600 区间；
    4. 步数 steps 自主决定在 28 - 60 区间；
    5. 调用统一的顶层 `llm_config` 执行模型转换，附带完备的离线规则兜底。
    """
    # 1. 尝试获取衣橱锚点与完整套装目录（交由 LLM 语义选装，避免关键字误杀）
    wm_ctx = {
        "char_anchor": "",
        "art_anchor": "",
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT_FALLBACK,
        "current_outfit_name": "",
        "current_outfit_tags": "",
        "wardrobe_catalog": "",
    }
    try:
        from run.wardrobe.wardrobe_manager import get_wardrobe_manager
        wm = get_wardrobe_manager() if get_wardrobe_manager else None
        wm_ctx = build_wardrobe_context(wm, is_about_bot=is_about_bot)
    except Exception as e:
        logger.debug(f"[SD Optimizer] 读取衣橱系统异常: {e}")

    char_anchor = wm_ctx["char_anchor"]
    outfit_tags = wm_ctx["current_outfit_tags"]
    current_outfit_name = wm_ctx["current_outfit_name"]
    wardrobe_catalog = wm_ctx["wardrobe_catalog"]
    negative_prompt = wm_ctx["negative_prompt"]

    # 2. 从配置读取 SD 分辨率映射区间并自适应对齐
    cfg_dict = {}
    if hasattr(config, "ai_generated_art") and hasattr(config.ai_generated_art, "config"):
        cfg_dict = config.ai_generated_art.config
    elif isinstance(config, dict):
        cfg_dict = config
    ai_cfg = cfg_dict.get("ai绘画", {}) if isinstance(cfg_dict, dict) else {}

    min_dim = int(ai_cfg.get("sd分辨率映射最小边长", 1100))
    max_dim = int(ai_cfg.get("sd分辨率映射最大边长", 1600))
    default_w, default_h = 1152, 1536
    raw_default_res = str(ai_cfg.get("sd画图默认分辨率", "")).strip()
    if "," in raw_default_res:
        try:
            dw_s, dh_s = raw_default_res.split(",", 1)
            default_w, default_h = int(dw_s.strip()), int(dh_s.strip())
        except Exception:
            pass
    min_aligned, max_aligned = normalize_resolution_bounds(min_dim, max_dim)
    width, height = map_aspect_ratio_to_resolution(
        aspect_ratio,
        default_w=default_w,
        default_h=default_h,
        min_dim=min_dim,
        max_dim=max_dim,
    )

    # 3. 准备调用 LLM 转换为纯 Danbooru 词条
    llm = get_llm_config(config)

    wardrobe_rule = ""
    if is_about_bot:
        wardrobe_rule = f"""
   - 当前衣橱着装（{current_outfit_name or '默认'}）："{outfit_tags}"
   - 衣橱可选套装目录（格式：套装名 [分类]: 描述 | tags）：
{wardrobe_catalog or '（暂无）'}
   - 【智能选装规则】：
     1) 若用户未指定特定服装或未要求换装，请完整保留当前衣橱着装 tags；
     2) 若用户描述了特定服饰风格或局部特征（如“花嫁”、“荷叶边的日常裙子”、“牛仔吊带裙”、“蛋糕裙”等），请先在【衣橱可选套装目录】中按语义匹配最贴合的套装，直接选用该套装的 tags；**严格区分 [daily] 日常裙装 与 [sleepwear] 睡裙，绝不能把日常荷叶边裙误选为睡裙**；
     3) 若用户明确指定了衣橱目录中不存在的全新服饰（如“比基尼”、“宇航服”），请**忽略当前衣橱着装**，直接按用户要求输出精准的 Danbooru 服装 tags，切勿将当前常服开衫/百褶裙与新服装混拼冲突！"""

    system_instruction = f"""你是一个专精于 Stable Diffusion (SD/SDXL) 的动漫提示词优化专家。
【极端重要规则】：
1. SD 模型（如 SDXL、WaiIllustrious、NoobAI）无法识别中文，也无法理解自然语言完整句子。
2. 你必须将用户的绘图要求完全转换为【纯英文逗号分隔的 Danbooru tag 词条】（例如: masterpiece, best quality, 1girl, solo, nightgown, frills, sitting, on bed, looking at viewer）。
3. 严禁输出任何中文字符！严禁输出自然语言段落！
4. 【角色与设定保护】：
   - 角色核心外貌锚点（若有）："{char_anchor}"。必须原样保留在最前面并保持英文 tag 格式！{wardrobe_rule}
5. 【参数规范】：
   - width 与 height 必须在 {min_aligned} 到 {max_aligned} 之间（已预设为 width={width}, height={height}，可根据构图微调至 {min_aligned}~{max_aligned} 内 64 的倍数）。
   - 采样步数 steps 必须自主选在 28 到 60 之间（默认推荐 30~45）。
   - cfg 推荐 4.5 到 7.0。
   - negative_prompt 输出纯英文 Danbooru 负面 tags（需包含多指/多手/多腿/肢体畸形及低画质过滤，如 extra fingers, too many fingers, extra arms, extra legs, bad anatomy, bad hands）。

你必须仅输出合法的 JSON 格式，不要包含任何 markdown 代码块以外的解释：
{{
  "positive_prompt": "masterpiece, best quality, aesthetic, 1girl, solo, ...",
  "negative_prompt": "lowres, bad anatomy, bad hands, extra fingers, extra arms, extra legs, text, error, ...",
  "width": {width},
  "height": {height},
  "steps": 32,
  "cfg": 5.0
}}"""

    user_msg = f"用户原始绘图需求：{user_prompt}\n是否绘制Bot本人肖像：{is_about_bot}"

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{llm['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm['apikey']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": llm["model"],
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_msg}
                    ],
                    "temperature": llm["temperature"]
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # 剔除代码块
                clean_json = re.sub(r"^```(?:json)?\s*", "", content)
                clean_json = re.sub(r"\s*```$", "", clean_json).strip()
                parsed = json.loads(clean_json)

                # 约束校验
                res_w, res_h = clamp_resolution_to_bounds(
                    int(parsed.get("width", width)),
                    int(parsed.get("height", height)),
                    min_dim=min_dim,
                    max_dim=max_dim,
                )

                res_steps = int(parsed.get("steps", 32))
                res_steps = max(28, min(60, res_steps))

                pos = parsed.get("positive_prompt", "")
                opt_neg = parsed.get("negative_prompt", "")
                if opt_neg and negative_prompt:
                    existing = {t.strip().casefold() for t in negative_prompt.split(",") if t.strip()}
                    extra_neg = [t.strip() for t in opt_neg.split(",") if t.strip() and t.strip().casefold() not in existing]
                    neg = f"{negative_prompt}, {', '.join(extra_neg)}" if extra_neg else negative_prompt
                else:
                    neg = opt_neg or negative_prompt

                # 确保无中文遗留
                pos_cleaned = re.sub(r"[\u4e00-\u9fa5]+", "", pos)
                pos_cleaned = re.sub(r",\s*,+", ",", pos_cleaned).strip(" ,")

                return {
                    "positive_prompt": pos_cleaned or pos,
                    "negative_prompt": neg,
                    "width": res_w,
                    "height": res_h,
                    "steps": res_steps,
                    "cfg": float(parsed.get("cfg", 5.0))
                }
    except Exception as e:
        logger.warning(f"[SD Optimizer] LLM 提示词优化失败，执行规则兜底: {e}")

    # 4. 离线/故障规则兜底（确保绝不崩溃，依然输出 Danbooru 风格提示词）
    fallback_tags = ["masterpiece", "best quality", "aesthetic", "highly detailed"]
    if char_anchor:
        fallback_tags.append(char_anchor)
    prompt_lower = user_prompt.lower()
    has_custom_clothing = any(
        kw in prompt_lower
        for kw in [
            "睡裙", "睡衣", "nightgown", "pajama", "sleepwear", "泳装", "比基尼", "swimsuit",
            "bikini", "礼服", "旗袍", "汉服", "制服", "uniform", "cosplay", "lo裙", "lolita"
        ]
    )
    if outfit_tags and not has_custom_clothing:
        fallback_tags.append(outfit_tags)

    # 简单提取常用词
    if any(k in prompt_lower for k in ["睡裙", "nightgown"]):
        fallback_tags.append("pure white ruffled nightgown, thin shoulder straps, delicate frills")
    if any(k in prompt_lower for k in ["床", "bed", "bedroom"]):
        fallback_tags.append("sitting on bed, cozy bedroom, soft moonlight, indoor")
    if any(k in prompt_lower for k in ["笑", "smile"]):
        fallback_tags.append("gentle smile, looking at viewer")
    if any(k in prompt_lower for k in ["熊", "bear"]):
        fallback_tags.append("holding teddy bear")

    return {
        "positive_prompt": ", ".join(t.strip(" ,") for t in fallback_tags if t and t.strip(" ,")),
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": 32,
        "cfg": 5.0
    }


async def optimize_prompt_for_img2img(
    user_prompt: str,
    config: Any,
    is_about_bot: bool = False,
    denoise: float = 0.65
) -> Dict[str, Any]:
    """
    针对 ComfyUI / SD 以图生图 (img2img) 的专门提示词指导优化器：
    - 分析用户对原图的修改意图（如换装、变换发色、修改背景或微调动作表情）；
    - 保留原图构图与主体的关键特征，并强化用户要求的修改点；
    - 给出最佳推荐重绘幅度 denoise（0.3~0.8）。
    """
    llm = get_llm_config(config)

    char_anchor = ""
    try:
        from run.wardrobe.wardrobe_manager import get_wardrobe_manager
        wm = get_wardrobe_manager() if get_wardrobe_manager else None
        if wm and is_about_bot:
            char_anchor = wm.get_character_anchor() or ""
    except Exception:
        pass

    system_instruction = f"""你是一个二次元以图生图 (Image-to-Image / img2img) 提示词指导专家。
用户提供了一张参考图片，并提出了针对该图片的重绘或编辑要求。
你的任务是将用户的修改要求转化为最适合以图生图的纯英文 Danbooru 提示词：
1. 聚焦于用户想要修改或新增的元素（例如服装变更、发色调整、表情、背景光影等）。
2. 若涉及角色外观锚点，保留基础特征："{char_anchor}"。
3. 推荐合理的重绘幅度 denoise：
   - 微调细节/高清平滑/仅微调表情：denoise 选在 0.35 ~ 0.45；
   - 换装/更改背景/中度重绘：denoise 选在 0.55 ~ 0.68；
   - 彻底大重绘/姿态改变：denoise 选在 0.70 ~ 0.82。
4. 步数 steps 建议在 28 到 50 之间。

输出必须为合法的 JSON 格式：
{{
  "positive_prompt": "masterpiece, best quality, aesthetic, ...",
  "negative_prompt": "lowres, bad anatomy, bad hands, blurry, messy hair, ...",
  "denoise": 0.65,
  "steps": 32,
  "cfg": 5.5
}}"""

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{llm['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm['apikey']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": llm["model"],
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": f"以图生图用户修改需求：{user_prompt}"}
                    ],
                    "temperature": llm["temperature"]
                }
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                clean_json = re.sub(r"^```(?:json)?\s*", "", content)
                clean_json = re.sub(r"\s*```$", "", clean_json).strip()
                parsed = json.loads(clean_json)
                parsed_denoise = float(parsed.get("denoise", denoise))
                parsed_steps = int(parsed.get("steps", 32))
                return {
                    "positive_prompt": parsed.get("positive_prompt", user_prompt),
                    "negative_prompt": parsed.get(
                        "negative_prompt",
                        "lowres, bad anatomy, bad hands, extra fingers, extra arms, extra legs, extra limbs, fused fingers, blurry, messy hair"
                    ),
                    "denoise": max(0.2, min(0.85, parsed_denoise)),
                    "steps": max(28, min(60, parsed_steps)),
                    "cfg": float(parsed.get("cfg", 5.5))
                }
    except Exception as e:
        logger.warning(f"[Img2Img Optimizer] LLM 提示词指导失败，使用默认规则: {e}")

    return {
        "positive_prompt": f"masterpiece, best quality, aesthetic, {user_prompt}",
        "negative_prompt": "lowres, bad anatomy, bad hands, extra fingers, extra arms, extra legs, extra limbs, fused fingers, blurry, messy hair",
        "denoise": denoise,
        "steps": 32,
        "cfg": 5.5
    }
