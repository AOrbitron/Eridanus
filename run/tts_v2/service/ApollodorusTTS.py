import asyncio
import uuid
from pathlib import Path
from typing import Optional
import httpx
from developTools.utils.logger import get_logger
from .PrettyDerbyTTS import PrettyDerby_TTS, resolve_pretty_derby_speaker, PRETTY_DERBY_SPEAKERS, PRETTY_DERBY_ALIASES
from .HoliveTTS import HoliveTTS, SPEAKERS as HOLIVE_SPEAKERS

logger = get_logger("ApollodorusTTS")

# Apollodorus 网关支持的角色全集：Hololive (51) + PrettyDerby (9)
APOLLODORUS_SPEAKERS = list(HOLIVE_SPEAKERS.keys()) + list(PRETTY_DERBY_SPEAKERS)

# 常见 Hololive 常用别名/简称映射
HOLIVE_ALIASES = {
    "gura": "GawrGura",
    "gawrgura": "GawrGura",
    "calli": "MoriCalliope",
    "moricalliope": "MoriCalliope",
    "ina": "NinomaeInanis",
    "kiara": "TakanashiKiara",
    "watson": "AmeliaWatson",
    "amelia": "AmeliaWatson",
    "kronii": "OuroKronii",
    "mumei": "NanashiMumei",
    "baelz": "HakosBaelz",
    "fauna": "CeresFauna",
    "suisei": "HoshimachiSuisei",
    "miko": "SakuraMiko",
    "marine": "HoushouMarine",
    "fubuki": "ShirakamiFubuki",
    "pekora": "UsadaPekora",
    "aqua": "MinatoAqua",
    "ayame": "NakiriAyame",
    "subaru": "OozoraSubaru",
    "korone": "InugamiKorone",
    "okayu": "NekomataOkayu",
}

def resolve_apollodorus_speaker(speaker: str) -> Optional[str]:
    """解析 speaker 是否属于 apollodorus 网关支持的角色（含赛马娘与 Hololive）"""
    if not speaker:
        return None
    spk_clean = speaker.strip()
    spk_lower = spk_clean.lower()
    
    # 1. 精确匹配
    if spk_clean in APOLLODORUS_SPEAKERS:
        return spk_clean

    # 2. 赛马娘别名解析 (如 natuki, 米浴, 目白麦昆 等)
    pd_resolved = resolve_pretty_derby_speaker(spk_clean)
    if pd_resolved:
        return pd_resolved

    # 3. Hololive 大小写精确不敏感匹配
    for h in HOLIVE_SPEAKERS:
        if h.lower() == spk_lower:
            return h

    # 4. Hololive 常用别名映射
    if spk_lower in HOLIVE_ALIASES:
        return HOLIVE_ALIASES[spk_lower]

    return None

async def synthesize_apollodorus_gateway(
    text: str,
    speaker: str,
    language: str = "JP",
    api_key: Optional[str] = None,
    base_url: str = "http://api.apollodorus.xyz"
) -> Optional[str]:
    """
    通过 api.apollodorus.xyz/tts 网关合成
    若成功返回保存的音频本地路径，失败返回 None
    """
    if not api_key:
        return None

    resolved_speaker = resolve_apollodorus_speaker(speaker) or speaker
    url = f"{base_url.rstrip('/')}/tts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "speaker": resolved_speaker,
        "language": language
    }
    
    cache_path = Path("data/voice/cache") / f"{uuid.uuid4().hex}.wav"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"[ApollodorusTTS] 请求网关 /tts: speaker={resolved_speaker}, text={text[:30]}")
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                cache_path.write_bytes(resp.content)
                logger.info(f"[ApollodorusTTS] 网关合成成功保存至: {cache_path}")
                return str(cache_path)
            else:
                logger.warning(f"[ApollodorusTTS] 网关返回非200状态码: {resp.status_code}, {resp.text[:100]}")
    except Exception as e:
        logger.warning(f"[ApollodorusTTS] 网关请求发生异常: {e}")
    return None

async def synthesize_apollodorus_or_fallback(
    text: str,
    speaker: str,
    language: str = "JP",
    api_key: Optional[str] = None,
    base_url: str = "http://api.apollodorus.xyz"
) -> str:
    """
    优先走 apollodorus 网关，失败或未配 key 时自动降级到直连 HF (PrettyDerby 或 Hololive)
    """
    resolved = resolve_apollodorus_speaker(speaker) or speaker
    
    # 1. 尝试网关
    if api_key:
        result_path = await synthesize_apollodorus_gateway(
            text=text,
            speaker=resolved,
            language=language,
            api_key=api_key,
            base_url=base_url
        )
        if result_path:
            return result_path

    # 2. 降级：赛马娘直连
    if resolved in PRETTY_DERBY_SPEAKERS or resolve_pretty_derby_speaker(speaker):
        pd_spk = resolve_pretty_derby_speaker(speaker) or resolved
        logger.info(f"[ApollodorusTTS] 回退到 PrettyDerby 直连: {pd_spk}")
        return await PrettyDerby_TTS(text=text, speaker=pd_spk, lang_type=language)

    # 3. 降级：Hololive 直连
    logger.info(f"[ApollodorusTTS] 回退到 HoliveTTS 直连: {resolved}")
    cache_path = str(Path("data/voice/cache") / f"{uuid.uuid4().hex}.wav")
    return await HoliveTTS().synthesize_to_file(
        text=text,
        save_as=cache_path,
        speaker=resolved,
        language=language
    )
