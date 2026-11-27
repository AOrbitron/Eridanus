import asyncio
import base64
import hashlib
import io
import json
import os
import random
import re
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Union
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from PIL import Image
import numpy as np

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str
from framework_common.framework_util.reply_config import core_reply_enabled
from framework_common.utils.system_logger import get_logger
from run.ai_generated_art.service.audit_policy import requires_nsfw_audit
from run.ai_generated_art.service.setu_moderate import pic_audit_standalone
logger=get_logger(__name__)
try:
    from run.wardrobe.wardrobe_manager import get_wardrobe_manager
    from run.wardrobe.sd_prompt import ensure_art_anchor
except ImportError:
    get_wardrobe_manager = None
    ensure_art_anchor = None

from run.ai_generated_art.service.prompt_optimizer import (
    build_wardrobe_context,
    clamp_resolution_to_bounds,
    get_llm_config,
    map_aspect_ratio_to_resolution,
    normalize_resolution_bounds,
)

# 预设已知 Illustrious LoRA 映射列表（供 LLM 智能选取、提取与触发词自动注入）
KNOWN_LORAS = [
    {
        "name": "DeniaV1-Nuclear1811-IL.safetensors",
        "keywords": ["deniav1", "nuclear1811", "bot", "自设", "默认画风"],
        "trigger": "",
        "default_strength": 0.3,
        "description": "Illustrious 默认角色/画风平衡 LoRA，推荐权重 0.3"
    },
    {
        "name": "Denia-10.safetensors",
        "keywords": ["denia", "达妮娅", "wuthering waves"],
        "trigger": "Denia",
        "default_strength": 0.8,
        "description": "鸣潮达妮娅 Illustrious 角色 LoRA"
    },
    {
        "name": "lily_illustrious_xl_v2.safetensors",
        "keywords": ["lily", "莉莉", "wuwa_lily", "wuthering waves", "鸣潮"],
        "trigger": "wuwa_lily",
        "default_strength": 0.85,
        "description": "鸣潮莉莉 Illustrious v2.0 角色 LoRA"
    },
    {
        "name": "Chibi.safetensors",
        "keywords": ["chibi", "q版", "Q版", "二头身", "nunyu3", "萌版", "无边框"],
        "trigger": "Chibi, no lineart",
        "default_strength": 0.85,
        "description": "Artist @nunyu3 Q版/Chibi 萌系平涂无描边画风 LoRA"
    },
    {
        "name": "odyk.safetensors",
        "keywords": ["odyk", "jaggy lines", "粗粝线条", "笔触", "手绘粗糙感"],
        "trigger": "odyk, jaggy lines",
        "default_strength": 0.8,
        "description": "Odyk 独特锯齿手绘线条表现力画风 LoRA"
    },
    {
        "name": "detailed hand focus style illustriousXL v1.1.safetensors",
        "keywords": ["hand", "hands", "手部", "牵手", "手指细节", "持物"],
        "trigger": "",
        "default_strength": 0.65,
        "description": "Illustrious XL 精细手部与手指结构增强 LoRA"
    },
    {
        "name": "newPSG_v1.safetensors",
        "keywords": ["吊带袜天使", "panty", "stocking", "psg", "美式卡通", "粗线条", "gradient hair"],
        "trigger": "panty & stocking with garterbelt, gradient hair",
        "default_strength": 0.85,
        "description": "吊带袜天使 v3.0 粗线条复古美式卡通风格 LoRA"
    },
]

# 屏蔽词列表
CENSORED_WORDS = [
    "nsfw", "nipple", "pussy", "areola", "dick", "cameltoe", "ass", "boob",
    "arse", "penis", "porn", "sex", "bitch", "fuck", "blowjob", "handjob",
    "anal", "nude", "vagina", "boner"
]


def extract_and_strip_loras(prompt: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    从 prompt 中提取形如 <lora:filename:strength> 的标签，
    返回清洗后的 prompt 以及提取到的 lora 列表 [{"name": filename, "strength": float}]。
    ComfyUI CLIPTextEncode 无法直接解析 <lora:...> 语法，需提取并清洗文本。
    """
    loras = []

    def _replace(match):
        content = match.group(1).strip()
        parts = content.split(":")
        name = parts[0].strip()
        try:
            strength = float(parts[1]) if len(parts) > 1 else 1.0
        except (ValueError, TypeError):
            strength = 1.0
        loras.append({"name": name, "strength": strength})
        return ""

    cleaned = re.sub(r"<lora:([^>]+)>", _replace, prompt)
    cleaned = re.sub(r",\s*,+", ",", cleaned).strip(" ,")
    return cleaned, loras


def check_censored(positive_prompt: str) -> bool:
    """检查提示词是否包含敏感词"""
    words = positive_prompt.lower().replace(",", " ").split()
    for word in CENSORED_WORDS:
        if word in words:
            return True
    return False


def get_range(input_str: str, offset: int, range_len=4):
    offset = offset % len(input_str)
    return (input_str * 2)[offset:offset + range_len]


def get_sha256(input_str: str):
    hash_object = hashlib.sha256()
    hash_object.update(input_str.encode('utf-8'))
    return hash_object.hexdigest()


def shuffle_arr_v2(arr, key):
    sha_key = get_sha256(key)
    arr_len = len(arr)
    for i in range(arr_len):
        s_idx = arr_len - i - 1
        to_index = int(get_range(sha_key, i, range_len=8), 16) % (arr_len - i)
        arr[s_idx], arr[to_index] = arr[to_index], arr[s_idx]
    return arr


def decrypt_image_v3(image: Image.Image, psw: str):
    width = image.width
    height = image.height
    x_arr = np.arange(width)
    shuffle_arr_v2(x_arr, psw)
    y_arr = np.arange(height)
    shuffle_arr_v2(y_arr, get_sha256(psw))
    pixel_array = np.array(image)

    _pixel_array = pixel_array.copy()
    for x in range(height):
        pixel_array[y_arr[x]] = _pixel_array[x]
    pixel_array = np.transpose(pixel_array, axes=(1, 0, 2))

    _pixel_array = pixel_array.copy()
    for x in range(width):
        pixel_array[x_arr[x]] = _pixel_array[x]
    pixel_array = np.transpose(pixel_array, axes=(1, 0, 2))

    return pixel_array


def decrypt_pixel_shuffle(img_bytes: bytes, password: str = "1234") -> bytes:
    """
    智能还原解密 pixel_shuffle_3 混淆图片：
    1. 优先读取 PNG 元数据 Encrypt 标记；
    2. 若元数据被中转代理剥离，通过相邻像素梯度检测是否为高频随机噪点 (dx > 25)；
    3. 若确认加密，使用密码 sha256 还原矩阵，并校验解密后梯度是否降至自然图像阈值；
    4. 若已经是自然明文图像，绝不重复解密避免损坏。
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as pil_img:
            meta_encrypt = pil_img.info.get("Encrypt", "")
            
            # 检测是否为未解密的噪点图片
            is_encrypted = (meta_encrypt == "pixel_shuffle_3")
            if not is_encrypted:
                arr = np.array(pil_img, dtype=float)
                dx = float(np.abs(np.diff(arr, axis=1)).mean())
                dy = float(np.abs(np.diff(arr, axis=0)).mean())
                if dx > 25.0 and dy > 25.0:
                    is_encrypted = True
            
            if not is_encrypted:
                return img_bytes

            sha_pwd = get_sha256(password)
            dec_arr = decrypt_image_v3(pil_img, sha_pwd)
            
            # 双重验证：解密后的图像梯度必须显著下降（自然图像通常在 3~15）
            dx_dec = float(np.abs(np.diff(dec_arr.astype(float), axis=1)).mean())
            if dx_dec > 25.0:
                logger.warning(f"[ComfyUI] 尝试解密但梯度仍高 ({dx_dec:.2f})，保留原图")
                return img_bytes

            dec_img = Image.fromarray(dec_arr)
            buf = io.BytesIO()
            dec_img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        logger.warning(f"[ComfyUI] 像素解密异常: {e}")
        return img_bytes


def safe_parse_json(resp: httpx.Response) -> Any:
    """安全解析 HTTP 响应为 JSON，兼容 UTF-8、GBK、GB18030、CP936 等多编码，并兼容测试 Mock 响应"""
    content = getattr(resp, "content", None)
    if not isinstance(content, (bytes, bytearray, str)):
        return resp.json()
    if isinstance(content, str):
        return json.loads(content)
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    for enc in ("gb18030", "gbk", "cp936", "latin1"):
        try:
            return json.loads(content.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

    preview = content[:250].decode("utf-8", errors="replace")
    raise RuntimeError(f"服务端响应不是有效 JSON (状态码 {resp.status_code}): {preview}")


async def optimize_prompt_with_llm(
    user_prompt: str,
    config,
    is_about_bot: bool = False,
    wardrobe_ctx: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    实验性功能：调用主回复模型 (gemini-3.8-flash 或 core_reply) 对生图节点和提示词进行智能控制。
    输出标准结构字典：positive_prompt, negative_prompt, width, height, steps, cfg, sampler_name, scheduler, lora_name, lora_strength
    """
    comfy_cfg = config.ai_generated_art.config.get("comfyui", {})
    llm_cfg = get_llm_config(config)
    min_dim = int(comfy_cfg.get("resolution_min", 1100))
    max_dim = int(comfy_cfg.get("resolution_max", 1600))
    min_aligned, max_aligned = normalize_resolution_bounds(min_dim, max_dim)
    rec_v_w, rec_v_h = map_aspect_ratio_to_resolution("3:4", min_dim=min_dim, max_dim=max_dim)
    rec_h_w, rec_h_h = map_aspect_ratio_to_resolution("4:3", min_dim=min_dim, max_dim=max_dim)
    rec_s_w, rec_s_h = map_aspect_ratio_to_resolution("1:1", min_dim=min_dim, max_dim=max_dim)
    def_w, def_h = clamp_resolution_to_bounds(
        int(comfy_cfg.get("default_width", rec_v_w)),
        int(comfy_cfg.get("default_height", rec_v_h)),
        min_dim=min_dim,
        max_dim=max_dim,
    )

    api_key = llm_cfg["apikey"]
    base_url = llm_cfg["base_url"]
    model = llm_cfg["model"]
    temperature = llm_cfg["temperature"]

    lora_desc = "\n".join([
        f"- 文件名: '{item['name']}'，适用关键词: {', '.join(item['keywords'])}，触发词: '{item['trigger']}'"
        for item in KNOWN_LORAS
    ])

    wardrobe_rule = ""
    if is_about_bot and wardrobe_ctx:
        wardrobe_rule = f"""
   【智能选装与衣橱联动】：
   - 当前衣橱着装（{wardrobe_ctx.get('current_outfit_name') or '默认'}）："{wardrobe_ctx.get('current_outfit_tags', '')}"
   - 衣橱可选套装目录（格式：套装名 [分类]: 描述 | tags）：
{wardrobe_ctx.get('wardrobe_catalog') or '（暂无）'}
   - 规则：1) 未指定新服饰时保留当前着装；2) 描述了特定风格/局部特征（如“花嫁”、“荷叶边的日常裙子”等）时，先在目录中按语义匹配最贴合套装并选用其 tags，严格区分 [daily] 日常裙装与 [sleepwear] 睡裙；3) 指定了目录外全新服饰时忽略当前着装并按用户要求输出精准服装 tags，切勿混拼冲突服饰。"""

    system_instruction = f"""你是一个顶级的二次元动漫绘图与 ComfyUI 参数调控专家。你的任务是根据用户的中文或英文绘图要求，控制生成最完美的二次元插画节点参数。
