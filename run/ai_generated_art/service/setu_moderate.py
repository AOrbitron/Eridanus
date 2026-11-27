import base64
import httpx
from framework_common.framework_util.yamlLoader import YAMLManager

same_manager = YAMLManager.get_instance()
apikey = str(same_manager.ai_generated_art.config["ai绘画"].get("apikey") or "").strip().strip('"\'“”‘’`')
if apikey.lower().startswith("bearer "):
    apikey = apikey[7:].strip().strip('"\'“”‘’`')
eridanus_headers = {"Authorization": f"Bearer {apikey}"} if apikey and apikey.isascii() else {}

same_manager = YAMLManager.get_instance()
aiDrawController = same_manager.ai_generated_art.config.get("ai绘画")
tag_model = aiDrawController.get("反推和审核使用模型") if aiDrawController else "wd14-vit-v2-git"

'''
反推和审核使用模型可选:'wd14-vit-v2-git'，'wd14-convnext-v2-git'，'wd14-swinv2-v2-git'，'wd-vit-v3-git'，'wd14-convnext-v3-git'，
'wd14-swinv2-v3-git'，'wd14-large-v3-git'，'wd14-eva02-large-v3-git'
前提是你安装的插件是spawner1145的https://github.com/spawner1145/stable-diffusion-webui-wd14-tagger.git
否则只能使用'wd14-vit-v2-git'
'''

def parse_custom_url_auth(input_string: str):
    parts = input_string.split(' ', 1)
    clean_url = parts[0]
    auth_header = ''

    if len(parts) == 2 and parts[1]:
        credentials_string = parts[1]
        credentials_bytes = credentials_string.encode('utf-8')
        encoded_credentials_bytes = base64.b64encode(credentials_bytes)
        encoded_credentials_string = encoded_credentials_bytes.decode('utf-8')
        auth_header = f"Basic {encoded_credentials_string}"

    return clean_url, auth_header

async def pic_audit_standalone(
        img_base64,
        is_return_tags=False,
        audit=False,
        return_none=False,
        url = "http://server.20020026.xyz:7865"
):
    url, auth_header = parse_custom_url_auth(url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": auth_header
    }
    if apikey:
        headers=eridanus_headers
    async def get_caption(payload):
        async with httpx.AsyncClient(timeout=1000) as client:
            try:
                response = await client.post(
                    url=f"{url}/tagger/v1/interrogate",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()  # 抛出异常，如果请求失败
                return response.json()
            except httpx.HTTPStatusError as e:
                print(f"API失败，错误信息: {e.response.status_code}, {e.response.text}")
                return None

    payload = {"image": img_base64, "model": tag_model, "threshold": 0.35}

    resp_dict = await get_caption(payload)

    if not resp_dict:
        return None

    tags = resp_dict["caption"]
    replace_list = ["general", "sensitive", "questionable", "explicit"]
    to_user_list = ["这张图很安全!", "较为安全", "色情", "泰色辣!"]
    possibilities = {}
    to_user_dict = {}
    message = "这是审核结果:\n"

    for i, to_user in zip(replace_list, to_user_list):
        possibilities[i] = tags[i]
        percent = f":{tags[i] * 100:.2f}".rjust(6)
        message += f"[{to_user}{percent}%]\n"
        to_user_dict[to_user] = tags[i]

    value = list(to_user_dict.values())
    value.sort(reverse=True)
    reverse_dict = {v: k for k, v in to_user_dict.items()}
    message += f"最终结果为:{reverse_dict[value[0]].rjust(5)}"
    
    keys = list(tags.keys())
    tags_to_remove = {"general", "sensitive", "questionable", "explicit"}
    filtered_tags = [tag for tag in keys if tag not in tags_to_remove]
    tags_str = ",".join(filtered_tags)

    if return_none:
        value = list(possibilities.values())
        value.sort(reverse=True)
        reverse_dict = {v: k for k, v in possibilities.items()}
        return reverse_dict[value[0]] == "questionable" or reverse_dict[value[0]] == "explicit"

    if is_return_tags:
        return message, tags, tags_str
    if audit:
        return possibilities, message
    return message
