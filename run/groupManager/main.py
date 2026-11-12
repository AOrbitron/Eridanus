import asyncio

from developTools.event.events import GroupDecreaseNoticeEvent, GroupIncreaseNoticeEvent, GroupMessageEvent, \
    PrivateMessageEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.reply_config import legacy_reply as aiReplyCore
from framework_common.database_util.User import get_user
from run.groupManager.func_collection import quit_group
from developTools.message.message_components import Text, Image, At
from run.core_reply.service.reply_engine import ReplyEngine


def main(bot: ExtendBot, config):
    engine = ReplyEngine(config)
    checked_group = []

    @bot.on(GroupMessageEvent)
    async def group_message(event: GroupMessageEvent):
        if event.get("text"):
            if event.get("text")[0].strip() == "射精" or event.get("text")[0].strip() == "设置精华" or \
                    event.get("text")[0].strip() == "设精" or event.get("text")[0].strip() == "精华" or \
                    event.get("text")[0].strip() == "设置精华消息":
                if event.get("reply"):
                    await bot.set_essence_msg(int(event.get("reply")[0]["id"]))
                    await bot.send(event, "设置成功")
            elif event.get("text")[0].strip() == "取消精华" or event.get("text")[0].strip() == "取消精华消息" or \
                    event.get("text")[0].strip() == "取消设精" or event.get("text")[0].strip() == "取消射精" or \
                    event.get("text")[0].strip() == "不射精":
                if event.get("reply"):
                    await bot.delete_essence_msg(int(event.get("reply")[0]["id"]))
                    await bot.send(event, "取消成功")

            if event.get("text")[0].strip() == "recall" or event.get("text")[0].strip() == "撤回":
                if event.get("reply"):
                    user_info = await get_user(event.user_id, event.sender.nickname)
                    if not user_info.permission >= config.system_plugin.config["api_implements"]["recall_level"]:
                        await bot.send(event, "你没有足够的权限使用该功能哦~")
                    else:
                        await bot.recall(int(event.get("reply")[0]["id"]))

    @bot.on(GroupDecreaseNoticeEvent)
    async def group_decrease(event: GroupDecreaseNoticeEvent):
        if event.user_id != event.self_id:
            if config.groupManager.config["退群通知"]:
                await bot.send_group_message(event.group_id, f"{event.user_id} 悄悄离开了")

    @bot.on(GroupIncreaseNoticeEvent)
    async def GroupIncreaseNoticeHandler(event: GroupIncreaseNoticeEvent):
        if event.user_id != event.self_id:
            if config.groupManager.config["启用ai入群欢迎"]:
                data = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
                try:
                    name = data["data"]["nickname"]
                except:
                    name = "有新人"
                if not config.core_reply.config["enable"]:
                    r = await aiReplyCore([{"text": f"{name}加入了群聊，为他发送入群欢迎"}], event.group_id, config,
                                          bot=bot,
                                          tools=None)


                    if config.groupManager.config["is_at"]: await bot.send(event, [At(qq=event.user_id), str(r)])
                    else: await bot.send(event, str(r))
                else:
                    asyncio.create_task(engine.handle(bot, event, f"{name}加入了群聊，为他发送入群欢迎"))
            else:
                flag = False
                for single_group in config.groupManager.config["固定入群欢迎"]:
                    if event.group_id in single_group:
                        mes = single_group[event.group_id]
                        if config.groupManager.config["is_at"]: await bot.send(event, [At(qq=event.user_id), mes])
                        else: await bot.send(event, mes)
                        flag = True
                if not flag:
                    if config.groupManager.config["is_at"]: await bot.send(event, [At(qq=event.user_id), config.groupManager.config["通用入群欢迎"]])
                    else: await bot.send(event, config.groupManager.config["通用入群欢迎"])

    @bot.on(GroupMessageEvent)
    async def group_message(event: GroupMessageEvent):
        await quitgroup(event)

    @bot.on(GroupMessageEvent)
    async def _(event: GroupMessageEvent):
        if not config.groupManager.config["自动退群"]:
            return
        if event.group_id in checked_group:
            return
        r = await bot.get_group_info(event.group_id)
        try:
            num = r["data"]["member_count"]
        except:
            return  # 管你这那的
        if r["data"]["member_count"] != 0 and (
                r["data"]["member_count"] <= config.groupManager.config["自动退出少于此人数的群"]
                or r["data"]["member_count"] >= config.groupManager.config[
                    "自动退出多于此人数的群"]) and event.group_id not in config.common_config.censor_group["whitelist"]:
            await bot.quit(event.group_id)
            bot.logger.info_func(f"群{event.group_id}人数{r['data']['member_count']}，自动退出")
            await bot.send_friend_message(config.common_config.basic_config["master"]["id"],
                                          f"群{event.group_id}人数{r['data']['member_count']}，自动退出")
        else:
            checked_group.append(event.group_id)

    @bot.on(PrivateMessageEvent)
    async def private_message(event: PrivateMessageEvent):
        await quitgroup(event)

    async def quitgroup(event):
        if event.user_id == config.common_config.basic_config["master"]["id"]:
            if event.pure_text.startswith("退群"):
                group_id = int(event.pure_text.replace("退群", ""))
                await bot.quit(group_id)
                await bot.send(event, f"已退群{group_id}")
            if event.pure_text.startswith("/quit < "):
                threshold = int(event.pure_text.replace("/quit < ", ""))
                await quit_group(bot, event, config, threshold, "below")
            elif event.pure_text.startswith("/quit > "):
                threshold = int(event.pure_text.replace("/quit > ", ""))
                await quit_group(bot, event, config, threshold, "above")