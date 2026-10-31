import json
import os
import re
import pprint
import traceback

from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import File, Image, Video, Node, Text, At
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.manshuo_draw import manshuo_draw
from framework_common.utils.utils import download_img
from run.streaming_media.service.cloud_music.cloud_music_parsing import CloudMusicParser

song_level = {
    '标准': 'standard', 'standard': '标准',
    '极高': 'exhigh', 'exhigh': '极高',
    '无损': 'lossless', 'lossless': '无损',
    'hires': 'hires',
    '超清母带': 'jyeffect', 'jyeffect': '超清母带'
}

async def parse_cloud_music(bot: ExtendBot, event, config, url: str, level: str = None):
    """
    解析并下载网易云音乐
    """
    if config.streaming_media.config.get("网易云解析", {}).get("enable_proxy") and config.common_config.basic_config.get("proxy", {}).get("http_proxy"):
        proxy_url = config.common_config.basic_config["proxy"]["http_proxy"]
        proxies = {"http://": proxy_url, "https://": proxy_url}
    else:
        proxies = None

    bot.logger.info(f"开始解析网易云音乐链接:{url}")
    recall_id = None

    try:
        recall_id = await bot.send(event, [Text("正在解析网易云音乐链接...")])

        wyy_base_url = config.streaming_media.config.get("网易云解析", {}).get("wyy_prase_url")
        music = CloudMusicParser(proxies=proxies, base_url=wyy_base_url)
        detail_result = await music.getSongDetail(url)
        detail_data = detail_result["data"]

        music_name = f"{detail_data['al_name']} - {detail_data['ar_name']}"
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', music_name).strip()
        save_path = f"data/voice/cache/{safe_name}.mp3"
        music_url = detail_data["url"]

        if level is None or level not in song_level:
            await music.download_music(music_url, save_path)
        else:
            await music.download_music_stream(detail_data["id"], save_path, song_level.get(level, level))

        if not os.path.exists(save_path) or os.path.getsize(save_path) == 0:
            raise ValueError("音频下载失败，未生成有效音频文件")

        await bot.send(event, [File(file=save_path)])

        pic_url = detail_data.get('pic')
        if pic_url:
            pic_save_path = f"data/voice/cache/{safe_name}.jpg"
            await download_img(pic_url, pic_save_path)
            quality_desc = level if level else "外链直链"
            card_img = await manshuo_draw([
                {'type': 'basic_set', 'img_width': 750},
                {
                    'type': 'img',
                    'subtype': 'common_with_des_right',
                    'img': [pic_save_path],
                    'content': [
                        f"[title]{detail_data['al_name']}\n[/title]"
                        f"歌手：{detail_data['ar_name']}\n"
                        f"歌曲品质：{quality_desc}"
                    ]
                }
            ])
            await bot.send(event, [Image(file=card_img)])

    except Exception as e:
        bot.logger.error(f"音乐解析失败: {e}")
        traceback.print_exc()
        await bot.send(event, [Text(f"发送音乐失败: {e}")])
    finally:
        if recall_id and isinstance(recall_id, dict):
            msg_id = recall_id.get('data', {}).get('message_id')
            if msg_id:
                try:
                    await bot.recall(msg_id)
                except Exception as e:
                    bot.logger.warning(f"撤回提示消息失败: {e}")

def main(bot, config):
    @bot.on(GroupMessageEvent)
    async def dl_cloud_music(event):
        context = event.pure_text.strip()
        if event.message_chain.has(At) and event.message_chain.has(Text):
            context = "".join([t.text for t in event.message_chain.get(Text)]).strip()

        order_list = ["网易云解析", "网易云下载", "wyy下载", "网易云歌曲下载", "网易云歌曲解析"]
        level_list = ['标准', '极高', '无损', 'hires', '超清母带']

        if not any(context.startswith(word) for word in order_list):
            return

        level = next((t for t in level_list if t in context), None)
        song_content = re.compile('|'.join(map(re.escape, order_list + level_list))).sub('', context).strip()

        url_pattern = r'(https?://[^\s]+)'
        urls = re.findall(url_pattern, song_content)
        if urls:
            song_input = urls[0]
        else:
            digit_match = re.search(r'\d+', song_content)
            if digit_match:
                song_input = digit_match.group(0)
            else:
                await bot.send(event, [Text("请提供有效的网易云音乐分享链接或歌曲ID")])
                return

        await parse_cloud_music(bot, event, config, song_input.strip(), level)
