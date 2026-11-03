# -*- coding: utf-8 -*-
"""
impression_updater.py
用户印象更新器 —— 定期用 LLM 对历史对话做增量摘要，形成跨会话的压缩记忆
- 每 N 轮触发一次，融合旧印象与新对话生成新印象
- 支持双阶段强保障：阶段1 专属 Tool Calling 抽取硬事实并维护固定槽位；阶段2 生成第一人称主观情感印象
- 印象超过字数上限时自动压缩，避免无限膨胀
- 支持群聊气氛/话题印象（group_impression），每 M 条群消息触发一次
"""

import asyncio
import json
import re
import traceback
from typing import List, Dict, Optional, Any

from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.system_logger import get_logger
from run.core_reply.service.simple_chat import simplified_chat
from run.core_reply.service.llm_client import LLMClient

logger = get_logger(__name__)

SUMMARY_TRIGGER_TURNS = 3   # 每聊3轮触发一次用户印象更新
IMPRESSION_MAX_CHARS = 300  # 超过此字数触发压缩

GROUP_IMP_TRIGGER_MSGS = 10  # 每累计 N 条群消息触发一次群印象更新
GROUP_IMP_MAX_CHARS = 400    # 群印象最大字数

# 阶段1：专属硬事实提取与记忆槽位维护提示词（专注 Tool Calling）
MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE = """你是一个严谨客观的事实与记忆分析专家。你的唯一职责是审查对话，提取用户【{user_name}】的长期硬事实，并调用工具写入对应的长期记忆槽位（1-10）。

【你和TA的最新对话记录】：
{history_text}

---
【用户 {user_name} 当前的固定硬事实槽位（1-10）】：
{user_slots_text}

---
【Bot自身当前的全局独立生活经历槽位（1-10）】：
{global_slots_text}

---
【10个记忆槽位蓝图与分类规划】：
- 槽位1 [基础个人档案]：常住城市/常驻地、时区时差、学校学历、年龄称谓、从事职业等稳定事实
- 槽位2 [深度喜好偏好]：长期饮食口味、偏好美食、喜爱动漫游戏、音乐爱好等生活嗜好
- 槽位3 [雷区禁忌点]：绝对忌口食物、反感避讳的话题、容易引起冲突或不快的雷区
- 槽位4 [日常作息规律]：长期稳定的起居作息习惯、早起/熬夜规律、学习/工作作息规律（注意：仅限长期稳定规律，严禁记录“当前在工位/今天在摸鱼/正在排队”等即时动作）
- 槽位5 [性格特质风格]：说话风格特征、标志性口头禅、鲜明性格态度
- 槽位6 [重要人际社会]：重要亲友、宠物名字（如猫狗）、身边重要伙伴等社会关系
- 槽位7 [契约约定承诺]：与Bot约定好的具体事项、承诺做到的事、共同秘密或暗号
- 槽位8-9 [重大生平里程]：过往重要生平经历与转折事件（求学、考研、就业等里程碑成就及年份）
- 槽位10 [近期核心焦点]：近期正全力攻关或牵挂的持续数周/数月级重大现实事件（毕业设计、考研备考、找工作面试、转正答辩等阶段性攻坚；严禁记录当天瞬态或日常琐事）

---
【执行指令（严谨判定，杜绝瞬时噪音）】：
1. 仔细阅读最新对话，提取用户【{user_name}】真实确凿的长期客观事实：
   - 【严格区分长期事实与临时瞬态】：严禁将“此刻在工位”、“今天在摸鱼”、“正在吃外卖”、“准备去洗澡”、“在排队”、“在路上”等几小时内即失效的即时动作写入记忆槽位！此类日常报备与临时动作直接判定为【无事实更新】，绝不调用工具！
   - 【仅限长期稳定特征或重大阶段焦点】：只有城市常住地、特定忌口、长期爱好，或持续数周到数月的重大现实焦点（如“大四在准备毕业设计”、“备考今年年底考研”）才记入槽位。
   - 内容要求：纯客观、事实化、精炼准确（建议30-80字），明确包含具体事实。切勿抒情或写主观评价！
2. 如果旧槽位信息被明确更正、或阶段焦点已完成/已失效（例如用户提到“毕设答辩过了”、“顺利离职了”、“考完研了”），必须调用更新覆盖或调用 `clear_user_memory_slot(slot_id)` 清空！
3. 如果对话中提及了Bot自己的独立生活事件，可调用 `set_global_memory_slot(slot_id, content)` 更新Bot全局槽位。
4. 如果审查后确认本轮对话完全没有任何新的长期硬事实需要沉淀（例如纯日常寒暄、临时状态报备、表情包、无任何新事实），不要调用工具，直接回复【无事实更新】。
"""

