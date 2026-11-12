from collections import defaultdict

from developTools.event.events import GroupMessageEvent
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase
from framework_common.framework_util.yamlLoader import YAMLManager
from developTools.event.events import GroupMessageEvent,LifecycleMetaEvent
from developTools.message.message_components import Record, Node, Text, Image, At
from datetime import datetime, timedelta
from framework_common.utils.install_and_import import install_and_import
dateutil=install_and_import('python-dateutil', 'dateutil')
from dateutil.relativedelta import relativedelta
import time
from framework_common.manshuo_draw import *
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pprint

def main(bot, config):


    db=asyncio.run(AsyncSQLiteDatabase.get_instance())

    speech_cache = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    global batch_update_task
    batch_update_task = False


    async def batch_update_speeches():
        """优化后的批量更新函数 - 大幅减少数据库操作次数"""
        while True:
            try:
                await asyncio.sleep(300)

                if not speech_cache:
                    continue
                bot.logger.info(f"Start batch update speeches for {len(speech_cache)} users")

                current_batch = dict(speech_cache)

                await db.batch_update_speech_counts(current_batch)

                for user_id in current_batch.keys():
                    if user_id in speech_cache:
                        del speech_cache[user_id]

                bot.logger.info(f"Successfully batch updated {len(current_batch)} users")
            except Exception as e:
                bot.logger.error(f"Batch update error: {e}")

    @bot.on(GroupMessageEvent)
    async def on_start(event: GroupMessageEvent):
        """启动批量更新任务"""
        global batch_update_task
        if not batch_update_task:
            asyncio.create_task(batch_update_speeches())
            batch_update_task = True
            bot.logger.info("Batch update task started")

    @bot.on(GroupMessageEvent)
    async def number_speeches_count(event: GroupMessageEvent):
        """记录发言计数到内存缓存"""
        context = event.pure_text
        target_group = int(event.group_id)
        from_id = int(event.sender.user_id)
        today = datetime.now()
        year, month, day = today.year, today.month, today.day
        current_day = f'{year}_{month}_{day}'

        # 使用默认字典，自动创建嵌套结构
        speech_cache[from_id][target_group][current_day] += 1

    # 手动触发批量更新的函数（用于测试或特殊情况）
    async def manual_batch_update():
        """手动触发批量更新"""
        try:
            if speech_cache:
                current_batch = dict(speech_cache)
                await db.batch_update_speech_counts(current_batch)
                speech_cache.clear()
                bot.logger.info("Manual batch update completed")
            else:
                bot.logger.info("No data to update")
        except Exception as e:
            bot.logger.error(f"Manual batch update error: {e}")

    # 性能监控函数
    async def monitor_cache_performance():
        """监控缓存性能"""
        while True:
            await asyncio.sleep(60)  # 每分钟检查一次

            if speech_cache:
                total_users = len(speech_cache)
                total_records = sum(
                    len(groups) * len(days)
                    for groups in speech_cache.values()
                    for days in groups.values()
                )

                bot.logger.info(f"Cache stats - Users: {total_users}, Records: {total_records}")

                # 如果缓存过大，提前触发更新
                if total_records > 10000:  # 超过1万条记录时提前更新
                    bot.logger.warning("Cache size exceeded threshold, triggering early update")
                    await manual_batch_update()

    # 启动性能监控
    # asyncio.create_task(monitor_cache_performance())

    @bot.on(GroupMessageEvent)
    async def number_speeches_check(event: GroupMessageEvent):
        context = event.pure_text
        flag=True
        for i in ['发言排行','发言次数','bb次数','bb排行','b话王','逼话王','壁画王']:
            if i in context:
                context=context.replace(i,'')
                flag=False
        if flag:return
        if context in ['今日','每日','本日']:today = datetime.now()
        elif '昨日' == context:today =datetime.now() - timedelta(days=1)
        elif '明日' == context:
            await bot.send(event, '小南娘说话还挺逗')
            return
        else:return
        bot.logger.info(f"获取到发言排行榜查询需求")
        recall_id = await bot.send(event, f'收到查询指令，请耐心等待喵')
        year, month, day = today.year, today.month, today.day
        current_day = f'{year}_{month}_{day}'
        all_users =await db.read_all_users()
        target_group = int(event.group_id)
        number_speeches_check_list = []
        #处理得出本群的人员信息表
        friendlist_get = await bot.get_group_member_list(event.group_id)
        friendlist = [str(friend['user_id']) for friend in friendlist_get["data"]]
        for user in friendlist:
            if user not in all_users:continue
            if 'number_speeches' in all_users[user] and f'{target_group}' in all_users[user]['number_speeches'] and current_day in all_users[user]['number_speeches'][f'{target_group}']:
                try:
                    target_name = (await bot.get_group_member_info(target_group, user))['data']['nickname']
                except:
                    target_name = '小壁画'
                number_speeches_check_list.append({'name':user,'nicknime':target_name,'number_speeches_count':all_users[user]['number_speeches'][f'{target_group}'][current_day]})
        number_speeches_check_list_nolimited = sorted(number_speeches_check_list, key=lambda x: x["number_speeches_count"], reverse=True)
        number_speeches_check_list=[]
        for item in number_speeches_check_list_nolimited:
            number_speeches_check_list.append(item)
            if len(number_speeches_check_list) >= 16: break
        for idx, item in enumerate(number_speeches_check_list, start=1):
            item["rank"] = idx
        bot.logger.info(f"进入发言排行榜图片制作")
        number_speeches_check_draw_list = [
            {'type': 'basic_set','img_width':1200,'auto_line_change':False},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],
             'content': [f"[name]{context}发言排行榜[/name]\n[time]{datetime.now().strftime('%Y年%m月%d日 %H:%M')}[/time]"]},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list],
             'content': [f"[name]{list['nicknime']}[/name]\n[time]发言次数：{list['number_speeches_count']}次 排名：{list['rank']}[/time]" for list in number_speeches_check_list], 'number_per_row': 2,
             'background': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list]},
        ]
        await bot.send(event, Image(file=(await manshuo_draw(number_speeches_check_draw_list))))
        await bot.recall(recall_id['data']['message_id'])


    @bot.on(GroupMessageEvent)
    async def number_speeches_check_month(event: GroupMessageEvent):
        context = event.pure_text
        flag=True
        for i in ['发言排行','发言次数','bb次数','bb排行','b话王','逼话王','壁画王']:
            if i in context:
                context=context.replace(i,'')
                flag=False
        if flag:return
        if context in ['本月','当月','月度']:today = datetime.now()
        elif '上个月' == context or '上月' == context:

            today =datetime.now() - relativedelta(months=1)
        elif '明月' == context:
            await bot.send(event, '小南娘说话还挺逗')
            return
        else:return
        bot.logger.info(f"获取到发言排行榜查询需求")
        recall_id = await bot.send(event, f'收到查询指令，请耐心等待喵')
        year, month, day = today.year, today.month, today.day
        current_month = f'{year}_{month}_'
        all_users =await db.read_all_users()
        target_group = int(event.group_id)
        number_speeches_check_list = []
        #处理得出本群的人员信息表
        friendlist_get = await bot.get_group_member_list(event.group_id)
        friendlist = [str(friend['user_id']) for friend in friendlist_get["data"]]
        for user in friendlist:
            if user not in all_users:continue
            if 'number_speeches' in all_users[user] and f'{target_group}' in all_users[user]['number_speeches']:
                count=0
                for count_check in all_users[user]['number_speeches'][f'{target_group}']:
                    if current_month in count_check: count += int(all_users[user]['number_speeches'][f'{target_group}'][count_check])
                try:
                    target_name = (await bot.get_group_member_info(target_group, user))['data']['nickname']
                except:
                    target_name = '小壁画'
                number_speeches_check_list.append({'name':user,'nicknime':target_name,'number_speeches_count':count})
        number_speeches_check_list_nolimited = sorted(number_speeches_check_list, key=lambda x: x["number_speeches_count"], reverse=True)
        number_speeches_check_list=[]
        for item in number_speeches_check_list_nolimited:
            number_speeches_check_list.append(item)
            if len(number_speeches_check_list) >= 16: break
        for idx, item in enumerate(number_speeches_check_list, start=1):
            item["rank"] = idx
        bot.logger.info(f"进入发言排行榜图片制作")
        number_speeches_check_draw_list = [
            {'type': 'basic_set','img_width':1400,'auto_line_change':False},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],
             'content': [f"[name]{context}发言排行榜[/name]\n[time]{datetime.now().strftime('%Y年%m月%d日 %H:%M')}[/time]"]},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list],
             'content': [f"[name]{list['nicknime']}[/name]\n[time]发言次数：{list['number_speeches_count']}次 排名：{list['rank']}[/time]" for list in number_speeches_check_list], 'number_per_row': 2,
             'background': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list]},
        ]
        await bot.send(event, Image(file=(await manshuo_draw(number_speeches_check_draw_list))))
        await bot.recall(recall_id['data']['message_id'])



    @bot.on(GroupMessageEvent)
    async def number_speeches_check_year(event: GroupMessageEvent):
        context = event.pure_text
        flag=True
        for i in ['发言排行','发言次数','bb次数','bb排行','b话王','逼话王','壁画王']:
            if i in context:
                context=context.replace(i,'')
                flag=False
        if flag:return
        today = datetime.now()
        year, month, day = today.year, today.month, today.day
        if context in ['今年','年度']:pass
        elif '去年' == context or '去年' == context:
            year -= 1
        elif context in ['明年','来年']:
            await bot.send(event, '小南娘说话还挺逗')
            return
        else:return
        bot.logger.info(f"获取到发言排行榜查询需求")
        recall_id = await bot.send(event, f'收到查询指令，请耐心等待喵')

        current_month = f'{year}_'
        all_users =await db.read_all_users()
        target_group = int(event.group_id)
        number_speeches_check_list = []
        #处理得出本群的人员信息表
        friendlist_get = await bot.get_group_member_list(event.group_id)
        friendlist = [str(friend['user_id']) for friend in friendlist_get["data"]]
        for user in friendlist:
            if user not in all_users:continue
            if 'number_speeches' in all_users[user] and f'{target_group}' in all_users[user]['number_speeches']:
                count=0
                for count_check in all_users[user]['number_speeches'][f'{target_group}']:
                    if current_month in count_check: count += int(all_users[user]['number_speeches'][f'{target_group}'][count_check])
                try:
                    target_name = (await bot.get_group_member_info(target_group, user))['data']['nickname']
                except:
                    target_name = '小壁画'
                number_speeches_check_list.append({'name':user,'nicknime':target_name,'number_speeches_count':count})
        number_speeches_check_list_nolimited = sorted(number_speeches_check_list, key=lambda x: x["number_speeches_count"], reverse=True)
        number_speeches_check_list=[]
        for item in number_speeches_check_list_nolimited:
            number_speeches_check_list.append(item)
            if len(number_speeches_check_list) >= 16: break
        for idx, item in enumerate(number_speeches_check_list, start=1):
            item["rank"] = idx
        bot.logger.info(f"进入发言排行榜图片制作")
        number_speeches_check_draw_list = [
            {'type': 'basic_set','img_width':1400,'auto_line_change':False},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],
             'content': [f"[name]{context}发言排行榜[/name]\n[time]{datetime.now().strftime('%Y年%m月%d日 %H:%M')}[/time]"]},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list],
             'content': [f"[name]{list['nicknime']}[/name]\n[time]发言次数：{list['number_speeches_count']}次 排名：{list['rank']}[/time]" for list in number_speeches_check_list], 'number_per_row': 2,
             'background': [f"https://q1.qlogo.cn/g?b=qq&nk={list['name']}&s=640" for list in number_speeches_check_list]},
        ]
        await bot.send(event, Image(file=(await manshuo_draw(number_speeches_check_draw_list))))
        await bot.recall(recall_id['data']['message_id'])

