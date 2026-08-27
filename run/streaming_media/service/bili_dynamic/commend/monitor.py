from bilibili_api import Credential,dynamic,user,live
from bilibili_api import select_client
import asyncio
import gc
import requests
from bilibili_api.exceptions import ResponseCodeException
from bilibili_api.user import create_subscribe_group, set_subscribe_group,get_self_info,RelationType
from .dynamic import bili_user_get_sub_up_dynamic
from datetime import datetime, timedelta
import time
from ..data import *
from ..utils import *
from run.streaming_media.service.Link_parsing.Link_parsing import link_prising
from developTools.utils.logger import get_logger
logger=get_logger('bili_dynamic_monitor')
select_client("httpx")
#创建一个全局变量用来存储群聊列表
loop_cache = {'is_refresh_group':True,'group_list':[],'check_time':'',
                'is_refresh_data':True,'data_info':{},'credential':'',
              'need_repush_dynamic':{},'need_repush_live':{},
              }
#检测当前凭证是否失效,True--需要刷熊，False--不需要刷新
async def check_credential(credential = None):
    if credential is None:
        data_info = await data_init()
        credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                                buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    cookies_info = credential.get_cookies()
    cookies_check = ''
    for item in cookies_info:
        cookies_check += f'{item}={cookies_info[item]};'
    resp = requests.get("https://api.bilibili.com/x/relation/tags",
                        headers={'Cookie': cookies_check, 'User-Agent': 'Mozilla/5.0'})
    res = resp.json()
    #print(res['code'])
    if res['code'] == 0: return False
    elif res['code'] == -101: return True
    else: return True

#自动刷新当前凭证是否失效,True--刷熊成功，False--刷新失败或无法刷新
async def upgrade_credential(data_info = None):
    if data_info is None: data_info = await data_init()
    if data_info['cookies']['sessdata'] == '':return False
    credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                            buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'],
                            ac_time_value=data_info['cookies']['ac_time_value'])
    try: await credential.refresh()
    except: return False
    if await credential.check_refresh():
        return False
    else:
        logger.info_func("B站凭证已刷新喵")
        global loop_cache
        loop_cache['is_refresh_data'] = True
        data_info['cookies']['sessdata'] = credential.sessdata
        data_info['cookies']['bili_jct'] = credential.bili_jct
        data_info['cookies']['ac_time_value'] = credential.ac_time_value
        await data_save(data_info)
        return True


#检测一个up的动态是否被启用
async def bili_up_dynamic_monitor_is_enable(target = None):
    data_info = await data_init(upid=target)
    user_info = data_info['dynamic_info'][f'{target}']
    if user_info['enable'] == '':user_info['enable'] = True
    return user_info['enable']

#重新将所有订阅的up关注并保存在相应分组中
async def bili_up_subscribe_group_all_ups_resub():
    data_info = await data_init()
    user_info = data_info['dynamic_info'][f'up_info']
    user_info['status'] = True
    #创建一个up主分类并将其up设定在此分类里
    credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                            buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    # 检测credential需不需要刷新，此处缺少相关值无法自动刷新，只能重新登录
    if await check_credential(credential):
        user_info['status'] = False
        return user_info
    #获取所有关注的up主
    up_lists = [int(item) for item in data_info['dynamic_info'] if item.isdigit() and data_info['dynamic_info'][item]['enable'] and str(item) != str(data_info['cookies']['dedeuserid'])]
    for up in up_lists:
        up_info = user.User(up, credential)
        info_get_relation = await up_info.get_relation()
        #pprint.pprint(info_get_relation)
        if info_get_relation['relation']['attribute'] not in [2,6]:
            await up_info.modify_relation(RelationType(1))
        del up_info
    #将所有订阅up主都添加到相应分组中
    info = await set_subscribe_group(up_lists,[data_info['cookies']['subscribe_group_id']],credential)
    #pprint.pprint(info)
    del credential
    return user_info

