import asyncio
import hashlib
import io
import json
import os
import random
import re
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Union

import httpx
from PIL import Image
import numpy as np

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str
from framework_common.framework_util.reply_config import core_reply_enabled
from run.ai_generated_art.service.audit_policy import requires_nsfw_audit
from run.ai_generated_art.service.setu_moderate import pic_audit_standalone

try:
    from run.wardrobe.wardrobe_manager import get_wardrobe_manager
    from run.wardrobe.sd_prompt import ensure_art_anchor
except ImportError:
    get_wardrobe_manager = None
    ensure_art_anchor = None

from run.ai_generated_art.service.prompt_optimizer import (
    get_llm_config,
    map_aspect_ratio_to_resolution,
)

# 预设已知常用 LoRA 与底模映射列表（供 LLM 智能选取与触发词自动注入）
KNOWN_LORAS = [
    {
        "name": "chen-bin_v4.0.safetensors",
        "keywords": ["chen bin", "chenbin", "鬼针草", "细致丝袜", "网袜", "华丽质感", "二次元插画", "质感丝袜"],
        "trigger": "@4x0style",
        "default_strength": 0.8,
        "description": "Chen bin(鬼针草)画风，精湛细腻的面料与丝袜编织网纹，高光阴影层次"
    },
    {
        "name": "re-000180.safetensors",
        "keywords": ["rella", "透明感", "水彩少女", "通透光感", "高饱和细腻发丝", "水彩插画"],
        "trigger": "@shu, (Rella:1.2)",
        "default_strength": 0.8,
        "description": "Rella画师风格，标志性通透光感、精致水彩质感与细腻发丝"
    },
    {
        "name": "starshadowmagician_style_v2.safetensors",
        "keywords": ["starshadowmagician", "影法师", "厚涂", "星空", "华丽厚涂", "梦幻魔幻", "大场景厚涂"],
        "trigger": "(starshadowmagician:1.2), (hand-drawn:1.3)",
        "default_strength": 1.2,
        "description": "影法师画风，华丽厚涂与梦幻星空魔幻氛围，推荐权重1.2~1.5"
    },
    {
        "name": "saltystyle_v1_epoch20.safetensors",
        "keywords": ["saltywww", "咸鱼", "潮酷平涂", "日系平涂", "清新线条", "现代少女", "街头潮服"],
        "trigger": "@saltywww",
        "default_strength": 0.85,
        "description": "saltywww画风，日系清新潮酷平涂、干净干练的现代少女感"
    },
    {
        "name": "onineko_v2.2_epoch40.safetensors",
        "keywords": ["onineko", "おにねこ", "鬼猫", "糖果色", "萌系萝莉", "梦幻繁复", "华丽多饰品", "甜美洛丽塔"],
        "trigger": "@4x0style, onineko style",
        "default_strength": 0.85,
        "description": "おにねこ(Onineko)画风，极其梦幻华丽的糖果色、繁复蕾丝与萌系萝莉少女"
    },
    {
        "name": "umeharasei_v1_epoch30.safetensors",
        "keywords": ["umehara_sei", "umeharasei", "梅原晴", "水润肤色", "柔和插画", "清爽少女", "治愈系"],
        "trigger": "@umehava",
        "default_strength": 0.8,
        "description": "梅原晴(umehara_sei)画风，清爽透明感、柔和水润肤色与治愈系二次元插画"
    },
    {
        "name": "lily_20.safetensors",
        "keywords": ["lily", "莉莉", "wuthering waves", "鸣潮", "粉瞳", "白发粉瞳", "花朵发饰"],
        "trigger": "lily (wuthering waves), 1girl, pink eyes, gradient hair, flower hair ornament",
        "default_strength": 0.95,
        "description": "鸣潮莉莉专属角色外观与服饰"
    },
    {
        "name": "garter_belt_anima_v1.0.safetensors",
        "keywords": ["吊带袜", "garter belt", "garter", "大腿袜", "过膝袜", "蕾丝袜", "thighhighs"],
        "trigger": "garter belt, thighhighs",
        "default_strength": 0.85,
        "description": "精细吊带袜与过膝蕾丝袜细节强化"
    },
    {
        "name": "newPSG_A3P_v1.safetensors",
        "keywords": ["吊带袜天使", "panty", "stocking", "psg", "美式卡通", "粗线条", "复古画风"],
        "trigger": "panty and stocking style, retro cartoon",
        "default_strength": 0.9,
        "description": "吊带袜天使粗线条美式复古卡通画风"
    },
    {
        "name": "miaomiao_3d_harem_v1.0.safetensors",
        "keywords": ["3d", "三维", "精细3d", "3d动漫", "3d渲染", "miaomiao", "手办质感"],
        "trigger": "3d anime style, exquisite rendering, soft shadow",
        "default_strength": 0.8,
        "description": "MiaoMiao 3D 二次元高精手办与三维立体渲染感"
    }
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


async def optimize_prompt_with_llm(user_prompt: str, config) -> Dict[str, Any]:
    """
    实验性功能：调用主回复模型 (gemini-3.8-flash 或 core_reply) 对生图节点和提示词进行智能控制。
    输出标准结构字典：positive_prompt, negative_prompt, width, height, steps, cfg, sampler_name, scheduler, lora_name, lora_strength
    """
    comfy_cfg = config.ai_generated_art.config.get("comfyui", {})
    llm_cfg = get_llm_config(config)

    api_key = llm_cfg["apikey"]
    base_url = llm_cfg["base_url"]
    model = llm_cfg["model"]
    temperature = llm_cfg["temperature"]

    lora_desc = "\n".join([
        f"- 文件名: '{item['name']}'，适用关键词: {', '.join(item['keywords'])}，触发词: '{item['trigger']}'"
        for item in KNOWN_LORAS
    ])

    system_instruction = f"""你是一个顶级的二次元动漫绘图与 ComfyUI 参数调控专家。你的任务是根据用户的中文或英文绘图要求，控制生成最完美的二次元动漫图节点参数。
服务端搭载 Anima 2.9B DiT 动漫大模型。请遵循以下专业规则：
1. positive_prompt 必须转化为最贴合画面的高质量 Danbooru 风格逗号分隔英文 tags（如 masterpiece, best quality, aesthetic, 1girl, ...），不要包含任何中文。
   【核心规范·角色与着装保护】：若输入的提示词中已包含角色外貌锚点（如发色、瞳色、发型、呆毛、脸型）或服装穿搭（如开衫、贝雷帽、百褶裙、及膝袜、特定套装），必须完整严密保留这些核心设定标签，在此基础上扩充场景、动作、光影氛围与细节画质，绝不可丢弃或随意替换原有的角色和着装特征！
2. negative_prompt 给出恰当的负面标签（如 worst quality, low quality, blurry, bad anatomy 等）。
3. 比例与尺寸推荐（所有宽高比必须严格在 1200 到 1800 之间，且为 64 的倍数）：
   - 竖图/全身/立绘：width=1280, height=1728 或 width=1216, height=1792
   - 横图/场景/壁纸：width=1728, height=1280 或 width=1792, height=1216
   - 正方形/头像：width=1536, height=1536
4. 采样步数 steps 必须自主选在 28~60 之间（根据画面复杂精细度决定，推荐 30~45），cfg 推荐 4.0~5.5。
5. 采样器推荐 sampler_name="er_sde" 或 "euler", scheduler="simple"。
6. 检查是否匹配到以下可用 LoRA：
{lora_desc}
   - 如果用户需求明确匹配某种风格或角色（例如画莉莉、吊带袜、美式复古卡通、3D画风），请在 lora_name 中填入对应文件名，lora_strength 填 0.8~1.0，并在 positive_prompt 中加入其专属触发词。
   - 若不匹配任何可用 LoRA，则 lora_name 设为 null，lora_strength 设为 0。

你必须仅输出合法可解析的 JSON 对象，不得输出 markdown 代码块外多余文字：
{{
  "positive_prompt": "masterpiece, best quality, ...",
  "negative_prompt": "worst quality, low quality, ...",
  "width": 1280,
  "height": 1728,
  "steps": 32,
  "cfg": 4.5,
  "sampler_name": "er_sde",
  "scheduler": "simple",
  "lora_name": null,
  "lora_strength": 0.0
}}"""

    req_messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"用户绘图请求：{user_prompt}"}
    ]

    try:
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
                # 约束尺寸在 1200 - 1800 之间且为 64 倍数
                if "width" in parsed and "height" in parsed:
                    pw = max(1200, min(1800, int(parsed["width"])))
                    ph = max(1200, min(1800, int(parsed["height"])))
                    parsed["width"] = int(round(pw / 64) * 64)
                    parsed["height"] = int(round(ph / 64) * 64)

                return parsed
    except Exception as e:
        print(f"[ComfyUI LLM Control] LLM 智能优化参数失败，回退到默认参数: {e}")

    # 回退到基础默认解析 (尺寸 1200-1800, 步数 28-60)
    return {
        "positive_prompt": f"masterpiece, best quality, aesthetic, {user_prompt}",
        "negative_prompt": "worst quality, low quality, blurry, bad anatomy",
        "width": comfy_cfg.get("default_width", 1280),
        "height": comfy_cfg.get("default_height", 1728),
        "steps": comfy_cfg.get("default_steps", 32),
        "cfg": comfy_cfg.get("default_cfg", 4.5),
        "sampler_name": comfy_cfg.get("default_sampler", "er_sde"),
        "scheduler": comfy_cfg.get("default_scheduler", "simple"),
        "lora_name": comfy_cfg.get("default_lora", None),
        "lora_strength": comfy_cfg.get("default_lora_strength", 0.9)
    }


