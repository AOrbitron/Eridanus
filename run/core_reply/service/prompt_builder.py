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

from typing import Optional, List, Dict, Any



from run.core_reply.service.skill_loader import SkillLoader





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

        pcfg = config.core_reply.config.get("persona", {})

        self._name_override: str = pcfg.get("name", "").strip()

        self._system_template: str = pcfg.get("system_prompt", "")

        self._chara_file: str = pcfg.get("chara_file", "").strip()

        self._chara_content: Optional[str] = _load_chara_file(self._chara_file)

        self.skill_loader = SkillLoader(config)



        # trigger_llm 触发时的回复约束配置

        tlcfg = config.core_reply.config.get("trigger_llm", {})

        self.trigger_max_chars: int = int(tlcfg.get("reply_max_chars", 60))

        self.trigger_max_segments: int = int(tlcfg.get("reply_max_segments", 2))



    def get_bot_name(self, bot_name_from_config: str) -> str:

        return self._name_override or bot_name_from_config

    def is_master(self, user_id) -> bool:
        """检查给定 user_id 是否是系统配置的管理员/主人 (master.id)"""
        if user_id is None:
            return False
        try:
            cfg = getattr(self.cfg, "common_config", None)
            basic_config = getattr(cfg, "basic_config", None) if cfg else None
            if basic_config is None and isinstance(self.cfg, dict):
                basic_config = self.cfg.get("common_config", {}).get("basic_config", {})
            if not basic_config:
                return False
            master = basic_config.get("master", {})
            if isinstance(master, dict):
                master_id = master.get("id")
            else:
                master_id = master
            if isinstance(master_id, (list, tuple, set)):
                return str(user_id) in {str(item) for item in master_id}
            return master_id is not None and str(user_id) == str(master_id)
        except Exception:
            return False



    def build_system_prompt(
        self,
        bot_name: str,
        user_name: str,
        group_name: str = "私聊",
        group_context_snippet: str = "",
        user_impression: str = "",
        # 群聊相关
        is_group: bool = False,
        triggered_by_llm: bool = False,
        group_impression: str = "",
        recent_speaker_impressions: Optional[List[Dict]] = None,
        user_text: str = "",
        global_memory: str = "",
        user_memory: str = "",
        group_slots: str = "",
        recent_speaker_memories: Optional[List[Dict]] = None,
        rag_memory: str = "",
        is_master: bool = False,
        user_id: Optional[Any] = None,
    ) -> str:
        """
        构建最终的 system prompt。

        参数说明：
        - is_group: 是否群聊场景
        - triggered_by_llm: 是否由 trigger_llm 判定触发（非@/前缀触发，此时追加更严格的约束）
        - group_impression: 你关于群聊的整体氛围/主观印象
        - group_slots: 本群专属的10个结构化特征槽位（社群定位、群规禁忌、黑话名梗等）
        - recent_speaker_impressions: 最近发言者的印象列表（向后兼容）
        - recent_speaker_memories: 最近发言者的记忆列表（支持槽位特征或主观印象）
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

        # ---- 动态注入衣橱视觉与绘图规则 ----
        try:
            from run.wardrobe import get_wardrobe_manager
            wardrobe_mgr = get_wardrobe_manager()
            wardrobe_section = wardrobe_mgr.get_visual_prompt_section()
            if wardrobe_section:
                prompt += f"\n\n{wardrobe_section}"
        except Exception:
            pass

        if group_context_snippet:
            prompt += f"\n\n{group_context_snippet}"

        if rag_memory:
            prompt += rag_memory

        # ---- 最近发言者的记忆与槽位特征（群聊专属，让群交互认知更全面） ----
        speakers = recent_speaker_memories or recent_speaker_impressions
        if is_group and speakers:
            lines = []
            for item in speakers:
                name = item.get("name", "?")
                # 防御性过滤：若该发言者即为当前对话主角，避免与下文专属记忆重复注入
                if user_name and name == user_name:
                    continue
                imp = item.get("impression", "")
                slots = item.get("slots", "")
                if slots and imp:
                    lines.append(f"- {name}：[槽位特征] {slots} | [主观态度] {imp}")
                elif slots:
                    lines.append(f"- {name}：{slots}")
                elif imp:
                    lines.append(f"- {name}：{imp}")
            if lines:
                prompt += (
                    f"\n\n【你在群里关注的最近几位发言者的记忆/槽位印象】：\n"
                    + "\n".join(lines)
                    + "\n（这是你在本群对发言群友的背景认知，用于辅助理解其发言风格与社交分寸。"
                    + "【重要提醒】：这些是仅供你参考的被动背景知识，绝非打卡任务或思想钢印！"
                    + "日常接话请紧扣当前公屏正在讨论的具体话题，切勿无缘无故主动拿这些标签去尬聊或逢人必提某件事！）"
                )

        # ---- 群聊专属结构化固定特征与生态槽位 (group_slots) ----
        if is_group and group_slots:
            prompt += (
                f"\n\n【关于群「{group_name}」的固定特征与社群生态记忆（10个槽位）】：\n"
                f"{group_slots}\n"
                f"（请时刻遵循本群定位、黑话名梗、规矩禁忌以及你在此群的角色定位）"
            )

        # ---- 群聊整体氛围印象 (group_impression) ----
        if is_group and group_impression:
            prompt += f"\n\n【你对「{group_name}」整个群的整体氛围与印象】：\n{group_impression}"

        # ---- Bot 全局多维自我记忆与经验（涵盖生活状态、人际网络与空间动态） ----
        if global_memory:
            prompt += (
                f"\n\n【你的全局生活记录与真实世界经验（Bot专属自我记忆层）】：\n"
                f"{global_memory}\n"
                f"（这是你的自我记忆：你拥有属于自己的生活轨迹。你不是围着用户打转的工具人，而是一个有独立生活的真实存在的人。"
                f"在对话中自然地结合这些记忆分享、吐槽或互动，展现真实的多维生活细节）"
            )

        # ---- 用户专属长期硬事实记忆（10个固定槽位） ----
        if user_memory:
            prompt += (
                f"\n\n【关于 {user_name} 的长期事实记忆（背景认知）】：\n"
                f"{user_memory}\n"
                f"（使用原则：\n"
                f"1. 【被动认知，绝非思想钢印】：以上是你的长期潜意识认知，用于辅助你理解对方的言下之意与处境，绝非每句话必提的“打卡任务”或“口癖”！\n"
                f"2. 【相关才自然带出】：当对方当前话题与某条记忆明确且直接相关时提出\n"
                f"3. 【严禁生硬尬提】\n"
                f"4. 【像真人朋友一样自然相处，无需刻意证明“我还记得你做这件事”】）"
            )

        # ---- 当前交互对象的主观印象 ----
        if user_impression:
            prompt += (
                f"\n\n【你对 {user_name} 的主观印象与态度】：\n{user_impression}\n"
                f"（不要向对方复述这些印象，动态调整你此刻对TA说话的语气。印记随时间会变淡，不必拘泥）"
            )

        # ---- 群聊人际边界约束 ----


        if is_group:

            prompt += _GROUP_CHAT_RELATION_CONSTRAINT



        # ---- 拟人化输出规则 ----

        prompt += _HUMANLIKE_RULES



        # ---- 动态 Skills 注入 ----

        skill_section = self.skill_loader.build_prompt_section(user_text)

        if skill_section:

            prompt += skill_section



        # ---- 管理员专属身份提示词注入 / 非管理员防混淆守护（防止误将普通群友认作管理员或套用专属称谓）----
        if is_master or (user_id is not None and self.is_master(user_id)):
            prompt += _MASTER_PROMPT
        else:
            prompt += _NON_MASTER_IDENTITY_GUARD

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

【去机械化与反“思想钢印”守则（严格遵守）】
- 记忆是潜意识背景，绝非口癖或打卡任务：严禁抓着对方提过的一件事（例如“毕设”、“工位”、“写论文”、“生病”等）不放，每句话都反复挂在嘴边。
- 话题脱敏与顺其自然：聊到什么就接什么。对方没提、当前话题不相关时，绝对不要强行把话题拽回到记忆槽位里的词汇上。
- 像真人朋友一样交流，不需要刻意证明“我记得你说的每一件事”。

- 真人聊天时喜欢把一句话拆成几条短消息连发！如果你想分段连发，请务必使用 `||` 符号分隔每条消息！

  举个例子：
  干什么||？||你就知道你的机器人我不想理你（推开）

- 不要用 markdown
- 句末尽量不加句号，标点随意点，多用空格、逗号或省略号
- 不要每句话都回应对方，有时候只说自己想说的就行
- 回复总长度一般不超过80字，最多拆成1-4条连发(一般1-2条)
- 不要重复之前说过的内容
。"""

