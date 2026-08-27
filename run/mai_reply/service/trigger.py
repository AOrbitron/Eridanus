"""
trigger.py
触发判断模块 —— 基于 LLM 语义判断 + 异步高并发连接池
打通上下文记忆与全局情绪系统，支持流式请求防超时。
"""

import json
import random
import re
import traceback

import httpx
from typing import Tuple
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import At, Text
from developTools.utils.logger import get_logger

logger = get_logger(__name__)


class TriggerChecker:

    def __init__(self, config, context_manager, emotion_system):
        self.cfg = config
        self.ctx = context_manager  # 用于获取历史记录和判断消息ID
        self.emotion = emotion_system  # 用于获取当前心情和施加情绪波动

        tcfg = config.mai_reply.config.get("trigger", {})
        self.private_trigger: bool = tcfg.get("private_trigger", True)
        self.random_probability: int = int(tcfg.get("random_reply_probability", 3))

        # 提取人设名和配置中的别名
        pcfg = config.mai_reply.config.get("persona", {})
        self.bot_persona_name: str = pcfg.get("name", "").strip()
        aliases = tcfg.get("aliases", [])
        self.aliases: list = aliases if isinstance(aliases, list) else[aliases]

        hlcfg = config.mai_reply.config.get("human_like", {})
        self.base_ignore_prob: int = int(hlcfg.get("ignore_probability", 15))

        # --- LLM 判断专用配置 ---
        llm_cfg = config.mai_reply.config.get("trigger_llm", {})
        self.api_key = llm_cfg.get("api_key", "")
        self.base_url = llm_cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = llm_cfg.get("model", "gpt-3.5-turbo")

        # 是否使用流式请求以防止网关层超时
        self.use_stream: bool = llm_cfg.get("stream", False)

        # 建立高并发连接池
        limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
        self.http_client = httpx.AsyncClient(limits=limits, timeout=12.0)

    async def check(
        self,
        event,
        bot_self_id: int,
        bot_name: str,
        pure_text: str,
    ) -> Tuple[bool, str]:
        """
        判断是否触发（异步），返回 (should_reply, clean_text)
        """
        is_private = isinstance(event, PrivateMessageEvent)
        group_id = getattr(event, "group_id", None)
        user_id = event.user_id
        text = pure_text.strip()

        # 提取硬件级别的判定因子
        #print(bot_self_id)
        is_at = self._has_at(event=event,bot_self_id= bot_self_id)
        is_reply = self._is_reply_to_bot(event, bot_self_id)

        # 净化文本（去除残留的@字符）
        clean_text = self._remove_at_segments(event, text, bot_name, bot_self_id)
        if not clean_text:
            return False, text  # 无法提取文本时，默认不回复，但返回原始文本以供记录
        #print(is_at)
        if is_at:
            return True, clean_text
        # 私聊直接放行（如果配置允许）
        if is_private and self.private_trigger:
            return True, clean_text

        # =========================================================
        # 1. 组装极致拟人化的上下文 (群气氛 + 历史对话 + 当前心情)
        # =========================================================
        # 获取近期群氛围
        group_context = ""
        if group_id:
            group_context = self.ctx.build_group_context_snippet(group_id, bot_name)

        # 获取和当前用户的最近几句对话 (截取最后 4 条，防止 token 浪费)
        history = self.ctx.get_session_history(group_id, user_id)[-4:]
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history]) if history else "无最近聊天记录"

        # 获取全局心情
        current_mood = self.emotion.get_mood()
        current_score = self.emotion.get_score()

        prompt = f"""你是一个聊天机器人的“潜意识判断中枢”。
任务：根据上下文判断是否要回话，并评估这句话对机器人心情的影响。

【机器人当前状态】
名字/别名：{self.bot_persona_name or bot_name} / {self.aliases}
当前心情状态：{current_mood} (心情分数：{current_score}，-100为极差，100为极好)

【外界环境上下文】
{group_context}
-----------------
近期与该用户的对话记录：
{history_str}

【当前事件】
用户是否明确@了机器人：{is_at}
用户是否引用/回复了机器人：{is_reply}
用户当前发送的文本："{clean_text}"

【判断逻辑】
1. 回复意愿判断：被@、被回复、提到名字、接抛梗、被提问时应当回复。但在机器人心情极差（分数<-40）时，如果对方态度不好，哪怕被@也可以判断为不回复。如果是群友间无关的闲聊，判断为不回复。
2. 情绪波动打分：这句话让机器人产生的心情变化，给出一个 -10 到 +10 的整数。夸奖/善意给正数，辱骂/命令/恶心给负数，无关紧要给 0。

【强制输出格式】
严格输出一行，严禁任何废话：[REPLY: TRUE或FALSE][EMOTION: 数字]
"""

        payload = {
            "model": self.model,
            "messages":[{"role": "user", "content": prompt}],
            "temperature": 0.1,
            #"max_tokens": 20,
            "stream": self.use_stream
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        llm_decision = False
        emotion_delta = 0

        try:
            # =========================================================
            # 2. 发起请求（兼容 Stream 防超时 与 Non-Stream）
            # =========================================================
            result_text = ""
            if self.use_stream:
                async with self.http_client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=headers,timeout=1000) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "): continue
                        data_str = line[6:]
                        if data_str == "[DONE]": break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta and delta["content"]:
                                result_text += delta["content"]
                        except Exception:
                            pass
            else:
                resp = await self.http_client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                result_text = resp.json()["choices"][0]["message"]["content"]

            logger.info(f"[Trigger LLM] 判断结果: {result_text.strip()}")

            # =========================================================
            # 3. 解析结果并反向更新全局情绪
            # =========================================================
            reply_match = re.search(r"\[REPLY:\s*(TRUE|FALSE)\]", result_text, re.IGNORECASE)
            if reply_match:
                llm_decision = (reply_match.group(1).upper() == "TRUE")

            emo_match = re.search(r"\[EMOTION:\s*([+-]?\d+)\]", result_text, re.IGNORECASE)
            if emo_match:
                emotion_delta = int(emo_match.group(1))
                # 将判断出的情绪波动，真实反写回机器人的全局情绪系统中
                if emotion_delta != 0:
                    self.emotion.apply_llm_delta(emotion_delta)

        except Exception as e:
            logger.error(f"[Trigger LLM] 请求失败: {e}")
            traceback.print_exc()
            # 兜底降级：网络波动时回退到硬件因子
            llm_decision = is_at or is_reply

        # =========================================================
        # 4. 生理反应落地：情绪对“已读不回”概率的动态干扰
        # =========================================================
        # 获取受刚才那句话影响后的 最新心情分数
        new_score = self.emotion.get_score()
        dynamic_ignore_prob = self.base_ignore_prob

        if new_score < -30:
            # 心情很差，大概率不想理人 (最高可加到50%以上的不回概率)
            dynamic_ignore_prob += int(abs(new_score) / 2)
        elif new_score > 40:
            # 心情极好，比较积极 (降低已读不回概率)
            dynamic_ignore_prob = max(0, dynamic_ignore_prob - 10)

        # 最终决定
        if llm_decision:
            # 没被明确艾特或回复时，依据此刻动态心情概率，决定要不要“冷暴力已读不回”
            if not is_at and not is_reply:
                if dynamic_ignore_prob > 0 and random.randint(1, 100) <= dynamic_ignore_prob:
                    logger.info(f"[MaiReply] 生理反应触发: 当前心情分数 {new_score}, 故意无视了本次搭话。")
                    return False, clean_text
            return True, clean_text

        # 虽然 LLM 判定不需要理他，但如果设定了随机插嘴概率，就偶尔接一茬
        if self.random_probability > 0 and random.randint(1, 100) <= self.random_probability:
             return True, clean_text

        return False, clean_text

    # --- 底层辅助判断方法保持不变 ---
    def _is_reply_to_bot(self, event, bot_self_id: int) -> bool:
        if not hasattr(event, "message") or not event.message:
            return False

        for seg in event.message:
            seg_type = getattr(seg, "type", "") or ""
            if seg_type.lower() == "reply":
                data = getattr(seg, "data", {}) if hasattr(seg, "data") else {}
                qq_val = data.get("qq") or data.get("target") or data.get("user_id") or getattr(seg, "qq", None)
                if qq_val and bot_self_id:
                    try:
                        if int(str(qq_val).strip()) == bot_self_id:
                            return True
                    except:
                        pass

                msg_id = data.get("id") or data.get("message_id") or getattr(seg, "id", None) or getattr(seg, "message_id", None)
                if msg_id and self.ctx and self.ctx.is_bot_message(str(msg_id)):
                    return True
        return False

    @staticmethod
    def _has_at( event, bot_self_id: int) -> bool:
        #print(event)
        if not hasattr(event, "group_id"):
            #print("不是群消息")
            return False

        if not event.message_chain.has(At):
            #print("消息中没有At")
            return False
        if event.message_chain.get(At)[0].qq in [bot_self_id, 1000000]:
            return True

        return False

    @staticmethod
    def _remove_at_segments(event, text: str, bot_name: str, bot_self_id: int) -> str:
        if event.message_chain.has(Text):
            text = event.message_chain.get(Text)[0].text
        if event.message_chain.has(At):
            if event.message_chain.get(At)[0].qq in [bot_self_id, 1000000]:
                logger.info(f"[TriggerChecker] 消息中包含@机器人自己的At，原始文本: '{text}'，已替换为 '@{bot_name}'")
                text = f"@{bot_name}"+text
            else:
                text = f"@{event.message_chain.get(At)[0].name}"+text
        if not event.message_chain.has(Text) and not event.message_chain.has(At):
            logger.warning(f"[TriggerChecker] 无法提取文本内容，消息链中既没有 Text 也没有 At，原始消息链: {event.message_chain}")
            return None
        if bot_self_id:
            text = text.replace(f"@{bot_self_id}", "").strip()
        return text