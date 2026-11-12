import asyncio
import json
import ssl
from pathlib import Path
from typing import Optional, List

import httpx
import websockets

from developTools.utils.logger import get_logger
from framework_common.utils.random_session_hash import random_session_hash

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

logger = get_logger("BlueArchive_TTS")

BLUE_ARCHIVE_SPEAKERS = [
    'JP_Airi', 'JP_Akane', 'JP_Akari', 'JP_Ako', 'JP_Aris', 'JP_Arona', 'JP_Aru', 'JP_Asuna',
    'JP_Atsuko', 'JP_Ayane', 'JP_Azusa', 'JP_Cherino', 'JP_Chihiro', 'JP_Chinatsu', 'JP_Chise',
    'JP_Eimi', 'JP_Erica', 'JP_Fubuki', 'JP_Fuuka', 'JP_Hanae', 'JP_Hanako', 'JP_Hare',
    'JP_Haruka', 'JP_Haruna', 'JP_Hasumi', 'JP_Hibiki', 'JP_Hihumi', 'JP_Himari', 'JP_Hina',
    'JP_Hinata', 'JP_Hiyori', 'JP_Hoshino', 'JP_Iori', 'JP_Iroha', 'JP_Izumi', 'JP_Izuna',
    'JP_Juri', 'JP_Kaede', 'JP_Karin', 'JP_Kayoko', 'JP_Kazusa', 'JP_Kirino', 'JP_Koharu',
    'JP_Kokona', 'JP_Kotama', 'JP_Kotori', 'JP_Main', 'JP_Maki', 'JP_Mari', 'JP_Marina',
    'JP_Mashiro', 'JP_Michiru', 'JP_Midori', 'JP_Miku', 'JP_Mimori', 'JP_Misaki', 'JP_Miyako',
    'JP_Miyu', 'JP_Moe', 'JP_Momoi', 'JP_Momoka', 'JP_Mutsuki', 'JP_NP0013', 'JP_Natsu',
    'JP_Neru', 'JP_Noa', 'JP_Nodoka', 'JP_Nonomi', 'JP_Pina', 'JP_Rin', 'JP_Saki', 'JP_Saori',
    'JP_Saya', 'JP_Sena', 'JP_Serika', 'JP_Serina', 'JP_Shigure', 'JP_Shimiko', 'JP_Shiroko',
    'JP_Shizuko', 'JP_Shun', 'JP_ShunBaby', 'JP_Sora', 'JP_Sumire', 'JP_Suzumi', 'JP_Tomoe',
    'JP_Tsubaki', 'JP_Tsurugi', 'JP_Ui', 'JP_Utaha', 'JP_Wakamo', 'JP_Yoshimi', 'JP_Yuuka',
    'JP_Yuzu', 'JP_Zunko'
]

def resolve_blue_archive_speaker(speaker: str) -> Optional[str]:
    """支持别名解析，例如 Mari -> JP_Mari，伊织 -> JP_Iori 等"""
    if not speaker:
        return None
    spk = speaker.strip()
    if spk in BLUE_ARCHIVE_SPEAKERS:
        return spk
    
    # 尝试加上 JP_ 前缀
    with_jp = f"JP_{spk}"
    for s in BLUE_ARCHIVE_SPEAKERS:
        if s.lower() == with_jp.lower():
            return s
            
    # 大小写不敏感匹配
    for s in BLUE_ARCHIVE_SPEAKERS:
        raw_name = s.replace("JP_", "")
        if spk.lower() == raw_name.lower():
            return s

    return None

async def huggingface_blue_archive_tts(text: str, speaker: str = "JP_Mari", lang_type: str = "ja", proxy: Optional[str] = None) -> str:
    resolved = resolve_blue_archive_speaker(speaker) or speaker
    logger.info(f"BlueArchiveTTS 参数: speaker={resolved}, text={text}")
    url = "wss://avillia-bluearchivetts.hf.space/queue/join"
    session_hash = random_session_hash(10)
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
                    "fn_index": 0,
                    "data": [text, resolved, 1, False],
                    "session_hash": session_hash
                }))
            elif "output" in data:
                file_info = data["output"]["data"][1]
                file_name = file_info.get("name") if isinstance(file_info, dict) else str(file_info)
                file_url = f"https://avillia-bluearchivetts.hf.space/file={file_name}"
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(file_url)
                    resp.raise_for_status()
                    Path(save_path).write_bytes(resp.content)
                logger.info(f"BlueArchiveTTS 生成完成: {save_path}")
                return save_path

async def get_huggingface_blue_archive_speakers() -> List[str]:
    return list(BLUE_ARCHIVE_SPEAKERS)
