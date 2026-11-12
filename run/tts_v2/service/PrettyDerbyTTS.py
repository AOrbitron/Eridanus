import asyncio
import json
import ssl
from pathlib import Path
from typing import Optional

import httpx
import websockets

from developTools.utils.logger import get_logger
from framework_common.utils.random_session_hash import random_session_hash

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

logger = get_logger("PrettyDerby_TTS")

PRETTY_DERBY_SPEAKERS = [
    "agnes_digital_爱丽数码_アグネスデジタル",
    "curren_chan_真机伶_カレンチャン",
    "matikane_fukukitaru_待兼福来_マチカネフクキタル",
    "matikane_tannhauser_待兼诗歌剧_マチカネタンホイサ",
    "mejiro_mcqueen_目白麦昆_メジロマックイーン",
    "natuki",
    "nice_nature_优秀素质_ナイスネイチャ",
    "rice_shower_米浴_ライスシャワー",
    "satono_diamond_里见光钻_サトノダイヤモンド",
]

# 常见别名映射到全名
PRETTY_DERBY_ALIASES = {
    "natuki": "natuki",
    "爱丽数码": "agnes_digital_爱丽数码_アグネスデジタル",
    "agnes_digital": "agnes_digital_爱丽数码_アグネスデジタル",
    "真机伶": "curren_chan_真机伶_カレンチャン",
    "curren_chan": "curren_chan_真机伶_カレンチャン",
    "待兼福来": "matikane_fukukitaru_待兼福来_マチカネフクキタル",
    "matikane_fukukitaru": "matikane_fukukitaru_待兼福来_マチカネフクキタル",
    "待兼诗歌剧": "matikane_tannhauser_待兼诗歌剧_マチカネタンホイサ",
    "matikane_tannhauser": "matikane_tannhauser_待兼诗歌剧_マチカネタンホイサ",
    "目白麦昆": "mejiro_mcqueen_目白麦昆_メジロマックイーン",
    "mejiro_mcqueen": "mejiro_mcqueen_目白麦昆_メジロマックイーン",
    "优秀素质": "nice_nature_优秀素质_ナイスネイチャ",
    "nice_nature": "nice_nature_优秀素质_ナイスネイチャ",
    "米浴": "rice_shower_米浴_ライスシャワー",
    "rice_shower": "rice_shower_米浴_ライスシャワー",
    "里见光钻": "satono_diamond_里见光钻_サトノダイヤモンド",
    "satono_diamond": "satono_diamond_里见光钻_サトノダイヤモンド",
}

def resolve_pretty_derby_speaker(speaker: str) -> Optional[str]:
    """根据别名或完整名称匹配赛马娘发音人"""
    if not speaker:
        return None
    spk_lower = speaker.strip().lower()
    if speaker in PRETTY_DERBY_SPEAKERS:
        return speaker
    for k, v in PRETTY_DERBY_ALIASES.items():
        if spk_lower == k.lower() or k.lower() in spk_lower or spk_lower in k.lower():
            return v
    for full in PRETTY_DERBY_SPEAKERS:
        if spk_lower in full.lower():
            return full
    return None

async def PrettyDerby_TTS(text: str, speaker: str = "natuki", lang_type: str = "ja", proxy: Optional[str] = None) -> str:
    """赛马娘 Bert-VITS2 语音合成"""
    resolved = resolve_pretty_derby_speaker(speaker) or speaker
    logger.info(f"PrettyDerbyTTS 参数: speaker={resolved}, text={text}, lang_type={lang_type}")
    
    url = "wss://akitop-umamusume-bert-vits2.hf.space/queue/join?__theme=system"
    session_hash = random_session_hash(11)
    save_path = f"data/voice/cache/{session_hash}.wav"
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)

    async with websockets.connect(url, ssl=ssl_context) as ws:
        while True:
            await asyncio.sleep(0.5)
            raw = await ws.recv()
            if not raw:
                continue
            data = json.loads(raw)
            msg = data.get("msg")
            if msg == "send_hash":
                await ws.send(json.dumps({"session_hash": session_hash, "fn_index": 0}))
            elif msg == "send_data":
                await ws.send(json.dumps({
                    "data": [text, resolved, 0.2, 0.6, 0.8, 1, "JP"],
                    "event_data": None,
                    "fn_index": 0,
                    "session_hash": session_hash
                }))
            elif data.get("msg") == "process_completed" or "output" in data:
                if not data.get("success", True) and "data" not in data.get("output", {}):
                    raise RuntimeError(f"PrettyDerby TTS 服务端生成失败: {data}")
                output_data = data.get("output", {}).get("data", [])
                if len(output_data) < 2 or not output_data[1]:
                    raise RuntimeError(f"PrettyDerby TTS 未返回有效音频数据: {data}")
                file_info = output_data[1]
                file_name = file_info.get("name") if isinstance(file_info, dict) else str(file_info)
                file_url = f"https://akitop-umamusume-bert-vits2.hf.space/file={file_name}"
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(file_url)
                    resp.raise_for_status()
                    Path(save_path).write_bytes(resp.content)
                logger.info(f"PrettyDerbyTTS 生成完成: {save_path}")
                return save_path

async def get_PrettyDerby_speakers():
    return list(PRETTY_DERBY_SPEAKERS)
