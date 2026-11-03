"""
trigger.py
触发判断模块 —— 基于 LLM 语义判断 + 异步高并发连接池
打通上下文记忆与全局情绪系统，支持流式请求防超时。
"""

import asyncio
import json
import random
import re
import time
import traceback

import httpx
from typing import Tuple, Dict, List, Optional, Any
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import At, Text
from developTools.utils.logger import get_logger

logger = get_logger(__name__)


class TriggerChecker:

    def __init__(self, config, context_manager, emotion_system):
        self.cfg = config
        self.ctx = context_manager  # 用于获取历史记录和判断消息ID
        self.emotion = emotion_system  # 用于获取当前心情和施加情绪波动

        tcfg = config.core_reply.config.get("trigger", {})
        self.private_trigger: bool = tcfg.get("private_trigger", True)
        self.random_probability: int = int(tcfg.get("random_reply_probability", 3))

        # 提取人设名和配置中的别名
        pcfg = config.core_reply.config.get("persona", {})
        self.bot_persona_name: str = pcfg.get("name", "").strip()
        aliases = tcfg.get("aliases", [])
        self.aliases: list = aliases if isinstance(aliases, list) else[aliases]

        hlcfg = config.core_reply.config.get("human_like", {})
        self.base_ignore_prob: int = int(hlcfg.get("ignore_probability", 15))

        # --- LLM 判断专用配置 ---
        llm_cfg = config.core_reply.config.get("trigger_llm", {})
        self.api_key = llm_cfg.get("api_key", "")
        self.base_url = llm_cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = llm_cfg.get("model", "gpt-3.5-turbo")

        # 是否使用流式请求以防止网关层超时
        self.use_stream: bool = llm_cfg.get("stream", False)

        # 建立高并发连接池
        limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
        self.http_client = httpx.AsyncClient(limits=limits, timeout=12.0)

        # --- 窗口聚合与群聊时序上下文配置 ---
        win_cfg = llm_cfg.get("window", {})
        self.window_enabled: bool = bool(win_cfg.get("enable", True))
        self.window_duration: float = float(win_cfg.get("duration", 3.0))
        self.window_max_messages: int = int(win_cfg.get("max_messages", 10))
        self.group_context_lines: int = int(llm_cfg.get("group_context_lines", 5))

        # 窗口运行时状态管理：group_id -> dict
        # {
        #   "timer_task": asyncio.Task,
        #   "messages": [ {event, sender_name, clean_text, user_id, is_reply, bot_self_id, bot_name, future} ],
        # }
        self._group_windows: Dict[int, dict] = {}
        self._window_meta_lock = asyncio.Lock()

    async def check(
        self,
        event,
        bot_self_id: int,
        bot_name: str,
        pure_text: str,
    ) -> Tuple[bool, str]:
        """
        判断是否触发（异步），返回 (should_reply, clean_text)
        支持群聊消息窗口机制：高频群聊下自动聚合窗口期消息，窗口结束后一同送入上游 LLM 判断。
        """
        is_private = isinstance(event, PrivateMessageEvent)
        group_id = getattr(event, "group_id", None)
        user_id = event.user_id
        text = pure_text.strip()

        # 提取硬件级别的判定因子
        is_at = self._has_at(event=event, bot_self_id=bot_self_id)
        is_reply = self._is_reply_to_bot(event, bot_self_id)

        # 净化文本（去除残留的@字符）
        clean_text = self._remove_at_segments(event, text, bot_name, bot_self_id)
        if not clean_text:
            return False, text  # 无法提取文本时，默认不回复，但返回原始文本以供记录

        # 明确@机器人直接放行触发
        if is_at:
            return True, clean_text

        # 私聊直接放行（如果配置允许）
        if is_private and self.private_trigger:
            return True, clean_text

        # 如果是群聊且启用了窗口聚合机制
        if group_id and self.window_enabled and self.window_duration > 0:
            return await self._enqueue_group_window(
                group_id=group_id,
                event=event,
                clean_text=clean_text,
                user_id=user_id,
                is_reply=is_reply,
                bot_self_id=bot_self_id,
                bot_name=bot_name,
            )

        # 未开启窗口时，回退到单条判定
        batch_item = {
            "event": event,
            "sender_name": getattr(getattr(event, "sender", None), "nickname", f"用户{user_id}"),
            "clean_text": clean_text,
            "user_id": user_id,
            "is_reply": is_reply,
            "bot_self_id": bot_self_id,
            "bot_name": bot_name,
        }
        decisions = await self._evaluate_window_batch(group_id, [batch_item], bot_self_id, bot_name)
        should_reply = decisions.get(0, False)
        return should_reply, clean_text

    async def _enqueue_group_window(
        self,
        group_id: int,
        event,
        clean_text: str,
        user_id: int,
        is_reply: bool,
        bot_self_id: int,
        bot_name: str,
    ) -> Tuple[bool, str]:
        """将群消息投递入时间窗口中，等待窗口期结束一同批处理评估"""
        loop = asyncio.get_running_loop()
        item_future = loop.create_future()
        sender_name = getattr(getattr(event, "sender", None), "nickname", f"用户{user_id}")

        item = {
            "event": event,
            "sender_name": sender_name,
            "clean_text": clean_text,
            "user_id": user_id,
            "is_reply": is_reply,
            "bot_self_id": bot_self_id,
            "bot_name": bot_name,
            "future": item_future,
        }

        should_trigger_immediately = False
        async with self._window_meta_lock:
            if group_id not in self._group_windows:
                # 群内首人发消息，开启全新计时窗口
                win_state = {
                    "messages": [item],
                    "lock": asyncio.Lock(),
                    "timer_task": None,
                }
                # 启动倒计时任务，窗口到期后自动触发批量判断
                win_state["timer_task"] = asyncio.create_task(
                    self._window_timer(group_id, self.window_duration)
                )
                self._group_windows[group_id] = win_state
                logger.info(
                    f"[TriggerChecker] 群 {group_id} 开启新消息窗口 (持续 {self.window_duration}s)，"
                    f"首条消息来自 {sender_name}: '{clean_text}'"
                )
            else:
                win_state = self._group_windows[group_id]
                win_state["messages"].append(item)
                logger.info(
                    f"[TriggerChecker] 群 {group_id} 窗口追加消息 (当前 {len(win_state['messages'])} 条)，"
                    f"来自 {sender_name}: '{clean_text}'"
                )
                if len(win_state["messages"]) >= self.window_max_messages:
                    should_trigger_immediately = True

        if should_trigger_immediately:
            # 达到窗口最大容量上限，立即提前触发批量结算
            logger.info(f"[TriggerChecker] 群 {group_id} 窗口达到最大消息数 {self.window_max_messages}，立即结算")
            asyncio.create_task(self._flush_window(group_id))

        try:
            should_reply = await item_future
            return should_reply, clean_text
        except asyncio.CancelledError:
            return False, clean_text

    async def _window_timer(self, group_id: int, duration: float) -> None:
        """窗口到期倒计时"""
        try:
            await asyncio.sleep(duration)
            await self._flush_window(group_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[TriggerChecker] 窗口定时器执行异常: {e}")

    async def _flush_window(self, group_id: int) -> None:
        """清空并结算指定群的窗口消息，合并请求上游 LLM 判断"""
        win_state = None
        async with self._window_meta_lock:
            win_state = self._group_windows.pop(group_id, None)

        if not win_state:
            return

        timer = win_state.get("timer_task")
        if timer and not timer.done():
            timer.cancel()

        messages = win_state.get("messages", [])
        if not messages:
            return

        bot_self_id = messages[0]["bot_self_id"]
        bot_name = messages[0]["bot_name"]

        try:
            decisions = await self._evaluate_window_batch(
                group_id=group_id,
                batch=messages,
                bot_self_id=bot_self_id,
                bot_name=bot_name,
            )
            # 将判定结果通知给每个等待的 Future
            for idx, item in enumerate(messages):
                fut = item.get("future")
                if fut and not fut.done():
                    fut.set_result(decisions.get(idx, False))
        except Exception as e:
            logger.error(f"[TriggerChecker] 窗口批量判断异常: {e}")
            traceback.print_exc()
            for item in messages:
                fut = item.get("future")
                if fut and not fut.done():
                    fut.set_result(item.get("is_reply", False))

    async def _evaluate_window_batch(
        self,
        group_id: Optional[int],
        batch: List[dict],
        bot_self_id: int,
        bot_name: str,
    ) -> Dict[int, bool]:
        """
        将窗口内聚合的多条消息组合后，附带前序群聊上下文，发给上游 LLM 进行一次性判断。
        严格确保重点关注的是窗口中最新的一条消息。
        返回: { message_index: should_reply }
        """
        total = len(batch)
        if total == 0:
            return {}

        latest_idx = total - 1
        latest_item = batch[latest_idx]

        # =========================================================
        # 1. 组装极致拟人化的上下文 (群前序上下文 + 窗口内汇聚消息 + 当前心情)
        # =========================================================
        # 读取群聊前序上下文（可配最近N条，默认5条）
        group_context = ""
        if group_id and self.ctx:
            max_lines = self.group_context_lines if self.group_context_lines > 0 else None
            group_context = self.ctx.build_group_context_snippet(group_id, bot_name, max_lines=max_lines)

        # 整理窗口内的一批消息（明确标明是谁说了什么）
        window_lines = []
        for idx, m in enumerate(batch):
            sender = m["sender_name"]
            uid = m["user_id"]
            ctxt = m["clean_text"]
            tag = "【最新消息】" if idx == latest_idx else f"【消息{idx+1}】"
            window_lines.append(f"{tag} {sender}（QQ/ID: {uid}）：{ctxt}")
        window_msgs_str = "\n".join(window_lines)

        # 提取与最新发言者的近期私密/专属对话记录
        latest_uid = latest_item["user_id"]
        history = self.ctx.get_session_history(group_id, latest_uid)[-4:] if self.ctx else []
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history]) if history else "无最近聊天记录"

        # 获取全局心情
        current_mood = self.emotion.get_mood() if self.emotion else "平静"
        current_score = self.emotion.get_score() if self.emotion else 0

        prompt = f"""你是一个聊天机器人的“潜意识判断中枢”。
任务：根据群聊窗口内汇聚的新消息（重点关注最新的发言），结合前序聊天上下文判断机器人是否需要插嘴回话，并评估最新消息对机器人心情的影响。

【机器人当前状态】
名字/别名：{self.bot_persona_name or bot_name} / {self.aliases}
当前心情状态：{current_mood} (心情分数：{current_score}，-100为极差，100为极好)

【群聊前序聊天上下文（近期背景）】
{group_context if group_context else "无前序群聊记录"}
-----------------
近期与最新发言者的对话记录：
{history_str}

【本轮消息窗口内汇聚的群消息（共 {total} 条，首人发言开启窗口后一同送入）】
{window_msgs_str}

【当前重点关注的最新事件】
用户是否引用/回复了机器人：{latest_item.get("is_reply", False)}
最新发言人：{latest_item['sender_name']}（QQ: {latest_uid}）
最新发言文本：“{latest_item['clean_text']}”

【判断逻辑】
1. 你的判断重心必须落在【最新消息】上！窗口前面的消息与群聊前序上下文作为理解话题流向的背景。
2. 回复意愿判断：若最新消息提到机器人、向机器人提问、接抛梗或明显在与机器人互动，应当回复；如果是群友之间彼此无关的闲聊，必须判断为不回复！
3. 但在机器人心情极差（分数<-40）时，如果对方态度不好，也可以判断为不回复。
4. 情绪波动打分：评估最新消息对机器人的心情影响，给出一个 -10 到 +10 的整数。夸奖/善意给正数，辱骂/命令/恶心给负数，无关紧要给 0。

【强制输出格式】
严格输出一行，严禁任何废话：[REPLY: TRUE或FALSE][EMOTION: 数字]
"""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "stream": self.use_stream,
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
                async with self.http_client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=1000) as resp:
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

            logger.info(f"[Trigger LLM Window] 窗口({total}条) 判断结果: {result_text.strip()}")

            # =========================================================
            # 3. 解析结果与情绪写入
            # =========================================================
            reply_match = re.search(r"\[REPLY:\s*(TRUE|FALSE)\]", result_text, re.IGNORECASE)
            if reply_match:
                llm_decision = (reply_match.group(1).upper() == "TRUE")

            emo_match = re.search(r"\[EMOTION:\s*([+-]?\d+)\]", result_text, re.IGNORECASE)
            if emo_match:
                emotion_delta = int(emo_match.group(1))
                if emotion_delta != 0 and self.emotion:
                    self.emotion.apply_llm_delta(emotion_delta)

        except Exception as e:
            logger.error(f"[Trigger LLM Window] 请求失败: {e}")
            traceback.print_exc()
            # 兜底降级：网络波动时回退到最新一条是否引用Bot
            llm_decision = bool(latest_item.get("is_reply", False))

        # =========================================================
        # 4. 生理反应落地：情绪对“已读不回”概率的动态干扰
        # =========================================================
        new_score = self.emotion.get_score() if self.emotion else 0
        dynamic_ignore_prob = self.base_ignore_prob

        if new_score < -30:
            dynamic_ignore_prob += int(abs(new_score) / 2)
        elif new_score > 40:
            dynamic_ignore_prob = max(0, dynamic_ignore_prob - 10)

        final_latest_decision = False
        if llm_decision:
            if not latest_item.get("is_reply", False):
                if dynamic_ignore_prob > 0 and random.randint(1, 100) <= dynamic_ignore_prob:
                    logger.info(f"[MaiReply] 生理反应触发: 当前心情分数 {new_score}, 故意无视了本轮窗口搭话。")
                    final_latest_decision = False
                else:
                    final_latest_decision = True
            else:
                final_latest_decision = True
        else:
            if self.random_probability > 0 and random.randint(1, 100) <= self.random_probability:
                final_latest_decision = True

        # 构建判定字典：窗口内前面未命中的消息默认不触发，重点触发落于最新有效判断上
        decisions: Dict[int, bool] = {}
        for i in range(total):
            decisions[i] = False
        decisions[latest_idx] = final_latest_decision

        return decisions

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
    def _has_at(event, bot_self_id: int) -> bool:
        #print(event)
        if not hasattr(event, "group_id"):
            #print("?????")
            return False

        if not event.message_chain.has(At):
            #print("?????At")
            return False
        for seg in event.message_chain.get(At):
            qq = getattr(seg, "qq", None)
            if qq is None:
                qq = (getattr(seg, "data", {}) or {}).get("qq")
            if str(qq) in {str(bot_self_id), "1000000"} or (hasattr(event, "group_id") and str(event.group_id).startswith("11111")):
                return True
        return False
    @staticmethod
    def _remove_at_segments(event, text: str, bot_name: str, bot_self_id: int) -> str:
        # Rebuild from every segment so multiple At/Text parts are retained
        # in their original order (the old implementation only used [0]).
        chain = event.message_chain
        parts = []
        for seg in chain:
            if isinstance(seg, Text):
                parts.append(seg.text)
            elif isinstance(seg, At):
                qq = seg.qq
                name = getattr(seg, "name", None) or str(qq or "")
                if str(qq) in {str(bot_self_id), "1000000"}:
                    logger.info(f"[TriggerChecker] 消息中包含@机器人自己的At，已替换为 '@{bot_name}'")
                    continue
                else:
                    parts.append(f"[@{name}，QQ: {qq}]")
        if parts:
            text = "".join(parts)
        if not chain.has(Text) and not chain.has(At):
            logger.warning(f"[TriggerChecker] 无法提取文本内容，消息链中既没有 Text 也没有 At，原始消息链: {event.message_chain}")
            return None
        logger.info(f"清洗后的text: {text}")
        return text
