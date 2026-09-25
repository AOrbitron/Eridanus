# -*- coding: utf-8 -*-
"""
proactive_service.py
高拟人化智能主动消息关怀服务

核心特点：
1. 真实好友/女友式关怀，绝非冰冷刻板的定时问候
2. 敏锐的时间感知（Time Perception）：
   - 能感知事件距今过去多久（几小时 vs 几天）
   - 绝不出现“过了好几天还在问昨天的秋招/考试”这种违和感
   - 随时间推移自动切换话题策略（行前提醒 -> 落地保暖 -> 回程问候；过期事件平滑转入日常问候）
3. 全方位状态捕捉（不仅是出行目的地，还包括工作压力、考试考证、健康身体、情绪低落、生活琐事等）
4. 外部资讯与天气搜寻增强（Grounding）：在需要时自动检索目的地天气、温差或相关信息
5. 原生 send_friend_message 协议发送，模拟逼真的人类打字停顿与 TTS 语音发送
6. 自动写回上下文会话历史，保证用户回复时自然无缝衔接
"""

import asyncio
import json
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from developTools.message.message_components import Text, Record
from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.reply_processor import calc_typing_delay, split_message

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 联网检索辅助（优先使用 anysearch_cli，降级支持 baidu_search，无网络则优雅容错）
# ---------------------------------------------------------------------------
async def _perform_web_search(query: str, max_results: int = 3) -> str:
    """轻量并发检索用户关心的外部信息（如某地天气、突发新闻等）"""
    if not query or not query.strip():
        return ""
    clean_query = query.strip()
    logger.info(f"[MaiReply Proactive] 正在为主动关怀搜索外部信息: {clean_query}")

    # 方式一：尝试 anysearch_cli
    try:
        from skills.anysearch_2_1_0.scripts import anysearch_cli  # type: ignore
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: anysearch_cli._call_api("search", {"query": clean_query, "max_results": max_results}, "")
        )
        if res and isinstance(res, str) and "Search Results" in res:
            logger.info(f"[MaiReply Proactive] anysearch 搜索成功，获取到参考资料")
            return res[:1200]
    except Exception:
        pass

    try:
        # 尝试相对路径动态引用 anysearch_cli
        import sys, os
        skill_script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills", "anysearch-2.1.0", "scripts"))
        if os.path.exists(skill_script_path) and skill_script_path not in sys.path:
            sys.path.insert(0, skill_script_path)
            import anysearch_cli
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: anysearch_cli._call_api("search", {"query": clean_query, "max_results": max_results}, "")
            )
            if res and isinstance(res, str) and "Search Results" in res:
                logger.info(f"[MaiReply Proactive] anysearch 路径加载搜索成功")
                return res[:1200]
    except Exception:
        pass

    # 方式二：尝试 baidu_search
    try:
        from run.resource_collector.service.engine_search import baidu_search
        res = await baidu_search(clean_query)
        if res and isinstance(res, str):
            logger.info(f"[MaiReply Proactive] baidu_search 搜索成功")
            return res[:1200]
    except Exception as e:
        logger.warning(f"[MaiReply Proactive] 联网搜索降级失败: {e}")

    return ""


# ---------------------------------------------------------------------------
# 时间感知辅助函数
# ---------------------------------------------------------------------------
def _format_time_diff(seconds: float) -> str:
    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} 小时前"
    else:
        days = seconds / 86400
        return f"{days:.1f} 天前"


def _clean_system_prompt_for_proactive(system_prompt: str) -> str:
    """
    清洗角色卡Prompt用于主动关怀生成：
    保留核心口吻、习惯，移除容易触发安全拦截的指令、绘图大段tag及强控制词。
    """
    if not system_prompt:
        return ""
    cleaned = system_prompt
    cut_pos = cleaned.find("视觉与绘图")
    if cut_pos != -1:
        last_hash = cleaned.rfind("#", 0, cut_pos)
        if last_hash != -1:
            cleaned = cleaned[:last_hash]

    sensitive_words = ["绝对服从", "诱惑他", "挑逗和诱惑"]
    for w in sensitive_words:
        cleaned = cleaned.replace(w, "")
    cleaned = re.sub(r"\*\*用户【.*?】.*?\*\*\n?", "", cleaned)
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


