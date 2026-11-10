import asyncio
import re

from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, Image, At
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase
from framework_common.manshuo_draw import *
from run.anime_game_service.service.SteamSnooping import *
import threading



#检测是否需要启动的函数，距离bot启动一分钟后就不允许重新启动循环
async def dynamic_run_is_enable(up_type='check',db=None):
    if db is None: return True
    user_info = await db.read_user('bili_dynamic')
    upid = 'up_info'
    is_enable = True
    day_info = await date_get()
    user_info.setdefault(upid, {})
    if up_type == 'bot_up':
        user_info[upid]['computer_up_time'] = day_info['time']
        await db.write_user('bili_dynamic', user_info)
        return
    if day_info['time'] - user_info[upid]['computer_up_time'] > 60:
        is_enable = False
    return is_enable

def main(bot, config):
    # 初始化 Redis 数据库实例
    db=asyncio.run(AsyncSQLiteDatabase.get_instance())
    steam_api_key=config.anime_game_service.config['steamsnooping']['steam_api_key']
    #print(steam_api_key)

    monitor_activated = False
    dynamic_run_is_enabled = False

    @bot.on(LifecycleMetaEvent)
    async def _(event):
        nonlocal monitor_activated,dynamic_run_is_enabled
        if not monitor_activated:
            monitor_activated = True
            if config.anime_game_service.config['steamsnooping']['is_snooping']:
                asyncio.create_task(
                    steamsnoopall(bot, config, db, steam_api_key)
                )


    #绑定一个steamid
    @bot.on(GroupMessageEvent)
    async def bind_steamid(event: GroupMessageEvent):
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.lower().startswith('steambind '):
            #print(context)
            steamid=get_steam_id(context.replace('steambind ', '').strip())
            #print(steamid)
            if not steamid:
                await bot.send(event, '请输入正确的 Steam ID 或 Steam好友代码，格式: steambind [Steam ID 或 Steam好友代码]')
                return
            await db.write_user(userid, {'SteamSnooping':{'steamid':steamid}})
            await bot.send(event, ['成功绑定 ',At(qq=userid), f' 的steamid ({steamid}) 喵'])
        elif context.lower()=='steamunbind':
            await db.write_user(userid, {'SteamSnooping': {'steamid': None}})
            await bot.send(event, ['成功解除 ', At(qq=userid), f' 的steamid绑定'])


    #查询一个人的steam信息
    @bot.on(GroupMessageEvent)
    async def info_steamid(event: GroupMessageEvent):
        context, steamid, steam_friend_code, userid = event.pure_text, None, None, None
        if event.message_chain.has(At):
            try:
                if 'steaminfo' == event.processed_message[0]['text']:userid=event.message_chain.get(At)[0].qq
                else:return
            except Exception as e:return
        elif context.lower().startswith('steaminfo '):
            steamid=get_steam_id(context.replace('steaminfo ', ''))
            steam_friend_code = int(steamid) - STEAM_ID_OFFSET
        elif context.lower() == 'steaminfo':
            userid = str(event.sender.user_id)
        else:return

        if not (steamid and steam_friend_code):
            steaminfodata =await db.read_user(userid)
            if steaminfodata and  'SteamSnooping' in steaminfodata and 'steamid' in steaminfodata['SteamSnooping']:
                #await bot.send(event, Image(file=(await manshuo_draw())))
                steamid = steaminfodata["SteamSnooping"]["steamid"]
                steam_friend_code = int(steamid) - STEAM_ID_OFFSET
            else:
                await bot.send(event, '此用户好像还未绑定，发送"steamhelp"来查看帮助哦')
                return

        #await bot.send(event, f'steamid: {steamid}, steam_friend_code: {steam_friend_code}')

        proxy_config = config.common_config.basic_config['proxy']['http_proxy']
        proxy_config = proxy_config if proxy_config else None
        player_data = await get_user_data(steamid, proxy_config)
        if player_data['status'] is False:
            await bot.send(event, f'获取失败，请稍后重试喵')
            return
        recall_id = await bot.send(event, f'开始查询您的最近steam动态，请耐心等待喵')
        # 根据是否有userid构建不同的绘图参数
        proxy_for_draw = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
        
        if userid:
            try:user_name = (await bot.get_group_member_info(event.group_id, userid))['data']['nickname']
            except:user_name='未知'
            # 有userid时显示QQ和Steam双头像
            #if len(user_name) > 10: user_name = user_name[:10]
            draw_json=[
                {'type': 'basic_set', 'img_width': 1500,'proxy': proxy_for_draw},
                {'type': 'avatar', 'subtype': 'common', 'img': [f'https://q1.qlogo.cn/g?b=qq&nk={userid}&s=640',player_data["avatar_url"]],'upshift_extra':15,'number_per_row': 2,'auto_line_change':False,
                 'content': [f"[name]qq昵称: {user_name}[/name]\n[time]游玩时间：{player_data['recent_2_week_play_time']}[/time]",f'[name]Steam昵称: {player_data["player_name"]}[/name]\n[time]好友代码：{steam_friend_code}[/time]'],
                 'is_rounded_corners_img':False,'is_stroke_img':False,'is_shadow_img':False},'[title]您的最近游戏动态：[/title]',
                {'type': 'img', 'subtype': 'common_with_des_right',
                 'img': [f"{game['game_image_url']}" for game in player_data["game_data"]],
                 'content': [
                     f"[title]{game['game_name']}[/title]\n游玩时间：{game['play_time']} 小时\n{game['last_played']}"
                     f"\n成就：{game.get('completed_achievement_number')} / {game.get('total_achievement_number')}"
                     for game in player_data["game_data"]], 'number_per_row': 1,'is_crop':False}
            ]
        else:
            # 无userid时只显示Steam头像
            draw_json=[
                {'type': 'basic_set', 'img_width': 1500,'proxy': proxy_for_draw},
                {'type': 'avatar', 'subtype': 'common', 'img': [player_data["avatar_url"]],'upshift_extra':15,'auto_line_change':False,
                 'content': [f'[name]Steam昵称: {player_data["player_name"]}[/name]\n[time]好友代码：{steam_friend_code}[/time]\n[time]游玩时间：{player_data["recent_2_week_play_time"]}[/time]'],
                 'is_rounded_corners_img':False,'is_stroke_img':False,'is_shadow_img':False},'[title]最近游戏动态：[/title]',
                {'type': 'img', 'subtype': 'common_with_des_right',
                 'img': [f"{game['game_image_url']}" for game in player_data["game_data"]],
                 'content': [
                     f"[title]{game['game_name']}[/title]\n游玩时间：{game['play_time']} 小时\n{game['last_played']}"
                     f"\n成就：{game.get('completed_achievement_number')} / {game.get('total_achievement_number')}"
                     for game in player_data["game_data"]], 'number_per_row': 1,'is_crop':False}
            ]
        if len(player_data["game_data"]) == 0:
            draw_json.append('如果未查询到您的游玩记录，请检查您自己的隐私设置后再来尝试')
        #for item in draw_json:print(item)
        await bot.send(event, Image(file=(await manshuo_draw(draw_json))))
        await bot.recall(recall_id['data']['message_id'])

    #添加到视歼列表
    @bot.on(GroupMessageEvent)
    async def add_steamid_snoop(event: GroupMessageEvent):
        context, userid = event.pure_text, str(event.sender.user_id)
        target_group = str(event.group_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        else:
            check = context.lower().replace('steamadd', '').replace('steamremove', '').strip()
            if check != '' and bool(re.match(r'^[-+]?(\d+(\.\d*)?|\.\d+)$', check)):
                if check.isdigit(): userid = int(check)
                else: return
        if context.lower().startswith('steamadd') and context.lower() != 'steamaddall':
            steaminfodata =await db.read_user(userid)
            if not (steaminfodata and  'SteamSnooping' in steaminfodata and 'steamid' in steaminfodata['SteamSnooping']):
                await bot.send(event, '此用户好像还未绑定，发送"steamhelp"来查看帮助哦')
                return
            await db.write_user('SteamSnoopingList', {target_group:{userid:True,
                                                              f'{userid}_steamid':steaminfodata["SteamSnooping"]["steamid"],
                                                              }})
            await bot.send(event, [At(qq=userid), f' 已被加入视歼列表'])
        elif context.lower().startswith('steamremove') and context.lower() != 'steamremoveall':
            await db.write_user('SteamSnoopingList', {target_group:{userid:False}})
            await bot.send(event, [At(qq=userid), f' 已被移除视歼列表'])

    #查看当前群的视奸列表
    @bot.on(GroupMessageEvent)
    async def group_check_steamid(event: GroupMessageEvent):
        if event.pure_text.lower() == 'steamcheck':
            ids_list = await db.read_user('SteamSnoopingList')
            user_list, name_list = [],'当前群聊的 Steam视奸 列表为：\n'
            if not (ids_list and str(event.group_id) in ids_list) :
                await bot.send(event, '该群还没有绑定视奸用户哦')
            for user_id in ids_list[str(event.group_id)]:
                if ids_list[str(event.group_id)][user_id] is not True: continue
                user_list.append(user_id)
            if user_list == []:
                await bot.send(event, '该群还没有绑定视奸用户哦')
                return
            #print(user_list)
            for user_id in user_list :
                try:
                    target_name = (await bot.get_group_member_info(event.group_id, user_id))['data']['nickname']
                    name_list += f'@{target_name} '
                except:
                    pass
            await bot.send(event, name_list)

    #取消视奸当前群聊的所有人
    @bot.on(GroupMessageEvent)
    async def group_check_steamid_remove_all(event: GroupMessageEvent):
        if event.pure_text.lower() == 'steamremoveall':
            ids_list = await db.read_user('SteamSnoopingList')
            user_list, name_list = [],'已取消本群的视奸列表：：\n'
            if not (ids_list and str(event.group_id) in ids_list) :
                await bot.send(event, '该群还没有绑定视奸用户哦')
            for user_id in ids_list[str(event.group_id)]:
                if ids_list[str(event.group_id)][user_id] is not True: continue
                user_list.append(user_id)
            if user_list == []:
                await bot.send(event, '该群还没有绑定视奸用户哦')
                return
            #print(user_list)
            db_write_json = {}
            for user_id in user_list :
                try:
                    target_name = (await bot.get_group_member_info(event.group_id, user_id))['data']['nickname']
                    name_list += f'@{target_name} '
                except:
                    pass
                db_write_json[user_id] = False
            await db.write_user('SteamSnoopingList', {str(event.group_id): db_write_json})
            await bot.send(event, name_list)

    #取消视奸当前群聊的所有人
    @bot.on(GroupMessageEvent)
    async def group_check_steamid_add_all(event: GroupMessageEvent):
        if event.pure_text.lower() == 'steamaddall':
            all_users = await db.read_all_users()
            user_list, name_list, steam_add_json = [], '已更新本群的视奸列表：：\n', {}
            friendlist_get = await bot.get_group_member_list(event.group_id)
            for friend in friendlist_get["data"]:
                user_id = str(friend['user_id'])
                if user_id not in all_users:continue
                if 'SteamSnooping' not in all_users[user_id]:continue
                if 'steamid' not in all_users[user_id]['SteamSnooping']:continue
                target_name = (await bot.get_group_member_info(event.group_id, user_id))['data']['nickname']
                name_list += f'@{target_name} '
                steam_add_json[user_id] = True
                steam_add_json[f'{user_id}_steamid'] = all_users[user_id]['SteamSnooping']['steamid']

            await db.write_user('SteamSnoopingList', {str(event.group_id): steam_add_json})
            await bot.send(event, name_list)


    #菜单
    @bot.on(GroupMessageEvent)
    async def menu_steamid(event: GroupMessageEvent):
        if event.pure_text.lower() in ['steamhelp','steam帮助'] :
            draw_json=[
            {'type': 'basic_set','img_name_save': 'steamhelp.png'},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],'upshift_extra':15,
            'content': [f"[name]Steam视奸菜单[/name]\n[time]什么！你是怎么发现我可以视奸你的！！！！[/time]"]},
            '在这里你可以通过bot随时随地[title]视奸[/title]你朋友的steam状态\n[des]但是要小心使用，至少经过朋友同意或者不影响他人哦[/des]\n[title]指令菜单：[/title]'
            '\n- 绑定Steam账号：steambind [Steam ID 或 Steam好友代码]（可艾特） \neg: steambind 123456789\n- 解绑Steam账号：steamunbind（可艾特） '
            '\n- 查询Steam最近游玩内容：steaminfo\n（可艾特或者直接发送Steam ID or Steam好友代码）'
            '\n- 添加到当前群进行视奸：steamadd（可艾特）\n- 取消视奸：steamremove（可艾特）\n- 查看当前群视奸列表：steamcheck\n'
            '\n- 视奸当前群聊添加的所有人：steamaddall\n- 取消视奸当前群聊的所有人：steamremoveall\n- 查看当前群视奸列表：steamcheck\n'
            '[title]注意注意！[/title]要先绑定自身的steamid才能进行视奸哦～～\n[des]当然你也可以帮别人绑定哦（逃[/des]\n'
            '[des]                                             Function By 漫朔[/des]'
                       ]
            await bot.send(event, Image(file=(await manshuo_draw(draw_json))))




