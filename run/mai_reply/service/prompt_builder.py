"""
prompt_builder.py
Prompt 构建器 —— 组装系统提示词和用户消息
核心理念：使用自然语言风格构建 Prompt，让回复贴近人类习惯

新增：
- 群聊气氛印象（group_impression）注入
- 最近发言者印象批量注入
- trigger_llm 触发时的严格回复长度/句数约束
"""

import os
import json
import time
from datetime import datetime
from typing import Optional, List, Dict

from run.mai_reply.service.skill_loader import SkillLoader


# 角色卡解析支持 txt / json
def _load_chara_file(chara_file: str) -> Optional[str]:
    if not chara_file:
        return None
    base_dir = os.path.join("data", "system", "chara")
    path = os.path.join(base_dir, chara_file)
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(chara_file)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8") as f:
                print(f"加载到角色{chara_file}")
                return f.read().strip()
        elif ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                desc = data.get("description") or data.get("personality") or data.get("system_prompt", "")
                scenario = data.get("scenario", "")
                return f"{desc}\n{scenario}".strip()
            print(f"加载到角色{chara_file}")
            return str(data)
    except Exception:
        return None
    return None


class PromptBuilder:

    def __init__(self, config, emotion_system):
        self.cfg = config
        self.emotion = emotion_system
        pcfg = config.mai_reply.config.get("persona", {})
        self._name_override: str = pcfg.get("name", "").strip()
        self._system_template: str = pcfg.get("system_prompt", "")
        self._chara_file: str = pcfg.get("chara_file", "").strip()
        self._chara_content: Optional[str] = _load_chara_file(self._chara_file)
        self.skill_loader = SkillLoader(config)

        # trigger_llm 触发时的回复约束配置
        tlcfg = config.mai_reply.config.get("trigger_llm", {})
        self.trigger_max_chars: int = int(tlcfg.get("reply_max_chars", 60))
        self.trigger_max_segments: int = int(tlcfg.get("reply_max_segments", 2))

    def get_bot_name(self, bot_name_from_config: str) -> str:
        return self._name_override or bot_name_from_config

    def build_system_prompt(
        self,
        bot_name: str,
        user_name: str,
        group_name: str = "私聊",
        group_context_snippet: str = "",
        user_impression: str = "",
        # 新增参数
        is_group: bool = False,
        triggered_by_llm: bool = False,
        group_impression: str = "",
        recent_speaker_impressions: Optional[List[Dict]] = None,
        user_text: str = "",
        global_memory: str = "",
    ) -> str:
        """
        构建完整 system prompt。

        新增参数说明：
        - is_group: 是否群聊场景
        - triggered_by_llm: 是否由 trigger_llm 触发（而非@/前缀），触发时追加严格字数约束
        - group_impression: 对这个群的整体气氛/话题印象
        - recent_speaker_impressions: 最近发言者的印象列表，
          格式 [{"name": str, "user_id": int, "impression": str}, ...]
        """
        if self._chara_content:
            base = self._chara_content
        else:
            base = self._system_template

        now = datetime.now()
        time_str = now.strftime("%Y年%m月%d日 %H:%M")
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        time_str += f" {weekdays[now.weekday()]}"

        mood = self.emotion.get_mood()

        prompt = base.replace("{","{{").replace("}","}}").format(
            bot_name=bot_name,
            用户=user_name,
            time=time_str,
            mood=mood,
            group_name=group_name,
        )

        if group_context_snippet:
            prompt += f"\n\n{group_context_snippet}"

        # ---- 群聊整体气氛印象 ----
        if is_group and group_impression:
            prompt += f"\n\n【你对「{group_name}」这个群的整体印象】\n{group_impression}"

        # ---- 最近发言者的个人印象（群聊专用）----
        if is_group and recent_speaker_impressions:
            lines = []
            for item in recent_speaker_impressions:
                name = item.get("name", "?")
                imp = item.get("impression", "")
                if imp:
                    lines.append(f"- {name}：{imp}")
            if lines:
                prompt += (
                    f"\n\n【你对群里最近几位发言者的主观印象】\n"
                    + "\n".join(lines)
                    + "\n（回复时请根据以上印象自然地调整对不同人的语气和态度）"
                )

        # ---- Bot 全局记忆（日常大事件/生活记录）----
        if global_memory:
            prompt += f"\n\n【你近期的全局记忆与生活记录】\n{global_memory}"

        # ---- 当前触发用户的印象 ----
        if user_impression:
            prompt += (
                f"\n\n【你对 {user_name} 的主观印象与态度】\n{user_impression}\n"
                f"（重要：请务必根据以上印象，动态调整你此刻对TA的说话语气！如果印象好就亲昵，如果印象差就冷淡甚至回怼！）"
            )
        else:
            prompt += f"\n\n【你对 {user_name} 的主观印象与态度】\n你们还不算太熟，按你正常的心情回应即可。"

        # ---- 群聊人际边界约束 ----
        if is_group:
            prompt += _GROUP_CHAT_RELATION_CONSTRAINT

        # ---- 拟人化输出规则 ----
        prompt += _HUMANLIKE_RULES

        # ---- 动态 Skills 注入 ----
        skill_section = self.skill_loader.build_prompt_section(user_text)
        if skill_section:
            prompt += skill_section

        # ---- trigger_llm 触发的严格约束（追加在最后，优先级最高）----
        if triggered_by_llm and is_group:
            prompt += _build_trigger_constraint(
                max_chars=self.trigger_max_chars,
                max_segments=self.trigger_max_segments,
            )

        prompt = prompt.replace("{bot_name}", bot_name).replace("{用户}", user_name)
        return prompt.strip()


