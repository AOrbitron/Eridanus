import asyncio
from pathlib import Path
from typing import List
import httpx
from developTools.utils.logger import get_logger

logger = get_logger("OttoTTS")

OTTO_SPEAKERS = ["otto", "OTTO", "电棍", "吉吉国王"]

class OttoTTS:
    def __init__(self, endpoint: str = "https://ottohzys.wzq02.top"):
        self.endpoint = endpoint.rstrip("/")

    async def speak(self, text: str) -> str:
        origin_url = f"{self.endpoint}/make"
        data = {
            "text": text,
            "inYsddMode": "false",
            "norm": "false",
            "reverse": "false",
            "speedMult": 1.2,
            "pitchMult": 1,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(origin_url, data=data)
            response.raise_for_status()
            audio_id = response.json().get("id")
            if not audio_id:
                raise RuntimeError("Otto TTS 未返回音频 ID")
            return await self.download_audio(audio_id)

    async def download_audio(self, audio_id: str) -> str:
        audio_url = f"{self.endpoint}/get/{audio_id}.ogg"
        path = f"data/voice/cache/{audio_id}.ogg"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(audio_url)
            response.raise_for_status()
            Path(path).write_bytes(response.content)
            return path

async def get_otto_speakers() -> List[str]:
    return list(OTTO_SPEAKERS)
