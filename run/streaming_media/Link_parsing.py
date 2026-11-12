import asyncio
import gc
import re
import shutil
import os
import pprint
import json as json_handle
from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Image, File, Video, Node, Text, Image, Music, Json, At
from run.streaming_media.service.Link_parsing.core.login_core import ini_login_Link_Prising
from run.streaming_media.service.Link_parsing.Link_parsing import download_video_link_prising
from run.streaming_media.service.Link_parsing.core.common import download_audio
from run.streaming_media.service.Link_parsing.core.manshuo_api import (
    download_manshuo_api_media,
    should_use_manshuo_api,
)
from run.streaming_media.service.Link_parsing.music_link_parsing import netease_music_link_parse
from run.streaming_media.service.Link_parsing import *
import traceback
from collections import defaultdict
from time import time
teamlist = defaultdict(lambda: {'data': None, 'expire_at': 0})
global Cachecleaner
Cachecleaner=False
linking_prising_list = {}

async def _recall_message_if_available(bot, send_result):
    """仅在消息发送接口返回有效 message_id 时撤回消息。"""
    if not isinstance(send_result, dict):
        return
    data = send_result.get('data')
    if not isinstance(data, dict):
        return
    message_id = data.get('message_id')
    if message_id is None:
        return
    try:
        await bot.recall(message_id)
    except Exception as e:
        bot.logger.warning(f'撤回链接解析提示消息失败: {e}')


async def _convert_audio_to_mp3(audio_path):
    mp3_path = os.path.splitext(audio_path)[0] + '.mp3'
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', '-nostdin', '-y', '-i', audio_path,
        '-vn', '-codec:a', 'libmp3lame', '-q:a', '2', mp3_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        error = stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f'ffmpeg 转换 MP3 失败: {error[-1000:]}')
    if not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) <= 0:
        raise FileNotFoundError(f'ffmpeg 未生成有效 MP3 文件: {mp3_path!r}')
    return mp3_path


