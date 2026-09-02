import traceback
import re
import httpx
import random
import string
import os
from datetime import datetime
import json
import asyncio
import requests
import aiohttp
from framework_common.manshuo_draw import *
from PIL import Image
import pprint
from framework_common.utils.utils import download_img


async def random_img_search(target,num=1,custom_url=None):
    info = {'status':False}
    if target in ['龙图']:info = await random_long(num)
    elif target in ['神乐七奈','狗妈']: info = await random_shenyueqinai(num)
    elif target in ['配色']: info = await random_color(num)
    else: info = await random_today_pic(num, target,custom_url)
    return info

async def save_img(resp=None,url=None):
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choice(characters) for _ in range(10))
    img_path = f'data/pictures/cache/{random_string}.jpg'
    if resp is not None:
        with open(img_path, 'wb') as file:
            file.write(resp.content)
    elif url is not None:
        pass
    return img_path

async def random_today_pic(num = 1, tag = '贫乳',custom_url=None):
    info_json = {'status':False, 'img':[]}
    data = {"tag": tag, "num": num, "r18": 0, "size": "regular",'format':'json'}
    try:
        async with httpx.AsyncClient(timeout=100) as client:
            r = await client.get(custom_url, params=data)
            img_info = r.json()["data"]
        #pprint.pprint(img_info)
        if 'items' in img_info:
            for item in img_info['items']:
                img_path = item['full_url']
                info_json['img'].append(img_path)
        else:
            for item in img_info:
                img_url = item['urls']['regular']
                try:
                    proxy_url = img_url.replace("https://i.pixiv.re/", "https://i.yuki.sh/")
                    #print(proxy_url)
                    img_path = await download_img(proxy_url)
                except:
                    #print(img_url)
                    img_path = await download_img(img_url, proxy="http://127.0.0.1:7890")
                    pass

                info_json['img'].append(img_path)

    except Exception as e:
        traceback.print_exc()
        #print(e)
        return info_json

    if len(info_json['img']) == 0:
        info_json['status'] = False
    else:
        info_json['status'] = True
    #pprint.pprint(info_json)
    return info_json


async def random_color(num = 1):
    info_json = {'status':False, 'img':[]}
    header1 = {
        'content-type': 'text/plain; charset=utf-8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 Core/1.94.186.400 QQBrowser/11.3.5195.400'
    }
    API_URL = 'http://colormind.io/api/'
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url=API_URL,
            headers=header1,
            json={"model": "default"}
        ) as response:
            result = await response.read()
            # nonebot.logger.info(result)
            ret = json.loads(result)
    # nonebot.logger.info(ret)
    json_data = ret

    color_codes = []
    msg = ""

    try:
        msg += "[title]推荐的配色方案为：[/title]\n"
        for color in json_data["result"]:
            r, g, b = color
            color_code = "#{:02X}{:02X}{:02X}".format(r, g, b)
            img = Image.new("RGB", (100, 100), color_code)
            color_codes.append(img)
            msg += color_code + " "
    except:
        #msg = '\n调用接口失败，寄！'
        #await catch_str.finish(Message(f'{msg}'), at_sender=True)
        return info_json
    #print(msg)
    draw_list = [msg,{'type': 'img','img': color_codes,'is_shadow_img':False,'number_per_row':5},]
    img_path = await manshuo_draw(draw_list)
    #print(img_path)
    info_json['status'] = True
    info_json['img'].append(img_path)
    return info_json

async def random_shenyueqinai(num = 1):
    info_json = {'status':False, 'img':[]}
    valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff')
    images = [f for f in os.listdir('run/manshuo_test/data/img/nana') if f.lower().endswith(valid_extensions)]
    for _ in range(num):
        img_path = os.path.join('run/manshuo_test/data/img/nana', random.choice(images))
        info_json['img'].append(img_path)
        info_json['status'] = True
    return info_json


async def random_capoo(num = 1):
    info_json = {'status':False, 'img':[]}
    for _ in range(num):
        base_url = f"https://git.acwing.com/HuParry/capoo/-/raw/master/capoo ({random.randint(1, 456)}).gif"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(base_url, timeout=5.0)
                if resp.status_code == 302:
                    resp = await client.get(resp.headers['Location'])
            if resp.status_code == 200:
                info_json['status'] = True
                img_path = await save_img(resp)
                info_json['img'].append(img_path)
        except Exception as e:
            print(f"输出异常：{e}")
            return info_json
    print(info_json)
    return info_json

async def random_long(num = 1):
    info_json = {'status':False, 'img':[]}
    base_url = "https://raw.githubusercontent.com/Whiked/Dragonimg/main/drimg/"
    extensions = [".jpg", ".png", ".gif"]
    total_images = 1516

    for _ in range(num):
        selected_image_number = random.randint(1, total_images)
        for ext in extensions:
            image_url = f"{base_url}dragon_{selected_image_number}_{ext}"
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(image_url, timeout=5.0)
                    if resp.status_code == 302:
                        resp = await client.get(resp.headers['Location'])
                if resp.status_code == 200:
                    info_json['status'] = True
                    img_path = await save_img(resp)
                    info_json['img'].append(img_path)
                    break
            except Exception as e:
                print(f"输出异常：{e}")
                return info_json
    return info_json


if __name__ == '__main__':
    pass
    #main()
    asyncio.run(random_today_pic(2))