# 阶段2：增量更新主观印象：融合旧印象与新对话
GROUP_MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE = """你是一个严谨客观的社群生态与群聊记忆分析专家。你的唯一职责是审查群聊记录，提取群【{group_name}】的社群特征与客观事实，并调用工具写入对应的群记忆槽位（1-10）。

【群【{group_name}】最新公屏聊天片段】：
{window_text}

---
【群【{group_name}】当前的固定特征与生态槽位（1-10）】：
{group_slots_text}

---
【10个群记忆槽位蓝图与分类规划】：
- 槽位1 [社群定位与核心圈子]：本群核心定位与主题（如游戏开黑/二次元同好/学术考研/技术交流/同城校友/闲聊吹水）、成员整体身份特征
- 槽位2 [群规底线与敏感禁忌]：群内明文或潜规则禁止的事项、绝对避讳的话题、容易激化群矛盾的雷区与红线
- 槽位3 [专属黑话与经典名梗]：群内特有黑话暗号、经典历史事件梗、群专属称呼/外号、群友高频口头禅
- 槽位4 [活跃作息与时段节奏]：群内高频活跃时间规律（如早起打卡/深夜修仙/工作日摸鱼划水/周末集中开黑互动等）
- 槽位5 [群体气氛与社交基调]：本群整体氛围基调与风格（如欢脱沙雕/严肃硬核/毒舌互损/温和治愈/吵闹日常）
- 槽位6 [核心人物与成员生态]：群主/管理风格特征、标志性活跃成员角色定位、群内活跃小团体生态与互动关系
- 槽位7 [常驻热门与高频话题]：群里长期高频讨论的共同喜好或固定话题（特定游戏、某部连载作品、固定兴趣圈等）
- 槽位8 [重大历史与里程碑大事件]：本群经历过的重大历史事件、大型集体活动、具有纪念意义的转折时刻与大事件
- 槽位9 [Bot在本群的角色与契约]：Bot在本群被赋予的角色定位（如吉祥物/毒舌吐槽担当/小管家/游戏玩伴）、与本群约定好的专属互动方式或暗号
- 槽位10 [近期核心焦点与走向]：群内近期正在集中关注、组织或筹备的新事件（如近期新游戏开测、线下聚餐面基、群内比赛等）

---
【执行指令】：
1. 仔细阅读最新群聊片段。如果发现涉及本群社群特征、专属黑话名梗、群规雷区、热门话题、近期大事件或Bot在本群角色的客观事实，必须调用工具 set_group_memory_slot(slot_id, content) 写入或更新对应槽位！
   - 内容要求：纯客观、事实化、精炼准确（建议30-80字），突出群集体特征与事实。切勿个人化臆断或空洞抒情！
2. 如果旧槽位信息被明确更正或失效，调用更新覆盖或调用 clear_group_memory_slot(slot_id) 清空。
3. 如果审查后确认本轮群聊片段完全没有任何新的社群特征或群维度事实需要沉淀，不要调用工具，直接回复【无事实更新】。
"""

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
        self._main_llm = llm_client
        self._ctx = context_manager
        # 用户印象计数器：counter_key -> turn_count
        self._counters: Dict[str, int] = {}
        # 群印象计数器：group_id -> msg_count
        self._group_counters: Dict[int, int] = {}

        cfg = YAMLManager.get_instance()
        ccfg = cfg.core_reply.config.get("context", {})


        # 读取主回复模型配置作为保底回退
        lcfg = cfg.core_reply.config.get("llm", {})
        provider = str(lcfg.get("provider", "openai")).lower()
        if provider == "gemini":
            main_model = str(lcfg.get("gemini", {}).get("model") or "gemini-2.0-flash-001").strip()
            main_base_url = str(lcfg.get("gemini", {}).get("base_url") or "https://generativelanguage.googleapis.com").rstrip("/")
            main_keys = lcfg.get("gemini", {}).get("api_keys", [])
        else:
            main_model = str(lcfg.get("openai", {}).get("model") or "gpt-3.5-turbo").strip()
            main_base_url = str(lcfg.get("openai", {}).get("base_url") or "https://api.openai.com").rstrip("/")
            main_keys = lcfg.get("openai", {}).get("api_keys", [])
        main_oa_keys = [k for k in (main_keys if isinstance(main_keys, list) else [main_keys]) if k]

        # 读取 trigger_llm 配置（专门用于轻量判断与低成本提取记忆槽位/印象）
        imp_cfg = ccfg.get("Impression") or ccfg.get("impression") or {}
        slots_cfg = ccfg.get("Slots") or ccfg.get("slots") or {}

        # 记忆体系专用模型（优先读 memory_model 或 impression_model，留空则读 trigger_llm）
        trig_cfg = cfg.core_reply.config.get("trigger_llm", {}) or {}
        trig_model =str(trig_cfg.get("model")).strip()
        trig_base_url = str(trig_cfg.get("base_url") or "").strip().rstrip("/")
        trig_api_key = str(trig_cfg.get("api_key") or "").strip()

        # 优先级原则：
        # 1. 记忆体系默认且优先使用廉价快速的 trigger_llm 配置（避免调用昂贵的主回复大模型浪费 API 资源）
        # 2. 若 trigger_llm 未填写 model ，才自动回退到主回复模型配置
        if trig_model:
            target_model = trig_model
            target_base_url = trig_base_url if trig_base_url else main_base_url
            chosen_keys = [trig_api_key] if trig_api_key else (main_oa_keys if main_oa_keys else [""])

            custom_llm_cfg = {
                "provider": "openai",
                "stream": bool(trig_cfg.get("stream", True)),
                "max_tool_rounds": 10,
                "openai": {
                    "api_keys": chosen_keys,
                    "model": target_model,
                    "base_url": target_base_url,
                    "no_extra_paramters": False,
                    "temperature": 0.3,
                    "max_tokens": 1024,
                }
            }
            try:
                self._slot_llm = LLMClient(cfg, custom_llm_cfg=custom_llm_cfg)
            except Exception as e:
                logger.warning(f"[MaiReply] 基于 trigger_llm 端点构建记忆专用客户端失败，将回退主回复模型: {e}")
                self._slot_llm = self._main_llm

            self.model = target_model
            self.api_key = trig_api_key or (main_oa_keys[0] if main_oa_keys else "")
            self.base_url = target_base_url
            mem_modes = []
            if getattr(self._ctx, "enable_memory_slots", False) or getattr(self._ctx, "enable_group_memory_slots", False):
                mem_modes.append("槽位事实(Slots)")
            if getattr(self._ctx, "enable_impression", False) or getattr(self._ctx, "enable_group_impression", False):
                mem_modes.append("主观印象(Impression)")
            mem_tag = "+".join(mem_modes) if mem_modes else "记忆体系"
            logger.info(f"[MaiReply] {mem_tag}更新优先启用 trigger_llm 独立配置: model={self.model}, base_url={self.base_url}")
        else:
            self._slot_llm = self._main_llm
            self.model = main_model or "gpt-3.5-turbo"
            self.api_key = trig_api_key or (main_oa_keys[0] if main_oa_keys else "")
            self.base_url = main_base_url
            mem_modes = []
            if getattr(self._ctx, "enable_memory_slots", False) or getattr(self._ctx, "enable_group_memory_slots", False):
                mem_modes.append("槽位事实(Slots)")
            if getattr(self._ctx, "enable_impression", False) or getattr(self._ctx, "enable_group_impression", False):
                mem_modes.append("主观印象(Impression)")
            mem_tag = "+".join(mem_modes) if mem_modes else "记忆体系"
            logger.info(f"[MaiReply] trigger_llm 未配置，{mem_tag}更新自动回退使用主回复模型: model={self.model}")

        self.max_chars = int(imp_cfg.get("impression_max_chars", ccfg.get("impression_max_chars", IMPRESSION_MAX_CHARS)))
        # 用户印象更新轮数（优先读 user_trigger_turns，兼容 impression_trigger_turns）
        # 用户记忆（槽位/印象通用）更新间隔
        self.user_memory_trigger: int = int(
            ccfg.get("user_trigger_turns")
            or imp_cfg.get("impression_trigger_turns")
            or ccfg.get("impression_trigger_turns")
            or SUMMARY_TRIGGER_TURNS
        )
        self.user_imp_trigger: int = self.user_memory_trigger

        # 群聊记忆（群生态槽位/群印象通用）更新间隔，统一支持 group_trigger_messages
        self.group_memory_trigger: int = int(
            ccfg.get("group_trigger_messages")
            or ccfg.get("group_trigger_msgs")
            or GROUP_IMP_TRIGGER_MSGS
        )
        self.group_imp_trigger: int = self.group_memory_trigger
        self.group_imp_max_chars: int = int(imp_cfg.get("group_max_chars", ccfg.get("group_max_chars", GROUP_IMP_MAX_CHARS)))

        self.enable_group_impression: bool = bool(
            getattr(self._ctx, "enable_group_impression", False)
        )
        self.enable_impression: bool = bool(
            getattr(self._ctx, "enable_impression", False)
        )
        self.group_impression_ttl: int = int(imp_cfg.get("impression_ttl", ccfg.get("impression_ttl", 604800)))
        # 群聊记忆白名单（通用控制群印象与群生态槽位，兼容旧配置项）
        self.group_memory_whitelist_enabled: bool = bool(
            ccfg.get(
                "group_memory_whitelist_enabled",
                ccfg.get("group_impression_whitelist_enabled", True),
            )
        )
        raw_gwl = ccfg.get("group_memory_whitelist", ccfg.get("group_impression_whitelist", []))
        self.group_memory_whitelist: list = [
            int(x) for x in raw_gwl if str(x).isdigit()
        ]
        self.group_impression_whitelist_enabled: bool = self.group_memory_whitelist_enabled
        self.group_impression_whitelist: list = self.group_memory_whitelist
        # 群聊回复时读取最近 N 位发言者的记忆（通用支持槽位事实与主观印象）
        self.group_reply_speaker_memory_count: int = int(
            ccfg.get("group_reply_speaker_memory_count")
            or ccfg.get("group_reply_impression_count")
            or 3
        )
        self.group_reply_impression_count: int = self.group_reply_speaker_memory_count

    def is_group_memory_enabled(self, group_id) -> bool:
        """
        判断指定群聊是否允许启用群聊记忆（通用控制群生态槽位与群印象）：
        1. 若全局群记忆模式为 none，直接禁用；
        2. 若 group_memory_whitelist_enabled 为 True（白名单模式）：
           - 若填写了 group_memory_whitelist，仅在该列表中的群生效；
           - 若 group_memory_whitelist 为 []（未填写），自动使用 trigger_llm 配置的 whitelist；
        3. 若 group_memory_whitelist_enabled 为 False（全局模式）：
           - 对所有群生效。
        """
        group_mode = self._ctx.get_effective_group_memory_mode() if hasattr(self._ctx, "get_effective_group_memory_mode") else ("slots" if self.enable_group_impression else "none")
        if group_mode == "none":
            return False

        if not group_id:
            return False

        try:
            gid = int(group_id)
        except (ValueError, TypeError):
            return False

        # 白名单模式
        if self.group_memory_whitelist_enabled:
            if self.group_memory_whitelist:
                return gid in self.group_memory_whitelist

            # 若未填写，自动使用 trigger_llm 配置的 whitelist
            cfg = YAMLManager.get_instance()
            trig_cfg = cfg.core_reply.config.get("trigger_llm", {})
            trig_whitelist = [
                int(x) for x in trig_cfg.get("whitelist", []) if str(x).isdigit()
            ]
            return gid in trig_whitelist

        # 全局模式（group_memory_whitelist_enabled=False，对所有群生效）
        return True

    def is_group_impression_enabled(self, group_id) -> bool:
        """判断指定群是否启用了群印象（仅在 group_memory_mode 包含 impression 且群白名单通过时为 True）"""
        if hasattr(self._ctx, "is_group_impression_enabled"):
            return self._ctx.is_group_impression_enabled(group_id)
        return bool(getattr(self, "enable_group_impression", False)) and self.is_group_memory_enabled(group_id)

    def _counter_key(self, user_id: int, group_id) -> str:
        return f"{group_id or 'priv'}:{user_id}"

    async def _call_llm(self, prompt: str, tools=None, system_prompt: Optional[str] = None) -> str:
        """统一的LLM调用入口，优先走支持 Function Calling 的记忆专用 LLMClient（配置优先使用 trigger_llm，未配置时回退主回复模型）"""
        sys_p = system_prompt or "你是一个情感与记忆管理专家，负责帮助Bot记住他人的客观事实、更新自身独立生活记忆、并提炼主观情感态度。"
        target_llm = self._slot_llm or self._main_llm

        if tools:
            # 携带工具调用时，走支持函数调用的记忆专用 LLMClient（优先 trigger_llm）
            if target_llm:
                try:
                    res = await target_llm.chat(
                        messages=[{"role": "user", "content": prompt}],
                        system_prompt=sys_p,
                        tools=tools,
                        model=self.model,
                    )
                    if res is not None:
                        return res
                except Exception as e:
                    logger.warning(f"[MaiReply] 记忆模型函数调用失败，尝试主模型兜底: {e}")
                    if self._main_llm and target_llm != self._main_llm:
                        try:
                            res = await self._main_llm.chat(
                                messages=[{"role": "user", "content": prompt}],
                                system_prompt=sys_p,
                                tools=tools,
                            )
                            if res is not None:
                                return res
                        except Exception as me:
                            logger.error(f"[MaiReply] 主模型兜底执行工具调用亦失败: {me}")
            return ""

        # 普通文本生成（主观印象总结/压缩），优先走轻量记忆模型
        if target_llm:
            try:
                res = await target_llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=sys_p,
                    model=self.model,
                )
                if res is not None:
                    return res
            except Exception as e:
                logger.warning(f"[MaiReply] 记忆专属模型调用失败，尝试回退备用端点: {e}")
                if self._main_llm and target_llm != self._main_llm:
                    try:
                        res = await self._main_llm.chat(
                            messages=[{"role": "user", "content": prompt}],
                            system_prompt=sys_p,
                        )
                        if res is not None:
                            return res
                    except Exception as me:
                        logger.error(f"[MaiReply] 主模型回退调用亦失败: {me}")

        if self.base_url:
            res = await simplified_chat(
                self.base_url,
                [{"role": "user", "content": prompt}],
                self.model,
                self.api_key,
                system_prompt=sys_p,
            )
            return res or ""
        return ""

    def _parse_and_apply_fallback_slots(self, text: str, user_id: int, user_name: str) -> bool:
        """
        容错解析器：当部分模型或中转代理未走原生 tool_calls 而是以文本/JSON/函数代码输出时，
        自动提取并写入记忆槽位，确保 100% 成功率。
        """
        if not text or not text.strip() or "无事实更新" in text:
            return False

        applied = False

        # 1. 提取 XML/函数标记 (<tool_call>, <function=...>)
        xml_matches = re.finditer(r'(?:<tool_call>|<function=(?P<fn>[\w_]+)>)(.*?)(?:</tool_call>|</function>)', text, re.DOTALL)
        for xm in xml_matches:
            fn_tag = xm.group("fn") or ""
            payload_str = (xm.group(2) or "").strip()
            try:
                d = json.loads(payload_str)
                sid = d.get("slot_id") or (d.get("parameters", {}).get("slot_id") if isinstance(d.get("parameters"), dict) else None)
                cnt = d.get("content") or (d.get("parameters", {}).get("content") if isinstance(d.get("parameters"), dict) else "")
                tname = fn_tag or str(d.get("tool", "") or d.get("name", ""))
                if sid is not None and cnt:
                    sid_int = int(sid)
                    if "global" in tname:
                        self._ctx.memory_slots.set_global_slot(sid_int, str(cnt).strip())
                    else:
                        self._ctx.memory_slots.set_user_slot(user_id, sid_int, str(cnt).strip())
                    applied = True
                    logger.info(f"[MemorySlots 容错解析] 成功从XML标记解析写入槽位: {sid_int} -> {cnt}")
            except Exception:
                pass

        # 2. 提取 Markdown 代码块中的 JSON 或原生 JSON 列表/对象
        json_blocks = re.findall(r"```(?:json)?\s*([{\[].*?[}\]])\s*```", text, re.DOTALL)
        candidates = list(json_blocks)
        bare_objs = re.findall(r'(\{[^{}]*?"slot_id"[^{}]*?\})', text, re.DOTALL)
        candidates.extend(bare_objs)
        if not candidates:
            candidates = [text.strip()]

        for block in candidates:
            block_clean = block.strip()
            try:
                data = json.loads(block_clean)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        sid = item.get("slot_id")
                        content = item.get("content")
                        tool_name = str(item.get("tool", "") or item.get("name", "") or item.get("action", ""))
                        if sid is not None:
                            try:
                                sid_int = int(sid)
                                if "clear" in tool_name:
                                    if "global" in tool_name:
                                        self._ctx.memory_slots.clear_global_slot(sid_int)
                                    else:
                                        self._ctx.memory_slots.clear_user_slot(user_id, sid_int)
                                    applied = True
                                    logger.info(f"[MemorySlots 容错解析] 成功清空槽位: {tool_name} -> {sid_int}")
                                elif content:
                                    if "global" in tool_name:
                                        self._ctx.memory_slots.set_global_slot(sid_int, str(content).strip())
                                    else:
                                        self._ctx.memory_slots.set_user_slot(user_id, sid_int, str(content).strip())
                                    applied = True
                                    logger.info(f"[MemorySlots 容错解析] 成功从JSON解析写入槽位: {sid_int} -> {content}")
                            except Exception:
                                pass
            except Exception:
                pass

        # 3. 匹配函数调用形式：set_user_memory_slot(...)
        func_matches = re.finditer(
            r'(?P<fn>set_user_memory_slot|set_global_memory_slot|clear_user_memory_slot|clear_global_memory_slot)\s*\((.*?)\)',
            text,
            re.DOTALL
        )
        for m in func_matches:
            full_fn = m.group("fn")
            args_str = m.group(2)
            sid_m = re.search(r'(?:slot_id\s*=\s*)?(\d+)', args_str)
            cnt_m = re.search(r'(?:content\s*=\s*)?["\'](.*?)["\'](?:\s*[,)]|\s*$)', args_str, re.DOTALL)
            if sid_m:
                try:
                    sid = int(sid_m.group(1))
                    cnt = cnt_m.group(1).strip() if cnt_m else ""
                    if "clear" in full_fn:
                        if "global" in full_fn:
                            self._ctx.memory_slots.clear_global_slot(sid)
                        else:
                            self._ctx.memory_slots.clear_user_slot(user_id, sid)
                        applied = True
                        logger.info(f"[MemorySlots 容错解析] 成功从函数字符串解析清空槽位: {full_fn}({sid})")
                    elif cnt:
                        if "global" in full_fn:
                            self._ctx.memory_slots.set_global_slot(sid, cnt)
                        else:
                            self._ctx.memory_slots.set_user_slot(user_id, sid, cnt)
                        applied = True
                        logger.info(f"[MemorySlots 容错解析] 成功从函数字符串解析写入槽位: {full_fn}({sid}, {cnt})")
                except Exception:
                    pass

        return applied

    async def _extract_and_update_memory_slots(
        self, user_id: int, user_name: str, history_text: str
    ) -> None:
        """阶段1：专门使用 Tool Calling 分析对话并抽取硬事实，维护固定记忆槽位"""
        try:
            tools = self._ctx.memory_slots.build_updater_tools(user_id, user_name)
            user_slots_text = self._ctx.memory_slots.format_user_slots_for_updater(user_id)
            global_slots_text = self._ctx.memory_slots.format_global_slots_for_updater()

            prompt = MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE.format(
                user_name=user_name,
                history_text=history_text,
                user_slots_text=user_slots_text,
                global_slots_text=global_slots_text,
            )

            executed_calls = []
            wrapped_tools = {}
            for tname, tdict in tools.items():
                orig_func = tdict["func"]
                decl = tdict["declaration"]

                def _bind(name, func):
                    async def wrapper(*args, **kwargs):
                        executed_calls.append((name, kwargs))
                        return await func(*args, **kwargs)
                    wrapper.__doc__ = func.__doc__
                    return wrapper

                wrapped_tools[tname] = {
                    "func": _bind(tname, orig_func),
                    "declaration": decl,
                }

            result_text = await self._call_llm(
                prompt,
                tools=wrapped_tools,
                system_prompt="你是一个严谨客观的硬事实记忆提取专家，负责提取客观事实并调用工具更新记忆槽位。切忌主观抒情。",
            )

            if executed_calls:
                logger.info(f"[MaiReply] 记忆槽位更新完成，共触发 {len(executed_calls)} 次工具调用: {[c[0] for c in executed_calls]}")
            else:
                # 若模型未触发原生 tool call，尝试从回复文本做容错解析
                if result_text:
                    parsed = self._parse_and_apply_fallback_slots(result_text, user_id, user_name)
                    if not parsed and "无事实更新" not in result_text:
                        logger.debug(f"[MaiReply] 事实槽位分析无事实更新或未触发工具: {result_text[:60]}")
        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 记忆槽位事实提取失败: {e}")


    def _parse_and_apply_fallback_group_slots(self, text: str, group_id: int, group_name: str) -> bool:
        """
        容错解析器：当模型未走原生 tool_calls 时，从回复文本解析群记忆槽位
        """
        if not text or not text.strip() or "无事实更新" in text:
            return False

        applied = False

        # 1. 提取 XML/函数标记
        xml_matches = re.finditer(r'(?:<tool_call>|<function=(?P<fn>[\w_]+)>)(.*?)(?:</tool_call>|</function>)', text, re.DOTALL)
        for xm in xml_matches:
            payload_str = (xm.group(2) or "").strip()
            try:
                d = json.loads(payload_str)
                sid = d.get("slot_id") or (d.get("parameters", {}).get("slot_id") if isinstance(d.get("parameters"), dict) else None)
                cnt = d.get("content") or (d.get("parameters", {}).get("content") if isinstance(d.get("parameters"), dict) else "")
                if sid is not None and cnt:
                    self._ctx.memory_slots.set_group_slot(group_id, int(sid), str(cnt).strip())
                    applied = True
                    logger.info(f"[GroupMemorySlots 容错解析] 成功从XML写入群 {group_id} 槽位: {sid} -> {cnt}")
            except Exception:
                pass

        # 2. 提取 Markdown 代码块中的 JSON 或原生 JSON
        candidates = list(re.findall(r"`(?:json)?\s*([{\[].*?[}\]])\s*`", text, re.DOTALL))
        candidates.extend(re.findall(r'(\{[^{}]*?"slot_id"[^{}]*?\})', text, re.DOTALL))
        if not candidates:
            candidates = [text.strip()]

        for block in candidates:
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        sid = item.get("slot_id")
                        content = item.get("content")
                        tool_name = str(item.get("tool", "") or item.get("name", "") or item.get("action", ""))
                        if sid is not None:
                            sid_int = int(sid)
                            if "clear" in tool_name:
                                self._ctx.memory_slots.clear_group_slot(group_id, sid_int)
                                applied = True
                                logger.info(f"[GroupMemorySlots 容错解析] 成功清空群槽位: {group_id} -> {sid_int}")
                            elif content:
                                self._ctx.memory_slots.set_group_slot(group_id, sid_int, str(content).strip())
                                applied = True
                                logger.info(f"[GroupMemorySlots 容错解析] 成功写入群槽位: {group_id} -> {sid_int}: {content}")
            except Exception:
                pass

        # 3. 匹配函数调用形式：set_group_memory_slot(...)
        func_matches = re.finditer(
            r'(?P<fn>set_group_memory_slot|clear_group_memory_slot)\s*\((.*?)\)',
            text,
            re.DOTALL
        )
        for m in func_matches:
            full_fn = m.group("fn")
            args_str = m.group(2)
            sid_m = re.search(r'(?:slot_id\s*=\s*)?(\d+)', args_str)
            cnt_m = re.search(r"""(?:content\s*=\s*)?["'](.*?)["'](?:\s*[,)]|\s*$)""", args_str, re.DOTALL)
            if sid_m:
                try:
                    sid = int(sid_m.group(1))
                    cnt = cnt_m.group(1).strip() if cnt_m else ""
                    if "clear" in full_fn:
                        self._ctx.memory_slots.clear_group_slot(group_id, sid)
                        applied = True
                        logger.info(f"[GroupMemorySlots 容错解析] 成功清空群槽位: {full_fn}({sid})")
                    elif cnt:
                        self._ctx.memory_slots.set_group_slot(group_id, sid, cnt)
                        applied = True
                        logger.info(f"[GroupMemorySlots 容错解析] 成功写入群槽位: {full_fn}({sid}, {cnt})")
                except Exception:
                    pass

        return applied

    async def _extract_and_update_group_slots(
        self, group_id: int, group_name: str, window_text: str
    ) -> None:
        """群聊记忆槽位更新阶段：使用专属 Tool Calling 抽取社群特征事实并维护群固定槽位"""
        try:
            if not hasattr(self._ctx, "memory_slots") or not getattr(self._ctx, "enable_group_memory_slots", False):
                return

            tools = self._ctx.memory_slots.build_group_updater_tools(group_id, group_name)
            group_slots_text = self._ctx.memory_slots.format_group_slots_for_updater(group_id)

            prompt = GROUP_MEMORY_SLOT_EXTRACT_PROMPT_TEMPLATE.format(
                group_name=group_name,
                window_text=window_text,
                group_slots_text=group_slots_text,
            )

            executed_calls = []
            wrapped_tools = {}
            for tname, tdict in tools.items():
                orig_func = tdict["func"]
                decl = tdict["declaration"]

                def _bind(name, func):
                    async def wrapper(*args, **kwargs):
                        executed_calls.append((name, kwargs))
                        return await func(*args, **kwargs)
                    wrapper.__doc__ = func.__doc__
                    return wrapper

                wrapped_tools[tname] = {
                    "func": _bind(tname, orig_func),
                    "declaration": decl,
                }

            result_text = await self._call_llm(
                prompt,
                tools=wrapped_tools,
                system_prompt="你是一个严谨客观的群聊社群特征分析专家，负责提取社群硬事实并更新群记忆槽位。切忌个人化抒情。",
            )

            if executed_calls:
                logger.info(f"[MaiReply] 群【{group_name}】记忆槽位更新完成，触发 {len(executed_calls)} 次工具调用: {[c[0] for c in executed_calls]}")
            else:
                if result_text:
                    parsed = self._parse_and_apply_fallback_group_slots(result_text, group_id, group_name)
                    if not parsed and "无事实更新" not in result_text:
                        logger.debug(f"[MaiReply] 群槽位分析无事实更新或未触发工具: {result_text[:60]}")
        except Exception as e:
            traceback.print_exc()
            logger.error(f"[MaiReply] 群记忆槽位事实提取失败: {e}")


    # ------------------------------------------------------------------ 用户印象

    def tick(self, user_id: int, group_id, user_name: str, bot_name: str) -> None:
        """每次对话完成后调用，达到触发轮数时异步更新用户印象与硬事实记忆"""
        user_mode = self._ctx.get_effective_user_memory_mode() if hasattr(self._ctx, "get_effective_user_memory_mode") else "slots"
        if user_mode == "none":
            return
        key = self._counter_key(user_id, group_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        if self._counters[key] >= self.user_imp_trigger:
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

            recent = history[-8:]
            lines = []
            for msg in recent:
                role = user_name if msg["role"] == "user" else bot_name
                content = msg["content"]
                if isinstance(content, list):
                    content = next((p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"), "")
                content = str(content)[:200]
                lines.append(f"{role}：{content}")
            history_text = "\n".join(lines)

            user_mode = self._ctx.get_effective_user_memory_mode() if hasattr(self._ctx, "get_effective_user_memory_mode") else "slots"
            if user_mode == "none":
                return

            # 阶段 1：独立提取客观硬事实并更新记忆槽位
            if user_mode in ("slots", "both"):
                await self._extract_and_update_memory_slots(
                    user_id=user_id,
                    user_name=user_name,
                    history_text=history_text,
                )

            # 阶段 2：生成第一人称主观情感印象（仅在模式包含 impression 时执行，彻底杜绝浪费 API）
            if user_mode in ("impression", "both"):
                old_impression = self._ctx.get_impression(user_id) or ""
                prompt = SUMMARY_PROMPT_TEMPLATE.format(
                    bot_name=bot_name,
                    user_name=user_name,
                    history_text=history_text,
                    old_impression=old_impression or "（暂无，第一次聊）",
                    chars=self.max_chars,
                )

                new_impression = await self._call_llm(
                    prompt,
                    system_prompt="你是一个情感记忆提取器，帮助机器人记住并压缩对他人的主观印象。不加任何前缀。"
                )
                if new_impression:
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
        累计到 group_memory_trigger 条时，异步触发群记忆（槽位或印象）更新。
        """
        if not self.is_group_memory_enabled(group_id):
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
        if not self.is_group_memory_enabled(group_id):
            return
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

            group_mode = self._ctx.get_effective_group_memory_mode() if hasattr(self._ctx, "get_effective_group_memory_mode") else "slots"
            if group_mode == "none":
                return

            # 阶段 1：群聊结构化记忆槽位提取 (group_slots)
            if group_mode in ("slots", "both"):
                await self._extract_and_update_group_slots(
                    group_id=group_id,
                    group_name=group_name,
                    window_text=window_text,
                )

            # 阶段 2：生成群聊整体主观气氛印象（若仅启用 slots 则跳过，彻底避免 API 资源浪费）
            if group_mode in ("impression", "both"):
                old_impression = self._ctx.get_group_impression(group_id) or ""
                prompt = GROUP_IMP_PROMPT_TEMPLATE.format(
                    bot_name=bot_name,
                    group_name=group_name,
                    window_text=window_text,
                    old_impression=old_impression or "（暂无，刚开始旁观这个群）",
                    chars=self.group_imp_max_chars
                )
                new_impression = await self._call_llm(prompt)
                if new_impression:
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