服务端当前搭载 **WAI-NSFW-Illustrious v17.0 (SDXL Illustrious)** 大模型。请遵循以下专业规则：
1. positive_prompt 必须完全转化为纯正、流畅的 **Danbooru 风格英文逗号分隔 tags**（例如 masterpiece, best quality, extremely detailed, 1girl, ...），绝不可包含任何中文或自然语言长段落。
   【核心规范·角色与着装保护】：若输入的提示词中已包含角色外貌锚点（如 grey hair, gradient hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2) 等）或画风与服装设定（如 (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms 等），必须完整严密保留这些核心设定标签，绝不可丢弃或改写！{wardrobe_rule}
2. negative_prompt 给出标准 SDXL/Illustrious 负面标签（需包含多指、多手、多腿、肢体畸形及低画质过滤，如 lowres, bad anatomy, bad hands, extra fingers, too many fingers, extra arms, extra legs, extra limbs, fused fingers, missing fingers, text, error, worst quality, low quality, jpeg artifacts, signature, watermark, blurry）。
3. 比例与尺寸推荐（所有宽高比必须严格在 {min_aligned} 到 {max_aligned} 之间，且为 64 的倍数）：
   - 竖图/全身/立绘：width={rec_v_w}, height={rec_v_h} 或 width={min_aligned}, height={max_aligned}
   - 横图/场景/壁纸：width={rec_h_w}, height={rec_h_h} 或 width={max_aligned}, height={min_aligned}
   - 正方形/头像：width={rec_s_w}, height={rec_s_h}
4. 采样步数 steps 必须自主选在 28~60 之间（推荐 28~35），cfg 推荐 5.0~7.0。
5. 采样器推荐 sampler_name="euler_ancestral", scheduler="normal" 或 "karras"。
6. 检查是否匹配到以下可用 Illustrious LoRA：
{lora_desc}
   - 如果用户需求明确匹配某种风格或角色（例如画莉莉、达妮娅、Q版、Odyk线条、精细手部、吊带袜天使画风），请在 lora_name 中填入对应文件名，lora_strength 填 0.6~0.9，并在 positive_prompt 中加入其专属触发词。
   - 若不匹配任何可用 LoRA，则 lora_name 设为 null，lora_strength 设为 0。

你必须仅输出合法可解析的 JSON 对象，不得输出 markdown 代码块外多余文字：
{{
  "positive_prompt": "masterpiece, extremely detailed, ...",
  "negative_prompt": "lowres, bad anatomy, bad hands, worst quality, low quality, ...",
  "width": 1152,
  "height": 1536,
  "steps": 28,
  "cfg": 5.5,
  "sampler_name": "euler_ancestral",
  "scheduler": "normal",
  "lora_name": null,
  "lora_strength": 0.0
}}"""

    req_messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"用户绘图请求：{user_prompt}"}
    ]

    try:
        if not (base_url and api_key and model):
            raise ValueError("未配置 ComfyUI LLM base_url/apikey/model")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": req_messages,
                    "temperature": temperature
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # 去除可能的 markdown 代码块标记
                json_str = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
                json_str = re.sub(r"\s*```$", "", json_str, flags=re.MULTILINE).strip()
                parsed = json.loads(json_str)

                # 约束 steps 在 28 - 60
                if "steps" in parsed:
                    parsed["steps"] = max(28, min(60, int(parsed["steps"])))
                # 约束尺寸在配置的分辨率区间内且为 64 倍数
                if "width" in parsed and "height" in parsed:
                    parsed["width"], parsed["height"] = clamp_resolution_to_bounds(
                        int(parsed["width"]),
                        int(parsed["height"]),
                        min_dim=min_dim,
                        max_dim=max_dim,
                    )

                return parsed
    except Exception as e:
        print(f"[ComfyUI LLM Control] LLM 智能优化参数失败，回退到默认参数: {e}")

    # 回退到基础默认解析 (尺寸受 resolution_min~resolution_max 约束, 步数 28-60)
    return {
        "positive_prompt": f"masterpiece, best quality, aesthetic, {user_prompt}",
        "negative_prompt": (
            "lowres, bad anatomy, bad proportions, bad hands, poorly drawn hands, mutated hands, malformed hands, "
            "extra fingers, too many fingers, extra digit, fewer digits, missing fingers, fused fingers, "
            "extra arms, extra legs, extra limbs, missing arms, missing legs, fused limbs, worst quality, low quality, blurry"
        ),
        "width": def_w,
        "height": def_h,
        "steps": comfy_cfg.get("default_steps", 32),
        "cfg": comfy_cfg.get("default_cfg", 4.5),
        "sampler_name": comfy_cfg.get("default_sampler", "er_sde"),
        "scheduler": comfy_cfg.get("default_scheduler", "simple"),
        "lora_name": comfy_cfg.get("default_lora", None),
        "lora_strength": comfy_cfg.get("default_lora_strength", 0.9)
    }


# 服务端能力缓存（避免每次生图重复请求服务端模型/节点列表，带 TTL 防陈旧）
_SERVER_CAPABILITIES_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_SERVER_CAPABILITIES_TTL_SECONDS = 300.0
_SERVER_CAPABILITIES_REFRESH_MIN_AGE = 30.0

_QUOTE_CHARS = '"\'“”‘’「」『』《》`'
_INVISIBLE_CHARS = "\u200b\u200c\u200d\ufeff\u00a0\r\n\t"
_MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf")


def sanitize_header_token(raw_token: Any) -> str:
    """
    清洗 ComfyUI API Key / Token：
    - 去除首尾空白、零宽字符、误粘贴的中英文引号（如 “...” / "..." / '...'）；
    - 自动剥离误填写的重复 'Bearer ' 前缀；
    - 校验最终 Token 必须为纯 ASCII，防止 httpx 构造 Authorization 头时抛出晦涩的 UnicodeEncodeError。
    """
    if raw_token is None:
        return ""
    token = str(raw_token)
    strip_set = " " + _INVISIBLE_CHARS + _QUOTE_CHARS
    while True:
        cleaned = token.strip(strip_set)
        if cleaned.lower().startswith("bearer "):
            cleaned = cleaned[7:].strip(strip_set)
        if cleaned == token:
            break
        token = cleaned

    if token and not token.isascii():
        bad_chars = [(idx, ch, f"U+{ord(ch):04X}") for idx, ch in enumerate(token) if ord(ch) >= 128]
        sample = ", ".join(f"第{i + 1}位 '{c}' ({code})" for i, c, code in bad_chars[:3])
        raise ValueError(
            f"ComfyUI apikey 包含非 ASCII 字符（{sample}），HTTP Authorization 请求头仅支持 ASCII 字符。"
            "请检查配置文件中是否混入了中文引号“”或多余中文字符。"
        )
    return token


def parse_comfyui_connection(comfy_cfg: Dict[str, Any]) -> Tuple[str, str]:
    """
    统一解析 ComfyUI 连接地址与鉴权 Token（兼容网关直连与 ComfyUI-Login 插件）：
    - 支持 url / base_url 留尾斜杠或误粘贴 /login 后缀；
    - 支持直接把 ComfyUI-Login 链接写成 http://host:port/?token=xxx（自动提取 token 并还原基础 URL）；
    - 自动清洗 url 与 apikey 首尾误粘贴的中英文引号、空格与 Bearer 前缀。
    """
    strip_set = " " + _INVISIBLE_CHARS + _QUOTE_CHARS
    raw_url = str(comfy_cfg.get("base_url") or comfy_cfg.get("url") or "http://127.0.0.1:7860").strip(strip_set)
    if not raw_url:
        raw_url = "http://127.0.0.1:7860"

    raw_apikey = comfy_cfg.get("apikey") or ""
    query_token = ""

    parts = urlsplit(raw_url)
    if parts.scheme and parts.netloc:
        if parts.query:
            for k, v in parse_qsl(parts.query, keep_blank_values=False):
                if k.strip().lower() in ("token", "apikey", "api_key") and v.strip():
                    query_token = v.strip()
                    break
        clean_path = parts.path.rstrip("/")
        if clean_path.lower().endswith("/login"):
            clean_path = clean_path[:-6].rstrip("/")
        base_url = urlunsplit((parts.scheme, parts.netloc, clean_path, "", "")).rstrip("/")
    else:
        base_url = raw_url.rstrip("/")

    apikey = sanitize_header_token(raw_apikey) if str(raw_apikey or "").strip() else ""
    if not apikey and query_token:
        apikey = sanitize_header_token(query_token)

    return base_url, apikey


def build_comfyui_headers(apikey: str = "", accept: str = "application/json, */*") -> Dict[str, str]:
    """构建符合 ComfyUI / ComfyUI-Login 规范的 HTTP 请求头"""
    clean_key = sanitize_header_token(apikey)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": accept,
    }
    if clean_key:
        headers["Authorization"] = f"Bearer {clean_key}"
    return headers


def _extract_combo_options(node_obj: Any, field_name: str) -> List[str]:
    """从 ComfyUI /object_info 节点定义中提取下拉可选项列表（兼容经典列表格式与 V3 COMBO 格式）"""
    if not isinstance(node_obj, dict):
        return []
    req = node_obj.get("input", {}).get("required", {})
    if not isinstance(req, dict):
        return []
    spec = req.get(field_name)
    if not isinstance(spec, list) or not spec:
        return []
    first = spec[0]
    if isinstance(first, list):
        return [str(x) for x in first if isinstance(x, str)]
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        opts = spec[1].get("options")
        if isinstance(opts, list):
            return [str(x) for x in opts if isinstance(x, str)]
    return []


def _norm_asset_path(name: str) -> str:
    return (name or "").strip().replace("\\", "/").strip("/").casefold()


def _strip_model_ext(path_str: str) -> str:
    low = path_str.casefold()
    for ext in _MODEL_EXTS:
        if low.endswith(ext):
            return path_str[:-len(ext)]
    return path_str


def _collapse_asset_key(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", _strip_model_ext(name).casefold())


def resolve_comfyui_asset_path(
    target_name: str,
    available_items: List[str],
    preferred_subdirs: Optional[List[str]] = None,
) -> Tuple[str, bool]:
    """
    根据 ComfyUI 服务端返回的真实模型/LoRA 列表自动补全子目录与路径分隔符。
    示例：
      - 输入 'waiIllustriousSDXL_v170.safetensors' 或 'waiIllustriousSDXL_v170'
        -> 自动匹配 'Illustrious\\waiIllustriousSDXL_v170.safetensors'
      - 输入 'Illustrious/waiIllustriousSDXL_v170.safetensors'
        -> 自动修正分隔符为服务端真实值 'Illustrious\\waiIllustriousSDXL_v170.safetensors'
      - 输入 '明日方舟/Archetto3outfits'
        -> 自动匹配 'Anima\\人物\\明日方舟\\Archetto3outfits.safetensors'
    返回 (matched_or_original_name, is_matched)。
    """
    if not target_name or not available_items:
        return target_name, False

    raw = str(target_name).strip().strip(_QUOTE_CHARS)
    if not raw:
        return target_name, False

    # 1. 精确一致
    if raw in available_items:
        return raw, True

    norm_q = _norm_asset_path(raw)
    norm_q_no_ext = _strip_model_ext(norm_q)
    base_q = norm_q.rsplit("/", 1)[-1]
    base_q_no_ext = _strip_model_ext(base_q)
    collapsed_q = _collapse_asset_key(base_q)
    pref_tokens = [p.casefold() for p in (preferred_subdirs or []) if p]

    def _pick_best(candidates: List[str]) -> str:
        if len(candidates) == 1:
            return candidates[0]

        def _score(cand: str) -> Tuple[int, int, int, str]:
            norm_c = _norm_asset_path(cand)
            dir_part = norm_c.rsplit("/", 1)[0] if "/" in norm_c else ""
            pref_rank = 1
            if pref_tokens and dir_part:
                dir_segments = dir_part.split("/")
                if any(any(pt in seg for pt in pref_tokens) for seg in dir_segments):
                    pref_rank = 0
            depth = norm_c.count("/")
            return (pref_rank, depth, len(cand), norm_c)

        return min(candidates, key=_score)

    prepared = []
    for cand in available_items:
        if not isinstance(cand, str) or not cand:
            continue
        nc = _norm_asset_path(cand)
        nc_no_ext = _strip_model_ext(nc)
        bc = nc.rsplit("/", 1)[-1]
        bc_no_ext = _strip_model_ext(bc)
        prepared.append((cand, nc, nc_no_ext, bc, bc_no_ext))

    # 2. 路径归一化一致（兼容 / 与 \ 及大小写）
    hits = [c for c, nc, _, _, _ in prepared if nc == norm_q]
    if hits:
        return _pick_best(hits), True

    # 3. 路径归一化一致（忽略后缀名）
    hits = [c for c, _, nc_ne, _, _ in prepared if nc_ne == norm_q_no_ext]
    if hits:
        return _pick_best(hits), True

    # 4. 子路径后缀匹配（如用户写了 '明日方舟/Archetto3outfits'）
    if "/" in norm_q:
        hits = [
            c for c, nc, nc_ne, _, _ in prepared
            if nc.endswith("/" + norm_q) or nc_ne.endswith("/" + norm_q_no_ext)
        ]
        if hits:
            return _pick_best(hits), True

    # 5. 文件名精确匹配（含后缀）
    hits = [c for c, _, _, bc, _ in prepared if bc == base_q]
    if hits:
        return _pick_best(hits), True

    # 6. 文件名去后缀精确匹配（如 waiIllustriousSDXL_v170 -> Illustrious\waiIllustriousSDXL_v170.safetensors）
    hits = [c for c, _, _, _, bc_ne in prepared if bc_ne == base_q_no_ext]
    if hits:
        return _pick_best(hits), True

    # 7. 忽略分隔符（空格/下划线/连字符）后的文件名精确匹配
    if len(collapsed_q) >= 4:
        hits = [c for c, _, _, _, bc_ne in prepared if _collapse_asset_key(bc_ne) == collapsed_q]
        if hits:
            return _pick_best(hits), True

    # 8. 唯一无歧义子串匹配（仅针对长度 >= 4 且仅命中唯一候选时启用，避免误匹配无关模型）
    if len(base_q_no_ext) >= 4:
        hits = [c for c, _, _, _, bc_ne in prepared if base_q_no_ext in bc_ne]
        if len(hits) == 1:
            return hits[0], True
        if len(hits) > 1 and pref_tokens:
            pref_hits = [
                c for c in hits
                if "/" in _norm_asset_path(c)
                and any(pt in _norm_asset_path(c).rsplit("/", 1)[0] for pt in pref_tokens)
            ]
            if len(pref_hits) == 1:
                return pref_hits[0], True

    return target_name, False


async def get_server_capabilities(
    base_url: str,
    apikey: str = "",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    查询并缓存 ComfyUI 服务端已安装节点、调度器与可用模型/LoRA 列表。
    优先并发请求轻量级单节点 /object_info/{node}（总计仅数十 KB，避免下载数十 MB 的全量 /object_info 超时），
    并在不支持单节点查询的网关上自动降级到 /models/{folder} 或全量 /object_info。
    """
    clean_url, clean_key = parse_comfyui_connection({"base_url": base_url, "apikey": apikey})
    key_sig = hashlib.sha256(clean_key.encode("ascii")).hexdigest()[:12] if clean_key else ""
    cache_key = (clean_url, key_sig)

    now = time.monotonic()
    cached = _SERVER_CAPABILITIES_CACHE.get(cache_key)
    if not force_refresh and cached and (now - cached["ts"]) < _SERVER_CAPABILITIES_TTL_SECONDS:
        return cached["caps"]

    caps: Dict[str, Any] = {
        "has_teacache": False,
        "has_easycache": False,
        "has_remap_lora": False,
        "has_beta57": False,
        "available_ckpts": [],
        "available_unets": [],
        "available_loras": [],
        "available_clips": [],
        "available_vaes": [],
        "_fetched_at": now,
    }
    headers = build_comfyui_headers(clean_key)
    probe_ok = False

    def _populate_from_object_info(info: Dict[str, Any]) -> None:
        if "AnimaTeaCache" in info:
            caps["has_teacache"] = True
        if "EasyCache" in info:
            caps["has_easycache"] = True
        if "AnimaLoRARemapTagLoader" in info:
            caps["has_remap_lora"] = True
        if "KSampler" in info:
            sched_list = _extract_combo_options(info.get("KSampler"), "scheduler")
            if sched_list:
                caps["has_beta57"] = "beta57" in sched_list
        if "CheckpointLoaderSimple" in info:
            ckpts = _extract_combo_options(info.get("CheckpointLoaderSimple"), "ckpt_name")
            if ckpts:
                caps["available_ckpts"] = ckpts
        if "UNETLoader" in info:
            unets = _extract_combo_options(info.get("UNETLoader"), "unet_name")
            if unets:
                caps["available_unets"] = unets
        if "LoraLoader" in info:
            loras = _extract_combo_options(info.get("LoraLoader"), "lora_name")
            if loras:
                caps["available_loras"] = loras
        if "CLIPLoader" in info:
            clips = _extract_combo_options(info.get("CLIPLoader"), "clip_name")
            if clips:
                caps["available_clips"] = clips
        if "VAELoader" in info:
            vaes = _extract_combo_options(info.get("VAELoader"), "vae_name")
            if vaes:
                caps["available_vaes"] = vaes

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers, verify=False) as client:
            sem = asyncio.Semaphore(4)

            async def _fetch_node(node_name: str) -> Optional[Dict[str, Any]]:
                async with sem:
                    for attempt in range(2):
                        try:
                            r = await client.get(f"{clean_url}/object_info/{node_name}")
                            if r.status_code == 200:
                                parsed = safe_parse_json(r)
                                if isinstance(parsed, dict) and node_name in parsed:
                                    return parsed
                                return None
                            if r.status_code in (401, 403, 404):
                                return None
                        except Exception:
                            pass
                        if attempt == 0:
                            await asyncio.sleep(0.3)
                return None

            target_nodes = [
                "CheckpointLoaderSimple",
                "UNETLoader",
                "LoraLoader",
                "CLIPLoader",
                "VAELoader",
                "KSampler",
                "AnimaTeaCache",
                "EasyCache",
                "AnimaLoRARemapTagLoader",
            ]
            node_results = await asyncio.gather(*(_fetch_node(n) for n in target_nodes))
            for nr in node_results:
                if isinstance(nr, dict) and nr:
                    probe_ok = True
                    _populate_from_object_info(nr)

            # 降级 1：针对未通过 /object_info/{node} 获取到的模型分类，按需补查轻量 /models/{folder} 接口
            missing_folders = [
                (cap_key, folder)
                for cap_key, folder in (
                    ("available_ckpts", "checkpoints"),
                    ("available_unets", "diffusion_models"),
                    ("available_loras", "loras"),
                    ("available_clips", "text_encoders"),
                    ("available_vaes", "vae"),
                )
                if not caps[cap_key]
            ]
            if missing_folders:
                async def _fetch_models(folder: str) -> List[str]:
                    async with sem:
                        try:
                            r = await client.get(f"{clean_url}/models/{folder}")
                            if r.status_code == 200:
                                parsed = safe_parse_json(r)
                                if isinstance(parsed, list):
                                    return [str(x) for x in parsed if isinstance(x, str)]
                        except Exception:
                            pass
                    return []

                folder_results = await asyncio.gather(*(_fetch_models(folder) for _, folder in missing_folders))
                for (cap_key, _), items in zip(missing_folders, folder_results):
                    if items:
                        caps[cap_key] = items
                        probe_ok = True

            # 降级 2：兼容仅暴露全量 /object_info 的旧版服务或测试 Mock
            if not probe_ok:
                resp = await client.get(f"{clean_url}/object_info", timeout=25.0)
                if resp.status_code == 200:
                    info = safe_parse_json(resp)
                    if isinstance(info, dict) and info:
                        probe_ok = True
                        _populate_from_object_info(info)
    except Exception as e:
        logger.debug(f"[ComfyUI] 探测服务端能力失败 ({clean_url}): {e}")

    if probe_ok:
        _SERVER_CAPABILITIES_CACHE[cache_key] = {"ts": now, "caps": caps}
    return caps