async def test():
    db = await AsyncSQLiteDatabase.get_instance()
    all_users =await db.read_all_users()
    user_id = 1270858640
    group_id = 674822468
    # pprint.pprint(all_users[f'{user_id}'])
    # return
    # all_users_cache = {f'{user_id}':{'number_speeches':{f'{group_id}': all_users[f'{user_id}']['number_speeches'][f'{group_id}']}}}
    # all_users = all_users_cache
    times_count = 0
    user_cache_multiple = {}
    for user_id in all_users:
        if 'number_speeches' not in all_users[user_id]:continue
        #if user_id != '1270858640':continue
        times_count += 1
        print(user_id, times_count, len(all_users))
        user_cache = all_users[f'{user_id}']
        for group_id in all_users[f'{user_id}']['number_speeches']:
            #await db.delete_user_field(user_id, f'number_speeches.{group_id}')

            today = datetime.now()
            yestoday = datetime.now() - timedelta(days=1)
            last_month = datetime.now() - relativedelta(months=1)
            cache = {}
            #首先将今天和昨天的发言次数保存
            today_str, yestoday_str = f'{today.year}_{today.month}_{today.day}', f'{yestoday.year}_{yestoday.month}_{yestoday.day}'
            cache[today_str] = all_users[f'{user_id}']['number_speeches'][f'{group_id}'].get(today_str,0)
            cache[yestoday_str] = all_users[f'{user_id}']['number_speeches'][f'{group_id}'].get(yestoday_str,0)
            #然后保存本月和上个月的
            month_count, last_month_count = 0, 0
            for item in all_users[f'{user_id}']['number_speeches'][f'{group_id}']:
                if item in [today_str,yestoday_str]:continue
                if f'{today.year}_{today.month}_' in item: month_count += int(all_users[f'{user_id}']['number_speeches'][f'{group_id}'][item])
                if f'{last_month.year}_{last_month.month}_' in item: last_month_count += int(all_users[f'{user_id}']['number_speeches'][f'{group_id}'][item])
            cache[f'{today.year}_{today.month}'], cache[f'{last_month.year}_{last_month.month}'] = month_count, last_month_count
            #然后保存本年度和以往所有年度的
            for i in range(today.year):
                # if i == 0: continue
                # if f'{int(today.year) - i}' not in all_users[f'{user_id}']['number_speeches'][f'{group_id}']:break
                if not any(f'{int(today.year) - i}' in f'{key}' for key in all_users[f'{user_id}']['number_speeches'][f'{group_id}']):break
                year_count = 0
                for item in all_users[f'{user_id}']['number_speeches'][f'{group_id}']:
                    if f'{today.year - i}' == item:
                        year_count = int(all_users[f'{user_id}']['number_speeches'][f'{group_id}'][item])
                        if i != 0: break
                    if f'{today.year - i}_' in item:
                        if i == 0 and (f'{today.year}_{today.month}' in item or f'{today.year}_{today.month - 1}' in item): continue
                        year_count += int(all_users[f'{user_id}']['number_speeches'][f'{group_id}'][item])
                cache[f'{today.year - i}'] = year_count
            user_cache['number_speeches'][group_id] = cache
        user_cache_multiple[f'{user_id}'] = user_cache
        #pprint.pprint(user_cache)
        #return
    await db.write_multiple_users(user_cache_multiple, False)

    #await db.delete_user_field('1270858640','number_speeches.892088020')



if __name__ == '__main__':
    print('yes')
    asyncio.run(test())