import httpx
import re
import copy
from .login_core import ini_login_Link_Prising
from .common import json_init,filepath_init,COMMON_HEADER,GLOBAL_NICKNAME,no_draw_type
from urllib.parse import urlparse
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from developTools.utils.logger import get_logger
logger=get_logger()
import json
from framework_common.manshuo_draw.manshuo_draw import manshuo_draw
from framework_common.utils.utils import download_img
from framework_common.utils.random_str import random_str
import aiofiles
from io import BytesIO
from PIL import Image as PilImage
import numpy as np
from sklearn.cluster import KMeans
import asyncio
import sys
import time
from bilibili_api import video, live, article
import colorsys
import pprint
from bilibili_api import dynamic
from bilibili_api import login_v2, sync, search, user
from bilibili_api.opus import Opus
from bilibili_api.video import VideoDownloadURLDataDetecter, VideoQuality
from .bili import bili_init,av_to_bv,download_b,info_search_bili
from .common import name_qq_list,card_url_list,add_append_img,download_video,get_file_size_mb,download_img
try:
    from bilibili_api import select_client
    select_client("httpx")
except ImportError:
    #旧版本兼容问题，整合包更新后删除此部分代码
    pass
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())



async def get_dominant_color(img_url,absorb_color=False, k=4, image_resize=(100, 100)):
    if absorb_color is False or img_url is None:
        return_json = {'back_rgb': (194, 228, 255), 'layer_rgba': (235, 239, 253),
                       'font_title_rgb': (0,0,0), 'font_des_rgb': (148,148,148),
                       'img_des_rgba':(255, 255, 255, 255),'avatar_shadow_color':(0, 0, 0),
                       'avatar_shadow_max_alpha':120, 'avatar_shadow_intensity': 1,
                       'label_color':(251,114,153,255)}
        return return_json
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(img_url)
        resp.raise_for_status()
    image = PilImage.open(BytesIO(resp.content))
    image = image.resize(image_resize).convert('RGB')
    img_np = np.array(image).reshape(-1, 3)
    kmeans = KMeans(n_clusters=k)
    kmeans.fit(img_np)

    counts = np.bincount(kmeans.labels_)
    cluster_centers = kmeans.cluster_centers_.astype(int)

    # # 计算加权分数 = 频数 * 饱和度，选最大
    # weights = []
    # for i in range(k):
    #     r, g, b = cluster_centers[i] / 255
    #     h, l, s = colorsys.rgb_to_hls(r, g, b)
    #     weight = counts[i] * s  # 饱和度加权频数
    #     weights.append(weight)
    #
    # dominant_idx = np.argmax(weights)
    # dominant_rgb = tuple(int(c) for c in cluster_centers[dominant_idx])

    BLACK = np.array([0, 0, 0])
    WHITE = np.array([255, 255, 255])

    weights = []
    for i in range(k):
        color = cluster_centers[i]
        r, g, b = color / 255
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        count = counts[i]

        # 计算RGB空间与黑白的欧氏距离
        dist_black = np.linalg.norm(color - BLACK) / np.linalg.norm(WHITE - BLACK)  # 归一化距离0~1
        dist_white = np.linalg.norm(color - WHITE) / np.linalg.norm(WHITE - BLACK)  # 归一化距离0~1
        closest_dist = min(dist_black, dist_white)  # 越小表示越接近黑或白
        # 计算衰减系数：距离越接近0，权重越低，最低0.7
        # 这里用线性缩放，也可以根据需求改成非线性函数
        decay_factor = 0.3 + 0.7 * closest_dist  # closest_dist=0时0.7，closest_dist=1时1.0
        weight = count * s * decay_factor  # 饱和度加权频数，再乘以衰减
        weights.append(weight)

    dominant_idx = np.argmax(weights)
    dominant_rgb = tuple(int(c) for c in cluster_centers[dominant_idx])




    r,g,b = dominant_rgb
    dominant_rgba = (r,g,b,255)
    # 生成浅色的rgba
    lighten_factor = 0.45
    r, g, b = [x / 255.0 for x in dominant_rgb]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(1.0, l + (1.0 - l) * lighten_factor)
    r_l, g_l, b_l = colorsys.hls_to_rgb(h, l, s)
    dominant_rgba_deal = (int(r_l * 255), int(g_l * 255), int(b_l * 255), 255)  # alpha=200
    #print(dominant_rgb, dominant_rgba)
    font_title_rgb, font_des_rgb = (0, 0, 0), (148, 148, 148),
    #判断字体需不需要反转颜色
    r, g, b, a = dominant_rgba_deal
    check_font_rgb = 0.299 * r + 0.587 * g + 0.114 * b
    if check_font_rgb < 140: font_title_rgb = (255, 255, 255)
    if check_font_rgb < 195: font_des_rgb = (255, 255, 255)
    label_color = dominant_rgba
    r, g, b, a = label_color
    #print(0.299 * r + 0.587 * g + 0.114 * b)
    if 0.299 * r + 0.587 * g + 0.114 * b > 180:
        label_color = (251,114,153,255)
    return_json = {'back_rgb': dominant_rgb, 'layer_rgba': dominant_rgba_deal,
                   'font_title_rgb': font_title_rgb, 'font_des_rgb': font_des_rgb,
                   'img_des_rgba': dominant_rgba_deal, 'avatar_shadow_color': dominant_rgb,
                    'avatar_shadow_max_alpha':200, 'avatar_shadow_intensity': 1.2,
                    'label_color':label_color}
    #pprint.pprint(return_json)
    return return_json


