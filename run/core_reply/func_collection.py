# -*- coding: utf-8 -*-
"""
func_collection.py
函数调用集合 —— 供 Eridanus ai_llm / core_reply 插件的函数调用体系使用
"""

from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager

from run.core_reply.service.context_manager import ContextManager
from run.core_reply.service.emotion_system import EmotionSystem


async def clear_chat_history(bot: ExtendBot, event, config: YAMLManager):
    """清除当前用户在本会话的 MaiReply 对话历史"""
    ctx = ContextManager(config)
    group_id = getattr(event, "group_id", None)
    ctx.clear_session(group_id, event.user_id)
    await bot.send(event, "好的，对话记录已清除～")


async def get_current_mood(bot: ExtendBot, event, config: YAMLManager):
    """查看 MaiReply bot 当前的情绪状态"""
    emotion = EmotionSystem(config)
    mood = emotion.get_mood()
    score = emotion.get_score()
    direction = "↑" if score > 10 else ("↓" if score < -10 else "→")
    await bot.send(event, f"现在的状态：{mood}（情绪值 {score:+d} {direction}）")


async def update_system(bot: ExtendBot, event, config: YAMLManager):
    """
    管理员专用系统更新函数：
    1. 鉴权：仅允许 basic_config.yaml 中配置的 master.id 执行
    2. 读取 basic_config.yaml 中的 git_update_source 源配置（默认 0 号源）
    3. 后台执行更新逻辑（支持 AI 处理冲突与全文件类型清理）
    4. 完成后向管理员私信汇报更新结果
    5. 重启 Bot 进程使框架层修改生效
    """
    from tool import admin_update_system
    return await admin_update_system(bot, event, config)
