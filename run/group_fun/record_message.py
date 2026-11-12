import pprint
import random
import os
from developTools.message.message_components import Record, Node, Text, Image, At
from developTools.event.events import GroupMessageEvent
import re
from framework_common.manshuo_draw import *
from datetime import datetime, timedelta
# 构建分隔符正则表达式 
separators_pattern = '|'.join(re.escape(sep) for sep in ["|", "｜"])
message_list_global = {}        #用于删除怪话使用
message_group_global = {}       #用于避免短期内多次发送同一个怪话
_MAX_RECORD_CACHE = 1000

def _record_cache_set(msg_id, img_path):
    global message_list_global
    if len(message_list_global) >= _MAX_RECORD_CACHE:
        drop_keys = list(message_list_global.keys())[:200]
        for k in drop_keys:
            message_list_global.pop(k, None)
    message_list_global[msg_id] = img_path




async def parse_message_segments(event,bot):
    """解析消息段，将图片正确分配到对应的消息段"""
    pure_text = ''
    # 处理图片并重新整合消息
    for obj in event.message_chain:
        if obj.comp_type == 'text':
            pure_text += f"{obj.text}"
        elif obj.comp_type == 'image':
            if pure_text == '':
                pure_text += f"[title][emoji]{obj.url}[/emoji][/title]"
            else:
                pure_text += f"\n[title][emoji]{obj.url}[/emoji][/title]"
        elif obj.comp_type == 'at':
            try:
                userid, target_group = event.sender.user_id, event.group_id
                target_name = (await bot.get_group_member_info(target_group, obj.qq))['data']['nickname']
            except:
                target_name = '未知用户'
            pure_text += f"@{target_name}"

    return [{'text':pure_text}]

