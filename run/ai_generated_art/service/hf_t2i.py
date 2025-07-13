# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import json
import random
import time

import httpx

from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str
from framework_common.utils.utils import parse_arguments
from run.ai_generated_art.service.wildcard import replace_wildcards

logger=get_logger()

positives = '{},rating:general, best quality, very aesthetic, absurdres'
negatives = 'lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, cropped, worst quality, low quality, low score, bad score, average score, signature, watermark, username, blurry'
#positives = '{},masterpiece,best quality,amazing quality,very aesthetic,absurdres,newest,'


same_manager = YAMLManager.get_instance()
#print(same_manager.ai_generated_art.config,type(same_manager.ai_generated_art.config))
aiDrawController = same_manager.ai_generated_art.config.get("ai绘画")
ckpt = aiDrawController.get("sd默认启动模型") if aiDrawController else None
if_save = aiDrawController.get("sd图片是否保存到生图端") if aiDrawController else False
sd_w = int(aiDrawController.get("sd画图默认分辨率", "1024,1536").split(",")[0]) if aiDrawController else 1064
sd_h = int(aiDrawController.get("sd画图默认分辨率", "1024,1536").split(",")[1]) if aiDrawController else 1600
configs = aiDrawController.get("其他默认绘图参数",[])
default_args = {}
for config in configs:
    default_args = parse_arguments(config, default_args)

cookie = "cna=j117HdPDmkoCAXjC3hh/4rjk; ajs_anonymous_id=5aa505b4-8510-47b5-a1e3-6ead158f3375; t=27c49d517b916cf11d961fa3769794dd; uuid_tt_dd=11_99759509594-1710000225471-034528; log_Id_click=16; log_Id_pv=12; log_Id_view=277; xlly_s=1; csrf_session=MTcxMzgzODI5OHxEdi1CQkFFQ180SUFBUkFCRUFBQU12LUNBQUVHYzNSeWFXNW5EQW9BQ0dOemNtWlRZV3gwQm5OMGNtbHVad3dTQUJCNFkwRTFkbXAwV0VVME0wOUliakZwfHNEIp5sKWkjeJWKw1IphSS3e4R_7GyEFoKKuDQuivUs; csrf_token=TkLyvVj3to4G5Mn_chtw3OI8rRA%3D; _samesite_flag_=true; cookie2=11ccab40999fa9943d4003d08b6167a0; _tb_token_=555ee71fdee17; _gid=GA1.2.1037864555.1713838369; h_uid=2215351576043; _xsrf=2|f9186bd2|74ae7c9a48110f4a37f600b090d68deb|1713840596; csg=242c1dff; m_session_id=769d7c25-d715-4e3f-80de-02b9dbfef325; _gat_gtag_UA_156449732_1=1; _ga_R1FN4KJKJH=GS1.1.1713838368.22.1.1713841094.0.0.0; _ga=GA1.1.884310199.1697973032; tfstk=fE4KxBD09OXHPxSuRWsgUB8pSH5GXivUTzyBrU0oKGwtCSJHK7N3ebe0Ce4n-4Y8X8wideDotbQ8C7kBE3queYwEQ6OotW08WzexZUVIaNlgVbmIN7MQBYNmR0rnEvD-y7yAstbcoWPEz26cnZfu0a_qzY_oPpRUGhg5ntbgh_D3W4ZudTQmX5MZwX9IN8ts1AlkAYwSdc9sMjuSF8g56fGrgX9SFbgs5bGWtBHkOYL8Srdy07KF-tW4Wf6rhWQBrfUt9DHbOyLWPBhKvxNIBtEfyXi_a0UyaUn8OoyrGJ9CeYzT1yZbhOxndoh8iuFCRFg38WZjVr6yVWunpVaQDQT762H3ezewpOHb85aq5cbfM5aaKWzTZQ_Ss-D_TygRlsuKRvgt_zXwRYE_VymEzp6-UPF_RuIrsr4vHFpmHbxC61Ky4DGguGhnEBxD7Zhtn1xM43oi_fHc61Ky4DGZ6xfGo3-rjf5..; isg=BKKjOsZlMNqsZy8UH4-lXjE_8ygE86YNIkwdKew665XKv0I51IGvHCUz7_tDrx6l"
def random_session_hash(random_length):
    return random_str(random_length, "abcdefghijklmnopqrstuvwxyz1234567890")

