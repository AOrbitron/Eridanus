import os
import io
import json
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from developTools.message.message_components import Node, Text
from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager

logger = get_logger("breeze_tts")

# Breeze 官方支持的 33 种简体中文音频标签分类字典
BREEZE_AUDIO_TAGS_ZH: Dict[str, Dict[str, str]] = {
    "笑声 (Laughter)": {
        "[笑]": "普通大笑/笑声 (laugh)",
        "[轻笑]": "轻声微笑/轻笑 (chuckle)",
        "[咯咯笑]": "咯咯偷笑/欢笑 (giggle)",
    },
    "哭泣与痛苦 (Crying & pain)": {
        "[哭声]": "哭泣声 (cry)",
        "[抽泣]": "抽泣声 (sob)",
        "[呜咽]": "委屈呜咽 (whimper)",
        "[呻吟]": "痛苦低哼/呻吟 (groan)",
        "[哀号]": "悲伤哀号 (moan)",
    },
    "呼吸与叹息 (Breathing)": {
        "[叹气]": "叹息/叹气 (sigh)",
        "[惊呼]": "倒吸凉气/惊呼 (gasp)",
        "[吸气]": "深深吸气 (inhale)",
        "[呼气]": "缓缓呼气 (exhale)",
        "[喘息]": "剧烈喘息/喘粗气 (breathe heavily)",
    },
    "语气与腔调 (Vocal delivery)": {
        "[耳语]": "悄悄话/耳语轻声 (whisper)",
        "[喊叫]": "大声呼喊 (shout)",
        "[惨叫]": "惊叫/惨叫 (scream)",
        "[唱歌]": "吟唱/歌唱声线 (sing)",
        "[哼歌]": "闭口轻哼旋律 (hum)",
        "[结巴]": "结巴/犹豫吃螺丝 (stutter)",
        "[停顿]": "短暂停顿/静默节奏 (pause)",
    },
    "咽喉与鼻腔 (Throat & nose)": {
        "[清嗓]": "清喉咙/咳嗓子 (clear throat)",
        "[咳嗽]": "轻咳/咳嗽 (cough)",
        "[吸鼻子]": "受凉或难过吸鼻涕 (sniffle)",
    },
    "嘴部动作 (Mouth sounds)": {
        "[咂嘴]": "咂嘴/轻咂嘴唇 (lip smack)",
        "[啧嘴]": "啧嘴/咂舌 (click tongue)",
        "[吧唧嘴]": "吧唧嘴 (lip smack 兼容)",
        "[啧啧嘴]": "啧舌 (click tongue 兼容)",
    },
    "生理反射 (Body reflexes)": {
        "[打哈欠]": "困倦打哈欠 (yawn)",
        "[打喷嚏]": "打喷嚏 (sneeze)",
        "[打嗝]": "打嗝/抽嗝 (hiccup)",
        "[打饱嗝]": "吃饱打饱嗝 (burp)",
        "[吞咽]": "紧张/咽口水 (gulp)",
        "[干呕]": "恶心/干呕 (gag)",
    },
    "情绪反应 (Reaction sounds)": {
        "[闷哼]": "不屑/难受闷哼 (grunt)",
        "[冷笑]": "嘲讽/冷笑一声 (scoff)",
        "[哼鼻子]": "傲娇/哼气 (snort)",
    },
}

ALL_BREEZE_TAGS = {
    tag for category in BREEZE_AUDIO_TAGS_ZH.values() for tag in category.keys()
}
ALL_BREEZE_TAG_NAMES = {
    tag[1:-1] for tag in ALL_BREEZE_TAGS
}

DEFAULT_GATEWAY_URL = "http://api.apollodorus.xyz"
DEFAULT_DIRECT_URL = ""
DEFAULT_API_KEY = ""


