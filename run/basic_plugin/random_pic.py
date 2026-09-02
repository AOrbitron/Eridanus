import os
import re
import random
import httpx
from httpx._urlparse import urlparse
from developTools.message.message_components import Record, Node, Text, Image, At
from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Image
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str
from run.basic_plugin.service.random_pic import random_img_search


def main(bot: ExtendBot, config: YAMLManager):

    @bot.on(GroupMessageEvent)
    async def today_husband(event: GroupMessageEvent):
        text = str(event.pure_text)
        if not text.startswith("今") or not any(keyword in text for keyword in ["今日", "今天"]):
            return

        url_map = {
            "腿": [
                "https://api.dwo.cc/api/meizi",
            ],
            "头像": [
                "https://api.dwo.cc/api/dmtou",
            ],
            "cos": [
                "https://img.sorahub.site",
            ],
        }

        matched_key = next((k for k in url_map if k in text), None)
        url = None
        if matched_key:
            url_list = url_map[matched_key]
            url = random.choice(url_list)
            bot.logger.info(f"今日 {matched_key} API 选择：{url}")

        if not url:
            return

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                content_type = response.headers.get('Content-Type', '')

                if 'image' in content_type:
                    ext = get_image_extension(content_type)
                    img_path = f'data/pictures/cache/{random_str()}{ext}'
                    with open(img_path, 'wb') as f:
                        f.write(response.content)
                    await bot.send(event, [Image(file=img_path)])
                    return

                if 'json' in content_type or response.text.strip().startswith('{'):
                    try:
                        data = response.json()
                    except Exception:
                        await bot.send(event, 'API 返回的 JSON 无法解析喵~')
                        return

                    img_urls = extract_all_urls_from_json(data)
                    if not img_urls:
                        await bot.send(event, 'API 返回了 JSON 但没找到图片 URL 喵~')
                        return

                    img_url = random.choice(img_urls)
                    bot.logger.info(f"发现图片 URL：{img_url}")

                    ext = os.path.splitext(urlparse(img_url).path)[1] or '.jpg'
                    img_path = f'data/pictures/cache/{random_str()}{ext}'
                    img_response = await client.get(img_url)
                    with open(img_path, 'wb') as f:
                        f.write(img_response.content)

                    await bot.send(event, [Image(file=img_path)])
                    return

                # 其他格式
                await bot.send(event, 'API 返回了未知格式数据喵~')

        except Exception as e:
            bot.logger.error(f'API 请求失败: {e}')
            await bot.send(event, 'api失效了喵，请过一段时间再试试吧')

    def get_image_extension(content_type: str) -> str:
        if 'png' in content_type:
            return '.png'
        elif 'webp' in content_type:
            return '.webp'
        return '.jpg'

    def extract_all_urls_from_json(data):
        urls = []
        img_pattern = re.compile(
            r'https?://[^\s\'"]+\.(?:jpg|jpeg|png|webp|gif|bmp|tiff|svg)(?:\?[^\s\'"]*)?',
            re.IGNORECASE
        )

        def _scan(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    _scan(v)
            elif isinstance(obj, list):
                for v in obj:
                    _scan(v)
            elif isinstance(obj, str):
                matches = img_pattern.findall(obj)
                urls.extend(matches)

        _scan(data)
        return urls




    @bot.on(GroupMessageEvent)
    async def random_img(event: GroupMessageEvent):
        context, userid, nickname, group_id = event.pure_text, str(event.sender.user_id), event.sender.nickname, int(event.group_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):  context = event.message_chain.get(Text)[0].text
        Today_random_pic = config.basic_plugin.config["setu"]["today_img_list"]
        order_list = ["随机", "今日", '来一张', '来一个','来张']
        target_list =  ['龙图', '神乐七奈', '狗妈', '配色', ] + Today_random_pic
        if not (any(context.startswith(word) for word in order_list) and any(word in context for word in target_list)):return
        target = next((t for t in target_list if t in context), None)
        context = re.compile('|'.join(map(re.escape, order_list + target_list))).sub('', context)

        bot.logger.info(f"开始获取 {target} 喵")
        if any(word in context for word in ["个", "张"]):
            number_list = re.search(r'\d+', context)
            cmList = []
            if number_list:
                number = int(number_list.group())
                if number > 5:
                    await bot.send(event, '岚岚不干了喵！')
                    return
                info = await random_img_search(target,number,config.basic_plugin.config["setu"]["custom_pic_source"])
                if info['status'] is not True:
                    await bot.send(event, '获取失败了喵')
                    return
                for img_path in info['img']:cmList.append(Node(content=[Image(file=img_path)]))
            if cmList:await bot.send(event, cmList)
        else:
            info = await random_img_search(target,1,config.basic_plugin.config["setu"]["custom_pic_source"])
            if info['status'] is not True:

                await bot.send(event, '获取失败了喵')
                return
            img_path = info['img'][0]
            await bot.send(event, Image(file=img_path))