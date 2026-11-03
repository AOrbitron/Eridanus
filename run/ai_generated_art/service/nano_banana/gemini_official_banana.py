import base64
import os
import random
import traceback
from pathlib import Path
from typing import Dict, Any

import httpx
from framework_common.framework_util.reply_config import active_llm_config

from run.ai_generated_art.service.nano_banana.apikey_iterator import RoundRobinSelector

api_key_selector = None
async def call_gemini_api(contents, config) -> Dict[str, Any]:
    model_selected=config.ai_generated_art.config["ai绘画"]["nano_banana_config"]["model"]
    if config.ai_generated_art.config["ai绘画"]["nano_banana_config"]["base_url"]:
        url = f"{config.ai_generated_art.config['ai绘画']['nano_banana_config']['base_url']}/v1beta/models/{model_selected}:generateContent"
    else:
        url = f"{active_llm_config(config)['gemini']['base_url']}/v1beta/models/{model_selected}:generateContent"
    proxy = config.common_config.basic_config["proxy"]["http_proxy"] if config.common_config.basic_config["proxy"][
        "http_proxy"] else None
    proxies = {"http://": proxy, "https://": proxy} if proxy else None

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": "You are a capable drawing assistant. For every conversation with the user, you must output an image. It is crucial to ensure that you generate an image and not return only text."}
            ]
        },
        "contents": [{"parts": contents}],
        "safetySettings": [
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_HATE_SPEECH', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_HARASSMENT', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', "threshold": "BLOCK_None"}
        ],
        "tools": [{"google_search": {}}],
        "generationConfig":
            {"temperature": config.ai_generated_art.config["ai绘画"]["nano_banana_config"]["temperature"],"responseModalities": ["IMAGE"], "imageConfig": {"imageSize": "2K"}}
    }
    global api_key_selector
    api_keys = config.ai_generated_art.config["ai绘画"]["nano_banana_key"]

    if api_key_selector is None:
        api_key_selector = RoundRobinSelector(api_keys)

    api_key = api_key_selector.get_next()
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient(timeout=None, proxies=proxies) as client:
            response = await client.post(url, json=payload, headers=headers)

        print("API响应状态码:", response.status_code)
        response.raise_for_status()
        response_data = response.json()

        candidates = response_data.get("candidates")
        if not candidates:
            feedback = response_data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason")
            if block_reason:
                return {"success": False, "error": f"请求被阻止", "details": f"原因: {block_reason}"}
            raise ValueError("API响应中未包含 'candidates'。")

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts")

        if not parts:
            finish_reason = candidate.get("finishReason")
            if finish_reason:
                error_message = f"内容生成中止"
                details = f"原因: {finish_reason}. 这通常由安全设置或不当内容导致。"
                print(f"API调用失败: {details}")
                return {"success": False, "error": error_message, "details": details}
            else:
                raise ValueError("API响应的候选结果中既未包含 'parts'，也未提供中止原因。")

        base64_data = None
        text_responses = []
        for part in parts:
            if "inlineData" in part and part["inlineData"].get("data"):
                base64_data = part["inlineData"]["data"]
            if "text" in part:
                text_responses.append(part["text"])

        full_text_response = " ".join(text_responses).strip()

        if not base64_data and not full_text_response:
            raise ValueError("API响应既未包含图像数据，也未包含有效的文本。")

        save_path = None
        if base64_data:
            save_path = f"data/pictures/cache/{random.randint(1000, 9999)}.png"
            Path(os.path.dirname(save_path)).mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(base64.b64decode(base64_data))

        return {
            "success": True,
            "result_path": save_path,
            "text": full_text_response,
            "has_image": bool(base64_data)
        }
    except httpx.HTTPStatusError as e:
        error_details = f"HTTP错误 (状态码: {e.response.status_code}): {e.response.text}"
        print(error_details)
        return {"success": False, "error": "API请求失败", "details": error_details}
    except httpx.RequestError as e:
        error_details = f"请求错误: {e}"
        print(error_details)
        return {"success": False, "error": "网络连接或请求配置错误", "details": error_details}
    except (ValueError, KeyError, IndexError) as e:
        error_details = f"解析API响应失败: {e}\n{traceback.format_exc()}"
        print(error_details)
        return {"success": False, "error": "无法解析API响应", "details": error_details}
    except Exception as e:
        error_details = f"未知错误: {e}\n{traceback.format_exc()}"
        print(error_details)
        return {"success": False, "error": "处理过程中发生未知错误", "details": error_details}