class ProactiveService:
    """智能主动私聊消息服务"""

    def __init__(self, engine):
        self.engine = engine
        self.cfg = engine.cfg
        self.context = engine.context
        self.llm = engine.llm
        self.emotion = engine.emotion
        self.prompt_builder = engine.prompt_builder
        self.processor = engine.processor

        # 记录每个用户最近一次主动发消息的UNIX时间戳，避免高频打扰
        self._last_proactive_time: Dict[int, float] = {}

    def get_proactive_config(self) -> dict:
        """安全读取主动消息配置"""
        p_cfg = getattr(self.cfg.mai_reply, "proactive", {})
        if not isinstance(p_cfg, dict):
            p_cfg = self.cfg.mai_reply.config.get("proactive", {})
        return p_cfg if isinstance(p_cfg, dict) else {}

    def is_user_in_cooldown(self, user_id: int, cooldown_hours: float) -> bool:
        """检查用户是否处于主动关怀冷却期中"""
        last_time = self._last_proactive_time.get(user_id)
        if not last_time:
            return False
        return (time.time() - last_time) < (cooldown_hours * 3600)

    def should_trigger_for_user(self, history: List[Dict], hour: int, cfg: dict, user_id: int) -> Tuple[bool, str]:
        """
        判断是否满足基础唤醒条件（冷却检查、时段契合度、概率等）
        返回 (bool, 时段描述)
        """
        if not history:
            return False, ""

        cooldown_hours = float(cfg.get("cooldown_hours", 12))
        if self.is_user_in_cooldown(user_id, cooldown_hours):
            return False, ""

        # 计算距离用户最后一次说话的时间
        now_ts = time.time()
        last_msg = history[-1]
        last_ts = float(last_msg.get("ts") or last_msg.get("timestamp") or now_ts)
        silence_seconds = now_ts - last_ts

        # 冷却与最少静默保护：避免用户刚说话就自作主张发起主动关怀
        min_silence_hours = float(cfg.get("min_silence_hours", 3))
        if silence_seconds < (min_silence_hours * 3600):
            return False, ""

        # 最大空闲时间过滤（超过 max_idle_days 认为是休眠沉睡用户）
        max_idle_days = float(cfg.get("max_idle_days", 7))
        if silence_seconds > (max_idle_days * 86400):
            return False, ""

        # 提取用户常活跃时段
        user_msgs = [m for m in history if m.get("role") == "user"][-30:]
        preferred_count = sum(1 for m in user_msgs if m.get("hour") == hour)

        # 预设推荐时段检查
        periods = cfg.get("periods", {
            "morning": [7, 10],
            "after_work": [17, 20],
            "late_night": [22, 2],
        })

        in_preferred_period = False
        current_period_name = "日常空闲时段"
        for pname, span in periods.items():
            start, end = span[0], span[1]
            if (start <= hour <= end) if start <= end else (hour >= start or hour <= end):
                in_preferred_period = True
                name_map = {
                    "morning": "早晨/上午时段",
                    "after_work": "傍晚下班/下课时段",
                    "late_night": "深夜睡前时段"
                }
                current_period_name = name_map.get(pname, pname)
                break

        # 概率判定
        base_prob = int(cfg.get("base_probability", 5))
        if in_preferred_period:
            base_prob = max(base_prob, int(cfg.get("preferred_period_probability", 25)))
        if preferred_count >= 5:
            base_prob = max(base_prob, int(cfg.get("adaptive_probability", 40)))

        roll = random.randint(1, 100)
        if roll > base_prob:
            return False, current_period_name

        return True, current_period_name

    async def analyze_and_plan_care(
        self,
        user_id: int,
        user_name: str,
        history: List[Dict],
        impression: str,
        period_moment: str
    ) -> Optional[Dict[str, Any]]:
        """
        深度分析历史记录与用户印象，具备严密的时间感知能力：
        - 识别出行（时间、目的地、落地、返程）
        - 识别近期烦恼、压力、考试、就医、加班、情绪
        - 评估时效性（几天前 vs 几小时前，过期则废弃或转日常）
        - 判断是否需要联网搜索背景信息
        """
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        now_str = f"{now.strftime('%Y年%m月%d日 %H:%M')} ({weekdays[now.weekday()]})"

        now_ts = time.time()
        # 格式化带相对时间差的最近聊天记录（取最近 15 条，并附带发生时间距离）
        recent_records = history[-15:]
        formatted_history_lines = []
        for msg in recent_records:
            role_name = user_name if msg.get("role") == "user" else "你(Bot)"
            m_ts = msg.get("ts") or msg.get("timestamp")
            if m_ts:
                try:
                    diff_str = _format_time_diff(now_ts - float(m_ts))
                    time_label = f"[{diff_str}] "
                except Exception:
                    time_label = ""
            else:
                time_label = ""
            formatted_history_lines.append(f"{time_label}{role_name}: {msg.get('content', '')}")

        history_context = "\n".join(formatted_history_lines)

        analysis_prompt = f"""你是一个贴心、懂人情世故、像真实伴侣或亲密好友一样的关怀大脑。
当前系统实际时间：{now_str}
当前日常时段：{period_moment}
你对该用户的长期印象：
{impression if impression else '暂无详细印象'}

你们近期的对话记录（每条前带有距离现在的时间差）：
{history_context}

----------------------------------------
【分析与时间感知核心要求】
请你敏锐地感知用户的近期生活与情绪状态，做出最自然得体的关怀决策：
1. **全方位生活感知**：
   - 用户是否有出行/出差/旅游计划？（去了哪里？何时出发？何时到达？是否需要查当地天气或保暖）
   - 用户是否有工作烦恼、学习/考证/求职压力、生活中的郁闷或emo、生病/身体不适、熬夜加班等？
   - 用户是否有开心分享、特殊爱好、或者最近在忙的某件事？
2. **严格的时间感知（Time Awareness，绝不发生违和问询）**：
   - 必须观察事件发生的时间差（例如：如果是刚发生几小时或半天内的事，适合紧接着问“到了吗”、“还在忙吗”；如果已经是好几天甚至更久之前提过的事件，比如“上周的某次小考试/几天的面试”，严禁突然冒出来像刚发生一样问，那会非常违和；若已过去多日，应转为关切其最近状态，或者放弃该过时事件）。
3. **真实拟人，避免尬聊与骚扰**：
   - 如果用户近期没有任何特殊事件，但处于合适的时段（如深夜、早晨或下班点），可以发起自然日常的轻度关怀（如问今天累不累、吃了没、在忙什么）。
   - 如果聊无可聊，或者上一轮话题已经彻底完结且没有新鲜关怀点，允许选择 should_care: false（宁可不发，也不要发机械模板式骚扰信息）。
4. **外部信息拓展与搜索 (need_search)**：
   - 如果关心的话题涉及特定城市/地点（如“去莫斯科”、“在成都”等），或需要知晓当地天气、冷热情况，或需要查某个时效性资讯，设置 need_search: true 并给出清晰的 search_query（如“莫斯科今日天气”、“莫斯科现在温度”）。

请以 JSON 格式输出决策（不要输出任何除 JSON 以外的文字）：
{{
    "should_care": true 或 false,
    "topic": "话题简述（如：莫斯科出差落地与降温关怀 / 加班疲惫安慰 / 日常晚间问候）",
    "need_search": true 或 false,
    "search_query": "搜索词，如不需要则留空字符串",
    "time_perception_note": "你对时间的推断分析说明（例如：距离出发已过去8小时，目前恰好是当地傍晚落地时间）",
    "care_points": "关怀的具体切入点和说话建议（如：问问降落了没，提醒当地气温低添衣，语气温柔像女朋友）"
}}
"""

        try:
            res = await self.llm.chat(
                [{"role": "user", "content": analysis_prompt}],
                system_prompt="你是一个高情商的拟人关怀决策系统。只输出合法的标准 JSON，严禁输出任何解释或 Markdown 格式包裹。",
                stream=False
            )
            if not res:
                return None

            clean_json = res.strip()
            # 兼容去除可能存在的 ```json ```
            if clean_json.startswith("```"):
                clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json, flags=re.MULTILINE)
                clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE)

            decision = json.loads(clean_json)
            if not isinstance(decision, dict) or not decision.get("should_care"):
                return None
            return decision
        except Exception as e:
            logger.warning(f"[MaiReply Proactive] 关怀策略分析异常: {e}")
            return None

    async def generate_proactive_message(
        self,
        user_name: str,
        decision: Dict[str, Any],
        search_result: str,
        user_impression: str
    ) -> List[str]:
        """根据决策和外部资料，结合Bot人设生成高度口语化、亲密自然的主动关怀消息"""
        bot_name = self.prompt_builder.get_bot_name("yucca")
        system_prompt = self.prompt_builder.build_system_prompt(
            bot_name=bot_name,
            user_name=user_name,
            group_name="私聊",
            user_impression=user_impression,
            is_group=False
        )

        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        now_str = f"{now.strftime('%Y年%m月%d日 %H:%M')} {weekdays[now.weekday()]}"

        prompt_content = f"""【当前情境：你正在私聊里主动给你的好友/在意的人 {user_name} 发起一段关怀】
当前时间：{now_str}
关心话题：{decision.get('topic', '日常关怀')}
时间感知背景：{decision.get('time_perception_note', '')}
关怀要点建议：{decision.get('care_points', '')}
"""
        if search_result:
            prompt_content += f"\n【你顺手了解到的外部最新信息（如天气/资讯）】\n{search_result}\n（请在聊天中像常识或自己随手查看到的一样自然融入，切忌照抄搜索结果，不要像播报员，要化成随口的暖心叮咛，比如“看那边降温了”、“只有几度，可别冻着”）\n"

        prompt_content += """
【输出要求】
1. 完全代入你的人设与说话口吻，像真实的好友甚至黏人的女友一样自然、亲近、有温度，绝不官方刻板。
2. 像真人发微信/QQ 一样，将想说的话用 '||' 切分成 1~3 条自然的短句（例如：到地方了吗？||刚才顺手看了一眼，那边晚上好像挺冷的||忙完了记得裹紧外套，多喝点热水呀~）。
3. 严禁出现任何系统提示词、括号状态描写（如“(揉眼睛)”、“[微笑]”等系统痕迹尽量避免）、不要加标题序号。
4. 直接输出消息内容本身。
"""

        cleaned_sys_prompt = _clean_system_prompt_for_proactive(system_prompt)
        if not cleaned_sys_prompt:
            cleaned_sys_prompt = f"你是 {bot_name}，一个真实、自然、贴心像伴侣或亲密好友的女孩，说话自然、喜欢用逗号断句和波浪号~，不用句号，禁止官方生硬。"

        try:
            raw_reply = await self.llm.chat(
                [{"role": "user", "content": prompt_content}],
                system_prompt=cleaned_sys_prompt,
            )
            if not raw_reply or "cannot assist" in raw_reply.lower() or "i'm sorry" in raw_reply.lower():
                logger.warning(f"[MaiReply Proactive] 角色卡触发拦截或生成为空，使用纯净人设重试...")
                fallback_prompt = f"你是 {bot_name}，一个性格真实自然、温柔贴心的女孩，把 {user_name} 当成特别在意的好友或恋人。禁止说教，禁止官方语气。"
                raw_reply = await self.llm.chat(
                    [{"role": "user", "content": prompt_content}],
                    system_prompt=fallback_prompt,
                )

            if not raw_reply or "cannot assist" in raw_reply.lower():
                return []

            segments = self.processor.process(raw_reply)
            return segments
        except Exception as e:
            logger.error(f"[MaiReply Proactive] ????????: {e}", exc_info=True)
            return []

    async def send_proactive_care(
        self,
        bot,
        user_id: int,
        segments: List[str]
    ) -> None:
        """
        调用官方原生 bot.send_friend_message 发送分段主动私聊
        包含打字机延迟模拟与可选的语音 TTS 合成发送
        """
        if not segments:
            return

        full_reply_text = "||".join(segments)

        # 逐段模拟打字延迟并发送
        for i, seg in enumerate(segments):
            seg_text = seg.strip()
            if not seg_text:
                continue

            delay = calc_typing_delay(seg_text, self.processor.typing_ms_per_char, self.processor.typing_max_ms)
            if delay > 0:
                await asyncio.sleep(delay)

            # 调用官方协议接口发送私聊纯文本
            try:
                await bot.send_friend_message(user_id, [Text(seg_text)])
                logger.info(f"[MaiReply Proactive] -> {user_id} 发送成功: {seg_text}")
            except Exception as e:
                logger.error(f"[MaiReply Proactive] -> {user_id} 发送异常: {e}", exc_info=True)

            if i < len(segments) - 1 and self.processor.split_interval_ms > 0:
                await asyncio.sleep(self.processor.split_interval_ms / 1000.0)

        # 记录本次成功关怀的时间，防止短时间内重复触发
        self._last_proactive_time[user_id] = time.time()

        # 将主动发送的消息写回会话历史，保证用户回复时能顺畅承接
        try:
            self.context.append_to_session(None, user_id, "[你主动发起关怀]", full_reply_text)
            logger.info(f"[MaiReply Proactive] 已将主动关怀记录写入用户 {user_id} 的会话历史")
        except Exception as e:
            logger.warning(f"[MaiReply Proactive] 写入会话历史失败: {e}")

        # 可选 TTS 语音发送（根据全局配置与主动配置概率）
        await self._maybe_send_voice(bot, user_id, segments)

    async def _maybe_send_voice(self, bot, user_id: int, segments: List[str]) -> None:
        """检查并发送伴随语音"""
        try:
            voice_cfg = self.cfg.mai_reply.config.get("tts", {})
            voice_prob = int(voice_cfg.get("voice_reply_probability", 0))
            if voice_prob <= 0 or random.randint(1, 100) > voice_prob:
                return

            combined_text = ".".join(segments)
            # 去除括号说明
            combined_text = re.sub(r'[（(][^）)]*[）)]', '', combined_text).strip()
            if not combined_text:
                return

            speaker = voice_cfg.get("speaker", "natuki")
            from run.mai_reply.service.reply_engine import _get_gpt_sovits_client
            client = _get_gpt_sovits_client()
            if client and speaker in client.speakers:
                audio_path = await client.generate_tts(combined_text)
                if audio_path:
                    await bot.send_friend_message(user_id, [Record(file=audio_path)])
                    logger.info(f"[MaiReply Proactive] 用户 {user_id} 主动语音 (GPT-SoVITS) 发送完成")
                    return

            # HoliveTTS 降级
            from run.mai_reply.service.HoliveTTS import HoliveTTS
            import uuid
            tts = HoliveTTS()
            save_path = f"data/voice/cache/{uuid.uuid4()}.wav"
            lang = voice_cfg.get("lang_type", "JP").upper()
            audio_path = await tts.synthesize_to_file(
                text=combined_text,
                speaker=speaker,
                language=lang,
                save_as=save_path
            )
            if audio_path:
                await bot.send_friend_message(user_id, [Record(file=audio_path)])
                logger.info(f"[MaiReply Proactive] 用户 {user_id} 主动语音 (HoliveTTS) 发送完成")
        except Exception as e:
            logger.warning(f"[MaiReply Proactive] 用户 {user_id} 主动语音合成或发送失败: {e}")

    async def run_scan_round(self, bot) -> None:
        """执行单轮主动关怀巡检"""
        cfg = self.get_proactive_config()
        if not cfg.get("enable", False):
            return

        from framework_common.database_util.User import get_users_with_permission_above
        perm_level = int(cfg.get("permission_level", 1))
        users = await get_users_with_permission_above(perm_level - 1)
        if not users:
            return

        current_hour = datetime.now().hour
        enable_search = bool(cfg.get("enable_search", True))

        for uid in users:
            try:
                # 获取私聊历史
                history = self.context.get_session_history(None, uid)
                if not history:
                    continue

                should_trigger, period_moment = self.should_trigger_for_user(history, current_hour, cfg, uid)
                if not should_trigger:
                    continue

                # 获取用户印象
                user_impression = self.context.get_impression(uid)
                user_name = f"用户_{uid}"
                try:
                    # 尝试从 bot 获取用户好友昵称
                    if hasattr(bot, "get_stranger_info"):
                        info = await bot.get_stranger_info(user_id=uid)
                        if isinstance(info, dict) and info.get("nickname"):
                            user_name = info["nickname"]
                except Exception:
                    pass

                logger.info(f"[MaiReply Proactive] 正在为用户 {user_name} ({uid}) 分析关怀方案...")
                decision = await self.analyze_and_plan_care(uid, user_name, history, user_impression, period_moment)
                if not decision:
                    continue

                logger.info(f"[MaiReply Proactive] 用户 {uid} 关怀方案通过: {decision.get('topic')} | 理由: {decision.get('care_reason', '')}")

                # 如有需要，执行外部检索
                search_result = ""
                if enable_search and decision.get("need_search") and decision.get("search_query"):
                    search_result = await _perform_web_search(decision.get("search_query"))

                # 生成关怀话语
                segments = await self.generate_proactive_message(user_name, decision, search_result, user_impression)
                if not segments:
                    continue

                # 打印监控面板
                logger.info(
                    f"\n┌──────── MaiReply 主动关怀发送 ────────┐\n"
                    f"│  对象: {user_name} ({uid})\n"
                    f"│  话题: {decision.get('topic')}\n"
                    f"│  内容: {' || '.join(segments)}\n"
                    f"│  感知: {decision.get('time_perception_note')}\n"
                    f"└──────────────────────────────────────┘"
                )

                # 发送
                await self.send_proactive_care(bot, uid, segments)

                # 间隔，避免瞬时并发打爆
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"[MaiReply Proactive] 巡检处理用户 {uid} 发生异常: {e}", exc_info=True)
