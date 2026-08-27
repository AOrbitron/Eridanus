import sys
import asyncio
import copy
import re
from bilibili_api.exceptions import ResponseCodeException
from datetime import datetime
import traceback
from developTools.utils.logger import get_logger
import pprint
from run.streaming_media.service.Link_parsing.core import *
import os

try:
    from bilibili_api import select_client
    select_client("httpx")
except ImportError:
    #旧版本兼容问题，整合包更新后删除此部分代码
    pass
logger=get_logger("Link_parsing")
linking_cache = {}
import time
from run.streaming_media.service.Link_parsing.core.common import json_init
from bilibili_api import Credential, dynamic, user
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase
db=asyncio.run(AsyncSQLiteDatabase.get_instance())
credential_bili_global = None

async def link_prising(url,filepath=None,proxy=None,type=None,credential_bili=None,re_prising=False,absorb_color=False,up_info_get=False):
    json_check = copy.deepcopy(json_init)
    link_prising_json=None
    try:
        url_list = (re.findall(r"https?:[^\s\]\)]+", url))
        for url_check in url_list:
            url=url_check
            if 'b23' in url_check: break
        #print(url)
    except Exception as e:
        json_check['status'] = False
        return json_check
    #print(f'json_init:{json_init}\njson_check:{json_check}\nlink_prising_json:{link_prising_json}\n\n')
    #为链接解析添加缓存
    url = str(url)
    global linking_cache
    #pprint.pprint(linking_cache)

    if re_prising is True and url in linking_cache:
        linking_cache.pop(url)
    if url in linking_cache:
        #代表有缓存，开始判断返回
        try:
            if type != 'QQ_Check' and os.path.exists(linking_cache[url]['path']):
                return linking_cache[url]['info']
        except:pass
        if type == 'QQ_Check':
            return linking_cache[url]['info']
        linking_cache.pop(url)
    #是否从数据库获取B站凭证并用于解析,定义一个全局变量，不要重复从数据库读取

    try:
        match url:
            case url if 'bili' in url or 'b23' in url:
                logger.info(f"解析bilibili链接:{url}")
                global credential_bili_global
                if credential_bili is True:
                    if credential_bili_global is None:
                        user_info = await db.read_user('bili_dynamic')
                        if 'info' in user_info and 'cookies' in user_info['info']:
                            data_info = user_info['info']
                            credential_bili = Credential(sessdata=data_info['cookies']['sessdata'],
                                                         bili_jct=data_info['cookies']['bili_jct'],
                                                         buvid3=data_info['cookies']['buvid3'],
                                                         dedeuserid=data_info['cookies']['dedeuserid'], )
                            credential_bili_global = credential_bili
                        else:
                            credential_bili = None
                    else:
                        credential_bili = credential_bili_global
                link_prising_json = await bilibili(url, filepath=filepath,type=type,credential_bili=credential_bili,absorb_color=absorb_color,up_info_get=up_info_get)
            case url if 'douyin' in url:
                logger.info(f"解析抖音链接:{url}")
                link_prising_json = await dy(url, filepath=filepath,type_check=type)
            case url if 'weibo' in url:
                logger.info(f"解析微博链接:{url}")
                link_prising_json = await wb(url, filepath=filepath,type_check=type)
            case url if 'xhslink' in url or 'xiaohongshu' in url:
                logger.info(f"解析小红书链接:{url}")
                link_prising_json = await xiaohongshu(url, filepath=filepath,type_check=type)
            case url if 'x.com' in url:
                logger.info(f"解析x链接:{url}")
                link_prising_json = await twitter(url, filepath=filepath, proxy=proxy,type_check=type)
            case url if 'gal.manshuo.ink/archives/' in url or 'www.hikarinagi.com' in url :
                logger.info(f"解析Galgame链接:{url}")
                link_prising_json = await Galgame_manshuo(url, filepath=filepath)
            case url if 'www.mysqil.com' in url:
                #link_prising_json = await youxi_pil(url, filepath=filepath)
                pass
            case _:
                pass
        if link_prising_json is not None and link_prising_json['status'] is True and 'pic_path' in link_prising_json:
            linking_cache[url] = {'info':copy.deepcopy(link_prising_json), 'time':time.time(), 'path':link_prising_json['pic_path']}
    except ResponseCodeException as e:
        print(f"B站解析接口返回错误代码: {e.code}")
        json_check['status'] = False
        json_check['reason'] = str(e)
        json_check['code'] = e.code
        #traceback.print_exc()
        return json_check
    except Exception as e:
        json_check['status'] = False
        json_check['reason'] = str(e)
        traceback.print_exc()
        return json_check
    # finally:
    #     if credential_bili is not None:
    #         del credential_bili
    if link_prising_json is not None:
        if type == 'dynamic_check':
            if '编辑于 ' in link_prising_json['time']:
                time_check=link_prising_json['time'].split("编辑于 ")[1].strip()
            else:
                time_check = link_prising_json['time']
            possible_formats = [
                "%Y年%m月%d日 %H:%M",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%d %H:%M",
                "%d-%m-%Y %H:%M",
                "%Y.%m.%d %H:%M",
                "%Y年%m月%d日",
                "%Y/%m/%d",
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%Y.%m.%d",
            ]

            for fmt in possible_formats:
                try:
                    # 尝试解析日期字符串
                    check_time=datetime.strptime(time_check, fmt).strftime("%Y-%m-%d")
                    #print(f"check_time:{check_time}\nnow:{datetime.now().date()}")
                    if str(check_time) != str(datetime.now().date()):
                        link_prising_json['status'] = False
                        link_prising_json['check_time']=check_time
                        #print(f"时间不匹配，拒绝发送 {link_prising_json['time']}\ncheck_time:{check_time}\ndatetime:{datetime.now().date()}")
                    break
                except ValueError:
                    # 如果解析失败，继续尝试下一个格式
                    #traceback.print_exc()
                    continue

        logger.info(f"解析完成，返回识别结果")
        return link_prising_json
    else:
        json_check['status'] = False
        return json_check



