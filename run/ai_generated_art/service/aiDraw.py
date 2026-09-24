import asyncio
import base64
import io
import json
import math
import random
import re
import zipfile
from io import BytesIO

import httpx
import numpy as np
from PIL import Image, ImageDraw

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import parse_arguments
from run.ai_generated_art.service.wildcard import replace_wildcards
from .setu_moderate import pic_audit_standalone

same_manager = YAMLManager.get_instance()
apikey=same_manager.ai_generated_art.config["ai绘画"]["apikey"]
eridanus_headers={"Authorization": f"Bearer {apikey}"}
#print(same_manager.ai_generated_art.config,type(same_manager.ai_generated_art.config))
aiDrawController = same_manager.ai_generated_art.config.get("ai绘画")
ckpt = aiDrawController.get("sd默认启动模型") if aiDrawController else None
if_save = aiDrawController.get("sd图片是否保存到生图端") if aiDrawController else False
sd_w = int(aiDrawController.get("sd画图默认分辨率", "1024,1536").split(",")[0]) if aiDrawController else 1024
sd_h = int(aiDrawController.get("sd画图默认分辨率", "1024,1536").split(",")[1]) if aiDrawController else 1536
try:
    resolution_str = aiDrawController.get("sd最大分辨率", "1600,1600") if aiDrawController else "1600,1600"
    separator = next((s for s in [",", "*", "x"] if s in resolution_str), None)
    if separator:
        width, height = resolution_str.split(separator)
        sd_max_size = int(width) * int(height)
    else:
        sd_max_size = int(resolution_str)
except (ValueError, IndexError, TypeError):
    sd_max_size = 1600 * 1600
allow_nsfw_groups = [int(item) for item in aiDrawController.get("allow_nsfw_groups", [])] if aiDrawController else []
censored_words = ["nsfw", "nipple", "pussy", "areola", "dick", "cameltoe", "ass", "boob", "arse", "penis", "porn", "sex", "bitch", "fuck", "arse", "blowjob", "handjob", "anal", "nude", "vagina", "boner"]
positives = '{},rating:general, best quality, very aesthetic, absurdres'
negatives = 'blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, multiple views, gigantic breasts'
#positives = '{},masterpiece,best quality,amazing quality,very aesthetic,absurdres,newest,'
#negatives = 'nsfw,lowres,{bad},error,fewer,extra,missing,worst quality,jpeg artifacts,bad quality,watermark,unfinished,displeasing,chromatic aberration,signature,extra digits,artistic error,username,[abstract],blurry,film grain,scan artifacts,very displeasing,logo,dated,multiple views,gigantic breasts'
#negatives = '((nsfw)),((furry)),lowres,(bad quality,worst quality:1.2),bad anatomy,sketch,jpeg artifacts,ugly,poorly drawn,(censor),blurry,watermark,simple background,transparent background,{bad},error,fewer,extra,missing,jpeg artifacts,unfinished,displeasing,chromatic aberration,signature,extra digits,artistic error,username,scan,[abstract],film grain,scan artifacts,very displeasing,logo,dated,multiple views,gigantic breasts'
round_sd = 0
round_nai = 0

configs = aiDrawController.get("其他默认绘图参数",[])
default_args = {}

for config in configs:
    default_args = parse_arguments(config, default_args)

def check_censored(positive, censored_words):
    words = positive.lower().replace(',', ' ').split()
    for word in censored_words:
        if word.lower() in words:
            return True
    return
async def aiArtModerate(imgurl,api_user,api_secret):
    params = {
        'url': f'{imgurl}',
        'models': 'genai',
        'api_user': f'{api_user}',
        'api_secret': f'{api_secret}'
    }
    async with httpx.AsyncClient() as client:
        response = await client.get('https://api.sightengine.com/1.0/check.json', params=params)
        data = response.json()
    return data["type"]['ai_generated']*100
async def get_image_dimensions(base64_string):
    try:
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]
        image_bytes = base64.b64decode(base64_string)
        image_buffer = BytesIO(image_bytes)
        loop = asyncio.get_event_loop()
        image = await loop.run_in_executor(None, Image.open, image_buffer)
        width, height = image.size
        image.close()
        image_buffer.close()
        
        return width, height
        
    except Exception as e:
        raise Exception(f"处理图像时发生错误: {str(e)}")
    
