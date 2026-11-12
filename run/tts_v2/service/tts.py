"""
tts_v2 统一语音合成调度中心
支持：
- Breeze-TTS 2（达妮娅官方最新语音合成引擎，支持配音指导 instruction、33 种音频表现力标签与 1 小时临时声音克隆）
- PrettyDerby（赛马娘 Bert-VITS2 直连，包含 natuki、米浴、目白麦昆等 9 个角色及别名）
- HoliveTTS（Hololive Style Bert-VITS2 直连，包含 51 个角色）
- Blue Archive 在线 TTS（95 角色，如 JP_Mari, Mari, JP_Arona 等）
- OttoTTS（otto, 电棍, 吉吉国王 等）
- GPT-SoVITS（旧版本地/自建模型备用）
- Local VITS（本地 VITS 兼容保留）
- ApollodorusTTS 网关（辅助/扩展）
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from developTools.message.message_components import Node, Record, Text
from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager

from .breeze_tts import (
    AsyncBreezeTTSClient,
    BreezeVoiceCloneManager,
    breeze_clone_manager,
    format_breeze_audio_tags_nodes,
    protect_and_clean_breeze_text,
    BREEZE_AUDIO_TAGS_ZH,
    ALL_BREEZE_TAGS,
    ALL_BREEZE_TAG_NAMES,
)
from .GPT_SoVits import AsyncGPTSoVITSClient
from .PrettyDerbyTTS import (
    PRETTY_DERBY_SPEAKERS,
    PRETTY_DERBY_ALIASES,
    resolve_pretty_derby_speaker,
    get_PrettyDerby_speakers,
    PrettyDerby_TTS,
)
from .HoliveTTS import (
    HoliveTTS,
    SPEAKERS as HOLIVE_SPEAKERS,
    resolve_holive_speaker,
)
from .ApollodorusTTS import (
    APOLLODORUS_SPEAKERS,
    resolve_apollodorus_speaker,
    synthesize_apollodorus_or_fallback,
)
from .blue_archive_tts import (
    BLUE_ARCHIVE_SPEAKERS,
    resolve_blue_archive_speaker,
    huggingface_blue_archive_tts,
    get_huggingface_blue_archive_speakers,
)
from .ottoTTS import OttoTTS, OTTO_SPEAKERS, get_otto_speakers
from .vits import vits, get_vits_speakers
from .translator import clean_tts_text, translate_text

logger = get_logger("tts_v2")


def _cache_path(suffix: str = ".wav") -> str:
    path = Path("data/voice/cache") / f"{uuid.uuid4().hex}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _get_api_key_from_system() -> Optional[str]:
    """尝试从当前系统中获取 trigger_llm / openai / tts_v2 配置的 api_key"""
    try:
        cfg = YAMLManager.get_instance()
        # 1. 优先从 tts_v2 配置中获取
        key = cfg.tts_v2.config.get("breeze_tts", {}).get("api_key") or cfg.tts_v2.config.get("tts", {}).get("api_key")
        if key:
            return key
        # 2. 从 core_reply 的 trigger_llm 获取
        mai_cfg = getattr(cfg, "core_reply", None)
        if mai_cfg:
            key = mai_cfg.config.get("trigger_llm", {}).get("api_key")
            if key:
                return key
            # 3. 从 core_reply 的 openai api_keys 获取
            keys = mai_cfg.config.get("llm", {}).get("openai", {}).get("api_keys", [])
            if keys and keys[0] and keys[0] != "xxx":
                return keys[0]
    except Exception:
        pass
    return None


class TTSEngine(ABC):
    name: str

    @abstractmethod
    async def get_speakers(self, bot=None) -> dict[str, Any] | list[str]:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        speaker: str | None = None,
        *,
        bot=None,
        config=None,
        lang_type: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ) -> str:
        raise NotImplementedError


class BreezeTTSEngine(TTSEngine):
    """
    Breeze-TTS 2 语音合成引擎（官方端点）
    - 原生支持 /breeze/tts (配音指导 instruction 与声音设计) 及 /v1/audio/speech 端点；
    - 支持 33 种中文表现力音频标签（如 [叹气]、[轻笑] 等）；
    - 支持 1 小时有效期的自定义角色声音克隆；
    - 默认接管达妮娅声线（取代已停止维护的旧版 GPT-SoVITS）。
    """
    name = "breeze_tts"

    def __init__(self):
        self.client = AsyncBreezeTTSClient()
        self.clone_manager = breeze_clone_manager

    async def get_speakers(self, bot=None):
        base_speakers = list(self.client.speakers)
        try:
            remote_spks = await self.client.fetch_remote_speakers()
            for spk in remote_spks:
                if spk not in base_speakers:
                    base_speakers.append(spk)
        except Exception:
            pass
        cloned_speakers = [f"{s['speaker']} (克隆, 剩余{s['remaining_minutes']}分)" for s in self.clone_manager.list_cloned_speakers()]
        return base_speakers + cloned_speakers

    async def synthesize(
        self,
        text: str,
        speaker: str | None = None,
        *,
        bot=None,
        config=None,
        lang_type: str | None = None,
        api_key: str | None = None,
        instruction: str | None = None,
        cfg_scale: float | None = None,
        mode: str | None = None,
        connection_mode: str | None = None,
        auto_tag: bool = True,
        ref_audio: Union[str, bytes, None] = None,
        ref_text: str | None = None,
        speed: float | None = None,
        volume: float | None = None,
        voice_settings: dict | None = None,
        **kwargs,
    ) -> str:
        # 检查 speaker 是否命中 1 小时内临时克隆的角色
        clone_info = self.clone_manager.get_cloned_speaker(speaker or "")
        if clone_info:
            ref_audio = ref_audio or clone_info.get("audio_path")
            ref_text = ref_text or clone_info.get("ref_text")

        return await self.client.generate_tts(
            text=text,
            instruction=instruction,
            cfg_scale=cfg_scale,
            mode=mode,
            connection_mode=connection_mode,
            voice=speaker,
            speaker=speaker,
            speed=speed,
            volume=volume,
            voice_settings=voice_settings,
            auto_tag=auto_tag,
            ref_audio=ref_audio,
            ref_text=ref_text,
            bot=bot,
            config=config,
        )


class GPTSoVITSEngine(TTSEngine):
    """GPT-SoVITS 语音合成引擎（开源通用兼容，供本地或自建 GPT-SoVITS 服务的用户使用）"""
    name = "gpt_sovits"

    def __init__(self):
        self.client = AsyncGPTSoVITSClient()

    async def get_speakers(self, bot=None):
        return self.client.speakers

    async def synthesize(
        self,
        text: str,
        speaker: str | None = None,
        *,
        bot=None,
        config=None,
        lang_type: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ) -> str:
        return await self.client.generate_tts(text)


class PrettyDerbyEngine(TTSEngine):
    """赛马娘 Bert-VITS2 直连引擎"""
    name = "pretty_derby"

    async def get_speakers(self, bot=None):
        return await get_PrettyDerby_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        speaker = speaker or "natuki"
        resolved = resolve_pretty_derby_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await PrettyDerby_TTS(text=text, speaker=resolved, lang_type=target_lang)


class HoliveEngine(TTSEngine):
    """Hololive Style Bert-VITS2 直连引擎"""
    name = "holive"

    def __init__(self):
        self.client = HoliveTTS()

    async def get_speakers(self, bot=None):
        return self.client.speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        speaker = speaker or "MoriCalliope"
        resolved = resolve_holive_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        cache_path = _cache_path(".wav")
        return await self.client.synthesize_to_file(
            text=text,
            save_as=cache_path,
            speaker=resolved,
            language=target_lang,
        )


class BlueArchiveEngine(TTSEngine):
    """蔚蓝档案 Bert-VITS2 直连引擎"""
    name = "blue_archive"

    async def get_speakers(self, bot=None):
        return await get_huggingface_blue_archive_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        speaker = speaker or "JP_Mari"
        resolved = resolve_blue_archive_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "ja").lower()

        if any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await huggingface_blue_archive_tts(
            text=text,
            speaker=resolved,
            lang_type=target_lang,
        )


class OttoTTSEngine(TTSEngine):
    """电棍 / 活字印刷 TTS 引擎"""
    name = "otto"

    def _cfg(self, config=None):
        cfg = (config or YAMLManager.get_instance()).tts_v2.config
        return cfg.get("otto") or {}

    async def get_speakers(self, bot=None):
        return await get_otto_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        endpoint = self._cfg(config).get("endpoint", "https://ottohzys.wzq02.top")
        client = OttoTTS(endpoint=endpoint)
        return await client.speak(text)


class LocalVITSEngine(TTSEngine):
    """本地 VITS 兼容保留"""
    name = "vits"

    def _cfg(self, config=None):
        cfg = (config or YAMLManager.get_instance()).tts_v2.config
        return cfg.get("vits") or {}

    async def get_speakers(self, bot=None):
        cfg = self._cfg()
        base_url = cfg.get("base_url", "http://127.0.0.1:5009")
        speakers = await get_vits_speakers(base_url=base_url)
        if not speakers and cfg.get("speaker"):
            return [cfg.get("speaker")]
        return speakers

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        cfg = self._cfg(config)
        base_url = cfg.get("base_url", "http://127.0.0.1:5009")
        speaker = speaker or cfg.get("speaker", "綾地寧々")
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()
        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)
        return await vits(text=text, speaker=speaker, base_url=base_url)


class ApollodorusEngine(TTSEngine):
    """Apollodorus 统一语音网关（辅助/扩展使用）"""
    name = "apollodorus"

    async def get_speakers(self, bot=None):
        return list(APOLLODORUS_SPEAKERS)

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None, **kwargs):
        speaker = speaker or "natuki"
        resolved = resolve_apollodorus_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await synthesize_apollodorus_or_fallback(
            text=text,
            speaker=resolved,
            language=target_lang,
            api_key=token,
        )


class TTS:
    """
    tts_v2 统一入口：
    提供自动路由、文本清洗、表现力标签保护、角色解析、自动翻译与音频生成。
    """

    _engine_classes = (
        BreezeTTSEngine,
        PrettyDerbyEngine,
        HoliveEngine,
        GPTSoVITSEngine,
        BlueArchiveEngine,
        OttoTTSEngine,
        LocalVITSEngine,
        ApollodorusEngine,
    )

    def __init__(self):
        self.config = YAMLManager.get_instance()
        self.engines: Dict[str, TTSEngine] = {
            cls.name: cls() for cls in self._engine_classes
        }
        self.clone_manager = breeze_clone_manager

    def _tts_config(self, config=None) -> dict:
        cfg_obj = config or self.config
        if isinstance(cfg_obj, dict):
            return cfg_obj.get("tts", cfg_obj)
        if hasattr(cfg_obj, "tts_v2") and hasattr(cfg_obj.tts_v2, "config"):
            tts_cfg = cfg_obj.tts_v2.config.get("tts")
            if tts_cfg:
                return tts_cfg
        if hasattr(cfg_obj, "core_reply") and hasattr(cfg_obj.core_reply, "config"):
            mai_tts = cfg_obj.core_reply.config.get("tts")
            if mai_tts:
                return mai_tts
        if hasattr(cfg_obj, "get"):
            return cfg_obj.get("tts", {})
        return {}

    def _breeze_config(self, config=None) -> dict:
        cfg_obj = config or self.config
        if isinstance(cfg_obj, dict):
            return cfg_obj.get("breeze_tts", {})
        if hasattr(cfg_obj, "tts_v2") and hasattr(cfg_obj.tts_v2, "config"):
            b_cfg = cfg_obj.tts_v2.config.get("breeze_tts")
            if b_cfg:
                return b_cfg
        return {}

    @staticmethod
    def clean_text(text: str) -> str:
        return clean_tts_text(text)

    async def get_speakers(self, bot=None) -> Dict[str, Any]:
        """获取所有可用引擎的发音人列表"""
        res = {}
        for name, engine in self.engines.items():
            try:
                res[name] = await engine.get_speakers(bot)
            except Exception as e:
                logger.warning(f"获取引擎 {name} 角色列表异常: {e}")
                res[name] = []
        return res

    async def resolve(self, speaker: Optional[str], bot=None, config=None) -> Tuple[str, str]:
        """
        根据传入的 speaker 字符串自动识别所属引擎并规范化 speaker 名称。
        若未传 speaker，优先使用配置中的默认声线或默认发音人。
        达妮娅与克隆角色优先路由至 Breeze-TTS 2 引擎。
        """
        cfg = self._tts_config(config)
        default_speaker = cfg.get("default_speaker", "达妮娅")

        if not speaker:
            speaker = default_speaker

        spk = speaker.strip()

        # 0. 优先检查是否命中 1 小时有效期的自定义语音克隆角色
        cloned_info = self.clone_manager.get_cloned_speaker(spk)
        if cloned_info:
            logger.info(f"[TTS.resolve] 命中临时语音克隆角色: '{spk}' -> breeze_tts")
            return "breeze_tts", spk
        # 1. 检查是否为 Breeze 角色（达妮娅、dania、breeze 等，或其它 Breeze 注册发音人）
        breeze_engine = self.engines.get("breeze_tts")
        breeze_speakers = [s.lower() for s in await breeze_engine.get_speakers(bot)] if breeze_engine else []
        if spk.lower() in ["breeze", "breeze-tts", "breeze-tts-2", "breeze_tts"]:
            return "breeze_tts", "达妮娅"
        if spk.lower() in ["达妮娅", "dania"] or spk.lower() in breeze_speakers or (breeze_engine and spk in breeze_engine.client.speakers):
            return "breeze_tts", spk

        # 1.5 检查是否命中自建 GPT-SoVITS 专属角色
        gpt_engine = self.engines.get("gpt_sovits")
        if gpt_engine:
            gpt_spks = await gpt_engine.get_speakers(bot)
            if isinstance(gpt_spks, (list, tuple, set)) and spk in gpt_spks:
                return "gpt_sovits", spk


        # 2. 检查是否为赛马娘角色（直连 PrettyDerby，如 natuki、米浴、目白麦昆 等）
        pd_resolved = resolve_pretty_derby_speaker(spk)
        if pd_resolved:
            return "pretty_derby", pd_resolved

        # 3. 检查是否为 Hololive 角色（直连 HoliveTTS，如 MoriCalliope、GawrGura 等）
        holo_resolved = resolve_holive_speaker(spk)
        if holo_resolved:
            return "holive", holo_resolved

        # 4. 检查是否属于 Blue Archive 角色 (如 JP_Mari, Mari, JP_Arona 等)
        resolved_ba = resolve_blue_archive_speaker(spk)
        if resolved_ba:
            return "blue_archive", resolved_ba

        # 5. 检查是否为 Otto 角色 (otto, 电棍 等)
        if spk.lower() in [s.lower() for s in OTTO_SPEAKERS]:
            return "otto", "otto"

        # 6. 检查是否为本地 VITS 角色
        vits_spks = await self.engines["vits"].get_speakers(bot)
        if spk in vits_spks:
            return "vits", spk

        # 7. 检查 Apollodorus 网关支持
        apol_resolved = resolve_apollodorus_speaker(spk)
        if apol_resolved:
            return "apollodorus", apol_resolved

        # 8. 降级回退：优先回退至 Breeze 达妮娅
        logger.info(f"[TTS.resolve] 未明确识别到已知引擎角色名: '{spk}'，回退至 breeze_tts (达妮娅)")
        return "breeze_tts", "达妮娅"

    async def tts(
        self,
        text: str,
        speaker: Optional[str] = None,
        config=None,
        bot=None,
        mode: Optional[str] = None,
        connection_mode: Optional[str] = None,
        lang_type: Optional[str] = None,
        api_key: Optional[str] = None,
        instruction: Optional[str] = None,
        cfg_scale: Optional[float] = None,
        auto_tag: Optional[bool] = None,
        ref_audio: Optional[Union[str, bytes]] = None,
        ref_text: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        voice_settings: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """
        全局统一语音合成入口：
        路由引擎 -> 从配置读取默认参数 -> 确认是 breeze 时单独调用 trigger_llm 结构化输出语气与标签 -> 合成音频。
        """
        cfg = self._tts_config(config)
        breeze_cfg = self._breeze_config(config)

        # 1. 显式指定模式路由或自动角色识别
        if mode:
            mode_map = {
                "breeze": "breeze_tts",
                "breeze_tts": "breeze_tts",
                "breeze-tts": "breeze_tts",
                "dania": "breeze_tts",
                "达妮娅": "breeze_tts",
                "prettyderby": "pretty_derby",
                "pretty_derby": "pretty_derby",
                "holive": "holive",
                "hololive": "holive",
                "ottotts": "otto",
                "otto": "otto",
                "bluearchive": "blue_archive",
                "blue_archive": "blue_archive",
                "vits": "vits",
                "gpt_sovits": "gpt_sovits",
                "apollodorus": "apollodorus",
            }
            engine_name = mode_map.get(mode.lower(), mode.lower())
            resolved_speaker = speaker or cfg.get("default_speaker", "达妮娅")
        else:
            engine_name, resolved_speaker = await self.resolve(speaker, bot=bot, config=config)

        # 2. 从配置文件中读取默认参数（外部未传参时自动补齐）
        effective_conn_mode = connection_mode or breeze_cfg.get("connection_mode", "gateway")
        effective_mode = mode or breeze_cfg.get("mode", "breeze_tts")
        effective_cfg_scale = cfg_scale if cfg_scale is not None else float(breeze_cfg.get("cfg_scale", 4.0))
        effective_speed = speed if speed is not None else kwargs.get("speed", breeze_cfg.get("speed", 1.0))
        effective_volume = volume if volume is not None else kwargs.get("volume", breeze_cfg.get("volume", 1.0))
        effective_voice_settings = voice_settings or kwargs.get("voice_settings") or breeze_cfg.get("voice_settings")
        effective_auto_tag = auto_tag if auto_tag is not None else breeze_cfg.get("auto_add_audio_tags", True)
        auto_instruction = breeze_cfg.get("auto_generate_instruction", True)
        target_lang = lang_type or ("ZH" if engine_name == "breeze_tts" else cfg.get("lang_type", "JP"))
        api_token = api_key or breeze_cfg.get("api_key") or cfg.get("api_key") or _get_api_key_from_system()

        # 3. 仅在确认目标引擎是 breeze_tts 时，才执行标签保护与 trigger_llm 结构化增强
        if engine_name == "breeze_tts":
            cleaned_text = protect_and_clean_breeze_text(text)
            if not cleaned_text:
                raise ValueError("Breeze TTS 输入文本为空或不含可朗读文本")

            # 若未显式传入 instruction 且允许自动生成，或需要自动标签润色，则调用 trigger_llm 一次性结构化生成
            if not ref_audio:
                need_gen_instruct = (not instruction) and auto_instruction
                need_gen_tags = effective_auto_tag and not bool(re.search(r"\[(" + "|".join(re.escape(name) for name in ALL_BREEZE_TAG_NAMES) + r")\]", cleaned_text))
                if need_gen_instruct or need_gen_tags:
                    breeze_engine = self.engines.get("breeze_tts")
                    if breeze_engine and hasattr(breeze_engine, "client"):
                        cleaned_text, generated_instruct = await breeze_engine.client.enrich_with_trigger_llm(
                            cleaned_text,
                            instruction=instruction,
                            config=config,
                        )
                        if not instruction and generated_instruct:
                            instruction = generated_instruct

            if not instruction:
                instruction = breeze_cfg.get("default_instruction", "说话轻柔温和，略带自然真实的情感。")
        else:
            cleaned_text = self.clean_text(text)
            if not cleaned_text:
                raise ValueError("TTS 输入文本为空或全部为不可发音符号")

        # 4. 长度限制检查
        length_limit = int(cfg.get("length_limit", 150))
        if len(cleaned_text) > length_limit:
            logger.warning(f"文本超长 ({len(cleaned_text)} > {length_limit})，已自动截断")
            cleaned_text = cleaned_text[:length_limit]

        engine = self.engines.get(engine_name)
        if not engine:
            logger.warning(f"未知 TTS 引擎: {engine_name}，自动回退至 breeze_tts")
            engine = self.engines["breeze_tts"]
            resolved_speaker = "达妮娅"

        logger.info(
            f"[TTS] 路由调度: 引擎={engine_name}, 发音人={resolved_speaker}, "
            f"连接={effective_conn_mode}, 模式={effective_mode}, 长度={len(cleaned_text)}"
        )

        return await engine.synthesize(
            text=cleaned_text,
            speaker=resolved_speaker,
            bot=bot,
            config=config,
            lang_type=target_lang,
            api_key=api_token,
            instruction=instruction,
            cfg_scale=effective_cfg_scale,
            mode=effective_mode,
            connection_mode=effective_conn_mode,
            auto_tag=False,  # 已经在确认 breeze_tts 后由 trigger_llm 完成结构化润色，避免二次调用
            ref_audio=ref_audio,
            ref_text=ref_text,
            speed=effective_speed,
            volume=effective_volume,
            voice_settings=effective_voice_settings,
            **kwargs,
        )

    async def call_tts(
        self,
        bot,
        event,
        config,
        text: str,
        speaker: Optional[str] = None,
        lang_type: Optional[str] = None,
        instruction: Optional[str] = None,
        cfg_scale: Optional[float] = None,
        mode: Optional[str] = None,
        connection_mode: Optional[str] = None,
        auto_tag: Optional[bool] = None,
        ref_audio: Optional[Union[str, bytes]] = None,
        ref_text: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        voice_settings: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """供消息事件或外部模块调用的便捷方法，合成并直接发送音频"""
        try:
            cfg = self._tts_config(config)
            target_lang = lang_type or kwargs.get("lang_type") or ("ZH" if (speaker and any(s in str(speaker).lower() for s in ["breeze", "dania", "达妮娅"])) else cfg.get("lang_type", "JP"))
            path = await self.tts(
                text=text,
                speaker=speaker,
                config=config,
                bot=bot,
                lang_type=target_lang,
                instruction=instruction,
                cfg_scale=cfg_scale,
                mode=mode,
                connection_mode=connection_mode,
                auto_tag=auto_tag,
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed=speed,
                volume=volume,
                voice_settings=voice_settings,
                **kwargs,
            )
            await bot.send(event, Record(file=path))

        except Exception as e:
            logger.error(f"[call_tts] 合成或发送失败: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    async def get_all_speakers(self, bot, event, config) -> Dict[str, Any]:
        """获取所有可用角色并通过转发/分条消息展示"""
        catalogs = await self.get_speakers(bot)
        nodes = [
            Node(content=[Text(
                "🎭 可用语音角色列表：\n"
                "可使用指令：/角色名说 内容（例如：/达妮娅说早上好、/natuki说你好、/Mari说老师好、/otto说大家好）\n"
                "Breeze专属指令：/breeze 说话轻柔 说 内容、/breeze标签、/克隆语音 角色名 台词"
            )])
        ]

        for name, spks in catalogs.items():
            if not spks:
                continue
            if isinstance(spks, dict):
                spk_list = list(spks.keys())
            else:
                spk_list = list(spks)

            display_text = f"【{name}】 共 {len(spk_list)} 个角色\n"
            if len(spk_list) > 20:
                display_text += ", ".join(spk_list[:20]) + f"... 等共 {len(spk_list)} 个"
            else:
                display_text += ", ".join(spk_list)
            nodes.append(Node(content=[Text(display_text)]))

        await bot.send(event, nodes)
        return catalogs


_default_tts = TTS()


async def call_tts(
    bot,
    event,
    config,
    text: str,
    speaker: Optional[str] = None,
    lang_type: Optional[str] = None,
    instruction: Optional[str] = None,
    cfg_scale: Optional[float] = None,
    mode: Optional[str] = None,
    connection_mode: Optional[str] = None,
    auto_tag: Optional[bool] = None,
    ref_audio: Optional[Union[str, bytes]] = None,
    ref_text: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    return await _default_tts.call_tts(
        bot,
        event,
        config,
        text,
        speaker=speaker,
        lang_type=lang_type,
        instruction=instruction,
        cfg_scale=cfg_scale,
        mode=mode,
        connection_mode=connection_mode,
        auto_tag=auto_tag,
        ref_audio=ref_audio,
        ref_text=ref_text,
        **kwargs,
    )


async def get_all_speakers(bot, event, config) -> Dict[str, Any]:
    return await _default_tts.get_all_speakers(bot, event, config)


async def get_breeze_tags(bot=None, event=None, config=None) -> Dict[str, Any]:
    """获取 Breeze-TTS 2 表现力音频标签面板"""
    nodes = format_breeze_audio_tags_nodes(bot)
    if bot and event:
        await bot.send(event, nodes)
    return {
        "status": "success",
        "categories": BREEZE_AUDIO_TAGS_ZH,
        "all_tags": list(ALL_BREEZE_TAGS),
    }


async def clone_voice(
    speaker_name: str,
    audio_url_or_path: str,
    ref_text: str,
    user_id: int = 0,
    bot: Any = None,
    event: Any = None,
    config: Any = None,
) -> Dict[str, Any]:
    """
    克隆声音并注册为 1 小时内有效的临时角色。
    支持传入本地路径或网络音频 URL。
    """
    try:
        if not ref_text or not ref_text.strip():
            raise ValueError("语音克隆必需提供参考台词文本 (ref_text)，以便进行声学对齐")

        # 检查是否为网络 URL
        audio_source = audio_url_or_path
        if audio_url_or_path.startswith("http://") or audio_url_or_path.startswith("https://"):
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                resp = await client.get(audio_url_or_path)
                if resp.status_code != 200:
                    raise RuntimeError(f"下载参考音频失败: HTTP {resp.status_code}")
                audio_source = resp.content

        rec = breeze_clone_manager.register_cloned_speaker(
            name=speaker_name,
            audio_source=audio_source,
            ref_text=ref_text,
            user_id=user_id,
        )

        reply_str = (
            f"✅ 角色语音克隆成功！\n"
            f"角色名称：【{speaker_name}】\n"
            f"有效时长：1 小时（至 {time.strftime('%H:%M:%S', time.localtime(rec['expires_at']))}）\n"
            f"使用方式：/{speaker_name}说 要说的话\n"
            f"例如：/{speaker_name}说 博士，今天也要努力工作哦！"
        )
        if bot and event:
            await bot.send(event, Text(reply_str))

        return {"status": "success", "record": rec}
    except Exception as e:
        logger.error(f"[clone_voice] 克隆失败: {e}", exc_info=True)
        if bot and event:
            await bot.send(event, Text(f"❌ 角色语音克隆失败: {e}"))
        return {"status": "failed", "error": str(e)}


async def list_cloned_voices(bot=None, event=None) -> List[Dict[str, Any]]:
    """查询当前所有生效中的自定义语音克隆角色"""
    clones = breeze_clone_manager.list_cloned_speakers()
    if bot and event:
        if not clones:
            await bot.send(event, Text("当前没有生效中的临时语音克隆角色。\n可通过回复语音消息并发送：/克隆语音 角色名 台词 进行克隆！"))
        else:
            lines = ["🎤 当前生效中的语音克隆角色（1小时内有效）："]
            for c in clones:
                lines.append(f"• 【{c['speaker']}】：剩余 {c['remaining_minutes']} 分钟（至 {c['expires_at_str']}）| 台词: {c['ref_text'][:15]}...")
            lines.append("\n使用方式：/角色名说 要说的话")
            await bot.send(event, Text("\n".join(lines)))
    return clones
