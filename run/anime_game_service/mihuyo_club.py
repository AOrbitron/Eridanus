from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, Image, At
from framework_common.manshuo_draw import *
from run.anime_game_service.service.mihuyo_club import *


def main(bot, config):
    game_other_name_list = []
    for item in game_name_list:
        for name in game_name_list[item]:
            game_other_name_list.append(name)

    #绑定米游社
    @bot.on(GroupMessageEvent)
    async def mys_bing(event: GroupMessageEvent):
        context, userid=event.pure_text, str(event.sender.user_id)
        order_list = ['mihuyobind', '米游社绑定','米游社登录','绑定米游社']
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.lower() in order_list:
            # await bot.send(event, f'当前该功能维护ing，无法登录喵')
            # return
            await mys_login_new(userid, bot, event,config)

    #米游社签到
    @bot.on(GroupMessageEvent)
    async def mys_sign(event: GroupMessageEvent):
        order_list=['mihuyosign','米游社签到']
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.strip() in order_list:
            await mys_game_sign(userid, bot, event)

    #米游币签到
    @bot.on(GroupMessageEvent)
    async def mys_coin_sign_order(event: GroupMessageEvent):
        order_list=['mihuyocoinsign','米游币签到']
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.strip() in order_list:
            await bot.send(event, f'当前该功能维护ing')
            return
            await mys_coin_sign(userid, bot, event)

    #游戏别名签到
    @bot.on(GroupMessageEvent)
    async def mys_sign_other_gamename(event: GroupMessageEvent):
        order_list=['签到']
        target_list = game_other_name_list
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(context.endswith(word) for word in order_list): return
        target_games = next((t for t in target_list if t in context), None)
        if target_games is None:return
        else:target_games = target_games.strip()
        bot.logger.info(f'{target_games} 游戏签到')
        await mys_game_sign(userid, bot, event, target_games)

    #游戏便签
    @bot.on(GroupMessageEvent)
    async def mys_note_check_order(event: GroupMessageEvent):
        order_list=['便签']
        target_list = game_other_name_list
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(context.endswith(word) for word in order_list): return
        target_games = next((t for t in target_list if t in context), None)
        if target_games is None:return
        else:target_games = target_games.strip()
        bot.logger.info(f'{target_games} 便签查询')
        await bot.send(event, f'当前该功能维护ing')
        return
        await mys_note_check(userid, bot, event, target_games)

    #更改默认签到游戏
    @bot.on(GroupMessageEvent)
    async def change_default_game(event: GroupMessageEvent):
        order_list = ['mysgamechange']
        target_list = ['原神','崩铁','绝区零','崩坏三','未定事件簿','崩坏学园2']
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(context.startswith(word) for word in order_list): return
        target_games = next((t for t in target_list if t in context), None)
        if target_games is None:
            await bot.send(event, f'当前可更改的游戏别名如下：\n{target_list}')
            return
        else:target_games = target_games.strip()
        await change_default_sign_game(userid, target_games, bot, event)

    #菜单
    @bot.on(GroupMessageEvent)
    async def menu_help(event: GroupMessageEvent):
        order_list=['米游社帮助','mihuyohelp']
        if event.pure_text.lower() in order_list:
            await help_menu(bot,event)