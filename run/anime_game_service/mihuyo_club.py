from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, Image, At
from framework_common.manshuo_draw import *
from run.anime_game_service.service.mihuyo_club import *


def main(bot, config):
    game_other_name_list = []
    for item in game_name_list:
        for name in game_name_list[item]:
            game_other_name_list.append(name)

    def find_game_alias(context):
        normalized = (context or '').casefold()
        return next((alias for alias in sorted(set(game_other_name_list), key=len, reverse=True)
                     if alias.casefold() in normalized), None)
    resource_download_started = False
    if config.anime_game_service.config['mihuyo_club']['update_resource_auto']:
        proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
        resource_source = config.anime_game_service.config['mihuyo_club'].get('zzz', {}).get('resource_source', 'auto')
        resource_download_started = schedule_all_game_resource_download(
            getattr(bot, "loop", None), proxy=proxy, source=resource_source)

    @bot.on(LifecycleMetaEvent)
    async def mys_game_resource_startup(event: LifecycleMetaEvent):
        nonlocal resource_download_started
        if config.anime_game_service.config['mihuyo_club']['update_resource_auto'] and not resource_download_started:
            proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
            resource_source = config.anime_game_service.config['mihuyo_club'].get('zzz', {}).get('resource_source', 'auto')
            resource_download_started = schedule_all_game_resource_download(
                getattr(bot, "loop", None), proxy=proxy, source=resource_source)

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
        target_games = find_game_alias(context)
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
        target_games = find_game_alias(context)
        if target_games is None:return
        else:target_games = target_games.strip()
        bot.logger.info(f'{target_games} 便签查询')
        await mys_note_check(userid, bot, event, target_games,draw_type=True)

    #角色攻略与绝区零资源更新
    @bot.on(GroupMessageEvent)
    async def mys_character_guide_order(event: GroupMessageEvent):
        order_list = [
            '攻略', '更新资源', '资源更新', '更新攻略', '攻略更新',
            '角色攻略更新', '下载资源', '下载全部资源',
        ]
        target_list = game_other_name_list
        context, userid = event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(context.rstrip().endswith(word) for word in order_list):
            #兼容“绝区零角色攻略艾莲”这类攻略关键词前置的写法
            if not any(
                context.casefold().startswith(alias.casefold())
                and context[len(alias):].strip().startswith('角色攻略')
                for alias in target_list
            ):
                return
        target_games = find_game_alias(context)
        if target_games is None:
            return
        target_games = target_games.strip()
        bot.logger.info(f'{target_games} 角色攻略/资源更新')
        proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
        zzz_config = config.anime_game_service.config['mihuyo_club'].get('zzz', {})
        await handle_character_command(
            context, userid, bot, event, proxy=proxy,
            source=zzz_config.get('resource_source', 'auto'),
            first_resource=zzz_config.get('first_resource', '猫冬'))

    #绝区零抽卡记录
    @bot.on(GroupMessageEvent)
    async def mys_gacha_card_order(event: GroupMessageEvent):
        order_list = ['抽卡记录']
        target_list = game_other_name_list
        context, userid = event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(context.rstrip().endswith(word) for word in order_list):
            return
        target_games = find_game_alias(context)
        if target_games is None:
            return
        target_games = target_games.strip()
        bot.logger.info(f'{target_games} 抽卡记录查询')
        proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
        if target_games == '绝区零':
            await handle_card_command(context, userid, bot, event, proxy=proxy)
        elif target_games == '崩铁':
            await bot.send(event, '该游戏好像并未适配喵')
        else:
            #其他几个游戏似乎都不可用，直接ban
            #return
            from run.anime_game_service.service.mihuyo_club.command.game_card import handle_game_card_command
            normalized_target = next((game for game, aliases in game_name_list.items() if target_games in aliases), target_games)
            await handle_game_card_command(context, userid, normalized_target, bot, event, proxy=proxy)

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
