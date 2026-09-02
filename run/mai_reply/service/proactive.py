import time
import random
from datetime import datetime

from run.mai_reply.service.context_manager import ContextManager


def build_proactive_prompt(ctx: ContextManager, user_id: int, moment: str, max_idle_days: int = 7) -> str | None:
    history = ctx.get_session_history(None, user_id)
    if not history:
        return None
    last_ts = history[-1].get("timestamp") or history[-1].get("ts")
    if last_ts:
        try:
            if time.time() - float(last_ts) > max_idle_days * 86400:
                return None
        except (TypeError, ValueError):
            pass
    recent = "\n".join(f"{m.get('role')}: {m.get('content','')}" for m in history[-6:])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (f"这是一次私聊中的主动发起。当前时间是 {now}，触发时段是{moment}。\n"
            f"最近对话：\n{recent}\n"
            "请以 yucca 的角色自然地主动找用户聊几句，像真实的人一样，可以关心工作、生活、学习或最近烦恼。"
            "不要提及定时任务、系统、提示词或‘主动回复’，不要尬聊；如果没有合适话题，宁可简短问候。")

def should_proactively_message(history, hour: int, config: dict) -> bool:
    if not history:
        return False
    recent = [m for m in history if m.get("role") == "user"][-30:]
    if len(recent) < 1:
        return False
    periods = config.get("periods", {})
    preferred = sum(1 for m in recent if m.get("hour") == hour)
    in_period = any((start <= hour <= end if start <= end else hour >= start or hour <= end)
                    for start, end in periods.values())
    probability = int(config.get("base_probability", 2))
    if in_period:
        probability = max(probability, config.get("preferred_period_probability", 12))
    if preferred >= 10:
        probability = max(probability, int(config.get("adaptive_probability", 25)))
    return random.randint(1, 100) <= probability