def is_wav(data: bytes) -> bool:
    """检查字节流是否带有标准 RIFF WAVE 文件头"""
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    """将 16-bit 24kHz 单声道 PCM 裸流打包封装为标准 RIFF WAV 格式"""
    if is_wav(pcm_data):
        return pcm_data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def convert_to_wav_24k(input_path_or_bytes: Union[str, bytes], output_path: Optional[str] = None) -> str:
    """
    使用 ffmpeg 将输入音频转换为标准 24kHz 单声道 16-bit PCM WAV 格式。
    返回保存的 WAV 文件路径。
    """
    if not output_path:
        out_dir = Path("data/voice/cache/clones")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"{uuid.uuid4().hex}.wav")

    temp_input = None
    if isinstance(input_path_or_bytes, bytes):
        temp_input = Path("data/voice/cache") / f"temp_in_{uuid.uuid4().hex}"
        temp_input.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_input, "wb") as f:
            f.write(input_path_or_bytes)
        src_path = str(temp_input)
    else:
        src_path = str(input_path_or_bytes)

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", src_path,
            "-ar", "24000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            output_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.warning(f"[BreezeTTS] ffmpeg 转换异常: {result.stderr}，尝试直接拷贝/检测")
            if isinstance(input_path_or_bytes, bytes):
                with open(output_path, "wb") as f:
                    f.write(input_path_or_bytes)
            else:
                shutil.copy2(src_path, output_path)
    except Exception as e:
        logger.warning(f"[BreezeTTS] ffmpeg 执行失败 ({e})，直接复制文件")
        if isinstance(input_path_or_bytes, bytes):
            with open(output_path, "wb") as f:
                f.write(input_path_or_bytes)
        else:
            shutil.copy2(src_path, output_path)
    finally:
        if temp_input and temp_input.exists():
            try:
                temp_input.unlink()
            except Exception:
                pass

    return output_path


def protect_and_clean_breeze_text(text: str) -> str:
    """
    清洗文本，但严格保留合法的 Breeze 音频标签（如 [叹气]、[轻笑]）。
    去除多行代码块、行内代码、普通圆括号心理描写等无意义杂音。
    """
    if not text:
        return ""

    # 1. 保护已存在的合法 Breeze 音频标签
    placeholders = {}
    def _protect_tag(match):
        tag_str = match.group(0)
        key = f"__BREEZE_TAG_{len(placeholders)}__"
        placeholders[key] = tag_str
        return key

    tag_regex = r"\[(" + "|".join(re.escape(name) for name in ALL_BREEZE_TAG_NAMES) + r")\]"
    protected_text = re.sub(tag_regex, _protect_tag, text)

    # 2. 移除代码块与动作/心理描写
    protected_text = re.sub(r"https?://\S+", "", protected_text)
    protected_text = re.sub(r"```.*?```", "", protected_text, flags=re.DOTALL)
    protected_text = re.sub(r"`.*?`", "", protected_text)
    protected_text = re.sub(r"[（(][^）)]*[）)]", "", protected_text)
    # 移除普通非音频标签的方括号/黑括号
    protected_text = re.sub(r"[【\[][^】\]]*[】\]]", "", protected_text)
    protected_text = re.sub(r"\*[^*]+\*", "", protected_text)

    # 3. 还原保护的音频标签
    for k, v in placeholders.items():
        protected_text = protected_text.replace(k, v)

    # 4. 去除可能残留的单边符号
    protected_text = protected_text.replace("```", "").replace("`", "")
    return protected_text.strip()


def format_breeze_audio_tags_nodes(bot=None) -> List[Node]:
    """将 Breeze 所有音频表现力标签与语音克隆使用方式格式化为 Node 转发气泡列表"""
    nodes = [
        Node(content=[Text(
            "🎭 【Breeze-TTS 2 表现力音频标签一览】\n"
            "在待发音文本任意位置加入标签，例如：\n"
            "• [叹气]漂泊者，你就一点也不想着我吗？\n"
            "• [轻笑]今天真是个好天气呢，一起去散散步吧。\n"
            "• [打哈欠]好困呀，我想先去睡会儿了…\n\n"
            "支持的全部 33 个中文音频标签分类如下："
        )])
    ]

    for category, tags in BREEZE_AUDIO_TAGS_ZH.items():
        tag_lines = [f"{tag} : {desc}" for tag, desc in tags.items()]
        text_body = f"【{category}】\n" + "\n".join(tag_lines)
        nodes.append(Node(content=[Text(text_body)]))

    nodes.append(Node(content=[Text(
        "💡 【语音指令使用指南】\n"
        "1. 纯指令合成（带指定语气）：\n"
        "   /breeze 说话轻柔温和，略带怀念与感伤 说 喜欢的课与书籍。\n"
        "   /breeze 略带幽怨与娇嗔 说 [叹气]漂泊者，你就一点也不想着我吗？\n\n"
        "2. 简易指令合成（由 trigger_llm 自动生成语气与标签）：\n"
        "   /breeze说 早上好呀，今天也要加油哦！\n"
        "   /达妮娅说 哼，我才不在意你呢。[轻笑]\n\n"
        "3. 🎤 临时语音克隆（1 小时有效期）：\n"
        "   • 引用/回复一条语音消息，发送：/克隆语音 <角色名> <参考台词>\n"
        "     例如回复一条语音：/克隆语音 刻晴 剑光如雨！\n"
        "   • 1 小时内直接用该角色触发说话：\n"
        "     /刻晴说 博士，今天也要努力工作哦！\n"
        "     /刻晴 说话轻柔 说 晚上好，休息一会儿吧。\n"
        "   • 查询当前生效的克隆角色：发送 /克隆列表\n\n"
        "4. 查询标签说明：发送 /breeze标签 或 /breeze tags"
    )]))

    return nodes