#将一个up添加到订阅列表的同时将其添加到关注分组中
async def bili_up_dynamic_monitor_add(target = None,group = None, status = True, group_status = True):
    global loop_cache
    loop_cache['is_refresh_group'], loop_cache['is_refresh_data'] = True, True
    data_info = await data_init(upid=target)
    user_info = data_info['dynamic_info'][f'{target}']
    user_info['status'] = True
    user_info['enable'] = status
    up_info = user.User(target)
    info = await up_info.get_user_info()
    user_info['up_name'] = info['name']
    if group:
        if group_status and group not in user_info['push_groups']: user_info['push_groups'].append(group)
        elif group_status is False and group in user_info['push_groups']:
            user_info['push_groups'].remove(group)
    await data_save(data_info)
    #创建一个up主分类并将其up设定在此分类里
    credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                            buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    # 检测credential需不需要刷新，此处缺少相关值无法自动刷新，只能重新登录
    if await check_credential(credential):
        user_info['status'] = False
        return user_info
    # 要先关注才行（汗
    up_info = user.User(target,credential)
    # 先查看其与本人的关系，避免重复关注
    info_get_relation = await up_info.get_relation()
    if info_get_relation['relation']['attribute'] != 2:
        await up_info.modify_relation(RelationType(1))
    #将一个up添加至相应关注分组中
    info_set_subscribe_group = await set_subscribe_group([int(target)], [int(data_info['cookies']['subscribe_group_id'])], credential)
    #pprint.pprint(info_set_subscribe_group)
    return user_info

#检测一个up的最新动态
async def bili_up_dynamic_monitor(target = None, data_info = None, day_info = None, credential = None, data_is_save = True):
    if data_info is None: data_info = await data_init(upid=target)
    if day_info is None: day_info = await date_get()
    if credential is None: credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                            buvid3=data_info['cookies']['buvid3'],dedeuserid=data_info['cookies']['dedeuserid'])
    dynamic_list_result = []
    dynamic_list = await dynamic.get_dynamic_page_list(credential, host_mid=int(target))
    #pprint.pprint(dynamic_list)
    for item in dynamic_list:
        #print(item.get_dynamic_id())
        dynamic_list_result.append(item.get_dynamic_id())
    user_info = data_info['dynamic_info'][f'{target}']
    user_info['status'] = True
    if not dynamic_list_result:
        logger.error(f"未获取到动态id列表 up_name:{user_info['up_name']}  up_id: {target}")
        user_info['status'] = False
        return user_info
    #pprint.pprint(user_info)
    user_info['new_dynamic_id'] = dynamic_list_result[0]
    if user_info['new_dynamic_id'] in user_info['dynamic_id']:
        user_info['is_push'] = False
    else:
        user_info['is_push'] = True
    for item in dynamic_list_result:
        if item not in user_info['dynamic_id']:
            user_info['dynamic_id'].append(item)
    while len(user_info['dynamic_id']) > 20:
        user_info['dynamic_id'].pop(0)
    user_info['check_time'] = day_info['time']
    #若传入了data_info，则此处不做保存，由后面统一保存一次
    if data_is_save: await data_save(data_info)
    for item in dynamic_list:
        del item
    return user_info

