import asyncio
from pathlib import Path
from typing import Optional, List, Any
import httpx
from developTools.utils.logger import get_logger
from framework_common.utils.random_str import random_str

logger = get_logger("LocalVITS")

async def vits(text: str, speaker: str, base_url: str = "http://127.0.0.1:5009") -> str:
    url = f"{base_url.rstrip('/')}/get_audio"
    params = {
        "text": text,
        "speaker": speaker
    }
    p = f"data/voice/cache/{random_str()}.mp3"
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        Path(p).write_bytes(response.content)
    return p

async def get_vits_speakers(base_url: str = "http://127.0.0.1:5009", proxies: Optional[Any] = None) -> List[str]:
    url = f"{base_url.rstrip('/')}/get_speakers"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            res = response.json()
            if isinstance(res, list):
                return res
            elif isinstance(res, dict):
                return list(res.keys())
            return []
    except Exception as e:
        logger.warning(f"获取本地VITS角色失败: {e}")
        return []
