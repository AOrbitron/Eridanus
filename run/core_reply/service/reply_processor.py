"""
reply_processor.py
回复后处理器 —— 发送消息并自动记录 message_id 以便下次检测别人是否在"回复我"
"""

import asyncio
import random
import re
from typing import List

_TYPO_MAP = {
    "的": "地", "地": "的", "得": "的", "在": "再", "再": "在",
    "他": "她", "她": "他", "没": "有", "不": "步", "我": "窝",
    "你": "泥", "好": "号", "吗": "嘛", "呢": "捏", "嗯": "恩",
    "哦": "噢", "啊": "a", "吧": "把", "了": "l", "是": "事",
    "说": "碎", "想": "向", "来": "了", "去": "趋", "对": "队",
}
_SPLIT_PUNCTUATIONS =["。", "！", "？", "…", "...", "\n", "~", "～"]

def clean_markdown(text: str) -> str:
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    #text = re.sub(r"```[\s\S]*?```", "[代码省略]", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_message(text: str, threshold: int = 60) -> List[str]:
    if not text:
        return []

    # 第一步：优先使用特殊符号 || 进行切分
    if "||" in text:
        segments = [s.strip() for s in text.split("||") if s.strip()]
    else:
        segments = [text.strip()]

    final_segments = []

    # 第二步：遍历初步切分好的段落
    for seg in segments:
        if not seg:
            continue

        # 如果单条已经足够短，直接加入
        if len(seg) <= threshold:
            final_segments.append(seg)
            continue

        # 第三步：如果某单条依然超长，再按标点符号进行强行截断 (Fallback)
        current = ""
        i = 0
        while i < len(seg):
            char = seg[i]
            current += char
            # 处理省略号不被切断
            if seg[i:i + 3] == "...":
                current = current[:-1] + "..."
                i += 3
                if current.strip(): final_segments.append(current.strip())
                current = ""
                continue
            # 遇到标点且达到长度阈值一半时截断
            if char in _SPLIT_PUNCTUATIONS and len(current) >= threshold // 2:
                if current.strip(): final_segments.append(current.strip())
                current = ""
            i += 1

        if current.strip():
            final_segments.append(current.strip())

    return final_segments

def apply_typo(text: str, probability: int = 8) -> str:
    if not text or probability <= 0 or random.randint(1, 100) > probability: return text
    candidates =[(i, c) for i, c in enumerate(text) if c in _TYPO_MAP]
    if not candidates: return text
    idx, char = random.choice(candidates)
    return text[:idx] + _TYPO_MAP[char] + text[idx + 1:]

def calc_typing_delay(text: str, ms_per_char: int = 30, max_ms: int = 4000) -> float:
    if ms_per_char <= 0: return 0.0
    delay_ms = min(len(text) * ms_per_char, max_ms)
    delay_ms = max(0, delay_ms + delay_ms * random.uniform(-0.15, 0.15))
    return delay_ms / 1000.0


class ReplyProcessor:

    def __init__(self, config, context_manager=None):
        self.cfg = config
        self.ctx = context_manager  # 保存上下文管理器，用于写入 Bot 发过的消息 ID

        hlcfg = config.core_reply.config.get("human_like", {})
        self.typing_ms_per_char: int = int(hlcfg.get("typing_delay_ms_per_char", 30))
        self.typing_max_ms: int = int(hlcfg.get("typing_delay_max_ms", 4000))
        self.split_threshold: int = int(hlcfg.get("split_threshold", 60))
        self.split_interval_ms: int = int(hlcfg.get("split_interval_ms", 800))
        self.typo_probability: int = int(hlcfg.get("typo_probability", 8))
        self.quote_reply: bool = hlcfg.get("quote_reply", True)
        self.quote_probability: int = int(hlcfg.get("quote_reply_probability", 40))

    def process(self, raw_reply: str) -> List[str]:
        if not raw_reply: return[]
        text = clean_markdown(raw_reply)
        segments = split_message(text, self.split_threshold) if self.split_threshold > 0 else [text]
        if segments and self.typo_probability > 0:
            segments[0] = apply_typo(segments[0], self.typo_probability)
        return[s for s in segments if s.strip()]

    async def send_with_delay(self, bot, event, segments: List[str], quote_message_id=None) -> None:
        from developTools.message.message_components import Text, Reply

        for i, seg in enumerate(segments):
            delay = calc_typing_delay(seg, self.typing_ms_per_char, self.typing_max_ms)
            if delay > 0:
                await asyncio.sleep(delay)
            
            components =[]
            if i == 0 and quote_message_id and self.quote_reply:
                if random.randint(1, 100) <= self.quote_probability:
                    components.append(Reply(id=quote_message_id))

            if seg.startswith('1girl, teenager, anime style'):continue
            if '1girl, teenager, anime style' in seg:
                seg = seg[:seg.find('1girl, teenager, anime style')]
            if seg.endswith('\n'): seg = seg[:-1]

            components.append(Text(seg))
            # 执行发送
            if len(components) == 1:
                res = await bot.send(event, seg)
            else:
                res = await bot.send(event, components)

            # --- 智能感知核心：截获自己发出的 Message ID 并丢进 Redis ---
            # 无论底层框架返回 dict 还是对象，都可以优雅提取
            msg_id = None
            if isinstance(res, dict):
                msg_id = res.get("message_id")
            elif hasattr(res, "message_id"):
                msg_id = getattr(res, "message_id")
            elif isinstance(res, list) and len(res) > 0:
                if isinstance(res[0], dict):
                    msg_id = res[0].get("message_id")
                elif hasattr(res[0], "message_id"):
                    msg_id = getattr(res[0], "message_id")

            if msg_id and self.ctx:
                self.ctx.record_bot_message(str(msg_id))

            if i < len(segments) - 1 and self.split_interval_ms > 0:
                await asyncio.sleep(self.split_interval_ms / 1000.0)