def build_anima_workflow(
    positive_prompt: str,
    negative_prompt: str,
    width: int = 1280,
    height: int = 1728,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 4.5,
    sampler_name: str = "er_sde",
    scheduler: str = "simple",
    unet_name: str = "anima-base-v1.0.safetensors",
    clip_name: str = "qwen_3_06b_base.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    lora_name: Optional[str] = None,
    lora_strength: float = 0.9,
    loras: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "ComfyUI_Anima",
    hires_fix: bool = False,
    hires_scale: float = 1.333,
    hires_denoise: float = 0.38,
    hires_steps: int = 15
) -> Dict[str, Any]:
    """构建标准 Anima DiT 架构的 ComfyUI API Prompt 节点图（支持链式多 LoRA 串联加载与两阶段 Hires Fix 高清平滑精修）"""
    if seed == -1:
        seed = random.randint(1, 10**14)

    prompt_nodes = {
        "1": {
            "inputs": {
                "unet_name": unet_name,
                "weight_dtype": "default"
            },
            "class_type": "UNETLoader"
        },
        "2": {
            "inputs": {
                "clip_name": clip_name,
                "type": "stable_diffusion",
                "device": "default"
            },
            "class_type": "CLIPLoader"
        },
        "3": {
            "inputs": {
                "vae_name": vae_name
            },
            "class_type": "VAELoader"
        },
        "4": {
            "inputs": {
                "model": ["1", 0],
                "shift": 3.0
            },
            "class_type": "ModelSamplingAuraFlow"
        }
    }

    # 链式串联加载一个或多个 LoRA
    active_lora_list = []
    if loras:
        active_lora_list.extend(loras)
    elif lora_name:
        active_lora_list.append({"name": lora_name, "strength": float(lora_strength)})

    cur_model_ref = ["4", 0]
    cur_clip_ref = ["2", 0]

    for idx, l_item in enumerate(active_lora_list):
        ln = l_item.get("name")
        ls = float(l_item.get("strength", 0.9))
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

    model_ref = cur_model_ref
    clip_ref = cur_clip_ref

    prompt_nodes["6"] = {
        "inputs": {
            "text": positive_prompt,
            "clip": clip_ref
        },
        "class_type": "CLIPTextEncode"
    }

    prompt_nodes["7"] = {
        "inputs": {
            "text": negative_prompt,
            "clip": clip_ref
        },
        "class_type": "CLIPTextEncode"
    }

    if hires_fix:
        # 两阶段二次元经典高清精修工作流：阶段1生成基底构图，阶段2重采样抚平发丝毛躁
        base_w = int(round(width / hires_scale / 64) * 64)
        base_h = int(round(height / hires_scale / 64) * 64)
        prompt_nodes["8"] = {
            "inputs": {
                "width": base_w,
                "height": base_h,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        }
        prompt_nodes["9"] = {
            "inputs": {
                "seed": seed,
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": model_ref,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["85"] = {
            "inputs": {
                "samples": ["9", 0],
                "upscale_method": "bicubic",
                "width": int(width),
                "height": int(height),
                "crop": "disabled"
            },
            "class_type": "LatentUpscale"
        }
        prompt_nodes["95"] = {
            "inputs": {
                "seed": seed + 1,
                "steps": int(hires_steps),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": float(hires_denoise),
                "model": model_ref,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["85", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["10"] = {
            "inputs": {
                "samples": ["95", 0],
                "vae": ["3", 0]
            },
            "class_type": "VAEDecode"
        }
    else:
        prompt_nodes["8"] = {
            "inputs": {
                "width": int(width),
                "height": int(height),
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        }
        prompt_nodes["9"] = {
            "inputs": {
                "seed": seed,
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": model_ref,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0]
            },
            "class_type": "KSampler"
        }
        prompt_nodes["10"] = {
            "inputs": {
                "samples": ["9", 0],
                "vae": ["3", 0]
            },
            "class_type": "VAEDecode"
        }

    prompt_nodes["11"] = {
        "inputs": {
            "images": ["10", 0]
        },
        "class_type": "PreviewImage"
    }

    return prompt_nodes


def build_comfyui_img2img_workflow(
    image_name: str,
    positive_prompt: str,
    negative_prompt: str,
    denoise: float = 0.65,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 4.5,
    sampler_name: str = "er_sde",
    scheduler: str = "simple",
    unet_name: str = "anima-base-v1.0.safetensors",
    clip_name: str = "qwen_3_06b_base.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    loras: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "ComfyUI_Img2Img"
) -> Dict[str, Any]:
    """构建标准 ComfyUI 以图生图 (img2img) 节点工作流 (LoadImage + VAEEncode -> KSampler)"""
    if seed == -1:
        seed = random.randint(1, 10**14)

    prompt_nodes = {
        "1": {
            "inputs": {
                "unet_name": unet_name,
                "weight_dtype": "default"
            },
            "class_type": "UNETLoader"
        },
        "2": {
            "inputs": {
                "clip_name": clip_name,
                "type": "stable_diffusion",
                "device": "default"
            },
            "class_type": "CLIPLoader"
        },
        "3": {
            "inputs": {
                "vae_name": vae_name
            },
            "class_type": "VAELoader"
        },
        "4": {
            "inputs": {
                "model": ["1", 0],
                "shift": 3.0
            },
            "class_type": "ModelSamplingAuraFlow"
        }
    }

    cur_model_ref = ["4", 0]
    cur_clip_ref = ["2", 0]

    for idx, l_item in enumerate(loras or []):
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

    prompt_nodes["6"] = {
        "inputs": {
            "text": positive_prompt,
            "clip": cur_clip_ref
        },
        "class_type": "CLIPTextEncode"
    }

    prompt_nodes["7"] = {
        "inputs": {
            "text": negative_prompt,
            "clip": cur_clip_ref
        },
        "class_type": "CLIPTextEncode"
    }

    # 以图生图关键输入节点：加载服务端图片并进行 VAE 编码
    prompt_nodes["8"] = {
        "inputs": {
            "image": image_name
        },
        "class_type": "LoadImage"
    }

    prompt_nodes["81"] = {
        "inputs": {
            "pixels": ["8", 0],
            "vae": ["3", 0]
        },
        "class_type": "VAEEncode"
    }

    prompt_nodes["9"] = {
        "inputs": {
            "seed": seed,
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": float(denoise),
            "model": cur_model_ref,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["81", 0]
        },
        "class_type": "KSampler"
    }

    prompt_nodes["10"] = {
        "inputs": {
            "samples": ["9", 0],
            "vae": ["3", 0]
        },
        "class_type": "VAEDecode"
    }

    prompt_nodes["11"] = {
        "inputs": {
            "images": ["10", 0]
        },
        "class_type": "PreviewImage"
    }

    return prompt_nodes


async def upload_image_to_comfyui(img_source: Union[bytes, str, Path], base_url: str) -> str:
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

    upload_url = f"{base_url}/upload/image"
    files = {"image": (filename, raw_bytes, "image/png")}
    data = {"overwrite": "true", "subfolder": "", "type": "input"}

    client_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(timeout=30.0, headers=client_headers, verify=False) as client:
        resp = await client.post(upload_url, files=files, data=data)
        if resp.status_code == 200:
            res_data = resp.json()
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

    base_url = (comfy_cfg.get("url") or "http://127.0.0.1:7860").rstrip("/")
    timeout = float(comfy_cfg.get("timeout", 300))
    llm_control = comfy_cfg.get("主模型控制生图", False)

    # 尺寸与默认参数 (所有宽高比处于 1200 - 1800 区间)
    width = comfy_cfg.get("default_width", 1280)
    height = comfy_cfg.get("default_height", 1728)

    # 动态解析画幅比例 (aspect_ratio)
    ar = None
    if args and isinstance(args, dict):
        ar = args.get("aspect_ratio") or args.get("ar")
    if not ar and comfy_cfg.get("aspect_ratio"):
        ar = comfy_cfg.get("aspect_ratio")

    if ar:
        width, height = map_aspect_ratio_to_resolution(ar, default_w=width, default_h=height)

    steps = comfy_cfg.get("default_steps", 32)
    cfg_val = comfy_cfg.get("default_cfg", 4.5)
    sampler = comfy_cfg.get("default_sampler", "er_sde")
    scheduler = comfy_cfg.get("default_scheduler", "simple")
    unet = comfy_cfg.get("default_unet", "anima-base-v1.0.safetensors")
    clip = comfy_cfg.get("default_clip", "qwen_3_06b_base.safetensors")
    vae = comfy_cfg.get("default_vae", "qwen_image_vae.safetensors")
    lora = comfy_cfg.get("default_lora", None)
    lora_strength = comfy_cfg.get("default_lora_strength", 0.9)

    if args and isinstance(args, dict):
        if args.get("width"):
            width = int(args["width"])
        if args.get("height"):
            height = int(args["height"])
        if args.get("steps"):
            steps = int(args["steps"])
        if args.get("cfg"):
            cfg_val = float(args["cfg"])
        if args.get("unet"):
            unet = str(args["unet"])
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
            "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry"
        )

    # 2. 正向提示词装配与衣橱联动
    positive_prompt = prompt

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

        # 如果用户提示词中已经明确指定了具体服装 (例如睡裙、泳装、特定裙子等)，则不强行叠加默认常服以防服饰冲突
        has_custom_clothing = any(
            kw in positive_prompt.lower()
            for kw in [
                "睡裙", "睡衣", "nightgown", "pajama", "sleepwear", "吊带裙", "泳装", "比基尼", "swimsuit",
                "bikini", "礼服", "dress", "旗袍", "汉服", "制服", "uniform", "cosplay", "lo裙", "lolita"
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
            optimized = await optimize_prompt_with_llm(positive_prompt, config)
            positive_prompt = optimized.get("positive_prompt", positive_prompt)
            negative_prompt = optimized.get("negative_prompt", negative_prompt)
            if "width" in optimized:
                width = max(1200, min(1800, int(round(int(optimized["width"]) / 64) * 64)))
            if "height" in optimized:
                height = max(1200, min(1800, int(round(int(optimized["height"]) / 64) * 64)))
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

    workflow = build_anima_workflow(
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg_val,
        sampler_name=sampler,
        scheduler=scheduler,
        unet_name=unet,
        clip_name=clip,
        vae_name=vae,
        loras=active_loras,
        filename_prefix="ComfyUI_Anima",
        hires_fix=hires_fix,
        hires_scale=hires_scale,
        hires_denoise=hires_denoise,
        hires_steps=hires_steps
    )

    client_id = f"eridanus_{random_str(8)}"
    payload = {
        "prompt": workflow,
        "client_id": client_id
    }

    client_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=client_headers, follow_redirects=True, verify=False) as http_client:
            # 1. 提交任务到 /prompt
            prompt_resp = await http_client.post(f"{base_url}/prompt", json=payload)
            if prompt_resp.status_code != 200:
                raise RuntimeError(f"ComfyUI /prompt 响应错误 ({prompt_resp.status_code}): {prompt_resp.text}")

            prompt_data = prompt_resp.json()
            prompt_id = prompt_data.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 未返回 prompt_id: {prompt_data}")

            # 2. 轮询 /history/{prompt_id}
            elapsed = 0.0
            poll_interval = 2.0
            image_info = None

            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                try:
                    history_resp = await http_client.get(f"{base_url}/history/{prompt_id}")
                    if history_resp.status_code == 200:
                        history_data = history_resp.json()
                        if prompt_id in history_data:
                            task_history = history_data[prompt_id]
                            outputs = task_history.get("outputs", {})
                            # 查找 SaveImage 节点的输出
                            for node_id, node_out in outputs.items():
                                images = node_out.get("images", [])
                                if images:
                                    image_info = images[0]
                                    break
                            if image_info:
                                break
                except Exception:
                    # 忽略长轮询中的瞬时网络抖动或代理断开，下个周期自动重试
                    continue

            if not image_info:
                raise TimeoutError(f"ComfyUI 生图超时或未找到输出图像 (已等待 {elapsed} 秒)")

            # 3. 下载图像 /view (支持多轮重试防抖)
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

            # 4. 如果启用了解密，处理像素混淆
            if comfy_cfg.get("decrypt_encrypted_image", True):
                pwd = str(comfy_cfg.get("decrypt_password", "1234"))
                raw_bytes = decrypt_pixel_shuffle(raw_bytes, pwd)

            # 5. 保存到本地缓存
            save_dir = Path("data/pictures/cache")
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f"{random_str()}.png"
            with open(save_path, "wb") as f:
                f.write(raw_bytes)

            # 6. 后续图片审核
            if audit_required:
                try:
                    audit_res = await pic_audit_standalone(str(save_path), config)
                    if not audit_res:
                        return False
                except Exception:
                    pass

            return str(save_path)

    except Exception as e:
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
    3. 构建以图生图工作流 (LoadImage -> VAEEncode -> KSampler with denoise)
    4. 执行生成、自动无损解密并返回图片路径
    """
    draw_cfg = config.ai_generated_art.config.get("ai绘画", {})
    comfy_cfg = config.ai_generated_art.config.get("comfyui", {})

    base_url = (comfy_cfg.get("url") or "http://127.0.0.1:7860").rstrip("/")
    timeout = float(comfy_cfg.get("timeout", 300))

    # 1. 上传图片至 ComfyUI
    uploaded_image_name = await upload_image_to_comfyui(image_source, base_url)

    # 2. 提示词装配与参数解析
    if denoise is None:
        denoise = float(comfy_cfg.get("default_img2img_denoise", 0.65))
    if args and isinstance(args, dict) and "denoise" in args:
        denoise = float(args["denoise"])

    steps = int(args.get("steps", comfy_cfg.get("default_steps", 32))) if args and isinstance(args, dict) else comfy_cfg.get("default_steps", 32)
    cfg_val = float(args.get("cfg", comfy_cfg.get("default_cfg", 4.5))) if args and isinstance(args, dict) else comfy_cfg.get("default_cfg", 4.5)
    sampler = comfy_cfg.get("default_sampler", "er_sde")
    scheduler = comfy_cfg.get("default_scheduler", "simple")
    unet = comfy_cfg.get("default_unet", "anima-base-v1.0.safetensors")
    clip = comfy_cfg.get("default_clip", "qwen_3_06b_base.safetensors")
    vae = comfy_cfg.get("default_vae", "qwen_image_vae.safetensors")

    # 接入以图生图提示词指导优化器
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

    # 衣橱负面提示词补充
    wm = get_wardrobe_manager() if get_wardrobe_manager else None
    if wm:
        wm_neg = wm.get_negative_prompt()
        if wm_neg and wm_neg not in negative_prompt:
            negative_prompt = f"{negative_prompt}, {wm_neg}"

    # 链式 LoRAs
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
        if not any(a["name"] == l_item["name"] for a in active_loras):
            active_loras.append(l_item)

    # NSFW 敏感词检查
    audit_required = requires_nsfw_audit(draw_cfg, groupid)
    if audit_required and check_censored(positive_prompt):
        return "审核api: 提示词包含受限内容，已被拦截"

    # 构建以图生图 workflow
    workflow = build_comfyui_img2img_workflow(
        image_name=uploaded_image_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        denoise=denoise,
        steps=steps,
        cfg=cfg_val,
        sampler_name=sampler,
        scheduler=scheduler,
        unet_name=unet,
        clip_name=clip,
        vae_name=vae,
        loras=active_loras,
        filename_prefix="ComfyUI_Img2Img"
    )

    client_id = f"eridanus_img2img_{random_str(8)}"
    payload = {"prompt": workflow, "client_id": client_id}
    client_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=client_headers, follow_redirects=True, verify=False) as http_client:
            prompt_resp = await http_client.post(f"{base_url}/prompt", json=payload)
            if prompt_resp.status_code != 200:
                raise RuntimeError(f"ComfyUI /prompt 响应错误 ({prompt_resp.status_code}): {prompt_resp.text}")

            prompt_data = prompt_resp.json()
            prompt_id = prompt_data.get("prompt_id")
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
                        history_data = history_resp.json()
                        if prompt_id in history_data:
                            task_history = history_data[prompt_id]
                            outputs = task_history.get("outputs", {})
                            for node_id, node_out in outputs.items():
                                images = node_out.get("images", [])
                                if images:
                                    image_info = images[0]
                                    break
                            if image_info:
                                break
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
                try:
                    audit_res = await pic_audit_standalone(str(save_path), config)
                    if not audit_res:
                        return False
                except Exception:
                    pass

            return str(save_path)
    except Exception as e:
        print(f"[ComfyUI Img2Img Error] {traceback.format_exc()}")
        raise