async def _resolve_workflow_assets(
    base_url: str,
    apikey: str,
    ckpt: str,
    clip: str,
    vae: str,
    active_loras: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str, str, str, List[Dict[str, Any]], bool]:
    """
    结合 ComfyUI 服务端实际文件目录，自动补全底模 (ckpt/unet)、CLIP、VAE 与 LoRA 的完整子目录路径。
    - 例如配置 'waiIllustriousSDXL_v170.safetensors' -> 自动解析为 'Illustrious\\waiIllustriousSDXL_v170.safetensors'；
    - 自动识别模型实际位于 checkpoints 还是 diffusion_models/unet；
    - 若服务端已返回可用 LoRA 列表但某个自动注入/配置的 LoRA 不存在，则记录告警并跳过，避免整个工作流因单个缺失 LoRA 报错。
    """
    caps = await get_server_capabilities(base_url, apikey=apikey)

    def _do_resolve(c: Dict[str, Any]) -> Tuple[str, bool, bool, str, str, List[Dict[str, Any]]]:
        avail_ckpts = c.get("available_ckpts") or []
        avail_unets = c.get("available_unets") or []
        avail_loras = c.get("available_loras") or []
        avail_clips = c.get("available_clips") or []
        avail_vaes = c.get("available_vaes") or []

        is_anima = _is_anima_model(ckpt)
        resolved_ckpt = ckpt
        ckpt_matched = False

        if is_anima:
            if avail_unets:
                resolved_ckpt, ckpt_matched = resolve_comfyui_asset_path(
                    ckpt, avail_unets, preferred_subdirs=["anima"]
                )
            if not ckpt_matched and avail_ckpts:
                alt_ckpt, alt_ok = resolve_comfyui_asset_path(
                    ckpt, avail_ckpts, preferred_subdirs=["anima", "illustrious", "noob"]
                )
                if alt_ok:
                    resolved_ckpt = alt_ckpt
                    ckpt_matched = True
                    is_anima = False
        else:
            if avail_ckpts:
                resolved_ckpt, ckpt_matched = resolve_comfyui_asset_path(
                    ckpt, avail_ckpts, preferred_subdirs=["illustrious", "il", "noob", "sdxl"]
                )
            if not ckpt_matched and avail_unets:
                alt_unet, alt_ok = resolve_comfyui_asset_path(
                    ckpt, avail_unets, preferred_subdirs=["anima", "illustrious"]
                )
                if alt_ok:
                    resolved_ckpt = alt_unet
                    ckpt_matched = True
                    is_anima = True

        resolved_clip = clip
        resolved_vae = vae
        if is_anima:
            if avail_clips and clip:
                resolved_clip, _ = resolve_comfyui_asset_path(clip, avail_clips)
            if avail_vaes and vae:
                resolved_vae, _ = resolve_comfyui_asset_path(vae, avail_vaes)

        lora_pref = ["anima"] if is_anima else ["illustrious", "il", "sdxl", "noob"]
        resolved_loras: List[Dict[str, Any]] = []
        lora_renames: List[Tuple[str, str]] = []
        seen_loras = set()
        for l_item in active_loras:
            raw_ln = str(l_item.get("name") or "").strip()
            if not raw_ln:
                continue
            strength = float(l_item.get("strength", 0.8))
            if avail_loras:
                final_ln, ok = resolve_comfyui_asset_path(raw_ln, avail_loras, preferred_subdirs=lora_pref)
                if not ok:
                    logger.warning(f"[ComfyUI] 服务端未找到 LoRA '{raw_ln}'，已自动跳过加载")
                    continue
                if final_ln != raw_ln:
                    lora_renames.append((raw_ln, final_ln))
            else:
                final_ln = raw_ln
            norm_key = _norm_asset_path(final_ln)
            if norm_key not in seen_loras:
                seen_loras.add(norm_key)
                resolved_loras.append({"name": final_ln, "strength": strength})

        return resolved_ckpt, ckpt_matched, is_anima, resolved_clip, resolved_vae, resolved_loras, lora_renames

    resolved_ckpt, ckpt_matched, is_anima, resolved_clip, resolved_vae, resolved_loras, lora_renames = _do_resolve(caps)

    # 若底模在缓存列表中未命中且缓存距今超过 30 秒，主动刷新一次列表（兼容用户刚往服务器拷入新模型）
    has_model_catalog = bool(caps.get("available_ckpts") or caps.get("available_unets"))
    cache_age = time.monotonic() - float(caps.get("_fetched_at", 0.0))
    if has_model_catalog and not ckpt_matched and cache_age >= _SERVER_CAPABILITIES_REFRESH_MIN_AGE:
        caps = await get_server_capabilities(base_url, apikey=apikey, force_refresh=True)
        resolved_ckpt, ckpt_matched, is_anima, resolved_clip, resolved_vae, resolved_loras, lora_renames = _do_resolve(caps)

    if resolved_ckpt != ckpt:
        logger.info(f"[ComfyUI] 自动匹配底模路径: '{ckpt}' -> '{resolved_ckpt}'")
    for orig_ln, res_ln in lora_renames:
        logger.info(f"[ComfyUI] 自动匹配 LoRA 路径: '{orig_ln}' -> '{res_ln}'")

    return caps, resolved_ckpt, resolved_clip, resolved_vae, resolved_loras, is_anima


