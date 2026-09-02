"""
impression_updater.py
用户印象更新器 —— 定期用 LLM 对历史对话做增量摘要，形成跨会话的压缩记忆
- 每 N 轮触发一次，融合旧印象与新对话生成新印象
- 印象超过字数上限时自动压缩，避免无限膨胀
- 支持群聊气氛/话题印象（group_impression），每 M 条群消息触发一次
"""

import asyncio
import traceback
from typing import List, Dict, Optional

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.simple_chat import simplified_chat

logger = get_logger(__name__)

SUMMARY_TRIGGER_TURNS = 3   # 每聊3轮触发一次用户印象更新
IMPRESSION_MAX_CHARS = 300  # 超过此字数触发压缩

GROUP_IMP_TRIGGER_MSGS = 10  # 每累计 N 条群消息触发一次群印象更新
GROUP_IMP_MAX_CHARS = 400    # 群印象最大字数

# 增量更新：融合旧印象与新对话
SUMMARY_PROMPT_TEMPLATE = """你（{bot_name}）和 {user_name} 的最新对话：

{history_text}

---
你对TA的旧印象（可能为空）：
{old_impression}

请用不超过{chars}字更新你对 {user_name} 的印象记忆。要求：
- 第一人称（"我"），带主观感情色彩。
- 记下交往中的重要事件和过程
- 当前对话的场景(如果有的话)
- 融合旧印象与新对话，重点记录：TA的性格/口癖/喜好、你们聊过的重要话题、你对TA的情感态度
- 如果旧印象和新对话矛盾，以新对话为准
- 直接输出印象文字，不要任何前缀或解释"""

# 压缩：印象过长时精简
COMPRESS_PROMPT_TEMPLATE = """以下是你（{bot_name}）对 {user_name} 积累的印象记忆（当前{char_count}字，需要压缩）：

{old_impression}

请压缩到{chars}字以内，保留最重要的性格特征、你们的关系状态和你的情感态度。直接输出压缩后的文字，不要任何前缀。"""

# 群聊气氛/话题印象更新
GROUP_IMP_PROMPT_TEMPLATE = """你（{bot_name}）正在旁观一个群聊（群名：{group_name}）。

最近的群消息片段：
{window_text}

---
你对这个群的旧印象（可能为空）：
{old_impression}

请用不超过{chars}字更新你对这个群的整体印象。要求：
- 第一人称（"我"），带主观感情色彩
- 记录：这个群最近在聊什么话题、群内的整体气氛、活跃的成员和他们的风格
- 有什么有趣的梗/黑话/群内文化需要记下来
- 融合旧印象与新消息，新的覆盖旧的
- 直接输出印象文字，不要任何前缀或解释"""

GROUP_IMP_COMPRESS_TEMPLATE = """以下是你（{bot_name}）对群【{group_name}】的印象记忆（当前{char_count}字，需要压缩）：

{old_impression}

请压缩到{chars}字以内，保留最重要的群氛围、热门话题和群内文化。直接输出压缩后的文字，不要任何前缀。"""