async def hf_drawer(prompt, proxy, args):
    height = 1600
    width = 1064
    try:
        if proxy:
            proxies = {"http://": proxy, "https://": proxy}
        else:
            proxies = None
        session_hash = random_session_hash(11)
        queue_join_url = "https://asahina2k-animagine-xl-4-0.hf.space/queue/join?__theme=system"
        queue_join_params = {
            't': str(int(time.time() * 1000)),
            '__theme': 'system'
        }
        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Content-Type': 'application/json',
            'DNT': '1',
            'Origin': 'https://asahina2k-animagine-xl-4-0.hf.space',
            'Priority': 'u=1, i',
            'Referer': 'https://asahina2k-animagine-xl-4-0.hf.space/?__theme=system',
            'Sec-Ch-Ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Storage-Access': 'active',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
            'X-Zerogpu-Uuid': 'VA_BP1LgDDfZLIvtKee-g'
        }
        
        if "方" in prompt:
            prompt = prompt.replace("方", "")
            width = 1064
            height = 1064
        if "横" in prompt:
            prompt = prompt.replace("横", "")
            width = 1600
            height = 1064
        if "竖" in prompt:
            prompt = prompt.replace("竖", "")
            width = 1064
            height = 1600
            
        positive = str(args.get('p', default_args.get('p', positives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('p', positives) if isinstance(args, dict) else default_args.get('p', positives) if isinstance(default_args, dict) else positives)
        negative = str(args.get('n', default_args.get('n', negatives)) if isinstance(args, dict) and isinstance(default_args, dict) else args.get('n', negatives) if isinstance(args, dict) else default_args.get('n', negatives) if isinstance(default_args, dict) else negatives)
        positive = (("{}," + positive) if "{}" not in positive else positive).replace("{}", prompt) if isinstance(positive, str) else str(prompt)
        positive, _ = await replace_wildcards(positive)
        steps = int(args.get('steps', default_args.get('steps', 35)) if isinstance(args, dict) else default_args.get('steps', 35)) if isinstance(default_args, dict) else 35
        cfg = float(args.get('cfg', default_args.get('cfg', 6.5)) if isinstance(args, dict) else default_args.get('cfg', 6.5) if isinstance(default_args, dict) else 6.5)
        
        payload = {
            "data": [
                positive,
                negative,
                random.randint(0, 2 ** 32 - 1), width, height, cfg, steps, "Euler a", "Custom", "(None)", False, 0.55, 1.5, True
            ],
            "event_data": None,
            "fn_index": 5,
            "trigger_id": 43,
            "session_hash": session_hash
        }

        async with httpx.AsyncClient(headers=headers, proxies=proxies) as client:
            try:
                response = await client.post(queue_join_url, params=queue_join_params, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as status_error:
                print(f"HTTP error occurred: {status_error}")
                return None
            except httpx.RequestError as request_error:
                print(f"Request error occurred: {request_error}")
                return None
            
            queue_data_url = f"https://asahina2k-animagine-xl-4-0.hf.space/queue/data?session_hash={session_hash}"
            
            try:
                async with client.stream("GET", queue_data_url, headers=headers, timeout=60) as event_stream_response:
                    async for line in event_stream_response.aiter_text():
                        line = line.strip()
                        if line and not line.startswith("data:"):
                            continue
                        
                        try:
                            event_data = json.loads(line.replace("data:", "").strip())
                        except json.JSONDecodeError:
                            continue
                        
                        msg_type = event_data.get('msg')
                        if msg_type == 'process_completed':
                            imgurl = event_data['output']['data'][0][0]['image']['url']
                            return imgurl
                        elif msg_type in ['estimation', 'process_starts']:
                            print(event_data)
            except (httpx.RequestError, json.JSONDecodeError) as stream_error:
                print(f"Stream error occurred: {stream_error}")
                return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None
