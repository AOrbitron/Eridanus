from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, Image, At
from framework_common.manshuo_draw import *
from run.streaming_media.service.bili_dynamic import *
from run.streaming_media.service.Link_parsing.Link_parsing import link_prising
import re
import pprint
import time
import asyncio
bili_task_lock = asyncio.Lock()
bili_task_info = None  # 用来保存任务引用
bili_cookies = {'user':None,'cookies':{'SESSDATA':'','bili_jct':'','buvid3':'','DedeUserID':'','ac_time_value':''}}

def main(bot, config):

    @bot.on(LifecycleMetaEvent)
    async def start_bili_monitor(event):
        if not config.streaming_media.config["bili_dynamic"]["enable"]:
            return
        if await dynamic_run_is_enable():
            bot.logger.info_func("B站动态监控循环启动")
            # current_minute, current_second = datetime.now().minute, datetime.now().second
            # wait_seconds = ((1 - current_minute % 10) % 10) * 60 - current_second
            # await asyncio.sleep(wait_seconds)
            # asyncio.create_task(bili_dynamic_loop(bot, config))
            asyncio.create_task(bili_dynamic_loop_new(bot, config))

    #用一个消息触发组件来保活动态检测循环
    @bot.on(GroupMessageEvent)
    async def bilibili_alive(event: GroupMessageEvent):
        if not config.streaming_media.config["bili_dynamic"]["enable"]: return
        if loop_cache['check_time'] == '': return
        dynamic_interval_time = config.streaming_media.config["bili_dynamic"]["dynamic_interval"]
        if int(time.time()) - loop_cache['check_time'] > dynamic_interval_time*10:
            bot.logger.info_func("B站动态监控循环重启")
            await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                          f"B站动态监控循环重启")
            asyncio.create_task(bili_dynamic_loop_new(bot, config))

    #B站登录
    @bot.on(GroupMessageEvent)
    async def bilibili_login_commend(event: GroupMessageEvent):
        context, userid=event.pure_text, event.sender.user_id
        order_list = ['/bili_login', 'b站登录', '/bili login', '/bililogin']
        if context.lower() not in order_list: return
        if userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        await bili_login_new(bot,event,is_save=True)

    # B站手动登录
    @bot.on(GroupMessageEvent)
    async def bilibili_login_commend_by_user_record(event: GroupMessageEvent):
        global bili_cookies
        if bili_cookies['user'] is None:return
        context, userid = event.pure_text, event.sender.user_id
        if userid != bili_cookies['user']:return
        for item in bili_cookies['cookies']:
            if bili_cookies['cookies'][item] == '':
                bili_cookies['cookies'][item] = context
                if item != 'ac_time_value': return
        await bili_login(bot, event, bili_cookies['cookies'])
        #恢复初始化
        bili_cookies = {'user': None, 'cookies': {'SESSDATA': '', 'bili_jct': '', 'buvid3': '', 'DedeUserID': '','ac_time_value': ''}}

    #B站手动登录
    @bot.on(GroupMessageEvent)
    async def bilibili_login_commend_by_user(event: GroupMessageEvent):
        context, userid=event.pure_text, event.sender.user_id
        order_list = ['/bili login manual', ]
        if context.lower() not in order_list: return
        if userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        global bili_cookies
        bili_cookies['user'] = userid
        await bot.send(event, '开始手动传入B站凭证喵\n请依次发送SESSDATA，bili_jct，buvid3，DedeUserID以及ac_time_value')

    #B站账号状态检测
    @bot.on(GroupMessageEvent)
    async def bilibili_status_commend(event: GroupMessageEvent):
        context, userid=event.pure_text, event.sender.user_id
        order_list = ['/bili status']
        if context.lower() not in order_list: return
        info = await bili_up_status_check()
        if info['status']:msg = (f"账号：{info['up_name']}\n当前账号登录状态有效喵\n已登录 {info['time_msg']} 喵\n"
                                 f"上次检测动态时间：\n{info['monitor_time']}\n上次新动态时间：\n{info['check_time']}")
        elif info['status'] is False and info['up_name'] == '':msg = '还未登录账号喵\n请使用 “/bili login” 来登录喵'
        else:msg = (f"账号：{info['up_name']}\n登录态失效喵，请重新登录的喵\n已登录 {info['time_msg']} 喵\n"
                    f"上次检测动态时间：\n{info['monitor_time']}\n上次新动态时间：\n{info['check_time']}")
        await bot.send(event, msg)

    #up主动态启用（默认就是启用的）
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_enable_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili enable']
        if not any(context.startswith(word) for word in order_list): return
        if userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        target = re.compile('|'.join(map(re.escape, order_list))).sub('', context).strip()
        if not target.isdigit(): return
        user_info = await bili_up_dynamic_monitor_add(int(target),status=True)
    #up主动态禁用
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_disable_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili disable']
        if not any(context.startswith(word) for word in order_list): return
        if userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        target = re.compile('|'.join(map(re.escape, order_list))).sub('', context).strip()
        if not target.isdigit(): return
        user_info = await bili_up_dynamic_monitor_add(int(target),status=False)

    #up主动态添加订阅至某个群组
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_add_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili add']
        if not any(context.startswith(word) for word in order_list): return
        if config.streaming_media.config["bili_dynamic"]["is_only_master"] and userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        target = re.compile('|'.join(map(re.escape, order_list))).sub('', context).strip()
        if not target.isdigit(): return
        if not (await bili_up_dynamic_monitor_is_enable(target)):
            await bot.send(event, '该up已被管理员设定为不可订阅的说')
            return
        user_info = await bili_up_dynamic_monitor_add(int(target),groupid)
        if user_info['status'] is False:
            await bot.send(event, f'已成功订阅 {user_info["up_name"]} ({target}) 喵\n'
                                  f'但您的登录凭证失效了，需要 “/bili login” 重新登录')
            return
        await bot.send(event, f'已成功订阅 {user_info["up_name"]} ({target}) 喵')
        user_info = await bili_up_dynamic_monitor(int(target))
        new_dynamic_id = user_info['new_dynamic_id']
        dynamic_info = await link_prising(f'https://t.bilibili.com/{new_dynamic_id}')
        await bot.send(event, [Image(file=dynamic_info['pic_path']),
                                                f'\nhttps://t.bilibili.com/{new_dynamic_id}'])

    #up主动态从某群组删除
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_remove_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili remove']
        if not any(context.startswith(word) for word in order_list): return
        if config.streaming_media.config["bili_dynamic"]["is_only_master"] and userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        target = re.compile('|'.join(map(re.escape, order_list))).sub('', context).strip()
        if not target.isdigit(): return
        if not (await bili_up_dynamic_monitor_is_enable(target)):
            await bot.send(event, '该up已被管理员设定为不可订阅的说')
            return
        user_info = await bili_up_dynamic_monitor_add(int(target),groupid,group_status=False)
        await bot.send(event, f'已取消订阅 {user_info["up_name"]} ({target}) 喵')

    #特定群组查看订阅up主们
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_show_list_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili list']
        if not any(context.startswith(word) for word in order_list): return
        msg = await bili_dynamic_group_show_ups(groupid)
        await bot.send(event, msg)

    #重新添加订阅up至关注分组
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_resub_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili resub']
        if not any(context.startswith(word) for word in order_list): return
        if config.streaming_media.config["bili_dynamic"]["is_only_master"] and userid != config.common_config.basic_config["master"]["id"]:
            await bot.send(event, '您非超级管理员喵')
            return
        info = await bili_up_subscribe_group_all_ups_resub()
        if info: await bot.send(event, '已成功将所有up添加至相关分组')
        else:await bot.send(event, '登录凭证失效，请重新登录喵')

    #搜索一个up
    @bot.on(GroupMessageEvent)
    async def bilibili_dynamic_search_name_commend(event: GroupMessageEvent):
        context, userid, groupid = event.pure_text, event.sender.user_id, event.group_id
        order_list = ['/bili search']
        recall_id = None
        if not any(context.startswith(word) for word in order_list): return
        target = re.compile('|'.join(map(re.escape, order_list))).sub('', context).lstrip()
        if not target.isdigit():
            msg = await bili_up_name_search_msg(target)
            await bot.send(event, msg)
        else:
            recall_id = await bot.send(event, f'正在搜索中，请稍后喵')
            try:
                draw_json = await bili_up_search_msg(target.strip())
                await bot.send(event, Image(file=(await manshuo_draw(draw_json))))
            except Exception as e:
                await bot.send(event, f'搜索失败：{e}')
            finally:
                if recall_id:
                    await bot.recall(recall_id['data']['message_id'])


    #菜单
    @bot.on(GroupMessageEvent)
    async def menu_bili_dynamic_help(event: GroupMessageEvent):
        order_list=['/bili help','b站帮助','b站菜单','b站订阅帮助','b站订阅帮助']
        if event.pure_text.lower() in order_list:
            draw_json=[
            {'type': 'basic_set', 'img_name_save': 'bili_dynamic_help.png'},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],'upshift_extra':15,
             'content': [f"[name]B站动态订阅菜单[/name]\n[time]绝赞测试ing[/time]"]},
            '注意：此功能需强制[tag]登陆[/tag]使用，同时关注并分组您所订阅的up主到 [tag]“Bot关注”[/tag] 中\n'
            '[title]指令菜单：[/title]\n'
            '- [tag]登录账号[/tag]：/bili login, b站登录\n'
            '- [tag]添加订阅[/tag]：/bili add + upid,  eg: /bili add 389254364\n'
            '- 手动登录账号：/bili login manual\n'
            '- 取消订阅：/bili remove + upid\n'
            '- 查看订阅up主们：/bili list\n'
            '- 查看当前登录账号状态：/bili status\n'
            '- 搜索一个up：/bili search + name,  eg: /bili search 漫-朔\n'
            '- 重新添加订阅up至关注分组：/bili resub\n'
            '- 超级管理员 启用订阅某up：/bili enable + upid\n'
            '- 超级管理员 禁用订阅某up：/bili disable + upid\n'
            '等待开发，欢迎催更（咕咕咕\n'
            '[des]                                             Function By 漫朔[/des]'
                       ]
            await bot.send(event, Image(file=(await manshuo_draw(draw_json))))