def main(bot, config):

    @bot.on(GroupMessageEvent)
    async def today_message(event: GroupMessageEvent):
        context, userid, nickname, group_id, is_at = event.pure_text, str(event.sender.user_id), event.sender.nickname, int(event.group_id),False
        if event.message_chain.has(At) and event.message_chain.has(Text):
            is_at = True
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.strip() not in ['今日怪话','今日语录','群友怪话','群友语录']:  return
        global message_group_global
        message_group_global.setdefault(group_id,[])
        img_path_save = f'data/pictures/record_message/{group_id}'
        files = [f for f in os.listdir(img_path_save) if os.path.isfile(os.path.join(img_path_save, f))]
        if not files:
            await bot.send(event, '本群好像还没有群友的怪话呢\n发送“消息记录”来引用记录群友的怪话吧 ！')
            return
        if is_at:
            files_check = []
            for file in files:
                if file.startswith(f'{userid}_'):files_check.append(file)
            if files_check: files = files_check
            else:
                await bot.send(event, '这位群友还没有说过怪话呢\n发送“消息记录”来引用记录群友的怪话吧 ！')
                return
        #设定缓存机制以免短时间多次抽到同一个人
        files_check = files.copy()
        for item in message_group_global[group_id]:
            if item in files: files.remove(item)
        if files == []:
            if is_at:
                for item_check in files_check:
                    if item_check in message_group_global[group_id]: message_group_global[group_id].remove(item_check)
            else: message_group_global[group_id] = []
            files = files_check

        random_file = random.choice(files)
        message_group_global[group_id].append(random_file)
        message_id_info = await bot.send(event, Image(file=f'{img_path_save}/{random_file}'))
        if message_id_info is not None:
            _record_cache_set(message_id_info['data']['message_id'], f'{img_path_save}/{random_file}')

    @bot.on(GroupMessageEvent)
    async def record_message_delete(event: GroupMessageEvent):
        global message_list_global
        if event.get("reply") and event.get("text"):
            context = event.get("text")[0].strip().replace(' ','')
            if context not in ['删除','清理',"删掉"]: return
        else:
            return
        message_id = int(event.get("reply")[0]["id"])
        if message_id not in message_list_global:
            return
        img_path = message_list_global[message_id]
        message_list_global.pop(message_id)
        if os.path.isfile(img_path):
            os.remove(img_path)
        await bot.recall(message_id)
        await bot.send(event, '该消息记录已被清理喵')

    @bot.on(GroupMessageEvent)
    async def record_message_rank(event: GroupMessageEvent):
        context, userid, nickname, group_id, is_at = event.pure_text, str(event.sender.user_id), event.sender.nickname, int(event.group_id), False
        if context.strip() not in ['语录排行','怪话排行']: return
        bot.logger.info("开始怪话排行查询")
        img_path_save = f'data/pictures/record_message/{group_id}'
        files = [f for f in os.listdir(img_path_save) if os.path.isfile(os.path.join(img_path_save, f))]
        if not files:
            await bot.send(event, '本群好像还没有群友的怪话呢\n发送“消息记录”来引用记录群友的怪话吧 ！')
            return
        info = {}
        for item in files:
            if '_' in item:
                user_id = item.split("_", 1)[0]
                info.setdefault(user_id,0)
                info[user_id] += 1
        if info == {}:
            await bot.send(event, '本群好像还没有群友的怪话呢\n发送“消息记录”来引用记录群友的怪话吧 ！')
            return
        total_msg = 0
        for item in info: total_msg += info[item]
        info = dict(sorted(info.items(), key=lambda item: item[1], reverse=True)[:10])
        if event:
            self_id = event.self_id
            self_name = (await bot.get_group_member_info(event.group_id, self_id))['data']['nickname']
        else:
            self_id, self_name = '2319804644', '枫与岚'

        draw_list = [
            {'type': 'avatar', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={self_id}&s=640"],
             'upshift_extra': 15,
             'content': [f"[name]{self_name} 一直在看着你哦～[/name]\n[time]入典。入典？入典！[/time]"]},
            f"[title]本群怪话一共 {total_msg} 条喵[/title]",
            {'type': 'math', 'subtype': 'bar_chart',
             'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640" for user_id in info],
             'number_per_row': 1, 'chart_height': 75, 'upshift_label': -5,
             'is_stroke_label': True, 'font_label_size': 29, 'font_label_color': (255, 255, 255),
             'label_color': (80, 150, 240, 255),
             'content': list(info.values()), 'label': [f"{count}句" for count in info.values()]},
        ]
        bot.logger.info("开始绘图")
        img_path = await manshuo_draw(draw_list)
        if bot and event:
            recall_id = await bot.send(event, [f"{self_name} 一直在看着你哦～", Image(file=img_path)])


    @bot.on(GroupMessageEvent)
    async def record_message_reply(event: GroupMessageEvent):
        if event.get("reply") and event.get("text"):
            context = event.get("text")[0].strip().replace(' ','')
            if context not in ['记录消息','消息记录','入典']: return
        else:
            return
        bot.logger.info("开始进行消息记录")
        #print(int(event.get("reply")[0]["id"]))
        event_obj = await bot.get_msg(int(event.get("reply")[0]["id"]))
        if event_obj.message[0]['type'] == 'forward': return
        check = await parse_message_segments(event_obj,bot)
        #print(check)
        context = check[0]["text"]
        parts = re.split(r'\[title\].*?\[/title\]', context)
        context_len = len("".join(parts))
        img_width = 700
        userid, target_group = event_obj.sender.user_id, event.group_id
        try:
            target_name = (await bot.get_group_member_info(target_group, userid))['data']['nickname']
        except:
            target_name = '未知用户'
        check_name = f'                   --By {target_name}'
        #print(context_len)
        if 200 > context_len > 40:
            img_width = 1100
            check_name = f'                    {check_name}'
        elif 400 > context_len >= 200:
            img_width = 1500
            check_name = f'                                                  {check_name}'
        elif context_len >= 400:
            img_width = 2000
            check_name = f'                                                                                {check_name}'
        total_line_breaks = context.count('\n') + context.count('\r') + 1 + 1 * context.count('[title]')
        #print(total_line_breaks,total_line_breaks * 43,img_width / 3 - 40,context_len)
        if total_line_breaks * 43 > img_width / 3 - 40: img_width = total_line_breaks * 43 * 3 + 40
        if len(target_name) > 4:
            check_name = check_name[len(target_name)+3:]

        img_path_save = f'data/pictures/record_message/{target_group}'
        img_number = 0
        if os.path.exists(img_path_save):
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
            file_list = os.listdir(img_path_save)
            for filename in file_list:
                if filename.startswith(f'{userid}'):
                    ext = os.path.splitext(filename)[1].lower()  # 获取扩展名并转小写
                    if ext in image_extensions:
                        img_number += 1

            if f'{userid}_{img_number}.png' in file_list:
                for i in range(len(file_list)):
                    if f'{userid}_{img_number}.png' in file_list: img_number += 1
                    else:break
        img_name_save = f'{userid}_{img_number}.png'
        # 保证存储文件夹存在
        if not os.path.exists(img_path_save):
            os.makedirs(img_path_save)
        draw_list = [
        {'type': 'basic_set', 'img_width': img_width, 'font_title_size':125,'img_path_save':img_path_save, 'img_name_save': img_name_save},
        {'type': 'img', 'subtype': 'common_with_des_right','img': [f"https://q1.qlogo.cn/g?b=qq&nk={userid}&s=640"],
         'content': [f'{context}\n{check_name}']},
        ]
        img_path = await manshuo_draw(draw_list)
        message_id_info = await bot.send(event, Image(file=img_path))
        if message_id_info is not None:
            _record_cache_set(message_id_info['data']['message_id'], f'{img_path}')



    @bot.on(GroupMessageEvent)
    async def record_message_reply_forword(event: GroupMessageEvent):
        if event.get("reply") and event.get("text"):
            context = event.get("text")[0].strip().replace(' ','')
            if context not in ['记录消息','消息记录','入典']: return
        else:
            return
        event_obj = await bot.get_msg(int(event.get("reply")[0]["id"]))
        if event_obj is None or event_obj.message is None: return
        if event_obj.message[0]['type'] != 'forward': return
        bot.logger.info("开始进行消息记录")
        #pprint.pprint(event_obj)
        message_check = event_obj.message[0]['data'].get('content')
        if message_check is None:
            await bot.send(event, '暂不支持此命令，若需要请更换至napcat喵')
            return
        #pprint.pprint(message_check)
        #pprint.pprint(event_obj.processed_message)
        forward_list = []
        for item in message_check:
            time = datetime.utcfromtimestamp(item['time']) + timedelta(hours=8)
            per_item_check, per_result = item['message'], ''
            for per_msg in per_item_check:
                if per_msg['type'] == 'text':
                    per_result += per_msg['data']['text']
                elif per_msg['type'] == 'image':
                    if per_result == '': per_result += f"[title][emoji]{per_msg['data']['url']}[/emoji][/title]"
                    else: per_result += f"\n[title][emoji]{per_msg['data']['url']}[/emoji][/title]"
                elif per_msg['type'] == 'forward':
                    per_result += '这里是聊天记录喵'
            user_id = event.self_id
            if 'user_id' in item and int(item['user_id']) != 1094950020: user_id = item['user_id']
            else:
                try:
                    message_id = item['message_id']
                    event_obj_user = await bot.get_msg(int(message_id))
                    #pprint.pprint(event_obj_user)
                except:pass
            #print(user_id)
            per_message = {'group_id': item['group_id'], 'user_id':user_id, 'nickname':item['sender']['nickname'], 'avatar_img':f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640",
                           'time':time.strftime('%Y-%m-%d %H:%M:%S'), 'content':per_result}
            forward_list.append(per_message)
        #pprint.pprint(forward_list)

        userid, target_group = event_obj.sender.user_id, event.group_id
        img_path_save = f'data/pictures/record_message/{target_group}'
        img_number = 0
        if os.path.exists(img_path_save):
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
            file_list = os.listdir(img_path_save)
            for filename in file_list:
                if filename.startswith(f'{userid}'):
                    ext = os.path.splitext(filename)[1].lower()  # 获取扩展名并转小写
                    if ext in image_extensions:
                        img_number += 1
            if f'{userid}_{img_number}' in file_list:
                for i in range(len(file_list)):
                    if f'{userid}_{img_number}' in file_list: img_number += 1
                    else:break
        img_name_save = f'{userid}_{img_number}.png'
        # 保证存储文件夹存在
        if not os.path.exists(img_path_save):
            os.makedirs(img_path_save)
        draw_list, img_width, total_width, times_width = [], 700, 0, 0
        for item in forward_list:
            parts = re.split(r'\[title\].*?\[/title\]', item['content'])
            total_width += len("".join(parts))
            times_width += 1
            draw_list.append(
                {'type': 'avatar', 'img': [item['avatar_img']],'content': [f"[name]{item['nickname']}[/name]   [time]{item['time']}[/time]"],'padding_up_bottom':8,'padding_up_font':10,'avatar_size':50,'font_name_size':28})
            draw_list.append(f"   {item['content']}")
        if 200 > total_width/times_width > 40: img_width = 1100
        elif 400 > total_width/times_width >= 200: img_width = 1500
        elif total_width/times_width >= 400: img_width = 2000
        #print(f'final img width: {img_width}')；
        #pprint.pprint(draw_list)
        draw_list.append({'type': 'basic_set', 'img_width': img_width, 'font_title_size':125,'img_path_save':img_path_save, 'img_name_save': img_name_save, 'padding_up_layer':10})
        img_path = await manshuo_draw(draw_list)
        message_id_info = await bot.send(event, Image(file=img_path))
        if message_id_info is not None:
            _record_cache_set(message_id_info['data']['message_id'], f'{img_path}')