def _build_trigger_constraint(max_chars: int, max_segments: int) -> str:
    """
    构建 trigger_llm 触发时的严格回复约束块。
    这段追加在 system prompt 最末尾，以确保 LLM 优先遵守。
    """
    return f"""

【群聊插话约束（最高优先级，务必遵守）】
你现在是「主动插入群聊」的状态，不是被人直接找你说话。
- 总字数严格不超过 {max_chars} 字
- 最多分 {max_segments} 条发送（用 `||` 分隔），禁止超过此数量
- 说一两句点到为止，像正常群友随口接一句话一样，不要长篇大论
- 不要解释、不要总结、不要说废话
- 如果没有特别想说的，可以只发一个表情或一句极短的感叹"""


# 拟人化输出规则，始终追加
_HUMANLIKE_RULES = """

【你的说话方式（核心规则）】
- 说话要随意自然，像真实的人在聊天，绝对不要写长篇大论
- 真人聊天时喜欢把一句话拆成几条短消息连发！如果你想分段连发，请务必使用 `||` 符号分隔每条消息！
  举个例子：
  干什么||？||你就知道你的机器人我不想理你（推开）
- 不要用 markdown（没有加粗、没有#标题、没有列表）
- 句末尽量不加句号，标点随意点，多用空格、逗号或省略号
- 不要每句话都回应对方，有时候只说自己想说的就行
- 回复总长度一般不超过80字，最多拆成1-4条连发(一般1-2条)
- 不要重复之前说过的内容"""


# 群聊环境人际关系约束
_GROUP_CHAT_RELATION_CONSTRAINT = """

【群聊人际与边界约束（重要）】
你当前身处公开群聊环境（面对多个群成员）：
- 不要在群内和每个人都表现得特别亲近、暧昧、撒娇或当作唯一专属对象
- 保持自然的群友分寸感与边界感，不要见人就过度迎合、谄媚或对每个人都展现专属唯一亲密感
- 针对普通群友以自然随意、像群友搭话或随性吐槽的方式交流，只有针对特定非常熟悉/高好感度的人才适度展现更多亲近
- 严禁对所有群成员都展现出“只属于你”、“你是我唯一的...”等专属依恋姿态
"""
