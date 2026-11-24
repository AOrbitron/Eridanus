import json
import logging
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


def map_aspect_ratio_to_resolution(
    ar: Any,
    default_w: int = 1280,
    default_h: int = 1728
) -> Tuple[int, int]:
    """
    将宽高比 (aspect_ratio) 映射到分辨率。
    所有尺寸严格约束在 1200 - 1800 之间，且向下/向上对齐 64 的整数倍（适配 DiT 及 SDXL 显存格点）。
    """
    if not ar:
        return (default_w, default_h)

    ar_str = str(ar).strip().lower()

    # 标准比例映射表 (宽, 高 均处于 1200 - 1800 区间，64倍数)
    ar_map = {
        "1:1":  (1536, 1536),
        "3:4":  (1280, 1728),
        "4:3":  (1728, 1280),
        "2:3":  (1216, 1792),
        "3:2":  (1792, 1216),
        "4:5":  (1280, 1600),
        "5:4":  (1600, 1280),
        "5:7":  (1216, 1728),
        "7:5":  (1728, 1216),
        "9:16": (1216, 1792),
        "16:9": (1792, 1216),
        "9:21": (1216, 1792),
        "21:9": (1792, 1216),
    }

    if ar_str in ar_map:
        return ar_map[ar_str]

    if ":" in ar_str:
        try:
            parts = ar_str.split(":")
            rw, rh = float(parts[0]), float(parts[1])
            base_pixels = 1472 * 1472  # 约 2.16M 像素
            calc_w = int(round((base_pixels * (rw / rh)) ** 0.5 / 64) * 64)
            calc_h = int(round((base_pixels * (rh / rw)) ** 0.5 / 64) * 64)
            w = max(1200, min(1800, calc_w))
            h = max(1200, min(1800, calc_h))
            w = int(round(w / 64) * 64)
            h = int(round(h / 64) * 64)
            return (w, h)
        except Exception:
            pass

    return (default_w, default_h)


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
    3. 严格将分辨率约束在 1200 - 1800 区间；
    4. 步数 steps 自主决定在 28 - 60 区间；
    5. 调用统一的顶层 `llm_config` 执行模型转换，附带完备的离线规则兜底。
    """
    # 1. 尝试获取衣橱锚点
    char_anchor = ""
    outfit_tags = ""
    art_anchor = ""
    negative_prompt = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, "
        "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry"
    )

    try:
        from run.wardrobe.wardrobe_manager import get_wardrobe_manager
        wm = get_wardrobe_manager() if get_wardrobe_manager else None
        if wm:
            negative_prompt = wm.get_negative_prompt() or negative_prompt
            if is_about_bot:
                char_anchor = wm.get_character_anchor() or ""
                art_anchor = wm.get_art_anchor() or ""
                # 自定义服装检查：若提示词指定了睡裙、泳衣等具体服饰，不叠加日常开衫
                has_custom_clothing = any(
                    kw in user_prompt.lower()
                    for kw in [
                        "睡裙", "睡衣", "nightgown", "pajama", "sleepwear", "吊带裙", "泳装", "比基尼", "swimsuit",
                        "bikini", "礼服", "dress", "旗袍", "汉服", "制服", "uniform", "cosplay", "lo裙", "lolita"
                    ]
                )
                if not has_custom_clothing:
                    outfit_info = wm.get_current_outfit()
                    outfit_tags = outfit_info.get("clothing_tags", "") if outfit_info else ""
    except Exception as e:
        logger.debug(f"[SD Optimizer] 读取衣橱系统异常: {e}")

    # 2. 分辨率对齐 (1200 - 1800)
    width, height = map_aspect_ratio_to_resolution(aspect_ratio, default_w=1280, default_h=1728)

    # 3. 准备调用 LLM 转换为纯 Danbooru 词条
    llm = get_llm_config(config)

    system_instruction = f"""你是一个专精于 Stable Diffusion (SD/SDXL) 的动漫提示词优化专家。
【极端重要规则】：
1. SD 模型（如 SDXL、WaiIllustrious、NoobAI）无法识别中文，也无法理解自然语言完整句子。
2. 你必须将用户的绘图要求完全转换为【纯英文逗号分隔的 Danbooru tag 词条】（例如: masterpiece, best quality, 1girl, solo, nightgown, frills, sitting, on bed, looking at viewer）。
3. 严禁输出任何中文字符！严禁输出自然语言段落！
4. 【角色与设定保护】：
   - 角色核心外貌锚点（若有）："{char_anchor}"。必须原样保留在最前面并保持英文 tag 格式！
   - 当前着装设定（若有）："{outfit_tags}"。若用户未要求换装，请保留此服装 tags；若用户要求了特定服饰（如睡裙/泳装），将其转化为精准的 Danbooru 服装 tags！
5. 【参数规范】：
   - width 与 height 必须在 1200 到 1800 之间（已预设为 width={width}, height={height}，可根据构图微调至 1200~1800 内 64 的倍数）。
   - 采样步数 steps 必须自主选在 28 到 60 之间（默认推荐 30~45）。
   - cfg 推荐 4.5 到 7.0。
   - negative_prompt 输出纯英文 Danbooru 负面 tags。

你必须仅输出合法的 JSON 格式，不要包含任何 markdown 代码块以外的解释：
{{
  "positive_prompt": "masterpiece, best quality, aesthetic, 1girl, solo, ...",
  "negative_prompt": "lowres, bad anatomy, bad hands, text, error, ...",
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
                res_w = int(parsed.get("width", width))
                res_h = int(parsed.get("height", height))
                res_w = max(1200, min(1800, res_w))
                res_h = max(1200, min(1800, res_h))
                res_w = int(round(res_w / 64) * 64)
                res_h = int(round(res_h / 64) * 64)

                res_steps = int(parsed.get("steps", 32))
                res_steps = max(28, min(60, res_steps))

                pos = parsed.get("positive_prompt", "")
                neg = parsed.get("negative_prompt", negative_prompt)

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
    if outfit_tags:
        fallback_tags.append(outfit_tags)

    # 简单提取常用词
    prompt_lower = user_prompt.lower()
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
                    "negative_prompt": parsed.get("negative_prompt", "lowres, bad anatomy, bad hands, blurry, messy hair"),
                    "denoise": max(0.2, min(0.85, parsed_denoise)),
                    "steps": max(28, min(60, parsed_steps)),
                    "cfg": float(parsed.get("cfg", 5.5))
                }
    except Exception as e:
        logger.warning(f"[Img2Img Optimizer] LLM 提示词指导失败，使用默认规则: {e}")

    return {
        "positive_prompt": f"masterpiece, best quality, aesthetic, {user_prompt}",
        "negative_prompt": "lowres, bad anatomy, bad hands, blurry, messy hair",
        "denoise": denoise,
        "steps": 32,
        "cfg": 5.5
    }