async def call_bili_download_video(bot, event, config,type_download='video'):
    if event.group_id in teamlist:
        json_linking = teamlist[event.group_id]['data']
        teamlist.pop(event.group_id)
        recall_result = teamlist.pop(f'{event.group_id}_recall', None)
        await _recall_message_if_available(bot, recall_result)
    else:
        return {"status": "当前群聊没有已缓存的解析结果。"}
    audio_url = json_linking.get('audio_url')
    if should_use_manshuo_api(json_linking.get('url')):
        try:
            if type_download == 'video':
                video_url = json_linking.get('video_url')
                if not video_url:
                    await bot.send(event, '下载失败\n视频下载地址为空')
                    return
                video_path = await download_manshuo_api_media(
                    video_url,
                    'video',
                    filepath='data/pictures/cache/',
                    soft_type=json_linking.get('soft_type'),
                    audio_url=audio_url,
                    use_proxy=True,
                )
                size_in_mb = os.path.getsize(video_path) / (1024 * 1024)
                if size_in_mb < 25:
                    await bot.send(event, Video(file=video_path))
                elif size_in_mb < 80:
                    recall_id = await bot.send(event, '视频有些大，请耐心等待喵~~')
                    await bot.send(event, Video(file=video_path))
                    await _recall_message_if_available(bot, recall_id)
                elif size_in_mb < 300:
                    recall_id = await bot.send(event, '好大的视频，小的将发送至群文件喵~')
                    await bot.send(event, File(file=video_path))
                    await _recall_message_if_available(bot, recall_id)
                else:
                    await bot.send(event, '太大了，罢工！')
            elif type_download == 'audio':
                if not isinstance(audio_url, str) or not audio_url.strip():
                    await bot.send(event, '下载失败\n音频下载地址为空')
                    return
                audio_path = await download_manshuo_api_media(
                    audio_url,
                    'audio',
                    filepath='data/pictures/cache/',
                    soft_type=json_linking.get('soft_type'),
                    use_proxy=True,
                )
                await bot.send(event, File(file=audio_path))
            elif type_download == 'img':
                image_urls = json_linking.get('pic_url_list') or []
                if not image_urls:
                    await bot.send(event, '下载失败\n图片下载地址为空')
                    return
                image_paths = []
                for image_url in image_urls:
                    image_paths.append(await download_manshuo_api_media(
                        image_url,
                        'image',
                        filepath='data/pictures/cache/',
                        soft_type=json_linking.get('soft_type'),
                        use_proxy=True,
                    ))
                send_context = '小的找的图片如下，请君过目喵'
                if len(image_paths) == 1:
                    await bot.send(event, [f'{send_context}\n', Image(file=image_paths[0])])
                else:
                    node_list = [Node(content=[Text(send_context)])]
                    node_list.extend(Node(content=[Image(file=path)]) for path in image_paths)
                    await bot.send(event, node_list)
            return
        except Exception as e:
            traceback.print_exc()
            await bot.send(event, f'下载失败\n {e}')
            return

    if type_download == 'audio' and (not isinstance(audio_url, str) or not audio_url.strip()):
        await bot.send(event, '下载失败\n音频下载地址为空')
        return
    if json_linking['soft_type'] not in {'bilibili', 'dy', 'wb', 'xhs', 'x'}:
        if type_download == 'audio':
            await bot.send(event, '该类型音频暂未提供下载支持，敬请期待')
        else:
            await bot.send(event, '该类型视频图片暂未提供下载支持，敬请期待')
        return
    if json_linking['soft_type'] in {'x'}: proxy = config.common_config.basic_config["proxy"]["http_proxy"]
    else: proxy = None

    if config is not None and bot and config.common_config.basic_config["master"]["id"] == 1270858640:
        from run.manshuo_test.core import bot_http
        await bot_http.set_msg_emoji_like(event, 282)

    if type_download == 'video':
        if not json_linking.get('video_url'):
            await bot.send(event, '下载失败\n视频下载地址为空')
            return
        try:
            video_json = await download_video_link_prising(json_linking, filepath='data/pictures/cache/', proxy=proxy)
            if 'video' in video_json['type']:
                recall_id = None
                if video_json['type'] == 'video_bigger':
                    recall_id = await bot.send(event, f'视频有些大，请耐心等待喵~~')
                await bot.send(event, Video(file=video_json['video_path']))
                if video_json['type'] == 'video_bigger':
                    await _recall_message_if_available(bot, recall_id)
            elif video_json['type'] == 'file':
                recall_id = await bot.send(event, f'好大的视频，小的将发送至群文件喵~')
                await bot.send(event, File(file=video_json['video_path']))
                await _recall_message_if_available(bot, recall_id)
            elif video_json['type'] == 'too_big':
                await bot.send(event, f'太大了，罢工！')
        except Exception as e:
            traceback.print_exc()
            await bot.send(event, f'下载失败\n {e}')
    elif type_download == 'audio':
        try:
            audio_headers = None
            if json_linking.get('soft_type') == 'bilibili':
                # B站音频 CDN 与现有 download_b_file 使用相同的请求头。
                audio_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/100.0.4896.127 Safari/537.36',
                    'referer': 'https://www.bilibili.com',
                }
            audio_path = await download_audio(
                audio_url,
                path='data/pictures/cache/',
                proxy=proxy,
                headers=audio_headers,
            )
            if not audio_path or not os.path.isfile(audio_path) or os.path.getsize(audio_path) <= 0:
                raise FileNotFoundError(f'音频下载未生成有效文件: {audio_path!r}')
            send_audio_path = audio_path
            if json_linking.get('soft_type') == 'bilibili' and os.path.splitext(audio_path)[1].lower() == '.m4s':
                send_audio_path = await _convert_audio_to_mp3(audio_path)
            await bot.send(event, File(file=send_audio_path))
        except Exception as e:
            traceback.print_exc()
            await bot.send(event, f'下载失败\n {e}')
    elif type_download == 'img' and json_linking['pic_url_list'] != []:
        send_context = "小的找的图片如下，请君过目喵"
        if len(json_linking['pic_url_list']) == 1:
            await bot.send(event, [f'{send_context}\n', Image(file=await download_img(json_linking['pic_url_list'][0],'data/pictures/cache/', proxy=proxy))])
        else:
            node_list = [Node(content=[Text(send_context)])]
            for pic_url in json_linking['pic_url_list']:
                node_list.append(Node(content=[Image(file=await download_img(pic_url,'data/pictures/cache/', proxy=proxy))]))
            await bot.send(event, node_list)