#此版本是每次直接访问单个up主的当前动态列表，多次访问可能会导致风控
async def bili_dynamic_loop(bot, config):
    """B站动态检查的主循环"""
    subscribe_group_id_flag, notice_flag, group_list, up_list = True, True, [], []
    while True:
        logger.info_func("开始检测B站动态喵")
        #await bot.send_friend_message(config.common_config.basic_config["master"]['id'], f"开始检测B站动态喵")
        day_info = await date_get()
        """获取当前bot列表，避免检测多余up"""
        global group_list_global
        if group_list_global['is_refresh'] or group_list_global['group_list'] == []:
            group_list_global['is_refresh'] = False
            try:
                group_info = (await bot.get_group_list())["data"]
                for item in group_info:
                    if 'group_id' in item: group_list.append(item['group_id'])
                group_list_global['group_list'] = group_list
            except Exception as e:
                logger.error(f"B站动态获取群聊列表出错：{e}")
        else:
            group_list = group_list_global['group_list']

        #构建出需要检测的ups
        up_list = []
        data_info = await data_init()
        for up_id in data_info['dynamic_info']:
            if data_info['dynamic_info'][up_id]['enable'] is False:continue
            group_push_list = data_info['dynamic_info'][up_id]['push_groups']
            for group_id_check in group_push_list:
                if group_id_check in group_list:
                    up_list.append(up_id)
                    break
        # 记录本次检测时间
        data_info['dynamic_info'][f'up_info']['check_time'] = day_info['time']
        #当需要订阅列表不为空再执行
        if up_list != []:
            credential = Credential(sessdata=data_info['cookies']['sessdata'],
                                    bili_jct=data_info['cookies']['bili_jct'],
                                    buvid3=data_info['cookies']['buvid3'],
                                    dedeuserid=data_info['cookies']['dedeuserid'])
            #print(await credential.check_refresh())
            #检测credential需不需要刷新，此处缺少相关值无法自动刷新，只能重新登录
            if await check_credential(credential):
                if notice_flag:
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'], f"B站登录失效，请重新登录喵")
                    notice_flag = False
                gc.collect()
                await asyncio.sleep(600)
                continue
            notice_flag = True
            for up_id in up_list:
                try:
                    dynamic_info = await bili_up_dynamic_monitor(up_id,data_info,day_info,credential,False)
                    # 若获取不到动态列表，大概率是没关注同时也没有相应分组
                    if dynamic_info['status'] is False and subscribe_group_id_flag:
                        subscribe_group_id_flag = False
                        await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                                      f'检测到相关用户没有关注，请使用 “/bili resub” 重新关注up主们')
                except Exception as e:
                    logger.error(f"B站动态出错：{e}")
                    #await bot.send_friend_message(config.common_config.basic_config["master"]['id'],f"B站动态出错：{e}")
                    continue
                #pprint.pprint(dynamic_info)
                #检测到需要推送的情况下开始执行下一步
                if dynamic_info['is_push']:
                    new_dynamic_id = dynamic_info['new_dynamic_id']
                    if not new_dynamic_id: continue
                    for group_id in dynamic_info['push_groups']:
                        if group_id not in group_list:continue
                        try:
                            dynamic_info_prising = await link_prising(f'https://www.bilibili.com/opus/{new_dynamic_id}',credential_bili=credential)
                            logger.info_func(
                                f"推送动态 群号:{group_id} 关注id: {up_id} 最新动态id: {new_dynamic_id}")
                            await bot.send_group_message(group_id, [Image(file=dynamic_info_prising['pic_path']),
                                                                    f'\nhttps://t.bilibili.com/{new_dynamic_id}'])
                        except:
                            logger.error(
                                f"推送动态失败 群号:{group_id} 关注id: {up_id} 最新动态id: {new_dynamic_id}")
        #因为py传的都是地址，在此处同一存储即可
        await data_save(data_info)
        del credential
        #以下时间等待主要为了在分钟属于1的时候开始检测
        #interval = config.streaming_media.config["bili_dynamic"]["dynamic_interval"]
        gc.collect()
        await asyncio.sleep(60)
        current_minute, current_second = datetime.now().minute, datetime.now().second
        wait_seconds = ((1 - current_minute % 10) % 10) * 60 - current_second
        await asyncio.sleep(wait_seconds)