async def bilibili(url,filepath=None,is_twice=None,type=None,credential_bili=None,absorb_color=False,up_info_get=False):
    """
        哔哩哔哩解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    #url: str = str(event.message).strip()
    BILIBILI_HEADER, credential,BILI_SESSDATA=await bili_init()#获取构建credential
    json_check = copy.deepcopy(json_init)
    json_check['soft_type'] = 'bilibili'
    json_check['status'] = True
    json_check['video_url'] = False
    #logger.info(f'credential: {credential}')
    if not ( 'bili' in url or 'b23' in url ):return
    #构建绘图消息链
    if filepath is None:
        filepath = filepath_init
    contents=[]
    contents_dy=[]
    emoji_list = []
    label_list,image_list,context=[],[],''
    orig_desc=None
    introduce=None
    desc=None
    avatar_json=None
    url_reg = r"(http:|https:)\/\/(space|www|live).bilibili.com\/[A-Za-z\d._?%&+\-=\/#]*"
    header_img, right_icon = 'data/img/type_software/bili.png', 'data/img/type_software/bili_icon.png'
    b_short_rex = r"(https?://(?:b23\.tv|bili2233\.cn)/[A-Za-z\d._?%&+\-=\/#]+)"
    des_draw_type, des_draw_info = 'common_with_des', {}
    # 处理短号、小程序问题
    if "b23.tv" in url or "bili2233.cn" in url or "QQ小程序" in url :
        b_short_url = re.search(b_short_rex, url.replace("\\", ""))[0]
        #logger.info(f'b_short_url:{b_short_url}')
        resp = httpx.get(b_short_url, follow_redirects=True)
        url: str = str(resp.url)
        #print(f'url:{url}')
    # AV/BV处理
    #print(url)
    if "av" in url and 'BV' not in url:
        return
        url= 'https://www.bilibili.com/video/' + av_to_bv(url)
    if re.match(r'^BV[1-9a-zA-Z]{10}$', url):
        url = 'https://www.bilibili.com/video/' + url
    json_check['url'] = url
    #print(url)
    # ===============发现解析的是动态，转移一下===============
    if ('t.bilibili.com' in url or '/opus' in url or '/space' in url ) and BILI_SESSDATA != '':
        # 去除多余的参数
        if '?' in url:
            url = url[:url.index('?')]
        dynamic_id = int(re.search(r'[^/]+(?!.*/)', url)[0])
        #logger.info(dynamic_id)
        if credential_bili is None:
            dy = dynamic.Dynamic(dynamic_id, credential)
        else:
            dy = dynamic.Dynamic(dynamic_id, credential_bili)
        #is_opus =await dy.is_opus()#判断动态是否为图文
        json_check['url'] = f'https://t.bilibili.com/{dynamic_id}'

        dynamic_info = await dy.get_info()
        #print(json.dumps(dynamic_info, indent=4))
        orig_check=1        #判断是否为转发，转发为2
        type_set=None
        if dynamic_info is not None:
            paragraphs = []
            for module in dynamic_info['item']:
                if 'orig' in module:
                    orig_check=2
                    orig_context=dynamic_info['item'][module]
            for module in dynamic_info['item']['modules']:
                if 'module_dynamic' in module:
                    if orig_check==1:
                        type_set=13
                    elif orig_check==2:
                        paragraphs = dynamic_info['item']['modules']['module_dynamic']
                        type_set=14
                    break
            #获取头像以及名字
            owner_cover=dynamic_info['item']['modules']['module_author']['face']
            owner_name=dynamic_info['item']['modules']['module_author']['name']
            pub_time=dynamic_info['item']['modules']['module_author']['pub_time']
            #pprint.pprint(dynamic_info['item']['modules']['module_author'])
            #是否获取头图
            if up_info_get:
                u = user.User(dynamic_info['item']['modules']['module_author']['mid'])
                up_info = await u.get_user_info()
                header_img = await download_img('https://i0.hdslb.com/' + up_info['top_photo'],"data/pictures/cache/")
            if orig_check ==1:
                #avatar_json = await info_search_bili(dynamic_info, is_opus, filepath=filepath,card_url_list=card_url_list)
                #print('非转发')
                type_software='bilibili 动态'
                if 'opus' in dynamic_info['item']['modules']['module_dynamic']['major']:
                    opus_paragraphs = dynamic_info['item']['modules']['module_dynamic']['major']['opus']
                    text_list_check = ''
                    pics_context=[]
                    #print(json.dumps(opus_paragraphs, indent=4))


                    for text_check in opus_paragraphs['summary']['rich_text_nodes']:
                        #print('\n\n')
                        if text_check['type'] == 'RICH_TEXT_NODE_TYPE_EMOJI':
                            text_list_check += f"[emoji]{text_check['emoji']['icon_url']}[/emoji]"
                        elif text_check['type'] == 'RICH_TEXT_NODE_TYPE_TOPIC':
                            text_list_check += f"[tag]{text_check['orig_text']}[/tag]"
                        elif text_check['type'] == 'RICH_TEXT_NODE_TYPE_TEXT':
                            text_list_check += text_check['orig_text']
                        elif text_check['type'] == 'RICH_TEXT_NODE_TYPE_WEB':
                            text_list_check += f"[tag]{text_check['orig_text']}[/tag]"
                        elif text_check['type'] == 'RICH_TEXT_NODE_TYPE_BV':
                            text_list_check += f"[tag]{text_check['orig_text']}[/tag]"
                    #print(text_list_check)
                    if dynamic_info['item']['type'] == 'DYNAMIC_TYPE_ARTICLE':
                        type_software = 'BiliBili 专栏'
                        context += f"[title]{opus_paragraphs['title']}[/title]\n"
                        context += text_list_check
                        for pic_check in opus_paragraphs['pics']:
                            pics_context.append(pic_check['url'])
                        image_list = [item for item in pics_context]
                    else:
                        if opus_paragraphs['title'] is not None:
                            context += f"[title]{opus_paragraphs['title']}[/title]\n"
                        context += text_list_check
                        for pic_check in opus_paragraphs['pics']:
                            pics_context.append(pic_check['url'])
                        image_list = [item for item in pics_context]
                    #print(context)
                elif 'live_rcmd' in dynamic_info['item']['modules']['module_dynamic']['major']:
                    live_paragraphs = dynamic_info['item']['modules']['module_dynamic']['major']['live_rcmd']
                    content = json.loads(live_paragraphs['content'])
                    #print(json.dumps(content['live_play_info'], indent=4))
                    title,cover,pub_time = content['live_play_info']['title'],content['live_play_info']['cover'],content['live_play_info']['live_start_time']
                    parent_area_name,area_name=content['live_play_info']['parent_area_name'],content['live_play_info']['area_name']
                    image_list = [cover]
                    context += f"[title]{title}[/title]\n[des]{parent_area_name} {area_name}[/des]"
                    pub_time = datetime.fromtimestamp(pub_time).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    type_software = '直播'
                else:
                    paragraphs = dynamic_info['item']['modules']['module_dynamic']['major']['archive']
                    title,desc,cover,bvid=paragraphs['title'],paragraphs['desc'],paragraphs['cover'],paragraphs['bvid']
                    image_list = [cover]
                    context += f"[title]{title}[/title]\n[des]{desc}[/des]"
                    type_software = 'BiliBili 投稿'
                    #pprint.pprint(paragraphs)
                    if up_info_get:
                        des_draw_type = 'common_with_des_bili'
                        des_draw_info = {'duration': paragraphs['duration_text'], 'view': paragraphs['stat']['play'],
                               'danmaku': paragraphs['stat']['danmaku'], 'type': 'dynamic_video'}
                color_info = await get_dominant_color(image_list[0] if image_list else None,absorb_color=absorb_color)
                if len(image_list) == 1 and type_software in {'直播',}:
                    manshuo_draw_json=[{'type': 'basic_set', 'debug': False,
                        'font_title_color': color_info['font_title_rgb'],'font_des_color': color_info['font_des_rgb'],
                         'backdrop_color': {'color1': color_info['layer_rgba']},'shadow_font_color':color_info['back_rgb']},
                        {'type': 'backdrop', 'subtype': 'one_color','color':color_info['back_rgb']},
                        {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover], 'upshift_extra': 20,
                         'content': [f"[name]{owner_name}[/name]\n[time]{pub_time}[/time]"],
                         'background':header_img,'right_icon':right_icon,'shadow_color':color_info['avatar_shadow_color'],
                         'shadow_max_alpha':color_info['avatar_shadow_max_alpha'],'shadow_intensity':color_info['avatar_shadow_intensity']},
                        {'type': 'img', 'subtype': 'common_with_des_right', 'img': image_list, 'label': [type_software],'label_color':color_info['label_color'],
                         'content': [context],'description_color':color_info['img_des_rgba']}]
                elif len(image_list) == 1 and type_software in {'BiliBili 投稿'}:
                    manshuo_draw_json=[{'type': 'basic_set', 'debug': False,
                         'font_title_color': color_info['font_title_rgb'],'font_des_color': color_info['font_des_rgb'],
                         'backdrop_color': {'color1': color_info['layer_rgba']},'shadow_font_color':color_info['back_rgb']},
                        {'type': 'backdrop', 'subtype': 'one_color','color':color_info['back_rgb']},
                        {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover], 'upshift_extra': 20,
                         'content': [f"[name]{owner_name}[/name]\n[time]{pub_time}[/time]"],
                         'background':header_img,'right_icon':right_icon,'shadow_color':color_info['avatar_shadow_color'],
                         'shadow_max_alpha':color_info['avatar_shadow_max_alpha'],'shadow_intensity':color_info['avatar_shadow_intensity'] },
                        {'type': 'img', 'subtype': des_draw_type, 'img': image_list, 'label': [type_software],'label_color':color_info['label_color'],
                         'content': [context],'description_color':color_info['img_des_rgba'],'info':[des_draw_info]}]
                else:
                    manshuo_draw_json=[{'type': 'basic_set', 'debug': False,
                        'font_title_color': color_info['font_title_rgb'],'font_des_color': color_info['font_des_rgb'],
                         'backdrop_color': {'color1': color_info['layer_rgba']},'shadow_font_color':color_info['back_rgb']},
                        {'type': 'backdrop', 'subtype': 'one_color','color':color_info['back_rgb']},
                        {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover], 'upshift_extra': 20,
                         'content': [f"[name]{owner_name}[/name]\n[time]{pub_time}[/time]"],'shadow_color':color_info['avatar_shadow_color'],
                         'background':header_img,'right_icon':right_icon,},{'type': 'text','content': [context],
                         'shadow_max_alpha':color_info['avatar_shadow_max_alpha'],'shadow_intensity':color_info['avatar_shadow_intensity']},
                        {'type': 'img','img': image_list,'description_color':color_info['img_des_rgba']}]
                #pprint.pprint(manshuo_draw_json)
                if is_twice is not True:
                    if type not in no_draw_type:
                        json_check['pic_path'] = await manshuo_draw(manshuo_draw_json)
                    json_check['time'] = pub_time
                    json_check['pic_url_list'] = image_list
                    json_check['content'] = {'text': context, 'opus_type': dynamic_info['item']['type'], 'type':'dynamic'}
                    return json_check
                return manshuo_draw_json
            elif orig_check ==2:
                #print(json.dumps(paragraphs, indent=4))
                text_list_check = ''
                for text_check in paragraphs['desc']['rich_text_nodes']:
                    if 'emoji' in text_check:
                        text_list_check += f"[emoji]{text_check['emoji']['icon_url']}[/emoji]"
                    elif 'orig_text' in text_check:
                        text_list_check += text_check['orig_text']
                #contents.append(text_list_check)
                #print(text_list_check)

                for module in orig_context['modules']:
                    if 'module_dynamic' in module:
                        if 'opus' in orig_context['modules']['module_dynamic']['major']:
                            opus_orig_paragraphs=orig_context['modules']['module_dynamic']['major']['opus']
                            orig_title=opus_orig_paragraphs['summary']['text']
                            context += f"{orig_title}"
                            #logger.info(opus_orig_paragraphs)
                            image_list = [item['url'] for item in opus_orig_paragraphs['pics']]
                        else:
                            orig_paragraphs = orig_context['modules']['module_dynamic']['major']['archive']
                            orig_title, orig_desc, orig_cover, orig_bvid = orig_paragraphs['title'], orig_paragraphs['desc'], orig_paragraphs['cover'], orig_paragraphs['bvid']
                            image_list=[orig_cover]
                            context += f"[title]{orig_title}[/title]\n{orig_desc}"
                            try:
                                pics_context = paragraphs[1]['pic']['pics']
                            except KeyError:
                                pics_context = []
                            image_list = await add_append_img(image_list,[item['url'] for item in pics_context])

                orig_pub_time=orig_context['modules']['module_author']['pub_time']
                orig_owner_name = orig_context['modules']['module_author']['name']
                orig_owner_cover = orig_context['modules']['module_author']['face']


                if is_twice is True:
                    if orig_pub_time == '': orig_pub_time = pub_time
                    if len(image_list) != 1:
                        manshuo_draw_json = [{'type': 'backdrop', 'subtype': 'one_color'},
                            {'type': 'avatar', 'subtype': 'common', 'img': [orig_owner_cover], 'upshift_extra': 20,
                             'content': [f"[name]{orig_owner_name}[/name]\n[time]{orig_pub_time}[/time]"],
                             'background':header_img,'right_icon':right_icon, 'label': label_list},{'type': 'text','content': [context]},{'type': 'img','img': image_list}]
                    else:
                        manshuo_draw_json = [{'type': 'backdrop', 'subtype': 'one_color',},
                            {'type': 'avatar', 'subtype': 'common', 'img': [orig_owner_cover], 'upshift_extra': 20,
                             'content': [f"[name]{orig_owner_name}[/name]\n[time]{orig_pub_time}[/time]"],
                             'background':header_img,'right_icon':right_icon, },
                            {'type': 'img', 'subtype': 'common_with_des_right', 'img': image_list,
                             'content': [context]}]
                    return manshuo_draw_json

                orig_url= 'orig_url:'+'https://t.bilibili.com/' + orig_context['id_str']
                manshuo_draw_json2=await bilibili(orig_url,f'{filepath}orig_',is_twice=True)
                manshuo_draw_json = [
                    {'type': 'basic_set', 'debug': False, 'font_title_color': (0,0,0),
                     'backdrop_color': {'color1': (235, 239, 253)}},
                    {'type': 'backdrop', 'subtype': 'one_color', 'color': (194, 228, 255)},
                    {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover], 'upshift_extra': 20,
                     'content': [f"[name]{owner_name}[/name]  [time]{pub_time}[/time]"],'avatar_size':50,
                     'label': label_list}, {'type': 'text','content': [text_list_check]}]
                if type not in no_draw_type:
                    json_check['pic_path'] = await manshuo_draw(await add_append_img(manshuo_draw_json,manshuo_draw_json2,layer=2))
                json_check['time'] = pub_time
                json_check['content'] = {'text': text_list_check, 'opus_type': dynamic_info['item']['type'], 'type':'dynamic'}
                return json_check

        return None

    # 直播间识别
    if 'live' in url:
        room_id = re.search(r'\/(\d+)$', url).group(1)
        room = live.LiveRoom(room_display_id=int(room_id))
        data_get_url_context=await room.get_room_info()
        #pprint.pprint(data_get_url_context)
        room_info = data_get_url_context['room_info']
        title, cover, keyframe = room_info['title'], room_info['cover'], room_info['keyframe']
        owner_name,owner_cover = data_get_url_context['anchor_info']['base_info']['uname'], data_get_url_context['anchor_info']['base_info']['face']
        area_name,parent_area_name=room_info['area_name'],room_info['parent_area_name']

        #print(f'owner_cover:{owner_cover}\ncover:{cover}')

        if cover =='':
            cover='https://gal.manshuo.ink/usr/uploads/galgame/img/bili-logo.webp'
        context += f'[title]{title}[/title]\n[des]{parent_area_name} {area_name}[/des]'

        if f'{room_info["live_status"]}' == '1':
            live_status, live_start_time = True, room_info['live_start_time']
            pub_time = datetime.fromtimestamp(live_start_time).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        else:pub_time, live_status ='暂未开启直播', False
        #是否获取头图
        if up_info_get:
            u = user.User(room_info['uid'])
            up_info = await u.get_user_info()
            header_img = await download_img('https://i0.hdslb.com/' + up_info['top_photo'], "data/pictures/cache/")
        color_info = await get_dominant_color(cover,absorb_color=absorb_color)
        manshuo_draw_json = [
            {'type': 'basic_set', 'debug': False, 'font_title_color': color_info['font_title_rgb'],'font_des_color': color_info['font_des_rgb'],
             'backdrop_color': {'color1': color_info['layer_rgba']},'shadow_font_color':color_info['back_rgb']},
            {'type': 'backdrop', 'subtype': 'one_color', 'color': color_info['back_rgb']},
            {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover], 'upshift_extra': 20,
             'content': [f"[name]{owner_name}[/name]\n[time]{pub_time}[/time]"],
             'background':header_img,'right_icon':right_icon, 'shadow_color':color_info['avatar_shadow_color'],
            'shadow_max_alpha':color_info['avatar_shadow_max_alpha'],'shadow_intensity':color_info['avatar_shadow_intensity']},
            {'type': 'img', 'subtype': 'common_with_des_right', 'img': [cover],'label': ['直播'],'label_color':color_info['label_color'],
             'content': [context],'description_color':color_info['img_des_rgba']}]

        if is_twice is not True:
            if type not in no_draw_type:
                json_check['pic_path'] = await manshuo_draw(manshuo_draw_json)
            json_check['pic_url_list'].append(cover)
            json_check['content'] = {'text': context, 'type':'live','live_status':live_status}
            return json_check
        return manshuo_draw_json
    # 专栏识别
    if 'read' in url:
        read_id = re.search(r'read\/cv(\d+)', url).group(1)
        ar = article.Article(read_id)
        # 如果专栏为公开笔记，则转换为笔记类
        # NOTE: 笔记类的函数与专栏类的函数基本一致
        if ar.is_note():
            ar = ar.turn_to_note()
        # 加载内容
        await ar.fetch_content()
        #print(ar.markdown())
        markdown_path = f'{filepath}{read_id}.md'
        with open(markdown_path, 'w', encoding='utf8') as f:
            f.write(ar.markdown())
        logger.info('专栏未做识别，跳过，欢迎催更')

        return None
    # 收藏夹识别
    if 'favlist' in url and BILI_SESSDATA != '':
        logger.info('收藏夹未做识别，跳过，欢迎催更')
        return None
    try:
        video_id = re.search(r"video\/[^\?\/ ]+", url)[0].split('/')[1]
        if credential_bili is not None:
            v = video.Video(video_id, credential=credential_bili)
        else:
            v = video.Video(video_id, credential=credential)
        video_info = await v.get_info()
    except Exception as e:
        logger.info('无法获取视频内容，该进程已退出')
        json_check['status'] = False
        return json_check
    #print(json.dumps(video_info, indent=4))
    owner_cover_url=video_info['owner']['face']
    owner_name = video_info['owner']['name']
    #logger.info(owner_cover)
    if video_info is None:
        logger.info(f"识别：B站，出错，无法获取数据！")
        return None
    video_title, video_cover, video_desc, video_duration = video_info['title'], video_info['pic'], video_info['desc'], \
        video_info['duration']
    pub_time = datetime.utcfromtimestamp(video_info['pubdate']) + timedelta(hours=8)
    pub_time=pub_time.strftime('%Y-%m-%d %H:%M:%S')
    # 校准 分p 的情况
    page_num = 0
    if 'pages' in video_info:
        # 解析URL
        parsed_url = urlparse(url)
        # 检查是否有查询字符串
        if parsed_url.query:
            # 解析查询字符串中的参数
            query_params = parse_qs(parsed_url.query)
            # 获取指定参数的值，如果参数不存在，则返回None
            page_num = int(query_params.get('p', [1])[0]) - 1
        else:
            page_num = 0
        if 'duration' in video_info['pages'][page_num]:
            video_duration = video_info['pages'][page_num].get('duration', video_info.get('duration'))
        else:
            # 如果索引超出范围，使用 video_info['duration'] 或者其他默认值
            video_duration = video_info.get('duration', 0)
    download_url_data = await v.get_download_url(page_index=page_num)
    #pprint.pprint(download_url_data)
    detecter = VideoDownloadURLDataDetecter(download_url_data)
    streams = detecter.detect()
    #pprint.pprint(streams)
    #这里获取的视频链接最高不超过1080P
    try:
        video_url, audio_url = None, None
        if credential_bili is not None:
            for stream in streams:
                if hasattr(stream, 'video_quality') and video_url is None and stream.video_quality == VideoQuality._1080P:
                    video_url = stream.url
                    #print(stream.video_quality)
                    break
        for stream in streams:
            if hasattr(stream, 'video_quality') and video_url is None:
                video_url = stream.url
                #print(stream.video_quality)
            elif hasattr(stream, 'audio_quality') and audio_url is None:
                audio_url = stream.url
            if video_url and audio_url: break
        json_check['video_url'], json_check['audio_url'] = video_url, audio_url
    except Exception as e:
        json_check['video_url'] = False
    context += f'[title]{video_title}[/title]\n[des]{video_desc} [/des]'
    # 是否获取头图
    if up_info_get:
        u = user.User(video_info['owner']['mid'])
        up_info = await u.get_user_info()
        header_img = await download_img('https://i0.hdslb.com/' + up_info['top_photo'], "data/pictures/cache/")
        des_draw_type = 'common_with_des_bili'
    color_info = await get_dominant_color(video_cover, absorb_color=absorb_color)
    #获取播放量信息，用以增加新的标识
    des_draw_info = {'duration':video_info['duration'], 'view':video_info['stat']['view'], 'coin': video_info['stat']['coin'],
            'danmaku':video_info['stat']['danmaku'] ,'share':video_info['stat']['share'],'type':'video'}
    manshuo_draw_json = [
        {'type': 'basic_set', 'debug': False,'font_title_color': color_info['font_title_rgb'],'font_des_color': color_info['font_des_rgb'],
         'backdrop_color': {'color1': color_info['layer_rgba']},'shadow_font_color':color_info['back_rgb']},
        {'type': 'backdrop', 'subtype': 'one_color', 'color': color_info['back_rgb']},
        {'type': 'avatar', 'subtype': 'common', 'img': [owner_cover_url], 'upshift_extra': 20,
         'content': [f"[name]{owner_name}[/name]\n[time]{pub_time}[/time]"],
         'background':header_img,'right_icon':right_icon, 'shadow_color':color_info['avatar_shadow_color'],
        'shadow_max_alpha':color_info['avatar_shadow_max_alpha'],'shadow_intensity':color_info['avatar_shadow_intensity']},
        {'type': 'img', 'subtype': des_draw_type, 'img': [video_cover],'label': ['视频'],'label_color':color_info['label_color'],
         'content': [context],'description_color':color_info['img_des_rgba'],'info':[des_draw_info]}]

    if is_twice is not True:
        if type not in no_draw_type:
            json_check['pic_path'] = await manshuo_draw(manshuo_draw_json)
        json_check['pic_url_list'].append(video_cover)
        json_check['content'] = {'text': context, 'type':'video'}
        return json_check
    return manshuo_draw_json



async def download_video_link_prising(json,filepath=None,proxy=None):
    if filepath is None:filepath = filepath_init
    video_json={}
    if json['soft_type'] == 'bilibili':
        video_path=await download_b(json['video_url'], json['audio_url'], int(time.time()), filepath=filepath)
    elif json['soft_type'] == 'dy':
        video_path = await download_video(json['video_url'], filepath=filepath)
    elif json['soft_type'] == 'wb':
        video_path = await download_video(json['video_url'], filepath=filepath, ext_headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                "referer": "https://weibo.com/"
            })
    elif json['soft_type'] == 'x':
        video_path = await download_b(json['video_url'], json['audio_url'], int(time.time()),filepath=filepath,proxy=proxy)
    elif json['soft_type'] == 'xhs':
        video_path = await download_video(json['video_url'], filepath=filepath)
    video_json['video_path'] = video_path
    file_size_in_mb = get_file_size_mb(video_path)
    if file_size_in_mb < 25:
        video_type='video'
    elif file_size_in_mb < 80:
        video_type='video_bigger'
    elif file_size_in_mb < 300:
        video_type='file'
    else:
        video_type = 'too_big'
    video_json['type']=video_type
    return video_json