class ImpressionUpdater:

    def __init__(self, llm_client, context_manager):
        self._llm = llm_client
        self._ctx = context_manager
        # 用户印象计数器：counter_key -> turn_count
        self._counters: Dict[str, int] = {}
        # 群印象计数器：group_id -> msg_count
        self._group_counters: Dict[int, int] = {}

        cfg = YAMLManager.get_instance()
        self.model = cfg.mai_reply.config["context"]["impression_model"] if cfg.mai_reply.config["context"]["impression_model"] else cfg.mai_reply.config["trigger_llm"]["model"]
        self.api_key = cfg.mai_reply.config["trigger_llm"]["api_key"]
        self.base_url = cfg.mai_reply.config["trigger_llm"]["base_url"]


        ccfg = cfg.mai_reply.config.get("context", {})
        self.max_chars = int(ccfg.get("impression_max_chars", IMPRESSION_MAX_CHARS))
        self.group_imp_trigger: int = int(ccfg.get("group_trigger_msgs", GROUP_IMP_TRIGGER_MSGS))
        self.group_imp_max_chars: int = int(ccfg.get("group_max_chars", GROUP_IMP_MAX_CHARS))
       # self.enable_group_impression: bool = imp_cfg.get("enable_group_impression", True)


        self.enable_group_impression: bool = ccfg.get("enable_impression", True)
        self.group_impression_ttl: int = ccfg.get("impression_ttl", 604800)
        # 构建回复时，最多读取最近 N 位发言者的 impression
        self.group_reply_impression_count: int = ccfg.get("group_reply_impression_count", 3)
    def _counter_key(self, user_id: int, group_id) -> str:
        return f"{group_id or 'priv'}:{user_id}"

    async def _call_llm(self, prompt: str) -> str:
        """统一的LLM调用入口"""
        if not self.base_url:
            return await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是一个情感记忆提取器，帮助机器人记住并压缩对他人的印象。不加任何前缀。",
                model=self.model,
            )
        else:
            return await simplified_chat(
                self.base_url,
                [{"role": "user", "content": prompt}],
                self.model,
                self.api_key,
                system_prompt="你是一个情感记忆提取器，帮助机器人记住并压缩对他人的印象。不加任何前缀。"
            )

    # ------------------------------------------------------------------ 用户印象

    def tick(self, user_id: int, group_id, user_name: str, bot_name: str) -> None:
        """每次对话完成后调用，达到触发轮数时异步更新用户印象"""
        key = self._counter_key(user_id, group_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        if self._counters[key] >= SUMMARY_TRIGGER_TURNS:
            self._counters[key] = 0
            asyncio.create_task(
                self._update_impression(user_id, group_id, user_name, bot_name)
            )

    async def _update_impression(
        self, user_id: int, group_id, user_name: str, bot_name: str
    ) -> None:
        try:
            history: List[Dict] = self._ctx.get_session_history(group_id, user_id)
            if not history:
                return

            recent = history[-6:]
            lines = []
            for msg in recent:
                role = user_name if msg["role"] == "user" else bot_name
                content = msg["content"]
                if isinstance(content, list):
                    content = next((p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"), "")
                content = str(content)[:200]
                lines.append(f"{role}：{content}")
            history_text = "\n".join(lines)

            old_impression = self._ctx.get_impression(user_id) or ""

            prompt = SUMMARY_PROMPT_TEMPLATE.format(
                bot_name=bot_name,
                user_name=user_name,
                history_text=history_text,
                old_impression=old_impression or "（暂无，第一次聊）",
                chars=self.max_chars
            )
            new_impression = await self._call_llm(prompt)
            if not new_impression:
                return

            new_impression = new_impression.strip()

            if len(new_impression) > self.max_chars:
                compress_prompt = COMPRESS_PROMPT_TEMPLATE.format(
                    bot_name=bot_name,
                    user_name=user_name,
                    char_count=len(new_impression),
                    old_impression=new_impression,
                    chars=self.max_chars
                )
                compressed = await self._call_llm(compress_prompt)
                if compressed and compressed.strip():
                    new_impression = compressed.strip()

            self._ctx.update_impression(user_id, new_impression)
            logger.info(f"[MaiReply] 已更新对 {user_name}({user_id}) 的印象({len(new_impression)}字): {new_impression}")

        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 用户印象更新失败: {e}")

    # ------------------------------------------------------------------ 群聊印象

    def tick_group(self, group_id: int, group_name: str, bot_name: str) -> None:
        """
        每次有群消息进入旁观窗口时调用。
        累计到 group_imp_trigger 条时，异步触发群印象更新。
        """
        if not self.enable_group_impression:
            return
        self._group_counters[group_id] = self._group_counters.get(group_id, 0) + 1
        if self._group_counters[group_id] >= self.group_imp_trigger:
            self._group_counters[group_id] = 0
            asyncio.create_task(
                self._update_group_impression(group_id, group_name, bot_name)
            )

    async def _update_group_impression(
        self, group_id: int, group_name: str, bot_name: str
    ) -> None:
        try:
            window = self._ctx._load_group_window(group_id)
            if not window:
                return

            # 取最近 N 条窗口消息作为输入
            recent = window[-self.group_imp_trigger:]
            lines = []
            for item in recent:
                sender = item.get("sender", "?")
                text = str(item.get("text", ""))[:150]
                user_id = item.get("user_id")
                sender_label = f"{sender}（用户ID: {user_id}）" if user_id is not None else sender
                lines.append(f"{sender_label}：{text}")
            window_text = "\n".join(lines)

            old_impression = self._ctx.get_group_impression(group_id) or ""

            prompt = GROUP_IMP_PROMPT_TEMPLATE.format(
                bot_name=bot_name,
                group_name=group_name,
                window_text=window_text,
                old_impression=old_impression or "（暂无，刚开始旁观这个群）",
                chars=self.group_imp_max_chars
            )
            new_impression = await self._call_llm(prompt)
            if not new_impression:
                return

            new_impression = new_impression.strip()

            if len(new_impression) > self.group_imp_max_chars:
                compress_prompt = GROUP_IMP_COMPRESS_TEMPLATE.format(
                    bot_name=bot_name,
                    group_name=group_name,
                    char_count=len(new_impression),
                    old_impression=new_impression,
                    chars=self.group_imp_max_chars
                )
                compressed = await self._call_llm(compress_prompt)
                if compressed and compressed.strip():
                    new_impression = compressed.strip()

            self._ctx.update_group_impression(group_id, new_impression)
            logger.info(
                f"[MaiReply] 已更新群 {group_name}({group_id}) 的印象"
                f"({len(new_impression)}字): {new_impression[:80]}..."
            )

        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 群印象更新失败: {e}")