#新版本循环检测主要相对老版本修改了最新动态获取方式
#此版本将以较短时间访问当前登录人的关注动态列表，从中挑选出bot订阅的up主
async def bili_dynamic_loop_new(bot, config):
    """B站动态检查的主循环"""
    global loop_cache
    notice_flag, dynamic_interval_time= True, config.streaming_media.config["bili_dynamic"]["dynamic_interval"]
    credential, data_info = None, None
    while True:
        group_list, up_list = [], []
        logger.info_func("开始检测B站动态喵")
        #await bot.send_friend_message(config.common_config.basic_config["master"]['id'], f"开始检测B站动态喵")
        day_info = await date_get()
        """获取当前bot群组列表，避免检测多余up"""
        #print(loop_cache['is_refresh_group'],loop_cache['is_refresh_data'])
        if loop_cache['is_refresh_group'] or loop_cache['group_list'] == []:
            loop_cache['is_refresh_group'] = False
            try:
                group_info = (await bot.get_group_list())["data"]
                for item in group_info:
                    if 'group_id' in item: group_list.append(item['group_id'])
                loop_cache['group_list'] = group_list
            except Exception as e:
                logger.error(f"B站动态获取群聊列表出错：{e}")
        else:
            group_list = loop_cache['group_list']
        # 记录本次检测时间
        loop_cache['check_time'] = day_info['time']
        #构建出需要检测的up列表
        #若全局变量中显示需要刷新则从数据库中重新读取数据
        if loop_cache['is_refresh_data']:
            logger.info_func("重新从数据库读取B站数据以及凭证")
            #先删除之前引用的数据并进行一次垃圾回收
            del data_info
            del credential
            if 'data_info' in loop_cache: del loop_cache['data_info']
            if 'credential' in loop_cache: del loop_cache['credential']
            loop_cache['data_info'], loop_cache['credential'], credential, data_info = {}, '', None, None
            gc.collect()
            data_info = await data_init()
            # 构建credential，本次不在每次循环检测其是否有效
            # 修改为获取失败后检测是否有效，在根据条件发送通知
            credential = Credential(sessdata=data_info['cookies']['sessdata'],
                                    bili_jct=data_info['cookies']['bili_jct'],
                                    buvid3=data_info['cookies']['buvid3'],
                                    dedeuserid=data_info['cookies']['dedeuserid'])
            loop_cache['data_info'], loop_cache['credential'], loop_cache['is_refresh_data'] = data_info, credential, False
        else:
            data_info, credential = loop_cache['data_info'], loop_cache['credential']

        for up_id in data_info['dynamic_info']:
            if data_info['dynamic_info'][up_id]['enable'] is False:continue
            for group_id_check in data_info['dynamic_info'][up_id]['push_groups']:
                if group_id_check in group_list:
                    up_list.append(up_id)
                    break
        #当需要订阅列表不为空再执行
        if up_list == []:
            await asyncio.sleep(60)
            continue
        # 记录本次检测时间
        data_info['dynamic_info'][f'up_info']['check_time'] = day_info['time']
        dynamic_info_list, live_info_list = {}, {}
        try:
            dynamic_info_list = await dynamic.get_dynamic_page_info(credential, dynamic.DynamicType("all"))
            live_info_list = await live.get_live_followers_info(False, credential)
            notice_flag = True
        except ResponseCodeException as e:
            msg = f"B站动态检测获取当前用户动态列表出错：{e}"
            if e.code == -101:
                #自动刷新一次B站凭证，刷新成功则直接下一次检测
                if await upgrade_credential(data_info):
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'], 'B站凭证已自动刷新喵')
                    continue
                msg = f"B站账号未登录，请重新登录喵"
            elif e.code == -352: msg = f"当前风控ing"
            elif e.code == -400: msg = f"请求错误，请重新登录喵"
            if e.code != 0:
                loop_cache['is_refresh_data'] = True
                loop_cache['data_info'], loop_cache['credential'] = {}, ''
                logger.error(msg)
                if e.code in [-101,-400] and notice_flag:
                    notice_flag = False
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],msg)
                await asyncio.sleep(dynamic_interval_time)
            continue
        except Exception as e:
            logger.error(f"B站动态检测获取当前用户动态列表出错：{e}")
            #检测凭证是否有效
            if await check_credential(credential):
                # 自动刷新一次B站凭证，刷新成功则直接下一次检测
                if await upgrade_credential(data_info):
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],'B站凭证已自动刷新喵')
                    continue
                if notice_flag:
                    await bot.send_friend_message(config.common_config.basic_config["master"]['id'],f"B站登录失效，请重新登录喵")
                    notice_flag, loop_cache['is_refresh_data'] = False, True
                    loop_cache['data_info'], loop_cache['credential'] = {}, ''
                await asyncio.sleep(dynamic_interval_time)
            else:
                await asyncio.sleep(dynamic_interval_time)
            continue
        #当前用户动态页获取成功，开始对获取到的数据进行处理
        dynamic_sub_ids, live_sub_result = {}, {}
        for dynamic_info in dynamic_info_list['items']:
            if not dynamic_info['id_str'].isdigit():continue
            dynamic_id = int(dynamic_info['id_str'])
            dynamic_upid = str(dynamic_info['modules']['module_author']['mid'])
            if dynamic_upid not in up_list:continue
            if dynamic_upid not in dynamic_sub_ids:
                dynamic_sub_ids[dynamic_upid] = []
            dynamic_sub_ids[dynamic_upid].append(dynamic_id)
        #处理直播间信息，将有用数据拆分出来
        if 'rooms' in live_info_list:
            for item in live_info_list['rooms']:
                #continue
                living_upid = str(item['uid'])
                if living_upid not in up_list: continue
                live_sub_result[living_upid] = {'title': item['title'], 'roomid': item['roomid'],
                                                 'time': item['live_time'], 'is_end_live':False}
        #pprint.pprint(live_sub_result)
        #将用户动态页的关注up动态分类后处理是否有新动态，后面统一推送
        update_flag = False
        #这里处理动态更新数据
        #首先将所有up的推送指令设定为False
        for up_id in dynamic_sub_ids:
            user_info = data_info['dynamic_info'][up_id]
            user_info['is_push'] = False
            if dynamic_sub_ids[up_id][0] != user_info['new_dynamic_id'] and dynamic_sub_ids[up_id][0] not in user_info['dynamic_id']:
                user_info['is_push'], update_flag = True, True
                user_info['new_dynamic_id'] = dynamic_sub_ids[up_id][0]
            for item in dynamic_sub_ids[up_id]:
                if item not in user_info['dynamic_id']:
                    user_info['dynamic_id'].append(item)
            while len(user_info['dynamic_id']) > 20:
                user_info['dynamic_id'].pop(0)
        # #测试用
        # dynamic_sub_ids['3546883874097311'] = [1195745077337522183]
        # data_info['dynamic_info']['3546883874097311']['is_push'], update_flag = True, True
        #await data_save(data_info)
        #这里处理直播间数据
        for up_id in list(live_sub_result):
            # 首先对用户数据中缺失的进行初始化
            user_info = data_info['dynamic_info'][up_id]
            user_info.setdefault('living_info', {})
            for key in ['room_id', 'time', 'title','is_push','msg']:
                user_info['living_info'].setdefault(key, '')
            user_info['living_info']['is_push'] = False
            #接着进行赋值处理
            user_info['living_info']['room_id'], user_info['living_info']['title'] = live_sub_result[up_id]['roomid'], live_sub_result[up_id]['title']
            #检测是否需要推送
            #好像结束直播的时候time会变成0，单独处理
            if live_sub_result[up_id]['time'] == 0:
                live_sub_result.pop(up_id, None)
                continue
            if user_info['living_info']['time'] != live_sub_result[up_id]['time']:
                user_info['living_info']['is_push'], update_flag = True, True
                user_info['living_info']['time'] = live_sub_result[up_id]['time']
                user_info['living_info']['msg'] = f"{user_info['up_name']} 开启直播了喵"
        #因为需要检测退出直播通知，这里开始处理相关逻辑
        for up_id in up_list:
            if up_id in live_sub_result:continue
            # 首先对用户数据中缺失的进行初始化
            user_info = data_info['dynamic_info'][up_id]
            user_info.setdefault('living_info', {})
            for key in ['room_id', 'time', 'title','is_push','msg']:
                user_info['living_info'].setdefault(key, '')
            #默认初始化为不推送
            user_info = data_info['dynamic_info'][up_id]
            user_info['living_info']['is_push'] = False
            if user_info['living_info']['time'] != '':
                user_info['living_info']['is_push'], update_flag = True, True
                diff = abs(int(time.time()) - int(user_info['living_info']['time']))
                hours = diff // 3600
                minutes = (diff % 3600) // 60
                seconds = diff % 60
                parts = []
                if hours > 0: parts.append(f"{hours}小时")
                if minutes > 0: parts.append(f"{minutes}分钟")
                if seconds > 0 or not parts:  # 如果前面小时和分钟都没有，至少显示秒
                    parts.append(f"{seconds}秒")
                msg = "".join(parts)
                user_info['living_info']['msg'] = f"{user_info['up_name']} 直播了 {msg} 后下播了喵"
                live_time = user_info['living_info']['time']
                user_info['living_info']['time'] = ''
                #将其添加至直播检测推送名单中
                live_sub_result[up_id] = {'title': None, 'roomid': None, 'time': live_time, 'is_end_live': True}
                #live_sub_result[up_id]['is_end_live'] = True

        # 这里进行缓存动态推送，在新动态之前进行推送
        # 再次尝试将缓存的动态推送
        if loop_cache['need_repush_dynamic'] != {}:
            #logger.info_func(f"检测到有动态推送失败，尝试再次推送喵")
            for new_dynamic_id in list(loop_cache['need_repush_dynamic']):
                #检测该动态是否风控
                if loop_cache['need_repush_dynamic'][new_dynamic_id]['is_danger'] is not False:
                    loop_cache['need_repush_dynamic'][new_dynamic_id]['is_danger'] += 1
                    if loop_cache['need_repush_dynamic'][new_dynamic_id]['is_danger'] > 24:
                        loop_cache['need_repush_dynamic'].pop(new_dynamic_id, None)
                        continue
                    elif loop_cache['need_repush_dynamic'][new_dynamic_id]['is_danger'] % 6 != 0:
                        continue
                    elif loop_cache['need_repush_dynamic'][new_dynamic_id]['is_danger'] % 6 == 0:
                        logger.error(f"动态id: {new_dynamic_id} 已风控，尝试后将等待一段时间后重试")
                push_groups_success = []
                dynamic_info_prising = await link_prising(f'https://t.bilibili.com/{new_dynamic_id}',credential_bili=credential,
                                                         absorb_color=config.streaming_media.config["bili_dynamic"]["is_absorb_color"],
                                                         up_info_get=config.streaming_media.config["bili_dynamic"]["is_fetch_up_info"])
                if dynamic_info_prising['status']:
                    for group_id in loop_cache['need_repush_dynamic'][new_dynamic_id]['push_groups']:
                        if group_id not in group_list: continue
                        logger.info_func(
                            f"重新推送动态 群号:{group_id} 动态id: {new_dynamic_id}，图片地址：{dynamic_info_prising['pic_path']}")
                        try:
                            await bot.send_group_message(group_id,
                                                         [Image(file=dynamic_info_prising['pic_path']),
                                                          f'\nhttps://t.bilibili.com/{new_dynamic_id}'])
                            push_groups_success.append(group_id)
                        except Exception as e:
                            logger.error(
                                f"重新推送动态失败 群号:{group_id} 动态id: {new_dynamic_id}，原因：{e}，动态已存储，等待下次推送")
                else:
                    logger.error(
                        f"重新推送动态解析失败 动态id: {new_dynamic_id}，原因：{dynamic_info_prising['reason']}，动态已存储，等待下次推送")
                if push_groups_success:
                    for group_id in push_groups_success:
                        loop_cache['need_repush_dynamic'][new_dynamic_id]['push_groups'].remove(group_id)
            # 处理缓存中推送的动态
            for new_dynamic_id in list(loop_cache['need_repush_dynamic']):
                if loop_cache['need_repush_dynamic'][new_dynamic_id]['push_groups'] == []:
                    loop_cache['need_repush_dynamic'].pop(new_dynamic_id, None)

        # 再次尝试将缓存的直播推送
        if loop_cache['need_repush_live'] != {}:
            #logger.info_func(f"检测到有直播推送失败，尝试再次推送喵")
            for living_room_id in list(loop_cache['need_repush_live']):
                # 检测该动态是否风控
                if loop_cache['need_repush_live'][living_room_id]['is_danger'] is not False:
                    loop_cache['need_repush_live'][living_room_id]['is_danger'] += 1
                    if loop_cache['need_repush_live'][living_room_id]['is_danger'] > 24:
                        loop_cache['need_repush_live'].pop(living_room_id, None)
                        continue
                    elif loop_cache['need_repush_live'][living_room_id]['is_danger'] % 6 != 0:
                        continue
                    elif loop_cache['need_repush_live'][living_room_id]['is_danger'] % 6 == 0:
                        logger.error(f"直播房间id: {living_room_id} 已风控，尝试后将等待一段时间后重试")
                living_info_prising = await link_prising(f'https://live.bilibili.com/{living_room_id}', credential_bili=credential,
                                                         absorb_color=config.streaming_media.config["bili_dynamic"]["is_absorb_color"],
                                                         up_info_get=config.streaming_media.config["bili_dynamic"]["is_fetch_up_info"])
                pprint.pprint(living_info_prising)
                up_id, push_groups_success = loop_cache['need_repush_live'][living_room_id]['up_id'], []
                if living_info_prising['status']:
                    for group_id in loop_cache['need_repush_live'][living_room_id]['push_groups']:
                        if group_id not in group_list: continue
                        logger.info_func(
                            f"重新推送直播 群号:{group_id} 关注id: {up_id} 直播房间: {living_room_id}，图片地址：{living_info_prising['pic_path']}")
                        try:
                            await bot.send_group_message(group_id, [f"{loop_cache['need_repush_live'][living_room_id]['msg']}\n",Image(file=living_info_prising['pic_path'])])
                            push_groups_success.append(group_id)
                        except Exception as e:
                            logger.error(
                                f"重新推送直播失败 群号:{group_id} 关注id: {up_id} 直播房间: {living_room_id}，原因：{e}，直播已存储，等待下次推送")
                else:
                    logger.error(
                        f"推送直播解析失败 关注id: {up_id} 直播房间: {living_room_id}，原因：{living_info_prising['reason']}，直播已存储，等待下次推送")
                if push_groups_success:
                    for group_id in push_groups_success:
                        loop_cache['need_repush_live'][living_room_id]['push_groups'].remove(group_id)
            # 处理缓存中推送的直播
            for living_room_id in list(loop_cache['need_repush_live']):
                if loop_cache['need_repush_live'][living_room_id]['push_groups'] == []:
                    loop_cache['need_repush_live'].pop(living_room_id, None)


        #检测到关注up有新动态，开始尝试处理
        if update_flag is False:
            await asyncio.sleep(dynamic_interval_time)
            continue
        #有新动态，那就保存数据，此处修改为仅保存动态数据，避免影响cookies
        await dynamic_data_save(data_info['dynamic_info'])

        #构建需要推送的人员
        #push_ups_list = list(dict.fromkeys(list(dynamic_sub_ids.keys()) + list(live_sub_result.keys())))
        push_ups_list = list(set(dynamic_sub_ids.keys()) | set(live_sub_result.keys()))

        #开始制作动态图片并推送
        for up_id in push_ups_list:
            user_info = data_info['dynamic_info'][up_id]
            if user_info['enable'] is False: continue
            if user_info['is_push'] is False and user_info['living_info']['is_push'] is False: continue
            new_dynamic_id = user_info['new_dynamic_id']
            room_id = user_info['living_info']['room_id']
            #进行动态推送
            if up_id in dynamic_sub_ids and user_info['is_push']:
                dynamic_info_prising = await link_prising(f'https://t.bilibili.com/{new_dynamic_id}',credential_bili=credential,
                                                         absorb_color=config.streaming_media.config["bili_dynamic"]["is_absorb_color"],
                                                         up_info_get=config.streaming_media.config["bili_dynamic"]["is_fetch_up_info"])
                if dynamic_info_prising['code'] == -352: dynamic_info_prising['is_danger'] = 0
                #检测动态是否为视频
                if config.streaming_media.config["bili_dynamic"]["is_only_send_video"] and dynamic_info_prising['status'] and dynamic_info_prising['content']['type'] == 'dynamic':
                    if dynamic_info_prising['content']['opus_type'] != 'DYNAMIC_TYPE_AV':
                        continue
                # 此处检测是否为二游中奖通知，进行过滤
                if config.streaming_media.config["bili_dynamic"]["is_filter_winning"] and dynamic_info_prising['status'] and dynamic_info_prising['content']['type'] == 'dynamic':
                    if dynamic_info_prising['content']['opus_type'] == 'DYNAMIC_TYPE_FORWARD' and dynamic_info_prising['content']['text'].strip().startswith('恭喜@'):
                        continue
                if dynamic_info_prising['status']:
                    for group_id in user_info['push_groups']:
                        if group_id not in group_list: continue
                        logger.info_func(
                            f"推送动态 群号:{group_id} 关注id: {up_id} 最新动态id: {new_dynamic_id}，图片地址：{dynamic_info_prising['pic_path']}")
                        try:
                            await bot.send_group_message(group_id, [Image(file=dynamic_info_prising['pic_path']),
                                                                f'\nhttps://t.bilibili.com/{new_dynamic_id}'])
                        except Exception as e:
                            logger.error(
                                f"推送动态失败 群号:{group_id} 关注id: {up_id} 最新动态id: {new_dynamic_id}，原因：{e}，动态已存储，等待下次推送")
                            loop_cache['need_repush_dynamic'].setdefault(new_dynamic_id, {'push_groups': [], 'up_id': up_id, 'is_danger':False})
                            loop_cache['need_repush_dynamic'][new_dynamic_id]['push_groups'].append(group_id)
                else:
                    logger.error(
                        f"推送动态解析失败 关注id: {up_id} 最新动态id: {new_dynamic_id}，原因：{dynamic_info_prising['reason']}，动态已存储，等待下次推送")
                    # 对推送失败的动态进行缓存，下次再次尝试推送
                    loop_cache['need_repush_dynamic'][new_dynamic_id] = {'push_groups':user_info['push_groups'], 'up_id': up_id, 'is_danger':dynamic_info_prising.get('is_danger',False)}

            #进行直播推送
            if up_id in live_sub_result and user_info['living_info']['is_push']:
                living_info_prising = await link_prising(f'https://live.bilibili.com/{room_id}',credential_bili=credential,re_prising=live_sub_result[up_id]['is_end_live'],
                                                         absorb_color=config.streaming_media.config["bili_dynamic"]["is_absorb_color"],
                                                         up_info_get=config.streaming_media.config["bili_dynamic"]["is_fetch_up_info"])
                #pprint.pprint(living_info_prising)
                if living_info_prising['code'] == -352: living_info_prising['is_danger'] = 0
                if living_info_prising['status']:
                    #为了减少直播时重复推送的情况，此处在检测完直播后判断是否真的下播，未下播则不予推送并将数据复原
                    if live_sub_result[up_id]['is_end_live'] is True and living_info_prising['content']['live_status'] is True:
                        #此时检测到的和获取到的存在冲突，进行处理
                        user_info['living_info']['time'] = live_sub_result[up_id]['time']
                        await dynamic_data_save(data_info['dynamic_info'])
                        continue
                    for group_id in user_info['push_groups']:
                        if group_id not in group_list: continue
                        logger.info_func(
                            f"推送直播 群号:{group_id} 关注id: {up_id} 直播房间: {room_id}，图片地址：{living_info_prising['pic_path']}")
                        try:
                            await bot.send_group_message(group_id, [f"{user_info['living_info']['msg']}\n",
                                                                    Image(file=living_info_prising['pic_path'])])
                        except Exception as e:
                            logger.error(
                                f"推送直播失败 群号:{group_id} 关注id: {up_id} 直播房间: {room_id}，原因：{e}，直播已存储，等待下次推送")
                            loop_cache['need_repush_live'].setdefault(new_dynamic_id, {'push_groups':[],'msg':user_info['living_info']['msg'],'up_id':up_id, 'is_danger':False})
                            loop_cache['need_repush_live'][new_dynamic_id]['push_groups'].append(group_id)
                else:
                    logger.error(
                        f"推送直播解析失败 关注id: {up_id} 直播房间: {room_id}，原因：{living_info_prising['reason']}，直播已存储，等待下次推送")
                    # 对推送失败的动态进行缓存，下次再次尝试推送
                    loop_cache['need_repush_live'][room_id] = {'push_groups':user_info['push_groups'],'msg':user_info['living_info']['msg'],'up_id':up_id, 'is_danger':living_info_prising.get('is_danger',False)}
        loop_cache['is_refresh_data'] = True
        gc.collect()
        #此版延时30s即可
        await asyncio.sleep(dynamic_interval_time)