def _is_anima_model(model_name: str) -> bool:
    """判断目标模型是否为 Anima 拆分 UNet 架构（否则默认视为 Illustrious/SDXL 一体化 Checkpoint）"""
    low = (model_name or "").lower()
    return "anima" in low or "silvermoonmix" in low or "miaomiao" in low


def _attach_lora_nodes(
    prompt_nodes: Dict[str, Any],
    cur_model_ref: List[Any],
    cur_clip_ref: List[Any],
    active_lora_list: List[Dict[str, Any]],
    use_remap_lora: bool = False,
    is_29b: bool = False,
) -> Tuple[List[Any], List[Any]]:
    """在 ComfyUI 工作流节点图中链式串联一个或多个 LoraLoader（兼容 2.9B AnimaLoRARemapTagLoader）"""
    if use_remap_lora and is_29b and active_lora_list:
        tag_text = " ".join(
            f"<lora:{l_item['name'].replace('.safetensors', '')}:{float(l_item.get('strength', 0.8))}>,"
            for l_item in active_lora_list if l_item.get("name")
        )
        prompt_nodes["92"] = {
            "inputs": {
                "text": tag_text,
                "default_weight": 1,
                "weight_multiplier": 1,
                "auto_remap": True,
                "save_remapped": False,
                "extend_to_new_layers": False,
                "extend_strength": 0.5,
                "manifest": "Auto (Recommended)",
                "model": cur_model_ref,
                "clip": cur_clip_ref
            },
            "class_type": "AnimaLoRARemapTagLoader"
        }
        return ["92", 0], ["92", 1]

    for idx, l_item in enumerate(active_lora_list):
        ln = l_item.get("name")
        ls = float(l_item.get("strength", 0.8))
        if not ln:
            continue
        node_key = "5" if idx == 0 else str(50 + idx)
        prompt_nodes[node_key] = {
            "inputs": {
                "model": cur_model_ref,
                "clip": cur_clip_ref,
                "lora_name": ln,
                "strength_model": ls,
                "strength_clip": ls
            },
            "class_type": "LoraLoader"
        }
        cur_model_ref = [node_key, 0]
        cur_clip_ref = [node_key, 1]
    return cur_model_ref, cur_clip_ref


