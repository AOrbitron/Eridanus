from framework_common.framework_util.reply_config import core_reply_enabled

from developTools.event.events import GroupMessageEvent
from framework_common.database_util.Group import add_to_group


def main(bot,config):
    @bot.on(GroupMessageEvent)
    async def add_message_to_db(event: GroupMessageEvent):
        if core_reply_enabled(config):
            enabled = config.core_reply.config.get("context", {}).get("group_context_window", 15) > 0
        else:
            legacy = getattr(config, "ai_llm", None)
            enabled = bool(legacy and legacy.config.get("llm", {}).get("读取群聊上下文", False))
        if not enabled:
            return
        try:
            user_name=event.sender.nickname
        except:
            user_name=event.user_id
        try:

            message={"user_name":user_name,"user_id":event.user_id,"message":event.processed_message}

            await add_to_group(event.group_id,message)
        except Exception as e:
            bot.logger.error(f"group_mes database error {e}")
            