def process_image_dimensions(width, height, max_area=None, min_area=None, resolution_options=None, divisible_by=None, upscale_to_max=False):
    """
    参数:
        width: 输入宽度
        height: 输入高度
        max_area: 最大面积（可选）
        min_area: 最小面积（可选）
        resolution_options: 分辨率选项元组（可选），如 ((1024,1024), (1024,1536), (1536,1024))
        divisible_by: 输出尺寸必须能被此值整除（可选）
        upscale_to_max: 如果面积小于max_area，是否放大到接近max_area（可选，默认为False）
    返回:
        width, height: 处理后的宽度和高度
    """
    try:
        orig_width, orig_height = width, height
        orig_ratio = orig_width / orig_height
        
        new_width, new_height = orig_width, orig_height
        
        curr_area = orig_width * orig_height
        
        if max_area is not None and curr_area > max_area:
            scale = math.sqrt(max_area / curr_area)
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)
        
        if min_area is not None and curr_area < min_area:
            scale = math.sqrt(min_area / curr_area)
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)
        
        elif max_area is not None and curr_area < max_area and upscale_to_max:
            scale = math.sqrt(max_area / curr_area)
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)
                
        elif resolution_options is not None:
            best_match = None
            min_diff = float('inf')
            
            for opt_width, opt_height in resolution_options:
                opt_ratio = opt_width / opt_height
                ratio_diff = abs(orig_ratio - opt_ratio)
                
                if ratio_diff < min_diff:
                    min_diff = ratio_diff
                    best_match = (opt_width, opt_height)
                    
            new_width, new_height = best_match
        
        if divisible_by is not None and divisible_by > 0:
            new_width = (new_width // divisible_by) * divisible_by
            new_height = (new_height // divisible_by) * divisible_by
            new_width = max(new_width, divisible_by)
            new_height = max(new_height, divisible_by)
        
        return new_width, new_height
    
    except Exception as e:
        raise Exception(f"处理尺寸时发生错误: {str(e)}")
    
def parse_custom_url_auth(input_string: str):
    parts = input_string.split(' ', 1)
    clean_url = parts[0]
    auth_header = ''

    if len(parts) == 2 and parts[1]:
        credentials_string = parts[1]
        credentials_bytes = credentials_string.encode('utf-8')
        encoded_credentials_bytes = base64.b64encode(credentials_bytes)
        encoded_credentials_string = encoded_credentials_bytes.decode('utf-8')
        if apikey:
            auth_header = f"Bearer {apikey}"
        else:
            auth_header = f"Basic {encoded_credentials_string}"

    return clean_url, auth_header

async def n4(prompt, path, groupid, config, args):
    global round_nai
    width = 832
    height = 1216
    url = "https://image.novelai.net"

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1024
        height = 1024
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1216
        height = 832
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 832
        height = 1216

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    nai_sampler = str(args.get('nai-sampler', default_args.get('nai-sampler', 'k_euler_ancestral')) if isinstance(args, dict) else default_args.get('nai-sampler', 'k_euler_ancestral') if isinstance(default_args, dict) else 'k_euler_ancestral')
    nai_scheduler = str(args.get('nai-scheduler', default_args.get('nai-scheduler', 'karras')) if isinstance(args, dict) else default_args.get('nai-scheduler', 'karras') if isinstance(default_args, dict) else 'karras')
    nai_cfg = float(args.get('nai-cfg', default_args.get('nai-cfg', 5)) if isinstance(args, dict) else default_args.get('nai-cfg', 5) if isinstance(default_args, dict) else 5)
    
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False

    payload = {
        "input": positive,
        "model": "nai-diffusion-4-curated-preview",
        "action": "generate",
        "parameters": {
            "params_version": 3,
            "width": width,
            "height": height,
            "scale": nai_cfg,
            "sampler": nai_sampler,
            "steps": 23,
            "n_samples": 1,
            "ucPreset": 0,
            "qualityToggle": True,
            "dynamic_thresholding": False,
            "controlnet_strength": 1,
            "legacy": False,
            "add_original_image": True,
            "cfg_rescale": 0,
            "noise_schedule": nai_scheduler,
            "legacy_v3_extend": False,
            "skip_cfg_above_sigma": None,
            "use_coords": False,
            "seed": random.randint(0, 2 ** 32 - 1),
            "characterPrompts": [],
            "v4_prompt": {
                "caption": {
                    "base_caption": positive,
                    "char_captions": []
                },
                "use_coords": False,
                "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative,
                    "char_captions": []
                }
            },
            "negative_prompt": negative,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
            "deliberate_euler_ancestral_bug": False,
            "prefer_brownian": True
        }
    }

    headers = {
        "Authorization": f"Bearer {config.ai_generated_art.config['ai绘画']['nai_key'][int(round_nai)]}",
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://novelai.net",
        "priority": "u=1, i",
        "referer": "https://novelai.net/",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Microsoft Edge";v="132"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "x-correlation-id": "89SHW4",
        "x-initiated-at": "2025-01-27T16:40:54.521Z"
    }
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    if config.common_config.basic_config["proxy"]["http_proxy"]:
        proxies = {"http://": config.common_config.basic_config["proxy"]["http_proxy"], "https://": config.common_config.basic_config["proxy"]["http_proxy"]}
    else:
        proxies = None
    round_nai += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['nai_key'])
    if round_nai >= list_length:
        round_nai = 0
    async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
        response = await client.post(url=f'{url}/ai/generate-image', json=payload, headers=headers)
        response.raise_for_status()
        zip_content = response.content
        zip_file = io.BytesIO(zip_content)
        with zipfile.ZipFile(zip_file, 'r') as zf:
            file_names = zf.namelist()
            if not file_names:
                raise ValueError("The zip archive is empty.")
            file_name = file_names[0]
            if not file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                raise ValueError("The zip archive does not contain an image file.")
            image_data = zf.read(file_name)
            if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
                try:
                    check = await pic_audit_standalone(base64.b64encode(image_data).decode('utf-8'), return_none=True,url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
                    if check:
                        return False
                except Exception as e:
                    print(f"审核api失效,为保证安全已禁止画图请求: {e}")
                    return f"审核api失效,为保证安全已禁止画图请求: {e}"
            with open(path, 'wb') as img_file:
                img_file.write(image_data)
    return path


async def n3(prompt, path, groupid, config, args):
    global round_nai
    width = 832
    height = 1216
    url = "https://image.novelai.net"

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1024
        height = 1024
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1216
        height = 832
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 832
        height = 1216
        
    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    nai_sampler = str(args.get('nai-sampler', default_args.get('nai-sampler', 'k_euler_ancestral')) if isinstance(args, dict) else default_args.get('nai-sampler', 'k_euler_ancestral') if isinstance(default_args, dict) else 'k_euler_ancestral')
    nai_scheduler = str(args.get('nai-scheduler', default_args.get('nai-scheduler', 'karras')) if isinstance(args, dict) else default_args.get('nai-scheduler', 'karras') if isinstance(default_args, dict) else 'karras')
    nai_cfg = float(args.get('nai-cfg', default_args.get('nai-cfg', 5)) if isinstance(args, dict) else default_args.get('nai-cfg', 5) if isinstance(default_args, dict) else 5)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False

    payload = {
        "input": positive,
        "model": "nai-diffusion-3",
        "action": "generate",
        "parameters": {
            "params_version": 3,
            "width": width,
            "height": height,
            "scale": 5,
            "sampler": nai_sampler,
            "steps": 23,
            "n_samples": 1,
            "ucPreset": 0,
            "qualityToggle": True,
            "sm": False,
            "sm_dyn": False,
            "dynamic_thresholding": False,
            "controlnet_strength": 1,
            "legacy": False,
            "add_original_image": True,
            "cfg_rescale": 0,
            "noise_schedule": nai_scheduler,
            "legacy_v3_extend": False,
            "skip_cfg_above_sigma": None,
            "seed": random.randint(0, 2 ** 32 - 1),
            "characterPrompts": [],
            "negative_prompt": negative,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": []
        }
    }

    headers = {
        "Authorization": f"Bearer {config.ai_generated_art.config['ai绘画']['nai_key'][int(round_nai)]}",
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://novelai.net",
        "priority": "u=1, i",
        "referer": "https://novelai.net/",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Microsoft Edge";v="132"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "x-correlation-id": "89SHW4",
        "x-initiated-at": "2025-01-27T16:40:54.521Z"
    }
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    if config.common_config.basic_config["proxy"]["http_proxy"]:
        proxies = {"http://": config.common_config.basic_config["proxy"]["http_proxy"], "https://": config.common_config.basic_config["proxy"]["http_proxy"]}
    else:
        proxies = None
    round_nai += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['nai_key'])
    if round_nai >= list_length:
        round_nai = 0
    async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
        response = await client.post(url=f'{url}/ai/generate-image', json=payload, headers=headers)
        response.raise_for_status()
        zip_content = response.content
        zip_file = io.BytesIO(zip_content)
        with zipfile.ZipFile(zip_file, 'r') as zf:
            file_names = zf.namelist()
            if not file_names:
                raise ValueError("The zip archive is empty.")
            file_name = file_names[0]
            if not file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                raise ValueError("The zip archive does not contain an image file.")
            image_data = zf.read(file_name)
            if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
                try:
                    check = await pic_audit_standalone(base64.b64encode(image_data).decode('utf-8'), return_none=True,url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
                    if check:
                        return False
                except Exception as e:
                    print(f"审核api失效,为保证安全已禁止画图请求: {e}")
                    return f"审核api失效,为保证安全已禁止画图请求: {e}"
            with open(path, 'wb') as img_file:
                img_file.write(image_data)
    return path


async def SdreDraw(prompt, path, config, groupid, b64_in, args):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    args = args
    super_width, super_height = await get_image_dimensions(b64_in)
    super_width, super_height = process_image_dimensions(super_width, super_height, max_area=sd_max_size, min_area=768*768, divisible_by=8)
    width = int(args.get('w', super_width) if args.get('w', super_width) > 0 else super_width) if isinstance(args, dict) else super_width
    height = int(args.get('h', super_height) if args.get('h', super_height) > 0 else super_height) if isinstance(args, dict) else super_height
    denoising_strength = float(
        args.get('d', default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7) 
        if isinstance(args, dict) else 
        (default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7)
    )
    steps = min(int(args.get('steps', default_args.get('steps', 15)) if isinstance(args, dict) else default_args.get('steps', 15)) if isinstance(default_args, dict) else 15, 35)

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1064
        height = 1064
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1536
        height = 1024
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 1024
        height = 1536
    
    width, height = process_image_dimensions(width, height, max_area=sd_max_size, divisible_by=8)

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    sampler = str(args.get('sampler', default_args.get('sampler', 'Restart')) if isinstance(args, dict) else default_args.get('sampler', 'Restart') if isinstance(default_args, dict) else 'Restart')
    scheduler = str(args.get('scheduler', default_args.get('scheduler', 'Align Your Steps')) if isinstance(args, dict) else default_args.get('scheduler', 'Align Your Steps') if isinstance(default_args, dict) else 'Align Your Steps')
    cfg = float(args.get('cfg', default_args.get('cfg', 6.5)) if isinstance(args, dict) else default_args.get('cfg', 6.5) if isinstance(default_args, dict) else 6.5)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False
    
    payload = {
        "init_images": [b64_in],
        "denoising_strength": denoising_strength,
        "enable_hr": 'true',
        "hr_scale": 1.5,
        "hr_second_pass_steps": 15,
        "hr_upscaler": 'SwinIR_4x',
        "prompt": positive,
        "negative_prompt": negative,
        "seed": -1,
        "batch_size": 1,
        "n_iter": 1,
        "steps": steps,
        "save_images": if_save,
        "cfg_scale": cfg,
        "width": width,
        "height": height,
        "restore_faces": False,
        "tiling": False,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "clip_skip_steps": 2,
        "override_settings": {
            "CLIP_stop_at_last_layers": 2,
            "sd_model_checkpoint": ckpt,  # 指定大模型
        },
        "override_settings_restore_afterwards": False,
    }  # manba out
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    round_sd += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['sdUrl'])
    if round_sd >= list_length:
        round_sd = 0
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.post(url=f'{url}/sdapi/v1/img2img', json=payload, headers=headers)
    r = response.json()
    if 'images' not in r or len(r['images']) == 0:
        return None
    # 我的建议是，直接返回base64，让它去审查
    b64 = r['images'][0]
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        try:
            check = await pic_audit_standalone(b64, return_none=True, url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
            if check:
                return False
        except Exception as e:
            print(f"审核api失效,为保证安全已禁止画图请求: {e}")
            return f"审核api失效,为保证安全已禁止画图请求: {e}"
    image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
    # image = Image.open(io.BytesIO(base64.b64decode(p)))
    image.save(f'{path}')
    # image.save(f'{path}')
    return path


async def SdDraw0(prompt, path, config, groupid, args):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    args = args
    width = int(args.get('w', sd_w) if args.get('w', sd_w) > 0 else sd_w) if isinstance(args, dict) else sd_w
    height = int(args.get('h', sd_h) if args.get('h', sd_h) > 0 else sd_h) if isinstance(args, dict) else sd_h
    denoising_strength = float(
        args.get('d', default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7) 
        if isinstance(args, dict) else 
        (default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7)
    )
    steps = min(int(args.get('steps', default_args.get('steps', 15)) if isinstance(args, dict) else default_args.get('steps', 15)) if isinstance(default_args, dict) else 15, 35)

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1064
        height = 1064
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1536
        height = 1024
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 1024
        height = 1536
    
    width, height = process_image_dimensions(width, height, max_area=sd_max_size, divisible_by=8)

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    sampler = str(args.get('sampler', default_args.get('sampler', 'Restart')) if isinstance(args, dict) else default_args.get('sampler', 'Restart') if isinstance(default_args, dict) else 'Restart')
    scheduler = str(args.get('scheduler', default_args.get('scheduler', 'Align Your Steps')) if isinstance(args, dict) else default_args.get('scheduler', 'Align Your Steps') if isinstance(default_args, dict) else 'Align Your Steps')
    cfg = float(args.get('cfg', default_args.get('cfg', 6.5)) if isinstance(args, dict) else default_args.get('cfg', 6.5) if isinstance(default_args, dict) else 6.5)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False
    
    payload = {
        "denoising_strength": denoising_strength,
        "enable_hr": 'false',
        "hr_scale": 1.5,
        "hr_second_pass_steps": 15,
        "hr_upscaler": 'SwinIR_4x',
        "prompt": positive,
        "negative_prompt": negative,
        "seed": -1,
        "batch_size": 1,
        "n_iter": 1,
        "steps": steps,
        "save_images": if_save,
        "cfg_scale": cfg,
        "width": width,
        "height": height,
        "restore_faces": False,
        "tiling": False,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "clip_skip_steps": 2,
        "override_settings": {
            "CLIP_stop_at_last_layers": 2,
            "sd_model_checkpoint": ckpt,  # 指定大模型
        },
        "override_settings_restore_afterwards": False,
    }  # manba out
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    round_sd += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['sdUrl'])
    if round_sd >= list_length:
        round_sd = 0
        
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    if apikey:
        headers=eridanus_headers
    #print(payload)
    #print(headers)
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.post(url=f'{url}/sdapi/v1/txt2img', json=payload, headers=headers)
    r = response.json()

    b64 = r['images'][0]
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        try:
            check = await pic_audit_standalone(b64, return_none=True, url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
            if check:
                return False
        except Exception as e:
            print(f"审核api失效,为保证安全已禁止画图请求: {e}")
            return f"审核api失效,为保证安全已禁止画图请求: {e}"
    image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
    # image = Image.open(io.BytesIO(base64.b64decode(p)))
    image.save(f'{path}')
    # image.save(f'{path}')
    return path


async def getloras(config):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }

    url = f'{url}/sdapi/v1/loras'
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.get(url, headers=headers)
        r = response.json()
        result_lines = [f'<lora:{lora.get("name", "未知")}:1.0>,' for lora in r]
        result = '以下是可用的lora：\n' + '\n'.join(result_lines)
        return result


