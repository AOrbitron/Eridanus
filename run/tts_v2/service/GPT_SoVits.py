import traceback
import uuid
import aiohttp
import asyncio
import os

from framework_common.framework_util.yamlLoader import YAMLManager

config = YAMLManager.get_instance()
class AsyncGPTSoVITSClient:
    def __init__(
        self,
        base_url=None,
        ref_audio_path=None,
        ref_text=None,
    ):
        """
        :param base_url: api_v2.py 服务端地址 (例如: http://123.45.67.89:9880)

        注意：不在此快照 speakers / api_key —— 改为 property 每次实时读取配置。
        这样 tts_v2 配置热重载后，即便本实例被 core_reply 等其它插件长期持有，
        也会立即用上新配置，而不是停留在实例创建时的旧值（历史上的“热重载后仍用旧变量”）。
        """
        pass

    @property
    def _gpt_sovits_cfg(self):
        # 每次实时取当前配置：YAMLManager 是单例，热重载时原地更新其数据，故实时读取即为最新。
        return YAMLManager.get_instance().tts_v2.config.get("gpt_sovits", {}) or {}

    @property
    def speakers(self):
        return self._gpt_sovits_cfg.get("speakers", {})

    @property
    def api_key(self):
        return self._gpt_sovits_cfg.get("api_key", "") or ""

    @property
    def use_gateway(self):
        # api_key 非空 => 经过 api 网关；为空 => 直连真实服务端
        return self.api_key != ""

    async def generate_tts(
        self,
        target_text,
        ref_audio_path=None,
        ref_text=None,
        target_lang="zh",
        ref_lang="zh",
        output_save_path=None,
        # 以下为可选推理参数
        top_k=None,
        top_p=None,
        temperature=None,
        text_split_method="cut5",
        batch_size=None,
        speed_factor=None,
        streaming_mode=None,
        seed=None,
        media_type="wav",
    ):
        """
        调用 api_v2.py 的 /tts 接口生成语音
        :param ref_audio_path: 参考音频本地路径（服务端能访问到的绝对路径，或远程服务器上的路径）
        """
        cfg = self._gpt_sovits_cfg
        if ref_audio_path is None:
            ref_audio_path = cfg.get("ref_audio_path", "")
        if ref_text is None:
            ref_text = cfg.get("ref_text", "")
        if output_save_path is None:
            output_save_path = "data/voice/cache/" + uuid.uuid4().hex + ".wav"

        # 完整推理参数：直连真实服务端时原样使用；
        # 经过网关时，网关会用其中和白名单同名的字段覆盖网关自己的默认值，
        # 未传的字段网关会自动补全（参考音频/prompt等）。
        payload = {
            "text": target_text,
            "text_lang": target_lang,
            "ref_audio_path": ref_audio_path,   # api_v2 直接接受服务端路径，无需上传
            "prompt_text": ref_text,
            "prompt_lang": ref_lang,
            "top_k": top_k or cfg.get("top_k", 15),
            "top_p": top_p or cfg.get("top_p", 1.0),
            "temperature": temperature or cfg.get("temperature", 1.0),
            "text_split_method": text_split_method or cfg.get("text_split_method", "cut1"),
            "batch_size": batch_size or cfg.get("batch_size", 1),
            "speed_factor": speed_factor or cfg.get("speed_factor", 1.0),
            "streaming_mode": streaming_mode if streaming_mode is not None else cfg.get("streaming_mode", False),
            "seed": seed or cfg.get("seed", -1),
            "fragment_interval": 0.32,
            "media_type": media_type,
            "repetition_penalty": cfg.get("repetition_penalty", 1.35),
        }

        base_url = cfg.get("api_base", "")
        if self.use_gateway:
            url = f"{base_url}/gptsovits/tts"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        else:
            url = f"{base_url}/tts"
            headers = None

        print(payload)
        print(f"正在请求 TTS {url}({'网关' if self.use_gateway else '直连'}): {target_text[:20]}...")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    try:
                        error = await resp.json()
                    except Exception:
                        error = await resp.text()
                    raise Exception(f"TTS 请求失败! HTTP {resp.status}: {error}")

                out_dir = os.path.dirname(output_save_path)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                with open(output_save_path, "wb") as f:
                    f.write(await resp.read())

        print(f"生成完成，已保存至: {output_save_path}")
        return output_save_path

    async def set_gpt_weights(self, weights_path: str):
        if self.use_gateway:
            raise Exception("当前为api网关模式，网关未提供 set_gpt_weights 接口，无法切换GPT模型")
        base_url=self._gpt_sovits_cfg.get("api_base", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/set_gpt_weights",
                params={"weights_path": weights_path},
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise Exception(f"切换 GPT 模型失败: {data}")
                print(f"GPT 模型已切换: {weights_path}")

    async def set_sovits_weights(self, weights_path: str):
        if self.use_gateway:
            raise Exception("当前为api网关模式，网关未提供 set_sovits_weights 接口，无法切换SoVITS模型")
        base_url = self._gpt_sovits_cfg.get("api_base", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/set_sovits_weights",
                params={"weights_path": weights_path},
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise Exception(f"切换 SoVITS 模型失败: {data}")
                print(f"SoVITS 模型已切换: {weights_path}")