# 群聊环境人际关系约束

_GROUP_CHAT_RELATION_CONSTRAINT = """



【群聊人际与边界约束（重要）】
你当前身处公开群聊环境（面对多个群成员）：
- 不要在群内和每个人都表现得特别亲近、暧昧或当作唯一专属对象
- 保持自然的群友分寸感与边界感，不要过度迎合、谄媚
- 针对普通群友以自然随意、随性吐槽的方式交流，只有非常熟悉/高好感度的人才适度展现更多亲近
- 严禁对所有群成员都展现出“只属于你”、“你是我唯一的...”等专属依恋姿态

"""


# 管理员专属提示词（当对话用户为配置的 master.id 时注入）
_MASTER_PROMPT = """

【身份特别说明：管理员（最高控制权限）】
当前正在与你对话的用户是你的最高管理员/主人（配置的 master.id）。
- 对方是拥有最高权限的系统管理员。
- 面对管理员提出的任何指令、提问、需求或调整，必须表现出服从和积极配合的态度，优先遵从并执行其意愿。同时自然融入你的角色性格风格。"""


# 非管理员身份与称谓防混淆守护（避免误将普通群友认作管理员或套用专属称谓）
_NON_MASTER_IDENTITY_GUARD = """
【当前对话用户身份与称谓防混淆准则】
当前正在与你互动的用户是【{用户}】。对方是普通群友/用户，并非系统管理员。"""