async def ckpt2(model, config):
    global ckpt
    ckpt = model
    config.ai_generated_art.config["ai绘画"]["sd默认启动模型"] = model
    config.save_yaml("config",plugin_name="ai_generated_art")


async def getcheckpoints(config):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    url = f'{url}/sdapi/v1/sd-models'

    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.get(url, headers=headers)
        r = response.json()
        model_lines = [f'{model.get("model_name", "未知")}.safetensors' for model in r]
        result = f'当前底模: {ckpt}\n以下是可用的底模：\n' + '\n'.join(model_lines)
        return result

async def n4re0(prompt, path, groupid, config, b64_in, args):
    global round_nai
    super_width, super_height = await get_image_dimensions(b64_in)
    super_width, super_height = process_image_dimensions(super_width, super_height, resolution_options=((1024,1024), (1216,832), (832,1216)))
    width = int(args.get('w', super_width) if args.get('w', super_width) > 0 else super_width) if isinstance(args, dict) else super_width
    height = int(args.get('h', super_height) if args.get('h', super_height) > 0 else super_height) if isinstance(args, dict) else super_height
    args = args
    url = "https://image.novelai.net"
    denoising_strength = float(
        args.get('d', default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7) 
        if isinstance(args, dict) else 
        (default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7)
    )
    nai_sampler = str(args.get('nai-sampler', default_args.get('nai-sampler', 'k_euler_ancestral')) if isinstance(args, dict) else default_args.get('nai-sampler', 'k_euler_ancestral') if isinstance(default_args, dict) else 'k_euler_ancestral')
    nai_scheduler = str(args.get('nai-scheduler', default_args.get('nai-scheduler', 'karras')) if isinstance(args, dict) else default_args.get('nai-scheduler', 'karras') if isinstance(default_args, dict) else 'karras')
    nai_cfg = float(args.get('nai-cfg', default_args.get('nai-cfg', 5)) if isinstance(args, dict) else default_args.get('nai-cfg', 5) if isinstance(default_args, dict) else 5)

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1024
        height = 1024
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1216
        height = 832
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 832
        height = 1216

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    nai_cfg = float(args.get('nai-cfg', default_args.get('nai-cfg', 5)) if isinstance(args, dict) else default_args.get('nai-cfg', 5) if isinstance(default_args, dict) else 5)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False

    payload = {
        "input": positive,
        "model": "nai-diffusion-4-curated-preview",
        "action": "img2img",
        "parameters": {
            "params_version": 3,
            "width": width,
            "height": height,
            "scale": nai_cfg,
            "sampler": nai_sampler,
            "steps": 23,
            "n_samples": 1,
            "strength": denoising_strength,
            "noise": 0.2,
            "ucPreset": 0,
            "qualityToggle": True,
            "dynamic_thresholding": False,
            "controlnet_strength": 1,
            "legacy": False,
            "add_original_image": True,
            "cfg_rescale": 0,
            "noise_schedule": nai_scheduler,
            "legacy_v3_extend": False,
            "skip_cfg_above_sigma": None,
            "use_coords": False,
            "seed": random.randint(0, 2 ** 32 - 1),
            "image": b64_in,
            "characterPrompts": [],
            "extra_noise_seed": random.randint(0, 2 ** 32 - 1),
            "v4_prompt": {
                "caption": {
                    "base_caption": positive,
                    "char_captions": []
                },
                "use_coords": False,
                "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative,
                    "char_captions": []
                }
            },
            "negative_prompt": negative,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
            "deliberate_euler_ancestral_bug": False,
            "prefer_brownian": True
        }
    }

    headers = {
        "Authorization": f"Bearer {config.ai_generated_art.config['ai绘画']['nai_key'][int(round_nai)]}",
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://novelai.net",
        "priority": "u=1, i",
        "referer": "https://novelai.net/",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Microsoft Edge";v="132"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "x-correlation-id": "89SHW4",
        "x-initiated-at": "2025-01-27T16:40:54.521Z"
    }
    if config.common_config.basic_config["proxy"]["http_proxy"]:
        proxies = {"http://": config.common_config.basic_config["proxy"]["http_proxy"], "https://": config.common_config.basic_config["proxy"]["http_proxy"]}
    else:
        proxies = None
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    round_nai += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['nai_key'])
    if round_nai >= list_length:
        round_nai = 0
    async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
        response = await client.post(url=f'{url}/ai/generate-image', json=payload, headers=headers)
        response.raise_for_status()
        zip_content = response.content
        zip_file = io.BytesIO(zip_content)
        with zipfile.ZipFile(zip_file, 'r') as zf:
            file_names = zf.namelist()
            if not file_names:
                raise ValueError("The zip archive is empty.")
            file_name = file_names[0]
            if not file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                raise ValueError("The zip archive does not contain an image file.")
            image_data = zf.read(file_name)
            if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
                try:
                    check = await pic_audit_standalone(base64.b64encode(image_data).decode('utf-8'), return_none=True,url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
                    if check:
                        return False
                except Exception as e:
                    print(f"审核api失效,为保证安全已禁止画图请求: {e}")
                    return f"审核api失效,为保证安全已禁止画图请求: {e}"
            with open(path, 'wb') as img_file:
                img_file.write(image_data)
    return path

async def n3re0(prompt, path, groupid, config, b64_in, args):
    global round_nai
    super_width, super_height = await get_image_dimensions(b64_in)
    super_width, super_height = process_image_dimensions(super_width, super_height, resolution_options=((1024,1024), (1216,832), (832,1216)))
    width = int(args.get('w', super_width) if args.get('w', super_width) > 0 else super_width) if isinstance(args, dict) else super_width
    height = int(args.get('h', super_height) if args.get('h', super_height) > 0 else super_height) if isinstance(args, dict) else super_height
    args = args
    url = "https://image.novelai.net"
    denoising_strength = float(
        args.get('d', default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7) 
        if isinstance(args, dict) else 
        (default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7)
    )
    nai_sampler = str(args.get('nai-sampler', default_args.get('nai-sampler', 'k_euler_ancestral')) if isinstance(args, dict) else default_args.get('nai-sampler', 'k_euler_ancestral') if isinstance(default_args, dict) else 'k_euler_ancestral')
    nai_scheduler = str(args.get('nai-scheduler', default_args.get('nai-scheduler', 'karras')) if isinstance(args, dict) else default_args.get('nai-scheduler', 'karras') if isinstance(default_args, dict) else 'karras')
    nai_cfg = float(args.get('nai-cfg', default_args.get('nai-cfg', 5)) if isinstance(args, dict) else default_args.get('nai-cfg', 5) if isinstance(default_args, dict) else 5)

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1024
        height = 1024
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1216
        height = 832
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 832
        height = 1216

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False

    payload = {
        "input": positive,
        "model": "nai-diffusion-3",
        "action": "img2img",
        "parameters": {
            "params_version": 3,
            "width": width,
            "height": height,
            "scale": nai_cfg,
            "sampler": nai_sampler,
            "steps": 23,
            "n_samples": 1,
            "strength":denoising_strength,
            "noise":0.2,
            "ucPreset": 0,
            "qualityToggle": True,
            "dynamic_thresholding": False,
            "controlnet_strength": 1,
            "legacy": False,
            "add_original_image": True,
            "cfg_rescale": 0,
            "noise_schedule": nai_scheduler,
            "legacy_v3_extend": False,
            "skip_cfg_above_sigma": None,
            "use_coords": False,
            "seed": random.randint(0, 2 ** 32 - 1),
            "image": b64_in,
            "characterPrompts": [],
            "extra_noise_seed": random.randint(0, 2 ** 32 - 1),
            "negative_prompt": negative,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
            "deliberate_euler_ancestral_bug": False,
            "prefer_brownian": True
        }
    }

    headers = {
        "Authorization": f"Bearer {config.ai_generated_art.config['ai绘画']['nai_key'][int(round_nai)]}",
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://novelai.net",
        "priority": "u=1, i",
        "referer": "https://novelai.net/",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Microsoft Edge";v="132"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "x-correlation-id": "89SHW4",
        "x-initiated-at": "2025-01-27T16:40:54.521Z"
    }
    if config.common_config.basic_config["proxy"]["http_proxy"]:
        proxies = {"http://": config.common_config.basic_config["proxy"]["http_proxy"], "https://": config.common_config.basic_config["proxy"]["http_proxy"]}
    else:
        proxies = None
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    round_nai += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['nai_key'])
    if round_nai >= list_length:
        round_nai = 0
    async with httpx.AsyncClient(timeout=1000, proxies=proxies) as client:
        response = await client.post(url=f'{url}/ai/generate-image', json=payload, headers=headers)
        response.raise_for_status()
        zip_content = response.content
        zip_file = io.BytesIO(zip_content)
        with zipfile.ZipFile(zip_file, 'r') as zf:
            file_names = zf.namelist()
            if not file_names:
                raise ValueError("The zip archive is empty.")
            file_name = file_names[0]
            if not file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                raise ValueError("The zip archive does not contain an image file.")
            image_data = zf.read(file_name)
            if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
                try:
                    check = await pic_audit_standalone(base64.b64encode(image_data).decode('utf-8'), return_none=True,url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
                    if check:
                        return False
                except Exception as e:
                    print(f"审核api失效,为保证安全已禁止画图请求: {e}")
                    return f"审核api失效,为保证安全已禁止画图请求: {e}"
            with open(path, 'wb') as img_file:
                img_file.write(image_data)
    return path

async def SdmaskDraw(prompt, path, config, groupid, b64_in, args, mask_base64):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    args = args
    super_width, super_height = await get_image_dimensions(b64_in)
    super_width, super_height = process_image_dimensions(super_width, super_height, max_area=sd_max_size, min_area=768*768, divisible_by=8)
    width = int(args.get('w', super_width) if args.get('w', super_width) > 0 else super_width) if isinstance(args, dict) else super_width
    height = int(args.get('h', super_height) if args.get('h', super_height) > 0 else super_height) if isinstance(args, dict) else super_height
    denoising_strength = float(
        args.get('d', default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7) 
        if isinstance(args, dict) else 
        (default_args.get('d', 0.7) if isinstance(default_args, dict) else 0.7)
    )
    steps = min(int(args.get('steps', default_args.get('steps', 15)) if isinstance(args, dict) else default_args.get('steps', 15)) if isinstance(default_args, dict) else 15, 35)

    if "方" in prompt:
        prompt = prompt.replace("方", "")
        width = 1064
        height = 1064
    if "横" in prompt:
        prompt = prompt.replace("横", "")
        width = 1536
        height = 1024
    if "竖" in prompt:
        prompt = prompt.replace("竖", "")
        width = 1024
        height = 1536
    
    width, height = process_image_dimensions(width, height, max_area=sd_max_size, divisible_by=8)

    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
    positive, _ = await replace_wildcards(positive)
    sampler = str(args.get('sampler', default_args.get('sampler', 'Restart')) if isinstance(args, dict) else default_args.get('sampler', 'Restart') if isinstance(default_args, dict) else 'Restart')
    scheduler = str(args.get('scheduler', default_args.get('scheduler', 'Align Your Steps')) if isinstance(args, dict) else default_args.get('scheduler', 'Align Your Steps') if isinstance(default_args, dict) else 'Align Your Steps')
    cfg = float(args.get('cfg', default_args.get('cfg', 6.5)) if isinstance(args, dict) else default_args.get('cfg', 6.5) if isinstance(default_args, dict) else 6.5)

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw"):
        if check_censored(positive, censored_words):
            return False

    payload = {
        "init_images": [b64_in],
        "mask": mask_base64,
        "mask_blur": 4,  # 边缘模糊
        "inpaint_full_res": False,  # 更高分辨率修复 耗费算力，一般显卡建议关闭
        "inpaint_full_res_padding": 4,  # 小到中等大小的修复区域 建议 4 - 10 大型修复区域建议 10 - 20
        "inpainting_mask_invert": 1,  # 0 则反转蒙版
        "denoising_strength": denoising_strength,
        "enable_hr": 'true',
        "hr_scale": 1.5,
        "hr_second_pass_steps": 15,
        "hr_upscaler": 'SwinIR_4x',
        "prompt": positive,
        "negative_prompt": negative,
        "seed": -1,
        "batch_size": 1,
        "n_iter": 1,
        "steps": steps,
        "save_images": if_save,
        "cfg_scale": cfg,
        "width": width,
        "height": height,
        "restore_faces": False,
        "tiling": False,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "clip_skip_steps": 2,
        "override_settings": {
            "CLIP_stop_at_last_layers": 2,
            "sd_model_checkpoint": ckpt,  # 指定大模型
        },
        "override_settings_restore_afterwards": False,
    }  # manba out
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"
    round_sd += 1
    list_length = len(config.ai_generated_art.config['ai绘画']['sdUrl'])
    if round_sd >= list_length:
        round_sd = 0
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.post(url=f'{url}/sdapi/v1/img2img', json=payload, headers=headers)
    r = response.json()
    if 'images' not in r or len(r['images']) == 0:
        return None
    # 我的建议是，直接返回base64，让它去审查
    b64 = r['images'][0]
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        try:
            check = await pic_audit_standalone(b64, return_none=True, url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
            if check:
                return False
        except Exception as e:
            print(f"审核api失效,为保证安全已禁止画图请求: {e}")
            return f"审核api失效,为保证安全已禁止画图请求: {e}"
    image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
    # image = Image.open(io.BytesIO(base64.b64decode(p)))
    image.save(f'{path}')
    # image.save(f'{path}')
    return path

async def getsampler(config):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    url = f'{url}/sdapi/v1/samplers'    

    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.get(url, headers=headers)
        r = response.json()
        try:
            names_list = [item["name"] for item in r if "name" in item]
            if names_list:
                return f'\n'.join(names_list)
        except TypeError:
            pass
        if isinstance(r, dict) and "body" in r:
            names_list = [item["name"] for item in r["body"] if "name" in item]
            return f'\n'.join(names_list)
    
async def getscheduler(config):
    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    url = f'{url}/sdapi/v1/schedulers'
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.get(url, headers=headers)
        r = response.json()
        label_list = [item["label"] for item in r if "label" in item]
        result = f'\n'.join(label_list)
        return result

async def interrupt(config):
    global round_sd
    try:
        adjusted_index = int(round_sd) - 1
        sdUrls = config.ai_generated_art.config["ai绘画"]["sdUrl"]
        if adjusted_index < 0 or adjusted_index >= len(sdUrls):
            raise IndexError("索引超出范围，请检查 round_sd 的值。")
        url = sdUrls[adjusted_index]
        url, auth_header = parse_custom_url_auth(url)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth_header
        }
        post_data = {
            "114514": "1919810"
        }
        url = f'{url}/sdapi/v1/interrupt'
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=post_data, headers=headers)
            response.raise_for_status()
            return response.json()
    except (ValueError, IndexError) as e:
        print(f"参数错误: {e}")
        return None
    except httpx.HTTPError as e:
        print(f"请求失败: {e}")
        return None
    