async def test(url_check):
    from run.streaming_media.service.Link_parsing.core.bili import download_b
    link_info = await link_prising(url_check,absorb_color=True,up_info_get=True,credential_bili=True)
    pprint.pprint(link_info)

    # video_path = await download_b(link_info['video_url'], link_info['audio_url'], int(time.time()), filepath='data/pictures/cache/')
    # pprint.pprint(video_path)

#draw_video_thumbnail()
if __name__ == "__main__":#测试用，不用管

    url='https://gal.manshuo.ink/archives/297/'
    url = 'https://www.hikarinagi.com/p/21338'
    url='https://live.bilibili.com/26178650'
    url='https://gal.manshuo.ink/archives/451/'
    url='https://t.bilibili.com/1056778966646390806'
    #url='0.74 复制打开抖音，看看【齐木花卷的作品】好棒的版型.. # 穿搭 # dance # fy... https://v.douyin.com/OO5Ee2TV0a0/ 12/25 dnQ:/ o@q.Eu '
    url='https://www.xiaohongshu.com/discovery/item/67e0146c000000000b016af1?source=webshare&xhsshare=pc_web&xsec_token=ABM5sWfqwfUeG8RzcI666DLkKic1rMvcV0DboQigwq3wY=&xsec_source=pc_share'
    url='http://xhslink.com/a/HoZpetY3jCUfb'
    url='【【绫地宁宁 / 手书预告】恋爱裁判】https://www.bilibili.com/video/BV1JBMVzVEZr?vd_source=5e640b2c90e55f7151f23234cae319ec'
    url='https://live.bilibili.com/1947172143'
    url='https://t.bilibili.com/1082791822623768624?share_source=pc_native'
    url = 'https://gal.manshuo.ink/archives/746/'
    url = 'https://weibo.com/6625787085/5245617985290482'
    url = 'https://x.com/hn_luotianyi712/status/2003787316100509941?s=46'
    url = 'https://x.com/h_ta6_h_h_ta6_h/status/2004134080229908552?s=46'
    url = 'https://www.bilibili.com/video/BV1mrjN6qE4C/?spm_id_from=333.1387.upload.video_card.click'
    url = 'https://b23.tv/3JR5bfD'
    url = 'https://t.bilibili.com/1217329482778542083?spm_id_from=333.1387.0.0'
    url = 'https://t.bilibili.com/1217764206464466978'
    url = 'https://www.bilibili.com/video/BV1vvjR6REyP'
    url = '【那你的梦呢 仪玄？-哔哩哔哩】 https://b23.tv/SFkYzoC'
    url = 'https://b23.tv/rtvclYR'
    #url = 'https://live.bilibili.com/9576151'
    #url = 'http://xhslink.cn/o/4DZvlOLnu8q'
    #url = 'https://v.douyin.com/cZUlzDmvtok/ 09/15 :7pm oQk:/ N@J.VY '

    #url = '】 https://b23.tv/N4yiTRP'
    #url = '【挽昼麻麻-哔哩哔哩】 https://b23.tv/IjyAnfu'
    # data_info = await data_init()
    # credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
    #                         buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    info = asyncio.run(test(url))
    # pprint.pprint(info)
    # if info['status'] and info['content']['type'] == 'dynamic':
    #     if info['content']['opus_type'] == 'DYNAMIC_TYPE_FORWARD' and info['content']['text'].strip().startswith(('恭喜@',)):
    #         print('已过滤')


