import re
import httpx
from typing import Optional
from developTools.utils.logger import get_logger

logger = get_logger("tts_translator")


def normalize_language(target_lang: str) -> str:
    """Use one language identity for config values, translation and synthesis."""
    target = str(target_lang).strip().upper().replace("-", "_")
    aliases = {"EN": "EN", "EN_US": "EN", "EN_GB": "EN", "ENGLISH": "EN",
               "JP": "JP", "JA": "JP", "JA_JP": "JP",
               "ZH": "ZH", "ZH_CN": "ZH", "ZH_TW": "ZH", "CN": "ZH"}
    if target not in aliases:
        raise ValueError(f"不支持的 TTS 目标语言: {target_lang}，请使用 EN / JP / ZH")
    return aliases[target]


def translation_options(config=None, *, fallback_config=None) -> dict:
    """Keep explicit translator credentials separate from the last-resort trigger LLM."""
    if isinstance(config, dict):
        tts_config = config
        system_config = fallback_config
    else:
        tts_config = getattr(getattr(config, "tts_v2", None), "config", {}) or {}
        system_config = config or fallback_config
    settings = tts_config.get("translator", {}) or {}
    core = getattr(getattr(system_config, "core_reply", None), "config", {}) or {}
    trigger = core.get("trigger_llm", {}) or {}

    def options(values):
        return {key: str(values.get(key) or "").strip() or None
                for key in ("api_key", "base_url", "model")}

    return {**options(settings), "fallback_llm": options(trigger)}


def clean_tts_text(text: str) -> str:
    """清洗文本：去除 Markdown 代码块、行内代码、各类心理描写/动作描写括号（小括号、方括号、黑括号等），保留纯发音字符"""
    if not text:
        return ""
    # 1. 优先去掉多行 markdown 代码块 ```...```
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # 2. 去掉行内代码 `...`
    text = re.sub(r"`.*?`", "", text)
    # 3. 去掉各类动作/心理描写的括号内容：
    #    - 全角/半角圆括号: （...）, (...)
    #    - 方括号与黑括号: 【...】, [...]
    #    - 星号动作: *...*
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"[【\[][^】\]]*[】\]]", "", text)
    text = re.sub(r"\*[^*]+\*", "", text)
    # 4. 去除可能残留的单边符号与特殊标点
    text = text.replace("```", "").replace("`", "")
    text = text.replace("～", "").replace("~", "").replace("-", "")
    return text.strip()

async def translate_text(
    text: str,
    target_lang: str = "JP",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    model: Optional[str] = None,
    fallback_llm: Optional[dict] = None,
    preserve_audio_tags: bool = False,
    strict: bool = False,
) -> str:
    """Explicit translator first, then Youdao, then the configured trigger LLM.

    All three explicit translator fields are required. An absent or incomplete
    translator starts with Youdao; trigger credentials are used only after failure.
    Translate to EN/JP; ZH keeps the source, optionally with tags.

    The synthesis pipeline uses strict EN translation so an outage cannot silently
    produce Chinese speech for an English request. Direct callers retain the
    historical source-text fallback unless they also request strict mode.
    """
    target = normalize_language(target_lang)
    if preserve_audio_tags:
        from .breeze_tts import ALL_BREEZE_TAG_NAMES, protect_and_clean_breeze_text
        cleaned = protect_and_clean_breeze_text(text)
        tags = "|".join(re.escape(name) for name in ALL_BREEZE_TAG_NAMES)
        parts = re.split(r"(\[(?:" + tags + r")\])", cleaned)
    else:
        cleaned = clean_tts_text(text)
        parts = [cleaned]
    if not cleaned or target == "ZH":
        return cleaned

    translated = []
    for index, part in enumerate(parts):
        if index % 2 or not part.strip():
            translated.append(part)
            continue
        # Plain English (including punctuation/numbers) needs no network round trip.
        if target == "EN" and not any(c.isalpha() and not ("a" <= c.lower() <= "z") for c in part):
            translated.append(part)
            continue
        translated.append(await _translate_cleaned_text(
            part, target, api_key, base_url, model=model, fallback_llm=fallback_llm, strict=strict))
    return "".join(translated)