def main(bot, config):
    botname = config.common_config.basic_config["bot"]
    bili_login_check, douyin_login_check, xhs_login_check = ini_login_Link_Prising(type=0)
    if bili_login_check and douyin_login_check and xhs_login_check:
        bot.logger.info('✅ 链接解析功能已上线！')
    else:
        if not bili_login_check:
            #bot.logger.warning('⚠️ B站session未能成功获取')
            pass
        else:
            bot.logger.warning('✅ B站session成功获取')
        if not douyin_login_check:
            bot.logger.warning('⚠️ 未能获取到设置抖音的ck')
        else:
            bot.logger.info('✅ 抖音的ck成功获取！')
        if not xhs_login_check:
            bot.logger.warning('⚠️ 未能获取到设置小红书的ck')
        else:
            bot.logger.info('✅ 小红书的ck成功获取！')

    node_path = shutil.which("node")  # 自动查找 Node.js 可执行文件路径
    if not node_path:
        bot.logger.warning("⚠️ Node.js 未安装或未正确添加到系统 PATH 中!")
    try:
        import execjs
        if "Node.js" in execjs.get().name:
            bot.logger.info('✅ 系统已正确读取到node.js')
    except:
        pass

    proxy = config.common_config.basic_config["proxy"]["http_proxy"]


    @bot.on(GroupMessageEvent)
    async def Link_Prising_search(event: GroupMessageEvent):
        global Cachecleaner,linking_prising_list
        if event.sender.user_id in linking_prising_list:
            return
        
        type_link = None
        if not Cachecleaner:
            asyncio.create_task(cleanup_teamlist(bot))
            
        if event.message_chain.has(Json):
            url=event.message_chain.get(Json)[0].data
            event_context = json_handle.loads(url)
            if 'meta' in event_context:
                try:
                    url = "QQ小程序" + event_context['meta']['detail_1']['qqdocurl']
                    if config.streaming_media.config["bili_dynamic"]["is_QQ_chek"] is not True:
                        type_link = 'QQ_Check'
                except:
                    pass

        elif event.message_chain.has(Text):
            url=""
            for i in event.message_chain.get(Text):
                url+=i.text
        else:
            return
        if url.strip().startswith(('下载视频', '下载图片', '下载音频', '/bili ')): return
        link_prising_json = await link_prising(url, filepath='data/pictures/cache/', proxy=proxy, type=type_link,
                                               absorb_color=config.streaming_media.config["bili_dynamic"]["is_absorb_color"],
                                               up_info_get=config.streaming_media.config["bili_dynamic"]["is_fetch_up_info"],
                                               credential_bili=config.streaming_media.config["bili_dynamic"]["is_download_high_quality"],
                                               master_id=config.common_config.basic_config["master"]["id"])
        send_context = f'{botname}识别结果：'
        if link_prising_json['status']:
            bot.logger.info('链接解析成功，开始推送~~')
            has_video_url = isinstance(link_prising_json.get('video_url'), str) and bool(link_prising_json['video_url'].strip())
            has_audio_url = isinstance(link_prising_json.get('audio_url'), str) and bool(link_prising_json['audio_url'].strip())
            if has_video_url or has_audio_url:
                teamlist[event.group_id] = {'data': link_prising_json, 'expire_at': time() + 600}
                #send_context = f'可“下载视频”喵'
                if has_video_url:
                    send_context = config.streaming_media.config["bili_dynamic"]["linking_prising_video_text"]
                elif has_audio_url:
                    send_context = '可“下载音频”喵'
                if "QQ小程序" in url and config.streaming_media.config["bili_dynamic"]["is_QQ_chek"] is not True:
                    teamlist[f'{event.group_id}_recall'] = await bot.send(event, [f'{send_context}'])
                    return
            elif link_prising_json['pic_url_list'] != []:
                #send_context = f'{botname}发现了图片哟，发送‘下载图片’来推送喵'
                send_context = config.streaming_media.config["bili_dynamic"]["linking_prising_picture_text"]
                teamlist[event.group_id] = {'data': link_prising_json, 'expire_at': time() + 300}
            send_message = [f'{send_context}\n']
            if link_prising_json.get('pic_path'):
                send_message.append(Image(file=link_prising_json['pic_path']))
            teamlist[f'{event.group_id}_recall'] = await bot.send(event, send_message)
        else:
            if link_prising_json['reason']:
                #print(link_prising_json)
                bot.logger.error(str('bili_link_error ') + link_prising_json['reason'])

    #这里专门用来下载图片、视频或音频
    @bot.on(GroupMessageEvent)
    async def Linking_prising_download(event):
        if event.get("reply"): return
        if event.group_id in teamlist and event.message_chain.has(Text):
            if event.message_chain.has(At):
                context = "".join(i.text for i in event.message_chain.get(Text))
            else:
                context = event.pure_text
            if context.strip() in ["下载视频"]:
                bot.logger.info('视频下载ing')
                await call_bili_download_video(bot, event, config)
            elif context.strip() in ["下载图片"]:
                bot.logger.info('图片下载ing')
                await call_bili_download_video(bot, event, config,'img')
            elif context.strip() in ["下载音频"]:
                bot.logger.info('音频下载ing')
                await call_bili_download_video(bot, event, config, 'audio')

    #写一个方法专门用来引用开始下载、
    #这里专门用来下载图片、视频或音频
    @bot.on(GroupMessageEvent)
    async def Linking_prising_download_without_send(event):
        if event.get("reply") and event.get("text"):
            context = event.get("text")[0].strip()
            if not context.startswith(('下载视频', '下载图片', '下载音频')): return
            event_obj = await bot.get_msg(int(event.get("reply")[0]["id"]))
            #if event_obj.message[0]['type'] == 'forward': return
            if event_obj.message_chain.has(Json):
                url = event_obj.message_chain.get(Json)[0].data
            elif event_obj.message_chain.has(Text):
                url = "".join(i.text for i in event_obj.message_chain.get(Text))
            else: return
        elif not event.get("reply") and event.get("text"):
            context = event.get("text")[0].strip()
            if not context.startswith(('下载视频', '下载图片', '下载音频')): return
            if 'http' in context: url = context
            else: return
        else: return
        info = await link_prising(url, type='no_draw',credential_bili=config.streaming_media.config["bili_dynamic"]["is_download_high_quality"],
                                  master_id=config.common_config.basic_config["master"]["id"])
        if info['status']:
            teamlist[event.group_id] = {'data': info, 'expire_at': time() + 600}
            if context.startswith('下载视频'):
                bot.logger.info('视频下载ing')
                await call_bili_download_video(bot, event, config)
            elif context.startswith('下载图片'):
                bot.logger.info('图片下载ing')
                await call_bili_download_video(bot, event, config, 'img')
            elif context.startswith('下载音频'):
                bot.logger.info('音频下载ing')
                await call_bili_download_video(bot, event, config, 'audio')



    @bot.on(GroupMessageEvent)
    async def img_collect_download(event):
        context, userid, nickname, group_id = event.pure_text.strip(), event.sender.user_id, event.sender.nickname, event.group_id
        global linking_prising_list
        if context in ['开始链接解析','开启链接解析'] or userid in linking_prising_list:
            if userid not in linking_prising_list:
                await bot.send(event, '请发送需要解析的链接，完成请发送 “end” 喵')
                linking_prising_list[userid] = []
                return
            if context == 'end':
                await bot.send(event, '开始解析ing，请耐心等待喵')
                prising_list = []
                for url in linking_prising_list[userid]:
                    prising_list.append(await link_prising(url, type='no_draw',master_id=config.common_config.basic_config["master"]["id"]))
                await bot.send(event, '开始下载图片ing，请耐心等待喵')
                node_list = [Node(content=[Text("解析结果如下，请君过目喵")])]
                for prising_result in prising_list:
                    #pprint.pprint(prising_result)
                    if prising_result['status']:
                        msg = f"链接：{prising_result['url']}\n状态：解析成功喵"
                        node_list.append(Node(content=[Text(msg)]))
                        for img_url in prising_result['pic_url_list']:
                            try:
                                node_list.append(Node(content=[Image(file=await download_img(img_url,'data/pictures/cache/'))]))
                            except:
                                node_list.append(Node(content=[Text('此图片下载失败喵')]))
                    else:
                        msg = f"链接：{prising_result['url']}\n状态：解析失败了喵QAQ"
                        node_list.append(Node(content=[Text(msg)]))
                await bot.send(event, node_list)
                linking_prising_list.pop(userid)
            else:
                linking_prising_list[userid].append(context)

async def cleanup_teamlist(bot):
    global Cachecleaner
    if Cachecleaner:
        #bot.logger.info("不再重复启动清理程序。")
        return
    while True:
        bot.logger.info('清理链接解析过期缓存')
        Cachecleaner=True
        current_time = time()
        expired_keys = []
        for k, v in teamlist.items():
            if isinstance(k,str) and k.endswith('_recall'):
                continue
            if isinstance(v, dict) and 'expire_at' in v:
                if v['expire_at'] < current_time:
                    expired_keys.append(k)
            else:
                expired_keys.append(k)
                bot.logger.warning(f"teamlist[{k}] 格式错误，强制清理: {type(v)}")

        for key in expired_keys:
            # 同时清理对应的 _recall 键（如果存在）
            recall_key = f'{key}_recall'
            teamlist.pop(key, None)
            teamlist.pop(recall_key, None)
            bot.logger.debug(f"清理 teamlist 键: {key} 和 {recall_key}")

        bot.logger.debug(f"teamlist 当前键数: {len(teamlist)}")
        collected = gc.collect()
        bot.logger.info_func(f"回收了 {collected} 个对象")
        await asyncio.sleep(1000)