async def skipsd(config):
    global round_sd
    try:
        adjusted_index = int(round_sd) - 1
        sdUrls = config.ai_generated_art.config["ai绘画"]["sdUrl"]
        if adjusted_index < 0 or adjusted_index >= len(sdUrls):
            raise IndexError("索引超出范围，请检查 round_sd 的值。")
        url = sdUrls[adjusted_index]
        url, auth_header = parse_custom_url_auth(url)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth_header
        }
        post_data = {
            "114514": "1919810"
        }
        url = f'{url}/sdapi/v1/skip'
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=post_data, headers=headers)
            response.raise_for_status()
            return response.json()
    except (ValueError, IndexError) as e:
        print(f"参数错误: {e}")
        return None
    except httpx.HTTPError as e:
        print(f"请求失败: {e}")
        return None
    
async def SdOutpaint(prompt, path, config, groupid, b64_in, args):
    """
    使用纯 NumPy 分形噪声和内容感知插值优化扩图填充
    prompt中含 --left 1145/--right 1145/--up 1145/--down 1145这种就会触发扩图
    setre中的--d --ns --nf参数都会影响扩图的多样性
    --ns默认是5,代表扩图初始区域与原图边缘的相似度,--nf默认是20,代表离原图边缘越远图像和原图边缘的差异度，两个都是数值越大差异越大
    扩图算法的原理是根据边缘颜色对扩图区域进行延伸，然后利用原图边缘的轮廓信息进行插值填充，并附加噪声作为底图，最后经过蒙版后交给潜空间处理
    扩图可以理解成是从局部重绘拓展而来
    如果prompt中包含--full且处于扩图模式,直接将扩展后的图像调用SdreDraw进行全图重绘
    --overmask参数代表扩图对原图的覆盖长度,默认64
    """
    def extract_outpaint_params(prompt):
        patterns = {
            "left": r"--left\s*(\d*)",
            "right": r"--right\s*(\d*)",
            "up": r"--up\s*(\d*)",
            "down": r"--down\s*(\d*)",
            "full": r"--full"  # 新增对 --full 的检测
        }
        params = {"left": 0, "right": 0, "up": 0, "down": 0, "full": False}
        for direction, pattern in patterns.items():
            match = re.search(pattern, prompt)
            if direction == "full" and match:
                params["full"] = True
                prompt = re.sub(pattern, "", prompt).strip()
            elif match and direction != "full":
                params[direction] = int(match.group(1)) if match.group(1) else 0
                prompt = re.sub(pattern, "", prompt).strip()
        return params, prompt

    outpaint_params, cleaned_prompt = extract_outpaint_params(prompt)

    if all(value == 0 for value in list(outpaint_params.values())[:4]):  # 检查 left, right, up, down
        return await SdreDraw(cleaned_prompt, path, config, groupid, b64_in, args)

    global round_sd
    url = config.ai_generated_art.config["ai绘画"]["sdUrl"][int(round_sd)]
    OVERMASK = int(args.get('overmask', default_args.get('overmask', 64)) if isinstance(args, dict) else default_args.get('overmask', 64)) if isinstance(default_args, dict) else 64

    orig_width, orig_height = await get_image_dimensions(b64_in)
    canvas_width = orig_width + outpaint_params["left"] + outpaint_params["right"]
    canvas_height = orig_height + outpaint_params["up"] + outpaint_params["down"]

    # 参数配置
    denoising_strength = float(args.get('d', 0.75) if isinstance(args, dict) else 0.75)
    steps = min(int(args.get('steps', default_args.get('steps', 15)) if isinstance(args, dict) else default_args.get('steps', 15)) if isinstance(default_args, dict) else 15, 35)
    positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
    negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
    positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", cleaned_prompt) if isinstance(positive, str) else str(cleaned_prompt)
    positive, _ = await replace_wildcards(positive)
    sampler = str(args.get('sampler', default_args.get('sampler', 'Restart')) if isinstance(args, dict) else default_args.get('sampler', 'Restart') if isinstance(default_args, dict) else 'Restart')
    scheduler = str(args.get('scheduler', default_args.get('scheduler', 'Align Your Steps')) if isinstance(args, dict) else default_args.get('scheduler', 'Align Your Steps') if isinstance(default_args, dict) else 'Align Your Steps')
    cfg = float(args.get('cfg', default_args.get('cfg', 6.5)) if isinstance(args, dict) else default_args.get('cfg', 6.5) if isinstance(default_args, dict) else 6.5)
    noise_start = float(args.get('ns', default_args.get('ns', 5)) if isinstance(args, dict) else default_args.get('ns', 5)) if isinstance(default_args, dict) else 5
    noise_fact = float(args.get('nf', default_args.get('nf', 20)) if isinstance(args, dict) else default_args.get('nf', 20)) if isinstance(default_args, dict) else 20
    
    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and check_censored(positive, censored_words):
        return False

    # 初始化画布
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    with Image.open(io.BytesIO(base64.b64decode(b64_in.split(',')[1] if ',' in b64_in else b64_in))) as img:
        img = img.convert("RGBA")
        offset_x = outpaint_params["left"]
        offset_y = outpaint_params["up"]
        canvas.paste(img, (offset_x, offset_y))

    # 转换为 NumPy 数组
    img_array = np.array(canvas, dtype=np.float32)
    orig_region = img_array[offset_y:offset_y + orig_height, offset_x:offset_x + orig_width]

    # 生成纯 NumPy 分形噪声
    def generate_fractal_noise(shape, octaves=4, persistence=0.5):
        noise_array = np.zeros(shape)
        for octave in range(octaves):
            freq = 2 ** octave
            scale = persistence ** octave
            noise_base = np.random.uniform(-1, 1, (shape[0] // freq + 1, shape[1] // freq + 1))
            y = np.linspace(0, noise_base.shape[0] - 1, shape[0])
            x = np.linspace(0, noise_base.shape[1] - 1, shape[1])
            yv, xv = np.meshgrid(y, x, indexing='ij')
            noise_interp = np.zeros(shape)
            for i in range(shape[0]):
                for j in range(shape[1]):
                    y0, x0 = int(yv[i, j]), int(xv[i, j])
                    y1, x1 = min(y0 + 1, noise_base.shape[0] - 1), min(x0 + 1, noise_base.shape[1] - 1)
                    wy = yv[i, j] - y0
                    wx = xv[i, j] - x0
                    noise_interp[i, j] = (
                        noise_base[y0, x0] * (1 - wy) * (1 - wx) +
                        noise_base[y1, x0] * wy * (1 - wx) +
                        noise_base[y0, x1] * (1 - wy) * wx +
                        noise_base[y1, x1] * wy * wx
                    )
            noise_array += noise_interp * scale
        noise_array = (noise_array - np.min(noise_array)) / (np.max(noise_array) - np.min(noise_array)) * 255
        return noise_array

    # 内容感知填充函数
    def content_aware_fill(target_region, ref_region, direction, size):
        h, w, _ = target_region.shape
        noise_map = generate_fractal_noise((h, w))
        for y in range(h):
            for x in range(w):
                if direction == "left":
                    dist = size - x - 1
                    ref_x = 0
                    ref_y = y
                elif direction == "right":
                    dist = x
                    ref_x = -1
                    ref_y = y
                elif direction == "up":
                    dist = size - y - 1
                    ref_x = x
                    ref_y = 0
                else:  # down
                    dist = y
                    ref_x = x
                    ref_y = -1
                base_color = ref_region[ref_y, ref_x]
                fade_factor = dist / size
                noise_scale = noise_start + noise_fact * fade_factor
                noise_value = noise_map[y, x] * noise_scale / 255.0
                target_region[y, x] = base_color * (1 - fade_factor) + noise_value * fade_factor
                target_region[y, x] = np.clip(target_region[y, x] + np.random.normal(0, noise_scale, 4), 0, 255)

    # 填充扩展区域
    if outpaint_params["left"] > 0:
        left_region = img_array[offset_y:offset_y + orig_height, :outpaint_params["left"]]
        content_aware_fill(left_region, orig_region, "left", outpaint_params["left"])
        img_array[offset_y:offset_y + orig_height, :outpaint_params["left"]] = left_region

    if outpaint_params["right"] > 0:
        right_region = img_array[offset_y:offset_y + orig_height, offset_x + orig_width:canvas_width]
        content_aware_fill(right_region, orig_region, "right", outpaint_params["right"])
        img_array[offset_y:offset_y + orig_height, offset_x + orig_width:canvas_width] = right_region

    if outpaint_params["up"] > 0:
        up_region = img_array[:outpaint_params["up"], offset_x:offset_x + orig_width]
        content_aware_fill(up_region, orig_region, "up", outpaint_params["up"])
        img_array[:outpaint_params["up"], offset_x:offset_x + orig_width] = up_region

    if outpaint_params["down"] > 0:
        down_region = img_array[offset_y + orig_height:canvas_height, offset_x:offset_x + orig_width]
        content_aware_fill(down_region, orig_region, "down", outpaint_params["down"])
        img_array[offset_y + orig_height:canvas_height, offset_x:offset_x + orig_width] = down_region

    # 处理角落
    def fill_corner(corner_region, ref_color, size_y, size_x, direction_y, direction_x):
        noise_map = generate_fractal_noise((corner_region.shape[0], corner_region.shape[1]))
        for y in range(corner_region.shape[0]):
            for x in range(corner_region.shape[1]):
                dist_y = y if direction_y == "down" else size_y - y - 1
                dist_x = x if direction_x == "right" else size_x - x - 1
                dist = max(dist_x, dist_y)
                fade_factor = dist / max(size_x, size_y)
                noise_scale = noise_start + noise_fact * fade_factor
                noise_value = noise_map[y, x] * noise_scale / 255.0
                corner_region[y, x] = ref_color * (1 - fade_factor) + noise_value * fade_factor
                corner_region[y, x] = np.clip(corner_region[y, x] + np.random.normal(0, noise_scale, 4), 0, 255)

    if outpaint_params["left"] > 0 and outpaint_params["up"] > 0:
        corner = img_array[:outpaint_params["up"], :outpaint_params["left"]]
        fill_corner(corner, orig_region[0, 0], outpaint_params["up"], outpaint_params["left"], "up", "left")
        img_array[:outpaint_params["up"], :outpaint_params["left"]] = corner

    if outpaint_params["left"] > 0 and outpaint_params["down"] > 0:
        corner = img_array[offset_y + orig_height:canvas_height, :outpaint_params["left"]]
        fill_corner(corner, orig_region[-1, 0], outpaint_params["down"], outpaint_params["left"], "down", "left")
        img_array[offset_y + orig_height:canvas_height, :outpaint_params["left"]] = corner

    if outpaint_params["right"] > 0 and outpaint_params["up"] > 0:
        corner = img_array[:outpaint_params["up"], offset_x + orig_width:canvas_width]
        fill_corner(corner, orig_region[0, -1], outpaint_params["up"], outpaint_params["right"], "up", "right")
        img_array[:outpaint_params["up"], offset_x + orig_width:canvas_width] = corner

    if outpaint_params["right"] > 0 and outpaint_params["down"] > 0:
        corner = img_array[offset_y + orig_height:canvas_height, offset_x + orig_width:canvas_width]
        fill_corner(corner, orig_region[-1, -1], outpaint_params["down"], outpaint_params["right"], "down", "right")
        img_array[offset_y + orig_height:canvas_height, offset_x + orig_width:canvas_width] = corner

    # 转换回图像并编码为 Base64
    canvas = Image.fromarray(img_array.astype(np.uint8))
    buffered = io.BytesIO()
    canvas.save(buffered, format="PNG")
    canvas_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    # 如果有 --full，直接调用 SdreDraw 处理扩展后的图像
    if outpaint_params["full"]:
        return await SdreDraw(cleaned_prompt, path, config, groupid, canvas_data, args)

    # 生成蒙版（仅在非 --full 模式下执行）
    mask = Image.new("L", (canvas_width, canvas_height), 0)
    draw = ImageDraw.Draw(mask)
    if outpaint_params["left"] > 0:
        draw.rectangle([0, 0, outpaint_params["left"] + OVERMASK, canvas_height], fill=255)
    if outpaint_params["right"] > 0:
        draw.rectangle([orig_width + outpaint_params["left"] - OVERMASK, 0, canvas_width, canvas_height], fill=255)
    if outpaint_params["up"] > 0:
        draw.rectangle([0, 0, canvas_width, outpaint_params["up"] + OVERMASK], fill=255)
    if outpaint_params["down"] > 0:
        draw.rectangle([0, orig_height + outpaint_params["up"] - OVERMASK, canvas_width, canvas_height], fill=255)
    
    buffered = io.BytesIO()
    mask.save(buffered, format="PNG")
    mask_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    super_width, super_height = process_image_dimensions(canvas_width, canvas_height, max_area=sd_max_size, min_area=768*768, divisible_by=8)
    super_width1 = int(args.get('w', super_width) if args.get('w', super_width) > 0 else super_width) if isinstance(args, dict) else super_width
    super_height1 = int(args.get('h', super_height) if args.get('h', super_height) > 0 else super_height) if isinstance(args, dict) else super_height

    payload = {
        "init_images": [canvas_data],
        "mask": mask_data,
        "denoising_strength": denoising_strength,
        "prompt": positive,
        "negative_prompt": negative,
        "width": super_width1,
        "height": super_height1,
        "steps": steps,
        "cfg_scale": cfg,
        "mask_blur": 8,
        "inpainting_fill": 0,
        "inpaint_full_res": True,
        "sampler_name": sampler,
        "enable_hr": "false",
        "hr_scale": 1.5,
        "hr_second_pass_steps": 15,
        "hr_upscaler": "SwinIR_4x",
        "seed": -1,
        "batch_size": 1,
        "n_iter": 1,
        "save_images": if_save,
        "restore_faces": False,
        "tiling": False,
        "scheduler": scheduler,
        "clip_skip_steps": 2,
        "override_settings": {
            "CLIP_stop_at_last_layers": 2,
            "sd_model_checkpoint": ckpt,
        },
        "override_settings_restore_afterwards": False,
    }

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and not config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        print("审核api未配置,为保证安全已禁止画图请求")
        return "审核api未配置,为保证安全已禁止画图请求"

    round_sd += 1
    list_length = len(config.ai_generated_art.config["ai绘画"]["sdUrl"])
    if round_sd >= list_length:
        round_sd = 0
        
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }

    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.post(url=f'{url}/sdapi/v1/img2img', json=payload, headers=headers)
    
    r = response.json()
    if 'images' not in r or len(r['images']) == 0:
        return None

    b64 = r['images'][0]

    if groupid not in allow_nsfw_groups and aiDrawController.get("禁止nsfw") and config.ai_generated_art.config['ai绘画']['sd审核和反推api']:
        try:
            check = await pic_audit_standalone(b64, return_none=True, url=config.ai_generated_art.config['ai绘画']['sd审核和反推api'])
            if check:
                return False
        except Exception as e:
            print(f"审核api失效,为保证安全已禁止画图请求: {e}")
            return f"审核api失效,为保证安全已禁止画图请求: {e}"

    image = Image.open(io.BytesIO(base64.b64decode(b64)))
    image.save(f'{path}')
    return path

async def get_img_info(base64, api):
    async with httpx.AsyncClient(timeout=None, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        api, auth_header = parse_custom_url_auth(api)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth_header
        }
        response = await client.post(url=f'{api}/sdapi/v1/png-info', json={"image": base64}, headers=headers)
        data = response.json()
        formatted_json = json.dumps(data, indent=4, ensure_ascii=False)
        return formatted_json