async def _translate_cleaned_text(
    cleaned: str, target: str, api_key: Optional[str], base_url: Optional[str],
    *, model: Optional[str], fallback_llm: Optional[dict], strict: bool,
) -> str:
    """
    显式 translator → 有道 → trigger_llm → 公共备用；任一步成功立即返回。
    """
    def usable(value):
        if not isinstance(value, str) or not value.strip():
            return False
        # Some failed providers return the unmodified Chinese input as a success.
        return target != "EN" or not re.search(r"[\u3400-\u9fff\u3040-\u30ff]", value)

    async def llm_translate(options, label):
        values = {key: str(options.get(key) or "").strip()
                  for key in ("base_url", "model", "api_key")}
        if not all(values.values()):
            return None
        try:
            base = values["base_url"].rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            target_desc = "日文" if target == "JP" else "英文"
            payload = {
                "model": values["model"],
                "messages": [
                    {"role": "system", "content": f"你是一个专业的口语文本文档翻译员。请直接将用户的输入文本翻译为自然的{target_desc}。要求：绝不要添加任何说明、解释、罗马音或符号，只返回翻译后的纯文本。"},
                    {"role": "user", "content": cleaned},
                ],
                "temperature": 0.3,
                "max_tokens": max(200, len(cleaned) * 3),
            }
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.post(base + "/chat/completions", json=payload,
                    headers={"Authorization": "Bearer " + values["api_key"], "Content-Type": "application/json"})
                if response.status_code == 200:
                    choices = response.json().get("choices", [])
                    if choices and choices[0].get("finish_reason") != "length":
                        text = choices[0].get("message", {}).get("content")
                        if usable(text):
                            logger.info(f"[TTS Translator] {label} 翻译成功")
                            return text.strip()
        except Exception:
            # Avoid logging a credential-bearing client exception or response body.
            logger.debug(f"[TTS Translator] {label} 翻译异常，尝试下一来源")
        return None

    # 1. 仅三项均填全时优先使用专用 translator；不借用其他配置补全。
    result = await llm_translate({"base_url": base_url, "model": model, "api_key": api_key}, "translator")
    if result is not None:
        return result

    # 2. 未配置 translator 或调用失败时使用有道，不携带任何用户 key。
    try:
        yd_lang = "ja" if target == "JP" else "en"
        yd_data = {"q": cleaned, "from": "zh-CHS", "to": yd_lang}
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            response = await client.post("https://aidemo.youdao.com/trans", data=yd_data,
                                         headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 200:
                translations = response.json().get("translation")
                if isinstance(translations, list) and translations and usable(translations[0]):
                    trans = translations[0].strip()
                    logger.info(f"[TTS Translator] 有道翻译成功: '{cleaned}' -> '{trans}'")
                    return trans
    except Exception as exc:
        logger.debug(f"[TTS Translator] 有道翻译异常: {exc}")

    # 3. translator 不可用（或未配置）且有道失败后，才允许消耗 trigger_llm 配额。
    result = await llm_translate(fallback_llm or {}, "trigger_llm")
    if result is not None:
        return result

    # 3. 备用接口 2: appworlds (通用备用)
    try:
        to_lang = "ja" if target in ["JP", "JA"] else "en"
        import urllib.parse
        encoded_text = urllib.parse.quote(cleaned)
        url = f"https://translate.appworlds.cn?text={encoded_text}&from=zh-CN&to={to_lang}"
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            r = await client.get(url)
            if r.status_code == 200:
                res = r.json()
                if isinstance(res, dict) and usable(res.get("data")):
                    logger.info(f"[TTS Translator] AppWorlds 翻译成功: '{cleaned}' -> '{res['data']}'")
                    return str(res["data"])
    except Exception as e:
        logger.debug(f"[TTS Translator] AppWorlds 异常: {e}")

    # 4. 备用接口 3: findmyip
    try:
        to_lang = "ja" if target in ["JP", "JA"] else "en"
        url = "https://findmyip.net/api/translate.php"
        async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
            r = await client.get(url, params={"text": cleaned, "target_lang": to_lang})
            if r.status_code == 200:
                res = r.json()
                if isinstance(res.get("data"), dict) and usable(res["data"].get("translate_result")):
                    return res["data"]["translate_result"]
    except Exception as e:
        logger.debug(f"[TTS Translator] findmyip 异常: {e}")

    # 5. 备用接口 4: pearktrue
    try:
        mode = "ZH_CN2JA" if target in ["JP", "JA"] else "ZH_CN2EN"
        url = "https://api.pearktrue.cn/api/translate/"
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            r = await client.get(url, params={"text": cleaned, "type": mode})
            if r.status_code == 200:
                res = r.json()
                if isinstance(res.get("data"), dict) and usable(res["data"].get("translate")):
                    return res["data"]["translate"]
    except Exception as e:
        logger.debug(f"[TTS Translator] pearktrue 异常: {e}")

    if strict:
        raise RuntimeError(f"TTS 翻译为 {target} 失败：所有翻译接口均未返回有效译文，已停止合成")
    logger.warning(f"[TTS Translator] 翻译为 {target} 失败，回退原文")
    return cleaned
