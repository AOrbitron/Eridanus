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

"""
小红书下载链接
"""
XHS_REQ_LINK = "https://www.xiaohongshu.com/explore/"


async def xiaohongshu(url,filepath=None,type_check=None):
    """
        小红书解析
    :param event:
    :return:
    """
    contents=[]
    json_check = copy.deepcopy(json_init)
    json_check['soft_type'] = 'xhs'
    json_check['video_url'] = False
    json_check['status'] = True
    if filepath is None: filepath = filepath_init
    introduce=None
    match = re.search(r"(http:|https:)\/\/(xhslink|(www\.)xiaohongshu).com\/[A-Za-z\d._?%&+\-=\/#@]*",
                        str(url).replace("&amp;", "&").strip())
    if match:msg_url = match[0]
    else:msg_url = url
    # 如果没有设置xhs的ck就结束，因为获取不到
    xhs_ck=ini_login_Link_Prising(type=3)
    if xhs_ck == "" or xhs_ck is None:
        #logger.error(global_config)
        logger.warning('小红书ck未能成功获取，已启用默认配置，若失效请登录')
        xhs_ck='abRequestId=c6f047f3-ec40-5f6a-8a39-6335b5ab7e7e;webBuild=4.55.1;xsecappid=xhs-pc-web;a1=194948957693s0ib4oyggth91hnr3uu4hls0psf7c50000379922;webId=a0f8b87b02a4f0ded2c2c5933780e39e;acw_tc=0ad6fb2417376588181626090e345e91f0d4afd3f1601e0050cac6099b93e4;websectiga=f47eda31ec9%3B545da40c2f731f0630efd2b0959e1dd10d5fedac3dce0bd1e04d;sec_poison_id=3ffe8085-c380-4003-9700-4d63eb6f442f;web_session=030037a0a1c5b6776a218ed7ea204a5d5eaa3b;unread={%22ub%22:%2264676bf40000000027012fbf%22%2C%22ue%22:%2263f40762000000000703bfc2%22%2C%22uc%22:27};gid=yj4j4YjKKDx2yj4j4Yj2W1MiKjqM83D4lvkkMWS9xjyxI828Fq774U888qWjjJJ8y4K4Sif8;'
    # 请求头
    headers = {
                  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,'
                            'application/signed-exchange;v=b3;q=0.9',
                  'Cookie': xhs_ck,
                  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 EdgA/142.0.0.0'
              } | COMMON_HEADER
    if "xhslink" in msg_url:
        msg_url = httpx.get(msg_url, headers=headers, follow_redirects=True).url
        msg_url = str(msg_url)
    xhs_id = re.search(r'/explore/(\w+)', msg_url)
    if not xhs_id:
        xhs_id = re.search(r'/discovery/item/(\w+)', msg_url)
    if not xhs_id:
        xhs_id = re.search(r'source=note&noteId=(\w+)', msg_url)
    xhs_id = xhs_id[1]
    # 解析 URL 参数
    json_check['url']=msg_url
    parsed_url = urlparse(msg_url)
    params = parse_qs(parsed_url.query)
    # 提取 xsec_source 和 xsec_token
    xsec_source = params.get('xsec_source', [None])[0] or "pc_feed"
    xsec_token = params.get('xsec_token', [None])[0]
    html = httpx.get(f'{XHS_REQ_LINK}{xhs_id}?xsec_source={xsec_source}&xsec_token={xsec_token}', headers=headers).text
    # response_json = re.findall('window.__INITIAL_STATE__=(.*?)</script>', html)[0]
    try:
        response_json = re.findall('window.__INITIAL_STATE__=(.*?)</script>', html)[0]
    except IndexError:
        logger.error(f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n当前ck已失效，请联系管理员重新设置的小红书ck！")
        #await xhs.send(Message(f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n当前ck已失效，请联系管理员重新设置的小红书ck！"))
        return
    response_json = response_json.replace("undefined", "null")
    response_json = json.loads(response_json)
    note_data = response_json['note']['noteDetailMap'][xhs_id]['note']
    #print(json.dumps(response_json['note']['noteDetailMap'][xhs_id], indent=4))
    note_title,note_desc,type = note_data['title'],note_data['desc'].replace('#', '\n[tag]#', 1), note_data['type']
    if '#' in note_desc: note_desc += '[/tag]'
    if 'time' in note_data:
        xhs_time=note_data['time']
    elif 'lastUpdateTime' in note_data:
        xhs_time = note_data['lastUpdateTime']
    #logger.info(xhs_time)
    video_time = datetime.utcfromtimestamp(int(xhs_time)/1000) + timedelta(hours=8)
    video_time = video_time.strftime('%Y-%m-%d %H:%M:%S')
    if type == 'normal':
        #logger.info('这是一条解析有文字链接的图文:')
        context=f'[title]{note_title}[/title]\n{note_desc}'
        label_list=[]
    elif type == 'video':
        # 这是一条解析有水印的视频
        video_url = note_data['video']['media']['stream']['h264'][0]['masterUrl']
        json_check['video_url'] = video_url
        context = f'[title]{note_title}[/title]\n[des]{note_desc}[/des]'
        label_list=['视频']

    #这里获取主页图的图片
    try:


        #print(f'\n{xhs_id}\n')
        html = httpx.get(
            f'https://www.xiaohongshu.com/user/profile/{note_data["user"]["userId"]}?xsec_source={xsec_source}&xsec_token={xsec_token}',
            headers=headers).text
        response_json = re.findall('window.__INITIAL_STATE__=(.*?)</script>', html)[0]
        response_json = response_json.replace("undefined", "null")
        response_json = json.loads(response_json)
        #print(json.dumps(response_json, indent=4))
    except :
        logger.error(f"小红书主页图获取出错，使用默认图片")


    image_list = [item['urlDefault'] for item in note_data['imageList']]
    if type_check not in no_draw_type:
        if len(image_list) != 1:
            json_check['pic_path'] = await manshuo_draw([{'type': 'backdrop', 'subtype': 'one_color'},
                {'type': 'avatar', 'subtype': 'common', 'img': [note_data['user']['avatar']], 'upshift_extra': 20,
                 'content': [f"[name]{note_data['user']['nickname']}[/name]\n[time]{video_time}[/time]"], 'type_software': 'xhs','label':label_list }, image_list, [context]])
        else:
            json_check['pic_path'] = await manshuo_draw([{'type': 'backdrop', 'subtype': 'one_color'},
                {'type': 'avatar', 'subtype': 'common', 'img': [note_data['user']['avatar']], 'upshift_extra': 20,
                 'content': [f"[name]{note_data['user']['nickname']}[/name]\n[time]{video_time}[/time]"], 'type_software': 'xhs', },
                {'type': 'img', 'subtype': 'common_with_des_right', 'img': image_list, 'content': [context]}])
    json_check['pic_url_list'] = image_list
    return json_check