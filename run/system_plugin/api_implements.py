import asyncio
import random
import time
from typing import Optional
import pprint
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, startUpMetaEvent, \
    ProfileLikeEvent, PokeNotifyEvent, GroupBanNoticeEvent, Sender
from developTools.message.message_chain import MessageChain
from developTools.message.message_components import Record, Node, Text, Image
from framework_common.framework_util.func_map_loader import build_tool_map
from framework_common.framework_util.reply_config import legacy_reply as aiReplyCore, core_reply_enabled, active_llm_config
from framework_common.database_util.User import update_user, add_user, get_user
from framework_common.utils.utils import download_img
from framework_common.utils.random_str import random_str
import os

from run.core_reply.service.reply_engine import ReplyEngine


def main(bot, config):
    engine = ReplyEngine(config)
    master = config.common_config.basic_config["master"]["id"]

    avatar = False
    nudge_list = []
    if active_llm_config(config).get("func_calling", False):
        tools = build_tool_map()
    else:
        tools = None

    @bot.on(GroupMessageEvent)
    async def sendLike(event: GroupMessageEvent):
        if event.pure_text == "赞我":
            user_info = await get_user(event.user_id)
            if user_info.permission >= config.system_plugin.config["api_implements"]["send_like"]:
                await bot.send_like(event.user_id)
                await bot.send(event, config.system_plugin.config["api_implements"]["send_like_message"])
        if event.pure_text.startswith("改备注"):
            await bot.send(event, "已修改")
            remark = event.pure_text.split("改备注")[1].strip()
            await bot.set_friend_remark(event.user_id, remark)
        if event.pure_text=="罐头笑声":
            bot.logger.info("正在发送罐头笑声")
            await bot.send(event,Record(file="https://cdn.pixabay.com/download/audio/2022/09/21/audio_d8aacb968c.mp3?filename=wilrotich-crowd-laughing-07-120585.mp3"))

    @bot.on(GroupBanNoticeEvent)
    async def _(event: GroupBanNoticeEvent):
        if event.user_id == bot.id and event.duration != 0:
            await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                          f"bot在群{event.group_id}被禁言了{event.duration}秒\n操作者id:{event.operator_id}\n建议拉黑该群和该用户")

    @bot.on(GroupMessageEvent)
    async def changeAvatar(event: GroupMessageEvent):
        nonlocal avatar
        # bot.logger.info(event.processed_message)
        # bot.logger.error(event.get("image"))
        if event.pure_text == "换头像" and event.sender.user_id == master:
            await bot.send(event, "发来！")
            avatar = True
        if event.get("image") and avatar and event.sender.user_id == master:
            bot.logger.error(event.get("image")[0]["url"])
            r = await bot.set_qq_avatar(event.get("image")[0]["url"])
            bot.logger.error(r)
            await bot.send(event, "已更换头像！")
            avatar = False
        if event.get("mface"):
            pass
            # await bot.send(event,f"你的彩色小人gif在这里{event.get('mface')[0]['url']}")
        if event.pure_text == "给我管理" and event.sender.user_id == master:
            await bot.set_group_admin(event.group_id, event.sender.user_id, True)
            await bot.send(event, "给你了！")
        if event.pure_text == "取消管理" and event.sender.user_id == master:
            await bot.set_group_admin(event.group_id, event.sender.user_id, False)
            await bot.send(event, "取消了！")
        if event.pure_text.startswith("改群名") and event.sender.user_id == master:
            name = event.pure_text.split("改群名")[1].strip()
            await bot.set_group_name(event.group_id, name)
        if event.pure_text.startswith("我要头衔"):
            await bot.send(event,"你要牛魔")
            return
            title = event.pure_text.split("我要头衔")[1].strip()
            await bot.set_group_special_title(event.group_id, event.sender.user_id, title)
            await bot.send(event, "已设置头衔！")
        if event.pure_text == "禁言我":
            await bot.mute(event.group_id, event.sender.user_id, 60)
        if event.pure_text == "测试":
            test_select = ['你测你🐎呢？','测测你的','给你一拳!','你才是有问题的那个喵']
            await bot.send(event, random.choice(test_select))
            #r = Node(content=[Text("你好，我是机器人！")])
            #await bot.send(event, r)
            #await bot.send(event, Record(file="file://D:/python/Manyana/data/autoReply/voiceReply/a1axataxaWaQaia.wav"))

    @bot.on(PrivateMessageEvent)
    async def FriendMesHandler(event: PrivateMessageEvent):
        if event.pure_text == "戳我":
            await bot.friend_poke(event.sender.user_id)

    @bot.on(startUpMetaEvent)
    async def startUpHandler(event: startUpMetaEvent):
        bot.logger.info("启动成功！")
        bot_name = config.common_config.basic_config["bot"]
        bot.logger.info(f"Bot Name: {bot_name}")
        master_id = config.common_config.basic_config["master"]["id"]
        master_name = config.common_config.basic_config["master"]["name"]
        bot.logger.info(f"Bot master ID: {master_id}  |  Bot master Name: {master_name}")
        group_list = await bot.get_group_list()
        group_list = group_list["data"]
        friend_list = await bot.get_friend_list()
        friend_list = friend_list["data"]
        bot.logger.info(f"读取群列表数量: {len(group_list)}")
        bot.logger.info(f"读取好友列表数量: {len(friend_list)}")
        # 以防万一，给master添加权限
        master_id = config.common_config.basic_config["master"]["id"]
        master_name = config.common_config.basic_config["master"]["name"]
        await add_user(master_id, master_name, master_name)
        await update_user(master_id, permission=999, nickname=master_name)
        # r=await get_user(master_id)

        await update_user(111111111, permission=9999, nickname="主人")
    @bot.on(ProfileLikeEvent)
    async def profileLikeHandler(event: ProfileLikeEvent):
        bot.logger.info(f"{event.operator_id} 赞了你！")
        await bot.send_friend_message(event.operator_id, "谢谢！")

    @bot.on(PokeNotifyEvent)
    async def pokeHandler(event: PokeNotifyEvent):
        """
        戳一戳的功能实现，之所以这么复杂，是因为要获取戳一戳的具体内容。
        """
        if event.group_id and event.group_id in [913122269,1050663831]:
            return
        if event.target_id == bot.id:
            if event.group_id:
                try:
                    data = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
                    user_name = data["data"]["nickname"]
                except:
                    user_name = ""
                bot_name = config.common_config.basic_config["bot"]
                user_info = await get_user(event.user_id, user_name)
                try:
                    text = f"{user_info.nickname}{event.raw_info[2]['txt']}{bot_name}{event.raw_info[4]['txt']}"
                except:
                    bot.logger.error("获取不到戳一戳文本")
                    text = random.choice(["戳一戳你~","摸摸头","拍拍你"])
                bot.logger.info(text)
                # print(text)
                if config.system_plugin.config['api_implements']['nudge']['is_Reply_with_meme']:
                    if random.randint(1, 100) < config.system_plugin.config['api_implements']['nudge'][
                        'Reply_with_meme_probability']:
                        if config.system_plugin.config['api_implements']['nudge']['Reply_with_meme_method'] == 'url':
                            img_path = f"data/pictures/cache/{random_str()}.gif"
                            for url_img in config.system_plugin.config['api_implements']['nudge'][
                                'Reply_with_meme_url']:
                                try:
                                    await download_img(url_img, img_path)
                                    break
                                except:
                                    continue
                        else:
                            directory_img_check = config.system_plugin.config['api_implements']['nudge'][
                                'Reply_with_meme_local']
                            files_img_check = [f for f in os.listdir(directory_img_check) if
                                               os.path.isfile(os.path.join(directory_img_check, f))]
                            img_path = os.path.join(directory_img_check,
                                                    files_img_check[random.randint(0, len(files_img_check) - 1)])
                        await bot.send_group_message(event.group_id, Image(file=img_path))
                        return
                if core_reply_enabled(config) or active_llm_config(config).get("aiReplyCore", False):
                    if not config.core_reply.config["enable"]:
                        r = await aiReplyCore(
                            [{"text": text}],
                            event.user_id,
                            config,
                            tools=tools,
                            bot=bot,
                            event=poke_notify_to_group_message(event),
                        )
                    else:
                        # 最新版本ai对话
                        asyncio.create_task(engine.handle(bot, poke_notify_to_group_message(event), text))
                        return
                else:
                    reply_list = config.system_plugin.config['api_implements']['nudge']['replylist']
                    nonlocal nudge_list
                    if len(reply_list) == len(nudge_list): nudge_list = []
                    r = random.choice(reply_list)
                    for r_num in range(0, len(reply_list)):
                        if r in nudge_list:
                            r = random.choice(reply_list)
                        else:
                            break
                    nudge_list.append(r)
                if r:
                    await bot.send_group_message(event.group_id, r)

                if random.randint(1, 100) < config.system_plugin.config['api_implements']['nudge'][
                    'counter_probability']:
                    await bot.group_poke(event.group_id, event.user_id)
            else:
                bot_name = config.common_config.basic_config["bot"]
                user_info = await get_user(event.user_id)
                text = f"{user_info.nickname}{event.raw_info[2]['txt']}{bot_name}{event.raw_info[4]['txt']}"
                bot.logger.info(text)
                if core_reply_enabled(config) or active_llm_config(config).get("aiReplyCore", False):
                    if not config.core_reply.config["enable"]:
                        r = await aiReplyCore(
                            [{"text": text}],
                            event.user_id,
                            config,
                            tools=tools,
                            bot=bot,
                            event=poke_notify_to_group_message(event),
                        )
                    else:
                        # 最新版本ai对话
                        asyncio.create_task(engine.handle(bot, poke_notify_to_group_message(event), text))
                        return


                else:
                    reply_list = config.system_plugin.config['api_implements']['nudge']['replylist']
                    r = random.choice(reply_list)
                if r:
                    await bot.send_friend_message(event.user_id, r)
                if random.randint(1, 100) < config.system_plugin.config['api_implements']['nudge'][
                    'counter_probability']:
                    await bot.friend_poke(event.user_id)
        # await bot.send_friend_message(event.user_id, "你戳我干啥？")

    def poke_notify_to_group_message(poke_event: PokeNotifyEvent,
                                     message_content: str = "[戳一戳]",
                                     message_id: Optional[int] = None) -> GroupMessageEvent:
        """
        将 PokeNotifyEvent 转换为 GroupMessageEvent

        Args:
            poke_event: 戳一戳通知事件
            message_content: 转换后的消息内容，默认为 "[戳一戳]"
            message_id: 消息ID，如果不提供则使用当前时间戳

        Returns:
            GroupMessageEvent: 转换后的群消息事件
        """
        # 生成消息ID（如果未提供）
        if message_id is None:
            message_id = 114514  # 使用毫秒时间戳作为消息ID

        # 构造消息结构
        message_dict = {"type": "text", "data": {"text": message_content}}
        message_list = [message_dict]

        # 构造默认的发送者信息
        sender = Sender(
            user_id=poke_event.user_id,
            nickname="",  # 默认为空，可以根据需要填充
            sex="unknown",
            age=0,
            card="",
            area="",
            level="",
            role="member",  # 默认为普通成员
            title=""
        )

        # 创建 GroupMessageEvent 实例
        group_message_event = GroupMessageEvent(
            # 从 PokeNotifyEvent 继承的字段
            post_type="message",
            message_type="group",
            user_id=poke_event.user_id,
            group_id=poke_event.group_id or 0,  # 如果为 None 则设为 0
            time=getattr(poke_event, 'time', int(time.time())),  # 使用事件时间或当前时间

            # GroupMessageEvent 特有字段
            sub_type="normal",
            message_id=message_id,
            message=message_list,
            _raw_message=message_content,
            font=0,  # 默认字体
            sender=sender,
            to_me=False,  # 默认不是@机器人
            reply=None,  # 默认不是回复消息
            anonymous=None,  # 默认不是匿名消息

            # 其他默认字段
            original_message=None,
            processed_message=[],  # 会在 __init__ 中自动处理
            message_chain=MessageChain([]),  # 会在 __init__ 中自动设置
            pure_text=""  # 会在 __init__ 中自动设置
        )

        return group_message_event