class BreezeVoiceCloneManager:
    """
    Breeze-TTS 临时自定义语音克隆角色管理器。
    - 保存克隆音频到 data/voice/cache/clones 目录；
    - 记录触发角色名、参考音频路径、参考文本与过期时间（默认 1 小时 / 3600 秒）；
    - 支持一小时内通过 /xx说xxxx 或指定 speaker 触发语音克隆合成；
    - 持久化元数据至本地 JSON，兼容热重载。
    """

    DEFAULT_TTL_SECONDS = 3600.0  # 1 小时

    def __init__(self, data_file: str = "data/voice/cache/cloned_speakers.json"):
        self.data_file = Path(data_file)
        self.clones_dir = Path("data/voice/cache/clones")
        self.clones_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self.cleanup_expired()
            except Exception as e:
                logger.warning(f"[BreezeVoiceClone] 读取克隆角色记录失败: {e}")
                self._cache = {}

    def _save(self):
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[BreezeVoiceClone] 保存克隆角色记录失败: {e}")

    def cleanup_expired(self) -> int:
        """清理超过 1 小时的过期克隆角色与对应音频文件"""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if v.get("expires_at", 0) <= now]
        for k in expired_keys:
            info = self._cache.pop(k, None)
            if info:
                audio_path = Path(info.get("audio_path", ""))
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except Exception:
                        pass
        if expired_keys:
            self._save()
            logger.info(f"[BreezeVoiceClone] 已清理 {len(expired_keys)} 个过期的语音克隆角色: {expired_keys}")
        return len(expired_keys)

    def register_cloned_speaker(
        self,
        name: str,
        audio_source: Union[str, bytes],
        ref_text: str,
        user_id: int = 0,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> Dict[str, Any]:
        """
        注册一个新的临时克隆发音人：
        1. 转换/规范化音频为标准 24kHz WAV 并存入缓存目录；
        2. 设置当前时间 + 1 小时为过期时间；
        3. 保存至元数据。
        """
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip()) or "custom_speaker"
        target_wav_path = str(self.clones_dir / f"clone_{safe_name}_{uuid.uuid4().hex[:8]}.wav")

        converted_path = convert_to_wav_24k(audio_source, target_wav_path)
        now = time.time()
        expires_at = now + ttl_seconds

        record = {
            "speaker": name.strip(),
            "safe_name": safe_name,
            "audio_path": converted_path,
            "ref_text": (ref_text or "").strip(),
            "created_at": now,
            "expires_at": expires_at,
            "user_id": user_id,
        }

        self._cache[name.strip()] = record
        self._save()
        logger.info(
            f"[BreezeVoiceClone] 成功注册临时克隆角色: 【{name.strip()}】, "
            f"有效期 1 小时 (至 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))}), "
            f"音频: {converted_path}"
        )
        return record

    def get_cloned_speaker(self, name: str) -> Optional[Dict[str, Any]]:
        """查询有效的克隆角色，若已过期则自动删除并返回 None"""
        if not name:
            return None
        self.cleanup_expired()
        target = name.strip()
        for k, v in self._cache.items():
            if k == target or v.get("safe_name") == target:
                if v.get("expires_at", 0) > time.time():
                    return v
        return None

    def list_cloned_speakers(self) -> List[Dict[str, Any]]:
        """列出所有当前有效的克隆发音人"""
        self.cleanup_expired()
        results = []
        now = time.time()
        for k, v in self._cache.items():
            remain_sec = max(0.0, v.get("expires_at", 0) - now)
            results.append({
                "speaker": v.get("speaker", k),
                "ref_text": v.get("ref_text", ""),
                "audio_path": v.get("audio_path", ""),
                "remaining_minutes": int(remain_sec // 60),
                "expires_at_str": time.strftime("%H:%M:%S", time.localtime(v.get("expires_at", 0))),
            })
        return results


# 全局单例语音克隆管理器
breeze_clone_manager = BreezeVoiceCloneManager()


class AsyncBreezeTTSClient:
    """
    Breeze-TTS 2 异步客户端
    支持网关调用 (Bearer API Key) 与直连服务端两种连接模式。
    支持 /breeze/tts (配音指导与声音设计/克隆) 与 /v1/audio/speech (OpenAI流式语音规范) 两种端点。
    支持 trigger_llm 自动化语气生成与音频标签注入。
    支持上传 ref_audio 与 ref_text 进行高质量个性化语音克隆。
    """

    def __init__(self):
        pass

    @property
    def _cfg(self) -> Dict[str, Any]:
        """实时从 YAMLManager 中获取最新的 breeze_tts 配置"""
        try:
            return YAMLManager.get_instance().tts_v2.config.get("breeze_tts", {}) or {}
        except Exception:
            return {}

    @property
    def connection_mode(self) -> str:
        """'gateway' 或 'direct'"""
        mode = str(self._cfg.get("connection_mode", "gateway")).lower().strip()
        return "direct" if mode in ["direct", "直连", "local"] else "gateway"

    @property
    def gateway_url(self) -> str:
        return (self._cfg.get("gateway_url") or DEFAULT_GATEWAY_URL).rstrip("/")

    @property
    def direct_url(self) -> str:
        return (self._cfg.get("direct_url") or DEFAULT_DIRECT_URL).rstrip("/")

    @property
    def api_key(self) -> str:
        key = self._cfg.get("api_key")
        if key:
            return key
        try:
            cfg = YAMLManager.get_instance()
            k = cfg.tts_v2.config.get("tts", {}).get("api_key")
            if k:
                return k
            mai = getattr(cfg, "core_reply", None)
            if mai:
                k = mai.config.get("trigger_llm", {}).get("api_key")
                if k:
                    return k
        except Exception:
            pass
        return DEFAULT_API_KEY

    @property
    def mode(self) -> str:
        return self.default_mode

    @property
    def default_mode(self) -> str:
        """'breeze_tts' 或 'openai_speech'"""
        m = str(self._cfg.get("mode", "breeze_tts")).lower().strip()
        if "speech" in m or "openai" in m:
            return "openai_speech"
        return "breeze_tts"

    @property
    def auto_generate_instruction(self) -> bool:
        return bool(self._cfg.get("auto_generate_instruction", True))

    @property
    def auto_add_audio_tags(self) -> bool:
        return bool(self._cfg.get("auto_add_audio_tags", True))

    @property
    def default_instruction(self) -> str:
        return self._cfg.get("default_instruction", "说话轻柔温和，略带自然真实的情感。")

    @property
    def base_tone(self) -> str:
        """从配置文件读取角色固有性格与声音基调，若未配置则回退到 default_instruction"""
        return str(
            self._cfg.get("base_tone")
            or self._cfg.get("instruction_base_tone")
            or self.default_instruction
        ).strip()

    @property
    def default_cfg_scale(self) -> float:
        try:
            return float(self._cfg.get("cfg_scale", 4.0))
        except (ValueError, TypeError):
            return 4.0

    @property
    def default_voice(self) -> str:
        return self._cfg.get("voice", "dania")

    @property
    def default_model(self) -> str:
        return self._cfg.get("model", "breeze-tts-2")

    @property
    def default_speed(self) -> float:
        """默认语速调节（支持 0.5 ~ 2.0，默认 1.0）"""
        try:
            spd = self._cfg.get("speed")
            if spd is not None:
                return float(spd)
            vs = self._cfg.get("voice_settings")
            if isinstance(vs, dict) and "speed" in vs:
                return float(vs["speed"])
        except (ValueError, TypeError):
            pass
        return 1.0

    @property
    def default_volume(self) -> float:
        """默认音量调节（支持 0.1 ~ 2.0，默认 1.0）"""
        try:
            vol = self._cfg.get("volume")
            if vol is not None:
                return float(vol)
            vs = self._cfg.get("voice_settings")
            if isinstance(vs, dict) and "volume" in vs:
                return float(vs["volume"])
        except (ValueError, TypeError):
            pass
        return 1.0

    @property
    def default_voice_settings(self) -> Dict[str, Any]:
        """从配置中组装 voice_settings 字典"""
        raw_vs = self._cfg.get("voice_settings")
        vs: Dict[str, Any] = {}
        if isinstance(raw_vs, dict):
            vs.update(raw_vs)
        if "speed" not in vs and abs(self.default_speed - 1.0) > 1e-4:
            vs["speed"] = self.default_speed
        if "volume" not in vs and abs(self.default_volume - 1.0) > 1e-4:
            vs["volume"] = self.default_volume
        return vs

    async def fetch_remote_speakers(self) -> List[str]:
        """向上游微服务查询全部可用角色列表 (/breeze/speakers 或 /v1/speakers)"""
        now = time.time()
        if hasattr(self, "_remote_speakers_cache") and (now - getattr(self, "_last_speakers_fetch_time", 0.0) < 60.0):
            return list(self._remote_speakers_cache)

        is_gateway = (self.connection_mode == "gateway")
        target_url = f"{self.gateway_url}/breeze/speakers" if is_gateway else f"{self.direct_url}/v1/speakers"
        headers = {}
        if is_gateway and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    res_list = []
                    if isinstance(data, list):
                        res_list = [str(x) for x in data if x]
                    elif isinstance(data, dict):
                        cands = data.get("speakers") or data.get("data") or []
                        if isinstance(cands, list):
                            res_list = [str(x) for x in cands if x]
                    if res_list:
                        self._remote_speakers_cache = res_list
                        self._last_speakers_fetch_time = now
                        return list(res_list)
        except Exception as e:
            logger.debug(f"[BreezeTTS] 获取上游可用角色列表失败或上游未就绪: {e}")

        return list(getattr(self, "_remote_speakers_cache", []))

    @property
    def speakers(self) -> List[str]:
        spks = self._cfg.get("speakers", ["达妮娅", "dania", "breeze", "breeze-tts", "breeze-tts-2"])
        base_list = list(spks) if isinstance(spks, (list, tuple)) else ["达妮娅", "dania", "breeze"]
        cached_remote = getattr(self, "_remote_speakers_cache", [])
        for spk in cached_remote:
            if spk not in base_list:
                base_list.append(spk)
        return base_list

    async def enrich_with_trigger_llm(
        self,
        text: str,
        instruction: Optional[str] = None,
        config: Any = None,
    ) -> Tuple[str, str]:
        """
        利用 trigger_llm 对输入文本进行智能化处理：
        1. 若未传入 instruction 且开启了 auto_generate_instruction，自动生成配音语气指导语；
        2. 若开启了 auto_add_audio_tags 且文本中尚无音频标签，结合情绪与语境智能插入 [叹气]、[轻笑] 等表现力标签。
        """
        need_instruction = (not instruction) and self.auto_generate_instruction
        need_tags = self.auto_add_audio_tags and not bool(re.search(r"\[(" + "|".join(re.escape(name) for name in ALL_BREEZE_TAG_NAMES) + r")\]", text))

        if not need_instruction and not need_tags:
            return text, (instruction or self.default_instruction)

        llm_api_key = self.api_key
        llm_base_url = f"{self.gateway_url}/v1"
        llm_model = "gemini-2.5-flash"

        try:
            cfg_obj = config or YAMLManager.get_instance()
            mai_cfg = getattr(cfg_obj, "core_reply", None)
            if mai_cfg:
                t_cfg = mai_cfg.config.get("trigger_llm", {}) or {}
                if t_cfg.get("api_key"):
                    llm_api_key = t_cfg.get("api_key")
                if t_cfg.get("base_url"):
                    llm_base_url = t_cfg.get("base_url").rstrip("/")
                if t_cfg.get("model"):
                    llm_model = t_cfg.get("model")
                else:
                    openai_cfg = mai_cfg.config.get("llm", {}).get("openai", {})
                    if openai_cfg.get("model"):
                        llm_model = openai_cfg.get("model")
        except Exception as e:
            logger.debug(f"[BreezeTTS] 读取 trigger_llm 配置异常: {e}")

        base_tone = self.base_tone
        prompt = (
            "你是一个专业的AI语音合成配音导演与台词指导。\n"
            f"当前角色的固有性格与声音基调为：【{base_tone}】。\n"
            "请在保持这一基础声音基调与人设风格的前提下，结合具体的台词语境与情绪起伏，为待合成文本生成简练生动的配音语气指导语 (instruction)，"
            "并根据语境在台词合适位置插入0~2个合法的音频表现力标签 (tagged_text)。\n\n"
            "【可用中文音频表现力标签）】\n"
            "- 笑声：[笑]、[轻笑]、[咯咯笑]\n"
            "- 哭泣与痛苦：[哭声]、[抽泣]、[呜咽]、[呻吟]、[哀号]\n"
            "- 呼吸与叹息：[叹气]、[惊呼]、[吸气]、[呼气]、[喘息]\n"
            "- 语气与腔调：[耳语]、[喊叫]、[惨叫]、[唱歌]、[哼歌]、[结巴]、[停顿]\n"
            "- 咽喉与鼻腔 ：[清嗓]、[咳嗽]、[吸鼻子]\n"
            "- 嘴部动作：[咂嘴]、[啧嘴]\n"
            "- 生理反射 ：[打哈欠]、[打喷嚏]、[打嗝]、[打饱嗝]、[吞咽]、[干呕]\n"
            "- 情绪反应 ：[闷哼]、[冷笑]、[哼鼻子]\n\n"
            "生成要求：\n"
            "1. 必须输出标准 JSON 对象，包含且仅包含两个字段：\"instruction\" 和 \"tagged_text\"。\n"
            f"2. \"instruction\"：15字以内简练生动的配音指导语。必须符合角色的固有基调【{base_tone}】，在此基调上体现当前句子的细微情绪波动（例如在基调基础上体现略带撒娇、疑惑、欣慰等细微变化）。\n"
            "3. \"tagged_text\"：在原台词的恰当位置插入0~2个上述官方列出的合法音频标签（只能使用上方列出的官方标签，严禁自行臆造标签如 [大笑]、[微笑] 或使用英文标签），不得大幅修改原台词词句，若不适合加标签则保持原台词。\n"
            f"待合成文本：\"{text}\"\n"
            "仅输出 JSON 对象： {\"instruction\": \"...\", \"tagged_text\": \"...\"}"
        )

        chat_url = f"{llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if llm_api_key:
            headers["Authorization"] = f"Bearer {llm_api_key}"
        payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": "你是一个专业语音合成配音导演，请严格输出标准 JSON 格式。"},
                {"role": "user", "content": prompt}
            ],
            #"response_format": {"type": "json_object"},
            "temperature": 0.5,
            "max_tokens": 250,
        }

        final_instruction = instruction or self.default_instruction
        final_text = text

        try:
            logger.info(f"[BreezeTTS] 正在调用 trigger_llm 增强语气与标签 (model={llm_model})...")
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.post(chat_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        raw_content = choices[0]["message"].get("content", "").strip()
                        # Ignore Markdown fences and surrounding prose from non-structured models.
                        json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
                        dict_str = json_match.group(0) if json_match else None

                        if dict_str:
                            res_json = json.loads(dict_str)
                            if need_instruction and res_json.get("instruction"):
                                final_instruction = str(res_json["instruction"]).strip()
                            if need_tags and res_json.get("tagged_text"):
                                tagged_cand = str(res_json["tagged_text"]).strip()
                                if any(t in tagged_cand for t in ALL_BREEZE_TAGS):
                                    final_text = tagged_cand

                            logger.info(
                                f"[BreezeTTS] trigger_llm 增强成功: "
                                f"instruction='{final_instruction}', text='{final_text}'"
                            )
        except Exception as e:
            logger.warning(f"[BreezeTTS] trigger_llm 增强语气与标签失败，回退默认: {e}")

        return final_text, final_instruction

    async def generate_tts(
        self,
        text: str,
        instruction: Optional[str] = None,
        cfg_scale: Optional[float] = None,
        mode: Optional[str] = None,
        connection_mode: Optional[str] = None,
        voice: Optional[str] = None,
        speaker: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        voice_settings: Optional[Union[Dict[str, Any], str]] = None,
        save_path: Optional[str] = None,
        auto_tag: bool = True,
        ref_audio: Optional[Union[str, bytes]] = None,
        ref_text: Optional[str] = None,
        bot: Any = None,
        config: Any = None,
    ) -> str:
        """
        核心语音合成调度入口：
        支持网关模式与直连模式；
        支持自选传入指定 speaker（官方注册音色、克隆音色）；
        支持 voice_settings 规范化透传，支持调节 speed（语速）与 volume（音量）；
        支持 breeze_tts (/breeze/tts) 与 openai_speech (/v1/audio/speech) 两种模式；
        支持 ref_audio 与 ref_text 声音克隆 (Voice Clone) 模式。
        """
        # 1. 清洗文本并保留合法音频标签
        cleaned_text = protect_and_clean_breeze_text(text)
        if not cleaned_text:
            raise ValueError("Breeze TTS 输入文本为空或不含可朗读文本")

        # 2. 如果开启了 trigger_llm 自动生成或需要标签润色 (语音克隆模式下通常保留指定语气)
        if auto_tag and not ref_audio:
            cleaned_text, instruction = await self.enrich_with_trigger_llm(
                cleaned_text, instruction=instruction, config=config
            )

        # 3. 确定参数与模式
        chosen_mode = (mode or self.default_mode).lower().strip()
        is_speech_mode = ("speech" in chosen_mode or "openai" in chosen_mode)
        chosen_conn = (connection_mode or self.connection_mode).lower().strip()
        is_gateway = (chosen_conn not in ["direct", "直连", "local"])

        # CFG Scale 计算：声音克隆无指令时推荐 1.0；带语气指令时 4.0
        if cfg_scale is not None:
            scale = float(cfg_scale)
        elif ref_audio and not instruction:
            scale = 1.0
        else:
            scale = float(self.default_cfg_scale)

        # 发音人音色解析：支持自选传入更多 speaker
        chosen_speaker = speaker or voice or self.default_voice
        if str(chosen_speaker).lower() in ["breeze", "breeze-tts", "breeze-tts-2", "breeze_tts"]:
            target_speaker = "dania"
        else:
            target_speaker = str(chosen_speaker).strip()

        # 规范化并组装 voice_settings（支持 speed、volume）
        vs_dict: Dict[str, Any] = {}
        if isinstance(voice_settings, dict):
            vs_dict.update(voice_settings)
        elif isinstance(voice_settings, str) and voice_settings.strip():
            try:
                parsed = json.loads(voice_settings)
                if isinstance(parsed, dict):
                    vs_dict.update(parsed)
            except Exception:
                pass

        # 语速调节 (speed)
        act_speed = speed if speed is not None else vs_dict.get("speed", self.default_speed)
        if act_speed is not None:
            try:
                spd_val = float(act_speed)
                if abs(spd_val - 1.0) > 1e-4 or "speed" in vs_dict:
                    vs_dict["speed"] = spd_val
            except (ValueError, TypeError):
                pass

        # 音量调节 (volume)
        act_volume = volume if volume is not None else vs_dict.get("volume", self.default_volume)
        if act_volume is not None:
            try:
                vol_val = float(act_volume)
                if abs(vol_val - 1.0) > 1e-4 or "volume" in vs_dict:
                    vs_dict["volume"] = vol_val
            except (ValueError, TypeError):
                pass

        if not save_path:
            save_path = f"data/voice/cache/{uuid.uuid4().hex}.wav"

        # 4. 判断是否为声音克隆请求 (上传 ref_audio)
        ref_audio_bytes = None
        if ref_audio:
            if isinstance(ref_audio, bytes):
                ref_audio_bytes = ref_audio
            elif isinstance(ref_audio, (str, Path)) and os.path.exists(str(ref_audio)):
                with open(str(ref_audio), "rb") as rf:
                    ref_audio_bytes = rf.read()
            if ref_audio_bytes and not is_wav(ref_audio_bytes):
                # 尝试转为标准 WAV
                conv_path = convert_to_wav_24k(ref_audio_bytes)
                with open(conv_path, "rb") as wf:
                    ref_audio_bytes = wf.read()

        # 5. 组装请求地址、Headers 与 Payload
        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
            if ref_audio_bytes:
                # 声音克隆模式：使用 multipart/form-data
                target_url = f"{self.gateway_url}/breeze/tts" if is_gateway else f"{self.direct_url}/tts"
                headers = {}
                if is_gateway and self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                form_data = {
                    "text": cleaned_text,
                    "cfg_scale": str(scale),
                    "format": "wav",
                }
                if target_speaker:
                    form_data["speaker"] = str(target_speaker)
                    form_data["voice"] = str(target_speaker)
                if ref_text:
                    form_data["ref_text"] = str(ref_text)
                if instruction:
                    form_data["instruction"] = str(instruction)
                if vs_dict:
                    form_data["voice_settings"] = json.dumps(vs_dict, ensure_ascii=False)
                if "speed" in vs_dict:
                    form_data["speed"] = str(vs_dict["speed"])
                if "volume" in vs_dict:
                    form_data["volume"] = str(vs_dict["volume"])

                files = {
                    "ref_audio": ("ref_audio.wav", ref_audio_bytes, "audio/wav")
                }

                logger.info(
                    f"[BreezeTTS] 发起语音克隆合成: 连接={'网关' if is_gateway else '直连'}, "
                    f"URL={target_url}, speaker={target_speaker}, ref_bytes={len(ref_audio_bytes)}, "
                    f"vs={vs_dict or '无'}, text='{cleaned_text[:30]}...'"
                )
                resp = await client.post(target_url, data=form_data, files=files, headers=headers)

            elif is_speech_mode:
                # Mode 2: OpenAI /v1/audio/speech 模式
                target_url = f"{self.gateway_url}/v1/audio/speech" if is_gateway else f"{self.direct_url}/v1/audio/speech"
                headers = {"Content-Type": "application/json"}
                if is_gateway and self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                payload: Dict[str, Any] = {
                    "model": self.default_model,
                    "input": cleaned_text,
                    "text": cleaned_text,
                    "voice": str(target_speaker),
                    "speaker": str(target_speaker),
                    "response_format": "wav",
                    "cfg_scale": scale,
                }
                if instruction:
                    payload["instruction"] = instruction
                if vs_dict:
                    payload["voice_settings"] = vs_dict
                if "speed" in vs_dict:
                    payload["speed"] = vs_dict["speed"]
                if "volume" in vs_dict:
                    payload["volume"] = vs_dict["volume"]

                logger.info(
                    f"[BreezeTTS] 发起 speech 合成: 连接={'网关' if is_gateway else '直连'}, "
                    f"URL={target_url}, speaker={target_speaker}, vs={vs_dict or '无'}, text='{cleaned_text[:30]}...'"
                )
                resp = await client.post(target_url, json=payload, headers=headers)

            else:
                # Mode 1: 原生 Breeze /breeze/tts 模式
                target_url = f"{self.gateway_url}/breeze/tts" if is_gateway else f"{self.direct_url}/tts"
                headers = {"Content-Type": "application/json"}
                if is_gateway and self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                payload: Dict[str, Any] = {
                    "text": cleaned_text,
                    "format": "wav",
                    "cfg_scale": scale,
                    "speaker": str(target_speaker),
                    "voice": str(target_speaker),
                }
                if instruction:
                    payload["instruction"] = instruction
                if vs_dict:
                    payload["voice_settings"] = vs_dict
                if "speed" in vs_dict:
                    payload["speed"] = vs_dict["speed"]
                if "volume" in vs_dict:
                    payload["volume"] = vs_dict["volume"]

                logger.info(
                    f"[BreezeTTS] 发起原生合成: 连接={'网关' if is_gateway else '直连'}, "
                    f"URL={target_url}, speaker={target_speaker}, vs={vs_dict or '无'}, instruction='{instruction or '无'}', text='{cleaned_text[:30]}...'"
                )
                resp = await client.post(target_url, json=payload, headers=headers)

            if resp.status_code != 200:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise RuntimeError(f"Breeze TTS 请求失败! HTTP {resp.status_code}: {err}")

            raw_bytes = resp.content
            if not raw_bytes:
                raise RuntimeError("Breeze TTS 服务端返回空音频流")

            final_wav = pcm_to_wav(raw_bytes) if not is_wav(raw_bytes) else raw_bytes

        out_path = Path(save_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(final_wav)

        logger.info(f"[BreezeTTS] 音频合成完成，大小: {len(final_wav)} 字节，已保存至: {save_path}")
        return str(out_path)
