# -*- coding: utf-8 -*-
import base64
import json
from typing import Optional, Dict, Any

from qzone_api import QzoneApi
from qzone_api.api.api_parms import get_feeds, get_self_zone, get_send_comment

from run.qq_zone.service.QzoneResponseParser import QzoneResponseParser
from loguru import logger
from run.qq_zone.service.custom_api_base import ApiBaseFixed

api_base_fixed = ApiBaseFixed()


class QzoneApiFixed(QzoneApi):

    async def _send_zone(self, target_qq: int, content: str, cookies: str, g_tk: int) -> Optional[Dict[str, Any]]:
        params = {
            'syn_tweet_verson': 1,
            'paramstr': 1,
            'pic_template': '',
            'richtype': 0,
            'richval': '',
            'special_url': '',
            'subrichtype': 0,
            'pic_bo': '',
            'who': 1,
            'con': content,
            'feedversion': 1,
            'ver': 1,
            'ugc_right': 1,
            'to_sign': 0,
            'hostuin': target_qq,
            'code_version': 1,
            'format': 'fs',
            'qzreferrer': f'https://user.qzone.qq.com/{target_qq}'
        }
        try:
            url = f'{self.send_url}?g_tk={g_tk}'
            return await api_base_fixed._make_post_request(url=url, data=params, cookies=cookies)
        except Exception as e:
            logger.error(f'发送纯文字说说失败: {e}')
            return None

    async def _send_zone_with_pic(self, target_qq: int, pic_path: str, content: str, cookies: dict, g_tk: int) -> Optional[Dict[str, Any]]:
        try:
            with open(pic_path, 'rb') as f:
                image_data = f.read()
                base64_image = base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            logger.error(f'读取图片失败: {e}')
            return None

        skey = cookies.get('skey', '')
        p_skey = cookies.get('p_skey', '')

        upload_url = f'https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk={g_tk}'

        form_data = {
            'filename': 'filename',
            'uin': target_qq,
            'skey': skey,
            'zzpaneluin': target_qq,
            'zzpanelkey': '',
            'p_uin': target_qq,
            'p_skey': p_skey,
            'qzonetoken': '',
            'uploadtype': '1',
            'albumtype': '7',
            'exttype': '0',
            'refer': 'shuoshuo',
            'output_type': 'jsonhtml',
            'charset': 'utf-8',
            'output_charset': 'utf-8',
            'upload_hd': '1',
            'hd_width': '2048',
            'hd_height': '10000',
            'hd_quality': '96',
            'backUrls': 'http://upbak.photo.qzone.qq.com/cgi-bin/upload/cgi_upload_image,http://119.147.64.75/cgi-bin/upload/cgi_upload_image',
            'url': f'https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk={g_tk}',
            'base64': '1',
            'jsonhtml_callback': 'callback',
            'picfile': base64_image
        }
        cookies_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
        response = await api_base_fixed._make_post_request(url=upload_url, data=form_data, cookies=cookies_str)
        richval = QzoneResponseParser.extract_richval(response) if isinstance(response, dict) else ''
        pic_bo = QzoneResponseParser.extract_pic_bo(response) if isinstance(response, dict) else ''

        logger.info(f'上传图片响应: {response}')
        params = {
            'syn_tweet_verson': 1,
            'paramstr': 1,
            'pic_template': '',
            'richtype': 1,
            'richval': richval,
            'special_url': '',
            'subrichtype': 1,
            'pic_bo': pic_bo,
            'who': 1,
            'con': content,
            'feedversion': 1,
            'ver': 1,
            'ugc_right': 1,
            'to_sign': 0,
            'hostuin': target_qq,
            'code_version': 1,
            'format': 'fs',
            'qzreferrer': f'https://user.qzone.qq.com/{target_qq}'
        }
        try:
            url = f'{self.send_url}?g_tk={g_tk}'
            return await api_base_fixed._make_post_request(url=url, data=params, cookies=cookies_str)
        except Exception as e:
            logger.error(f'发送说说失败: {e}')
            return None

    async def _get_zone(self, target_qq: int, g_tk: int, cookies: str, page: int = 1, count: int = 10, begintime: int = 0) -> Optional[Dict[str, Any]]:
        try:
            params = get_feeds(target_qq, g_tk, page=page, count=count, begintime=begintime)
            return await api_base_fixed._make_get_request(self.user_url, params, cookies)
        except Exception as e:
            logger.error(f'获取空间动态失败: {e}')
            return None

    async def _get_messages_list(self, target_qq: int, g_tk: int, cookies: str, pos: int = 0, num: int = 20) -> Optional[Dict[str, Any]]:
        try:
            params = get_self_zone(target_qq, g_tk, pos, num)
            return await api_base_fixed._make_get_request(self.self_url, params, cookies)
        except Exception as e:
            logger.error(f'获取说说列表失败: {e}')
            return None

    async def _send_comments(self, target_qq: int, uin: int, content: str, cookies: str, g_tk: str, fid: str) -> Optional[Dict[str, Any]]:
        try:
            params = get_send_comment(target_qq, uin, content, fid)
            url = f'{self.send_comments_url}?g_tk={g_tk}'
            return await api_base_fixed._make_post_request(url=url, data=params, cookies=cookies)
        except Exception as e:
            logger.error(f'发送说说评论失败: {e}')
            return None