def build_illustrious_workflow(
    positive_prompt: str,
    negative_prompt: str,
    width: int = 1280,
    height: int = 1728,
    seed: int = -1,
    steps: int = 28,
    cfg: float = 5.5,
    sampler_name: str = "euler_ancestral",
    scheduler: str = "normal",
    ckpt_name: Optional[str] = None,
    unet_name: str = "waiIllustriousSDXL_v170.safetensors",
    clip_name: str = "qwen_3_06b_base.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    clip_skip: int = -2,
    lora_name: Optional[str] = None,
    lora_strength: float = 0.8,
    loras: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "ComfyUI_Illustrious",
    hires_fix: bool = False,
    hires_scale: float = 1.333,
    hires_denoise: float = 0.38,
    hires_steps: int = 15,
    cache_type: Optional[str] = None,
    teacache_thresh: float = 0.35,
    use_remap_lora: bool = False,
    force_is_anima: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    构建 ComfyUI API Prompt 节点图（默认 Illustrious/SDXL CheckpointLoaderSimple 架构；
    若传入 Anima 系列模型名则自动兼容切换 UNETLoader 架构）。
    """
    if seed == -1:
        seed = random.randint(1, 10**14)

    target_model = ckpt_name or unet_name
    is_anima = _is_anima_model(target_model) if force_is_anima is None else bool(force_is_anima)
    is_29b = is_anima and ("29b" in target_model.lower() or "2.9b" in target_model.lower())

    prompt_nodes: Dict[str, Any] = {}
    if is_anima:
        prompt_nodes["1"] = {
            "inputs": {"unet_name": target_model, "weight_dtype": "default"},
            "class_type": "UNETLoader"
        }
        prompt_nodes["2"] = {
            "inputs": {"clip_name": clip_name, "type": "stable_diffusion", "device": "default"},
            "class_type": "CLIPLoader"
        }
        prompt_nodes["3"] = {
            "inputs": {"vae_name": vae_name},
            "class_type": "VAELoader"
        }
        cur_model_ref = ["1", 0]
        cur_clip_ref = ["2", 0]
        vae_ref = ["3", 0]
        if not is_29b:
            prompt_nodes["4"] = {
                "inputs": {"model": cur_model_ref, "shift": 3.0},
                "class_type": "ModelSamplingAuraFlow"
            }
            cur_model_ref = ["4", 0]
    else:
        prompt_nodes["1"] = {
            "inputs": {"ckpt_name": target_model},
            "class_type": "CheckpointLoaderSimple"
        }
        prompt_nodes["4"] = {
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": int(clip_skip)},
            "class_type": "CLIPSetLastLayer"
        }
        cur_model_ref = ["1", 0]
        cur_clip_ref = ["4", 0]
        vae_ref = ["1", 2]

    if cache_type == "AnimaTeaCache":
        prompt_nodes["88"] = {
            "inputs": {
                "rel_l1_thresh": float(teacache_thresh),
                "start_percent": 0,
                "end_percent": 1,
                "cache_device": "cuda",
                "model": cur_model_ref
            },
            "class_type": "AnimaTeaCache"
        }
        cur_model_ref = ["88", 0]
    elif cache_type == "EasyCache":
        prompt_nodes["88"] = {
            "inputs": {
                "model": cur_model_ref,
                "reuse_threshold": 0.2,
                "start_percent": 0.15,
                "end_percent": 0.95,
                "verbose": False
            },
            "class_type": "EasyCache"
        }
        cur_model_ref = ["88", 0]

    active_lora_list = []
    if loras:
        active_lora_list.extend(loras)
    elif lora_name:
        active_lora_list.append({"name": lora_name, "strength": float(lora_strength)})

    model_ref, clip_ref = _attach_lora_nodes(
        prompt_nodes, cur_model_ref, cur_clip_ref, active_lora_list, use_remap_lora=use_remap_lora, is_29b=is_29b
    )

    prompt_nodes["6"] = {
        "inputs": {"text": positive_prompt, "clip": clip_ref},
        "class_type": "CLIPTextEncode"
    }
    prompt_nodes["7"] = {
        "inputs": {"text": negative_prompt, "clip": clip_ref},
        "class_type": "CLIPTextEncode"
    }

    if hires_fix:
        base_w = int(round(width / hires_scale / 64) * 64)
        base_h = int(round(height / hires_scale / 64) * 64)
        prompt_nodes["8"] = {
            "inputs": {"width": base_w, "height": base_h, "batch_size": 1},
            "class_type": "EmptyLatentImage"
        }
        prompt_nodes["9"] = {
            "inputs": {
                "seed": seed, "steps": int(steps), "cfg": float(cfg),
                "sampler_name": sampler_name, "scheduler": scheduler, "denoise": 1.0,
                "model": model_ref, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["85"] = {
            "inputs": {
                "samples": ["9", 0], "upscale_method": "bicubic",
                "width": int(width), "height": int(height), "crop": "disabled"
            },
            "class_type": "LatentUpscale"
        }
        prompt_nodes["95"] = {
            "inputs": {
                "seed": seed + 1, "steps": int(hires_steps), "cfg": float(cfg),
                "sampler_name": sampler_name, "scheduler": scheduler, "denoise": float(hires_denoise),
                "model": model_ref, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["85", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["10"] = {
            "inputs": {"samples": ["95", 0], "vae": vae_ref},
            "class_type": "VAEDecode"
        }
    else:
        prompt_nodes["8"] = {
            "inputs": {"width": int(width), "height": int(height), "batch_size": 1},
            "class_type": "EmptyLatentImage"
        }
        prompt_nodes["9"] = {
            "inputs": {
                "seed": seed, "steps": int(steps), "cfg": float(cfg),
                "sampler_name": sampler_name, "scheduler": scheduler, "denoise": 1.0,
                "model": model_ref, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["10"] = {
            "inputs": {"samples": ["9", 0], "vae": vae_ref},
            "class_type": "VAEDecode"
        }

    prompt_nodes["11"] = {
        "inputs": {"images": ["10", 0]},
        "class_type": "PreviewImage"
    }

    return prompt_nodes


# 向后兼容旧导入名称
build_anima_workflow = build_illustrious_workflow


def build_comfyui_img2img_workflow(
    image_name: str,
    positive_prompt: str,
    negative_prompt: str,
    denoise: float = 0.65,
    seed: int = -1,
    steps: int = 28,
    cfg: float = 5.5,
    sampler_name: str = "euler_ancestral",
    scheduler: str = "normal",
    ckpt_name: Optional[str] = None,
    unet_name: str = "waiIllustriousSDXL_v170.safetensors",
    clip_name: str = "qwen_3_06b_base.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    clip_skip: int = -2,
    loras: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "ComfyUI_Img2Img",
    force_is_anima: Optional[bool] = None,
) -> Dict[str, Any]:
    """构建标准 ComfyUI 以图生图 (img2img) 节点工作流（兼容 Illustrious Checkpoint 与 Anima 架构）"""
    if seed == -1:
        seed = random.randint(1, 10**14)

    target_model = ckpt_name or unet_name
    is_anima = _is_anima_model(target_model) if force_is_anima is None else bool(force_is_anima)

    prompt_nodes: Dict[str, Any] = {}
    if is_anima:
        prompt_nodes["1"] = {
            "inputs": {"unet_name": target_model, "weight_dtype": "default"},
            "class_type": "UNETLoader"
        }
        prompt_nodes["2"] = {
            "inputs": {"clip_name": clip_name, "type": "stable_diffusion", "device": "default"},
            "class_type": "CLIPLoader"
        }
        prompt_nodes["3"] = {
            "inputs": {"vae_name": vae_name},
            "class_type": "VAELoader"
        }
        prompt_nodes["4"] = {
            "inputs": {"model": ["1", 0], "shift": 3.0},
            "class_type": "ModelSamplingAuraFlow"
        }
        cur_model_ref = ["4", 0]
        cur_clip_ref = ["2", 0]
        vae_ref = ["3", 0]
    else:
        prompt_nodes["1"] = {
            "inputs": {"ckpt_name": target_model},
            "class_type": "CheckpointLoaderSimple"
        }
        prompt_nodes["4"] = {
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": int(clip_skip)},
            "class_type": "CLIPSetLastLayer"
        }
        cur_model_ref = ["1", 0]
        cur_clip_ref = ["4", 0]
        vae_ref = ["1", 2]

    cur_model_ref, cur_clip_ref = _attach_lora_nodes(
        prompt_nodes, cur_model_ref, cur_clip_ref, loras or []
    )

    prompt_nodes["6"] = {
        "inputs": {"text": positive_prompt, "clip": cur_clip_ref},
        "class_type": "CLIPTextEncode"
    }
    prompt_nodes["7"] = {
        "inputs": {"text": negative_prompt, "clip": cur_clip_ref},
        "class_type": "CLIPTextEncode"
    }
    prompt_nodes["8"] = {
        "inputs": {"image": image_name},
        "class_type": "LoadImage"
    }
    prompt_nodes["81"] = {
        "inputs": {"pixels": ["8", 0], "vae": vae_ref},
        "class_type": "VAEEncode"
    }
    prompt_nodes["9"] = {
        "inputs": {
            "seed": seed, "steps": int(steps), "cfg": float(cfg),
            "sampler_name": sampler_name, "scheduler": scheduler, "denoise": float(denoise),
            "model": cur_model_ref, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["81", 0]
        },
        "class_type": "KSampler"
    }
    prompt_nodes["10"] = {
        "inputs": {"samples": ["9", 0], "vae": vae_ref},
        "class_type": "VAEDecode"
    }
    prompt_nodes["11"] = {
        "inputs": {"images": ["10", 0]},
        "class_type": "PreviewImage"
    }

    return prompt_nodes


async def upload_image_to_comfyui(
    img_source: Union[bytes, str, Path],
    base_url: str,
    apikey: str = "",
) -> str:
    """
    将图片上传至 ComfyUI 服务端的 /upload/image 接口，返回已上传的图片名称。
    支持输入本地路径、URL 或原始 bytes。
    """
    if isinstance(img_source, (str, Path)) and os.path.exists(str(img_source)):
        with open(str(img_source), "rb") as f:
            raw_bytes = f.read()
        filename = f"upload_{os.path.basename(str(img_source))}"
    elif isinstance(img_source, str) and (img_source.startswith("http://") or img_source.startswith("https://")):
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(img_source)
            raw_bytes = resp.content
        filename = f"upload_{random_str(8)}.png"
    elif isinstance(img_source, bytes):
        raw_bytes = img_source
        filename = f"upload_{random_str(8)}.png"
    else:
        raise ValueError(f"无法识别的图片来源: {type(img_source)}")

    clean_url, clean_key = parse_comfyui_connection({"base_url": base_url, "apikey": apikey})
    upload_url = f"{clean_url}/upload/image"
    files = {"image": (filename, raw_bytes, "image/png")}
    data = {"overwrite": "true", "subfolder": "", "type": "input"}

    client_headers = build_comfyui_headers(clean_key)

    async with httpx.AsyncClient(timeout=30.0, headers=client_headers, verify=False) as client:
        resp = await client.post(upload_url, files=files, data=data)
        if resp.status_code == 200:
            res_data = safe_parse_json(resp)
            return res_data.get("name", filename)
        else:
            raise RuntimeError(f"上传图片至 ComfyUI 失败 ({resp.status_code}): {resp.text}")


async def comfyui_draw(
    prompt: str,
    config,
    groupid: Optional[int] = None,
    args: Optional[Dict[str, Any]] = None,
    is_about_bot: bool = False
) -> Optional[str]:
    """
    ComfyUI 生图核心入口：
    1. 检查权限与敏感词审计
    2. 支持主模型控制生图 (LLM Parameter Controller)
    3. 提交任务至 ComfyUI HTTP API 并等待完成
    4. 自动处理下载及 pixel_shuffle 图像解密
    5. 返回保存后的本地图片路径
    """
    draw_cfg = config.ai_generated_art.config.get("ai绘画", {})
    comfy_cfg = config.ai_generated_art.config.get("comfyui", {})

    base_url, apikey = parse_comfyui_connection(comfy_cfg)
    timeout = float(comfy_cfg.get("timeout", 300))
    llm_control = comfy_cfg.get("主模型控制生图", False)

    # 尺寸与默认参数 (受 resolution_min ~ resolution_max 约束，按比例自适应)
    min_dim = int(comfy_cfg.get("resolution_min", 1100))
    max_dim = int(comfy_cfg.get("resolution_max", 1600))
    width, height = clamp_resolution_to_bounds(
        int(comfy_cfg.get("default_width", 1152)),
        int(comfy_cfg.get("default_height", 1536)),
        min_dim=min_dim,
        max_dim=max_dim,
    )

    # 动态解析画幅比例 (aspect_ratio)
    ar = None
    if args and isinstance(args, dict):
        ar = args.get("aspect_ratio") or args.get("ar")
    if not ar and comfy_cfg.get("aspect_ratio"):
        ar = comfy_cfg.get("aspect_ratio")

    if ar:
        width, height = map_aspect_ratio_to_resolution(
            ar,
            default_w=width,
            default_h=height,
            min_dim=min_dim,
            max_dim=max_dim,
        )

    steps = comfy_cfg.get("default_steps", 28)
    cfg_val = comfy_cfg.get("default_cfg", 5.5)
    sampler = comfy_cfg.get("default_sampler", "euler_ancestral")
    scheduler = comfy_cfg.get("default_scheduler", "normal")
    ckpt = comfy_cfg.get("default_ckpt") or comfy_cfg.get("default_unet", "waiIllustriousSDXL_v170.safetensors")
    clip_skip = int(comfy_cfg.get("clip_skip", -2))
    clip = comfy_cfg.get("default_clip", "qwen_3_06b_base.safetensors")
    vae = comfy_cfg.get("default_vae", "qwen_image_vae.safetensors")
    lora = comfy_cfg.get("default_lora", None)
    lora_strength = comfy_cfg.get("default_lora_strength", 0.3)

    if args and isinstance(args, dict):
        if args.get("width"):
            width = int(args["width"])
        if args.get("height"):
            height = int(args["height"])
        if args.get("steps"):
            steps = int(args["steps"])
        if args.get("cfg"):
            cfg_val = float(args["cfg"])
        if args.get("ckpt") or args.get("unet"):
            ckpt = str(args.get("ckpt") or args.get("unet"))
        if args.get("clip_skip") is not None:
            clip_skip = int(args["clip_skip"])
        if args.get("sampler"):
            sampler = str(args["sampler"])
        if args.get("scheduler"):
            scheduler = str(args["scheduler"])

    # 接入衣橱系统 (WardrobeManager) 读取角色外观基础锚点、当前服装穿搭、艺术锚点及标准负面提示词
    wm = get_wardrobe_manager() if get_wardrobe_manager else None

    # 1. 负面提示词：优先支持外部指定，其次接入 Wardrobe 配置的权威 negative_prompt，最后回退默认
    if args and isinstance(args, dict) and (args.get("negative_prompt") or args.get("n")):
        negative_prompt = str(args.get("negative_prompt") or args.get("n"))
    elif wm:
        negative_prompt = wm.get_negative_prompt()
    else:
        negative_prompt = comfy_cfg.get(
            "default_negative_prompt",
            "lowres, bad anatomy, bad proportions, bad hands, poorly drawn hands, mutated hands, malformed hands, "
            "extra fingers, too many fingers, extra digit, fewer digits, missing fingers, fused fingers, "
            "extra arms, extra legs, extra limbs, missing arms, missing legs, fused limbs, malformed limbs, "
            "disconnected limbs, floating limbs, long neck, poorly drawn face, asymmetric eyes, cross-eyed, "
            "duplicate, clone, multiple views, text, error, cropped, worst quality, low quality, normal quality, "
            "jpeg artifacts, scan artifacts, film grain, chromatic aberration, signature, watermark, username, logo, dated, blurry, out of focus"
        )

    # 2. 正向提示词装配与衣橱联动
    positive_prompt = prompt
    wm_ctx = build_wardrobe_context(wm, is_about_bot=is_about_bot) if wm else None

    if is_about_bot:
        if wm:
            char_anchor = wm.get_character_anchor()
            outfit_info = wm.get_current_outfit()
            outfit_tags = outfit_info.get("clothing_tags", "")
            art_anchor = wm.get_art_anchor()
        else:
            bot_name = config.common_config.basic_config.get("bot", "Bot")
            char_anchor = config.ai_generated_art.config.get("gptimage2", {}).get("character_anchor", "")
            outfit_tags = ""
            art_anchor = None

        # 仅在未开启主模型控制时使用本地启发式防冲突；开启主模型控制时保留完整衣橱上下文交由 LLM 语义选装
        if not llm_control:
            # 优先尝试直接命中衣橱套装名
            matched_catalog_tags = ""
            if wm and hasattr(wm, "get_outfits"):
                prompt_cf = positive_prompt.casefold()
                for o_key, o_obj in (wm.get_outfits() or {}).items():
                    if o_key and o_key.casefold() in prompt_cf and isinstance(o_obj, dict) and o_obj.get("clothing_tags"):
                        matched_catalog_tags = o_obj["clothing_tags"]
                        break
            if matched_catalog_tags:
                outfit_tags = matched_catalog_tags
            else:
                has_custom_clothing = any(
                    kw in positive_prompt.lower()
                    for kw in [
                        "睡裙", "睡衣", "nightgown", "pajama", "sleepwear", "吊带裙", "泳装", "比基尼", "swimsuit",
                        "bikini", "礼服", "dress", "旗袍", "汉服", "制服", "uniform", "cosplay", "lo裙", "lolita",
                        "hoodie", "卫衣", "水手服", "汉元素", "洋装", "jacket", "skirt"
                    ]
                )
                if has_custom_clothing:
                    outfit_tags = ""

        # 避免提示词中重复包含角色基础锚点或当前服装
        components = []
        if char_anchor and char_anchor[:25].lower() not in positive_prompt.lower():
            components.append(char_anchor)
        if outfit_tags and outfit_tags[:25].lower() not in positive_prompt.lower():
            components.append(outfit_tags)
        components.append(positive_prompt)
        positive_prompt = ", ".join(c.strip(" ,") for c in components if c and c.strip(" ,"))

        if ensure_art_anchor and art_anchor:
            positive_prompt = ensure_art_anchor(positive_prompt, art_anchor)
    else:
        # 非特定 bot 自拍，依然与 SD 保持一致接入通用艺术画风锚点（若启用）
        if wm and ensure_art_anchor and comfy_cfg.get("always_apply_art_anchor", True):
            art_anchor = wm.get_art_anchor()
            if art_anchor:
                positive_prompt = ensure_art_anchor(positive_prompt, art_anchor)

    # 3. 链式多 LoRA 列表装配与纯文本净化 (兼容单一 LoRA、配置文件 fixed_loras、art_anchor/prompt 提取及 LLM 选取)
    active_loras: List[Dict[str, Any]] = []

    # 3.1 载入配置文件中设置的 fixed_loras (支持多个固定 LoRA 串联加载)
    fixed_loras = comfy_cfg.get("fixed_loras", [])
    if isinstance(fixed_loras, list):
        for fl in fixed_loras:
            if isinstance(fl, dict) and fl.get("name"):
                active_loras.append({
                    "name": fl["name"],
                    "strength": float(fl.get("strength", 0.8))
                })
                # 自动将该固定 LoRA 的触发词注入正面提示词
                fl_trigger = fl.get("trigger")
                if fl_trigger and fl_trigger.lower() not in positive_prompt.lower():
                    positive_prompt = f"{positive_prompt}, {fl_trigger}"

    # 3.2 提取 prompt/art_anchor 中的形如 <lora:name:strength>，剥离角度括号以防污染 CLIP 编码器
    positive_prompt, extracted_loras = extract_and_strip_loras(positive_prompt)
    for l_item in extracted_loras:
        raw_name = l_item["name"]
        matched_item = None
        for kl in KNOWN_LORAS:
            if raw_name.lower() in kl["name"].lower() or any(kw.lower() in raw_name.lower() for kw in kl.get("keywords", [])):
                matched_item = kl
                break
        if matched_item:
            cand_name = matched_item["name"]
            cand_trigger = matched_item.get("trigger", "")
        else:
            cand_name = raw_name if raw_name.endswith(".safetensors") else f"{raw_name}.safetensors"
            cand_trigger = ""

        # 避免重复加入相同 LoRA
        if not any(a["name"] == cand_name for a in active_loras):
            active_loras.append({"name": cand_name, "strength": l_item["strength"]})
            # 若包含专属触发词且提示词中未包含，自动合并触发词
            if cand_trigger and cand_trigger.split(",")[0].strip().lower() not in positive_prompt.lower():
                positive_prompt = f"{positive_prompt}, {cand_trigger}"

    # 3.3 实验性功能：主回复模型控制生图
    if llm_control:
        try:
            optimized = await optimize_prompt_with_llm(
                positive_prompt,
                config,
                is_about_bot=is_about_bot,
                wardrobe_ctx=wm_ctx,
            )
            positive_prompt = optimized.get("positive_prompt", positive_prompt)
            opt_neg = optimized.get("negative_prompt", "")
            # 始终保留衣橱系统的防畸变/防角/防兽耳核心负面约束，防止 LLM 覆盖丢失
            if opt_neg and negative_prompt:
                negative_prompt = f"{negative_prompt}, {opt_neg}"
            elif opt_neg:
                negative_prompt = opt_neg
            if "width" in optimized:
                width, _ = clamp_resolution_to_bounds(int(optimized["width"]), height, min_dim=min_dim, max_dim=max_dim)
            if "height" in optimized:
                _, height = clamp_resolution_to_bounds(width, int(optimized["height"]), min_dim=min_dim, max_dim=max_dim)
            if "steps" in optimized:
                steps = max(28, min(60, int(optimized["steps"])))
            cfg_val = optimized.get("cfg", cfg_val)
            sampler = optimized.get("sampler_name", sampler)
            scheduler = optimized.get("scheduler", scheduler)
            if optimized.get("lora_name"):
                opt_l_name = optimized["lora_name"]
                opt_l_str = optimized.get("lora_strength", 0.8)
                # 查找是否匹配已知 LoRA 并注入专属触发词
                matched_opt = next((kl for kl in KNOWN_LORAS if opt_l_name.lower() in kl["name"].lower()), None)
                if matched_opt:
                    opt_l_name = matched_opt["name"]
                    opt_trigger = matched_opt.get("trigger", "")
                    if opt_trigger and opt_trigger.split(",")[0].strip().lower() not in positive_prompt.lower():
                        positive_prompt = f"{positive_prompt}, {opt_trigger}"
                if not any(a["name"] == opt_l_name for a in active_loras):
                    active_loras.append({"name": opt_l_name, "strength": opt_l_str})
        except Exception as e:
            print(f"[ComfyUI] 主模型控制生图执行异常，使用原提示词: {e}")

    # 3.4 若用户通过 args 指定了 loras
    if args and isinstance(args, dict) and args.get("loras"):
        for arg_l in args["loras"]:
            if isinstance(arg_l, dict) and arg_l.get("name") and not any(a["name"] == arg_l["name"] for a in active_loras):
                active_loras.append({
                    "name": arg_l["name"],
                    "strength": float(arg_l.get("strength", 0.8))
                })

    # 3.5 若用户指定了 default_lora 且当前为空
    if not active_loras and lora:
        active_loras.append({"name": lora, "strength": lora_strength})

    # NSFW 敏感词检查
    audit_required = requires_nsfw_audit(draw_cfg, groupid)
    if audit_required and check_censored(positive_prompt):
        return "审核api: 提示词包含受限内容，已被拦截"

    hires_fix = comfy_cfg.get("enable_hires_fix", False)
    if args and isinstance(args, dict) and "hires_fix" in args:
        hires_fix = bool(args["hires_fix"])
    hires_scale = float(comfy_cfg.get("hires_scale", 1.333))
    hires_denoise = float(comfy_cfg.get("hires_denoise", 0.38))
    hires_steps = int(comfy_cfg.get("hires_steps", 15))

    # 探测服务端能力并自动匹配底模 / CLIP / VAE / LoRA 的真实子目录路径
    caps, ckpt, clip, vae, active_loras, is_anima = await _resolve_workflow_assets(
        base_url=base_url,
        apikey=apikey,
        ckpt=ckpt,
        clip=clip,
        vae=vae,
        active_loras=active_loras,
    )
    enable_cache = comfy_cfg.get("enable_teacache", False) and is_anima
    teacache_thresh = float(comfy_cfg.get("teacache_thresh", 0.35))

    cache_type = None
    if enable_cache:
        if caps.get("has_teacache"):
            cache_type = "AnimaTeaCache"
        elif caps.get("has_easycache"):
            cache_type = "EasyCache"

    if scheduler == "beta57" and not caps.get("has_beta57"):
        scheduler = "beta"

    use_remap_lora = bool(is_anima and caps.get("has_remap_lora") and ("29b" in ckpt.lower() or "2.9b" in ckpt.lower()))

    workflow = build_illustrious_workflow(
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg_val,
        sampler_name=sampler,
        scheduler=scheduler,
        ckpt_name=ckpt,
        clip_name=clip,
        vae_name=vae,
        clip_skip=clip_skip,
        loras=active_loras,
        filename_prefix="ComfyUI_Illustrious",
        hires_fix=hires_fix,
        hires_scale=hires_scale,
        hires_denoise=hires_denoise,
        hires_steps=hires_steps,
        cache_type=cache_type,
        teacache_thresh=teacache_thresh,
        use_remap_lora=use_remap_lora,
        force_is_anima=is_anima,
    )

    return await _execute_comfyui_workflow(
        workflow=workflow,
        base_url=base_url,
        timeout=timeout,
        comfy_cfg=comfy_cfg,
        draw_cfg=draw_cfg,
        groupid=groupid,
        config=config,
        client_prefix="eridanus",
        apikey=apikey,
    )


async def _execute_comfyui_workflow(
    workflow: Dict[str, Any],
    base_url: str,
    timeout: float,
    comfy_cfg: Dict[str, Any],
    draw_cfg: Dict[str, Any],
    groupid: Optional[int],
    config: Any = None,
    client_prefix: str = "eridanus",
    apikey: Optional[str] = None,
) -> Union[str, bool, None]:
    """统一提交 ComfyUI API 工作流、轮询完成状态、下载并无损解密图像，返回缓存文件路径"""
    client_id = f"{client_prefix}_{random_str(8)}"
    payload = {"prompt": workflow, "client_id": client_id}
    parsed_url, parsed_key = parse_comfyui_connection(
        {"base_url": base_url, "apikey": comfy_cfg.get("apikey") if apikey is None else apikey}
    )
    base_url = parsed_url
    client_headers = build_comfyui_headers(parsed_key)
    audit_required = requires_nsfw_audit(draw_cfg, groupid)

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=client_headers, follow_redirects=True, verify=False) as http_client:
            prompt_resp = await http_client.post(f"{base_url}/prompt", json=payload)
            if prompt_resp.status_code != 200:
                err_text = ""
                for enc in ("utf-8", "gb18030", "gbk", "cp936"):
                    try:
                        err_text = prompt_resp.content.decode(enc)
                        break
                    except UnicodeDecodeError:
                        pass
                if not err_text:
                    err_text = prompt_resp.content[:300].decode("utf-8", errors="replace")
                if prompt_resp.status_code in (401, 403):
                    raise RuntimeError(
                        f"ComfyUI 鉴权失败 ({prompt_resp.status_code})，请检查 ComfyUI-Login 或网关 apikey 是否正确（切勿包含中文引号“”）: {err_text[:200]}"
                    )
                raise RuntimeError(f"ComfyUI /prompt 响应错误 ({prompt_resp.status_code}): {err_text[:500]}")

            prompt_data = safe_parse_json(prompt_resp)
            if isinstance(prompt_data, dict):
                if "error" in prompt_data:
                    err_val = prompt_data["error"]
                    err_msg = err_val.get("message") or str(err_val) if isinstance(err_val, dict) else str(err_val)
                    raise RuntimeError(f"ComfyUI /prompt 报错: {err_msg}")
                if "node_errors" in prompt_data and prompt_data["node_errors"]:
                    # 精简 node_errors，避免把数百个模型名全部吐到错误消息里
                    brief_errs = []
                    for nid, nerr in prompt_data["node_errors"].items():
                        if isinstance(nerr, dict):
                            ctype = nerr.get("class_type", nid)
                            msgs = [
                                (e.get("details") or e.get("message") or str(e))[:220]
                                for e in (nerr.get("errors") or [])
                                if isinstance(e, dict)
                            ]
                            brief_errs.append(f"{ctype}({nid}): {'; '.join(msgs) or str(nerr)[:220]}")
                        else:
                            brief_errs.append(f"{nid}: {str(nerr)[:220]}")
                    raise RuntimeError(f"ComfyUI 节点验证失败: {' | '.join(brief_errs)}")

            prompt_id = prompt_data.get("prompt_id") if prompt_data else None
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 未返回 prompt_id: {prompt_data}")

            elapsed = 0.0
            poll_interval = 2.0
            image_info = None

            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                try:
                    history_resp = await http_client.get(f"{base_url}/history/{prompt_id}")
                    if history_resp.status_code == 200:
                        history_data = safe_parse_json(history_resp)
                        if prompt_id in history_data:
                            task_history = history_data[prompt_id]
                            status_obj = task_history.get("status", {})
                            if isinstance(status_obj, dict) and status_obj.get("status_str") == "error":
                                err_msgs = status_obj.get("messages") or []
                                raise RuntimeError(f"ComfyUI 执行节点报错: {str(err_msgs)[:400]}")
                            outputs = task_history.get("outputs", {})
                            for node_id, node_out in outputs.items():
                                images = node_out.get("images", [])
                                if images:
                                    image_info = images[0]
                                    break
                            if image_info:
                                break
                except RuntimeError:
                    raise
                except Exception:
                    continue

            if not image_info:
                raise TimeoutError(f"ComfyUI 生图超时或未找到输出图像 (已等待 {elapsed} 秒)")

            filename = image_info.get("filename")
            subfolder = image_info.get("subfolder", "")
            img_type = image_info.get("type", "output")
            view_params = {"filename": filename, "type": img_type}
            if subfolder:
                view_params["subfolder"] = subfolder

            raw_bytes = None
            last_err = None
            for retry in range(3):
                try:
                    view_resp = await http_client.get(f"{base_url}/view", params=view_params)
                    if view_resp.status_code == 200 and len(view_resp.content) > 0:
                        raw_bytes = view_resp.content
                        break
                    last_err = f"HTTP {view_resp.status_code}"
                except Exception as e:
                    last_err = str(e)
                await asyncio.sleep(1.5)

            if not raw_bytes:
                raise RuntimeError(f"下载 ComfyUI 图像失败: {last_err}")

            if comfy_cfg.get("decrypt_encrypted_image", True):
                pwd = str(comfy_cfg.get("decrypt_password", "1234"))
                raw_bytes = decrypt_pixel_shuffle(raw_bytes, pwd)

            save_dir = Path("data/pictures/cache")
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f"{random_str()}.png"
            with open(save_path, "wb") as f:
                f.write(raw_bytes)

            if audit_required:
                audit_url = str(draw_cfg.get("sd审核和反推api") or "").strip()
                if audit_url:
                    try:
                        img_b64 = base64.b64encode(raw_bytes).decode("ascii")
                        is_nsfw = await pic_audit_standalone(img_b64, return_none=True, url=audit_url)
                        if is_nsfw:
                            return False
                    except Exception as audit_err:
                        logger.warning(f"[ComfyUI] 图片审核调用异常，已放行: {audit_err}")

            return str(save_path)
    except Exception:
        print(f"[ComfyUI Drawer Error] {traceback.format_exc()}")
        raise


async def comfyui_img2img(
    image_source: Union[str, bytes, Path],
    prompt: str,
    config,
    groupid: Optional[int] = None,
    args: Optional[Dict[str, Any]] = None,
    is_about_bot: bool = False,
    denoise: Optional[float] = None
) -> Optional[str]:
    """
    ComfyUI 以图生图 (img2img) 核心入口：
    1. 上传参考图片至 ComfyUI 服务端 (/upload/image)
    2. 支持以图生图提示词指导优化 (optimize_prompt_for_img2img)
    3. 构建以图生图工作流 (Illustrious Checkpoint / Anima 兼容，自动识别服务端模型与 LoRA 路径)
    4. 执行生成、自动无损解密并返回图片路径
    """
    draw_cfg = config.ai_generated_art.config.get("ai绘画", {})
    comfy_cfg = config.ai_generated_art.config.get("comfyui", {})

    base_url, apikey = parse_comfyui_connection(comfy_cfg)
    timeout = float(comfy_cfg.get("timeout", 300))

    uploaded_image_name = await upload_image_to_comfyui(image_source, base_url, apikey=apikey)

    if denoise is None:
        denoise = float(comfy_cfg.get("default_img2img_denoise", 0.65))
    if args and isinstance(args, dict) and "denoise" in args:
        denoise = float(args["denoise"])

    steps = int(args.get("steps", comfy_cfg.get("default_steps", 28))) if args and isinstance(args, dict) else comfy_cfg.get("default_steps", 28)
    cfg_val = float(args.get("cfg", comfy_cfg.get("default_cfg", 5.5))) if args and isinstance(args, dict) else comfy_cfg.get("default_cfg", 5.5)
    sampler = comfy_cfg.get("default_sampler", "euler_ancestral")
    scheduler = comfy_cfg.get("default_scheduler", "normal")
    ckpt = comfy_cfg.get("default_ckpt") or comfy_cfg.get("default_unet", "waiIllustriousSDXL_v170.safetensors")
    clip_skip = int(comfy_cfg.get("clip_skip", -2))
    clip = comfy_cfg.get("default_clip", "qwen_3_06b_base.safetensors")
    vae = comfy_cfg.get("default_vae", "qwen_image_vae.safetensors")

    from run.ai_generated_art.service.prompt_optimizer import optimize_prompt_for_img2img
    try:
        opt_info = await optimize_prompt_for_img2img(prompt, config, is_about_bot=is_about_bot, denoise=denoise)
        positive_prompt = opt_info.get("positive_prompt", prompt)
        negative_prompt = opt_info.get("negative_prompt", "")
        denoise = opt_info.get("denoise", denoise)
        steps = opt_info.get("steps", steps)
    except Exception as e:
        logger.debug(f"[ComfyUI Img2Img] 提示词优化异常: {e}")
        positive_prompt = prompt
        negative_prompt = "lowres, bad anatomy, bad hands, blurry, messy hair"

    wm = get_wardrobe_manager() if get_wardrobe_manager else None
    if wm:
        wm_neg = wm.get_negative_prompt()
        if wm_neg and wm_neg not in negative_prompt:
            negative_prompt = f"{negative_prompt}, {wm_neg}"

    active_loras: List[Dict[str, Any]] = []
    fixed_loras = comfy_cfg.get("fixed_loras", [])
    if isinstance(fixed_loras, list):
        for fl in fixed_loras:
            if isinstance(fl, dict) and fl.get("name"):
                active_loras.append({
                    "name": fl["name"],
                    "strength": float(fl.get("strength", 0.8))
                })
                fl_trigger = fl.get("trigger")
                if fl_trigger and fl_trigger.lower() not in positive_prompt.lower():
                    positive_prompt = f"{positive_prompt}, {fl_trigger}"

    positive_prompt, extracted_loras = extract_and_strip_loras(positive_prompt)
    for l_item in extracted_loras:
        cand_name = l_item["name"] if l_item["name"].endswith(".safetensors") else f"{l_item['name']}.safetensors"
        if not any(a["name"] == cand_name for a in active_loras):
            active_loras.append({"name": cand_name, "strength": l_item["strength"]})

    audit_required = requires_nsfw_audit(draw_cfg, groupid)
    if audit_required and check_censored(positive_prompt):
        return "审核api: 提示词包含受限内容，已被拦截"

    caps, ckpt, clip, vae, active_loras, is_anima = await _resolve_workflow_assets(
        base_url=base_url,
        apikey=apikey,
        ckpt=ckpt,
        clip=clip,
        vae=vae,
        active_loras=active_loras,
    )
    if scheduler == "beta57" and not caps.get("has_beta57"):
        scheduler = "beta"

    workflow = build_comfyui_img2img_workflow(
        image_name=uploaded_image_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        denoise=denoise,
        steps=steps,
        cfg=cfg_val,
        sampler_name=sampler,
        scheduler=scheduler,
        ckpt_name=ckpt,
        clip_name=clip,
        vae_name=vae,
        clip_skip=clip_skip,
        loras=active_loras,
        filename_prefix="ComfyUI_Img2Img",
        force_is_anima=is_anima,
    )

    return await _execute_comfyui_workflow(
        workflow=workflow,
        base_url=base_url,
        timeout=timeout,
        comfy_cfg=comfy_cfg,
        draw_cfg=draw_cfg,
        groupid=groupid,
        config=config,
        client_prefix="eridanus_img2img",
        apikey=apikey,
    )
