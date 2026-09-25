# -*- coding: utf-8 -*-
import base64
import json
from typing import Optional, Dict, Any

from qzone_api import QzoneApi
from qzone_api.api.api_parms import get_feeds, get_self_zone

from run.qq_zone.service.QzoneResponseParser import QzoneResponseParser
from loguru import logger
from run.qq_zone.service.custom_api_base import ApiBaseFixed

api_base_fixed = ApiBaseFixed()


def format_cookies(cookies: Any) -> tuple[dict, str]:
    """统一将 cookies 转换为 (dict, str)，并确保包含核心 Cookie 字段"""
    if isinstance(cookies, dict):
        c_dict = cookies.copy()
    elif isinstance(cookies, str):
        c_dict = {}
        for item in cookies.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                c_dict[k.strip()] = v.strip()
    else:
        c_dict = {}

    c_str = "; ".join([f"{k}={v}" for k, v in c_dict.items()])
    return c_dict, c_str


class QzoneApiFixed(QzoneApi):

    async def _send_zone(self, target_qq: int, content: str, cookies: Any, g_tk: int) -> Optional[Dict[str, Any]]:
        _, cookies_str = format_cookies(cookies)
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
            return await api_base_fixed._make_post_request(url=url, data=params, cookies=cookies_str)
        except Exception as e:
            logger.error(f'发送纯文字说说失败: {e}')
            return None

    async def _send_zone_with_pic(self, target_qq: int, pic_path: str, content: str, cookies: Any, g_tk: int) -> Optional[Dict[str, Any]]:
        try:
            with open(pic_path, 'rb') as f:
                image_data = f.read()
                base64_image = base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            logger.error(f'读取图片失败: {e}')
            return None

        cookies_dict, cookies_str = format_cookies(cookies)

        skey = cookies_dict.get('skey', '')
        p_skey = cookies_dict.get('p_skey', '')
        p_uin = cookies_dict.get('p_uin') or f"o{target_qq}"

        upload_url = f'https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk={g_tk}'

        form_data = {
            'filename': 'filename',
            'uin': target_qq,
            'skey': skey,
            'zzpaneluin': target_qq,
            'zzpanelkey': '',
            'p_uin': p_uin,
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

    async def _get_zone(self, target_qq: int, g_tk: int, cookies: Any, page: int = 1, count: int = 10, begintime: int = 0) -> Optional[Dict[str, Any]]:
        try:
            _, cookies_str = format_cookies(cookies)
            params = get_feeds(target_qq, g_tk, page=page, count=count, begintime=begintime)
            return await api_base_fixed._make_get_request(self.user_url, params, cookies_str)
        except Exception as e:
            logger.error(f'获取空间动态失败: {e}')
            return None

    async def _get_messages_list(self, target_qq: int, g_tk: int, cookies: Any, pos: int = 0, num: int = 20) -> Optional[Dict[str, Any]]:
        try:
            _, cookies_str = format_cookies(cookies)
            params = get_self_zone(target_qq, g_tk, pos, num)
            return await api_base_fixed._make_get_request(self.self_url, params, cookies_str)
        except Exception as e:
            logger.error(f'获取说说列表失败: {e}')
            return None

    async def _send_comments(
        self,
        target_qq: int,
        uin: int,
        content: str,
        cookies: Any,
        g_tk: Any,
        fid: str,
        comment_id: Optional[str] = None,
        comment_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        发送说说评论或楼中楼回复
        - target_qq: 发说说的博主QQ (hostUin)
        - uin: 评论者QQ (被回复者QQ)
        - fid: 说说 tid
        - comment_id: 如果是楼中楼回复，传入被回复的那条评论ID (cid)
        - comment_name: 被回复人的昵称，用于前缀艾特与正文格式化
        """
        try:
            _, cookies_str = format_cookies(cookies)
            
            # QQ空间接口标准：topicId 必须是 hostUin_tid 形式
            clean_fid = str(fid).split("_")[-1] if "_" in str(fid) else str(fid)
            topic_id = f"{target_qq}_{clean_fid}"
            
            # 清理正文可能已自带的普通 @昵称 前缀，替换为 QQ空间标准 UBB @ 标签
            final_content = content.strip()
            if comment_name and final_content.startswith(f"@{comment_name}"):
                final_content = final_content[len(f"@{comment_name}"):].strip()
            elif final_content.startswith("@"):
                import re
                final_content = re.sub(r"^@[^ ]+\s*", "", final_content).strip()

            # QQ空间标准艾特语法格式：@{uin:QQ号,nick:昵称,who:1}
            # 这种格式在网页端、手机QQ空间中能真正渲染成带链接的高亮艾特，并给被艾特者发送空间提醒
            if uin and comment_name:
                ubb_at = f"@{{uin:{uin},nick:{comment_name},who:1}} "
                final_content = ubb_at + final_content

            params = {
                "uin": target_qq,          # 当前登录操作者QQ
                "hostUin": target_qq,      # 说说所属博主QQ
                "feedsType": 100,
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "topicId": topic_id,
                "plat": "qzone",
                "source": "ic",
                "platformid": 50,
                "format": "fs",
                "ref": "feeds",
                "content": final_content,
                "qzreferrer": f"https://user.qzone.qq.com/{target_qq}"
            }

            # 楼中楼/定向二级回复必须携带的字段
            if comment_id:
                params["comment_uin"] = str(uin)
                params["comment_id"] = str(comment_id)
                params["t1_source"] = 1
                params["t1_uin"] = target_qq
                params["t1_tid"] = clean_fid
            elif uin and int(uin) != target_qq:
                params["comment_uin"] = str(uin)

            url = f"{self.send_comments_url}?g_tk={g_tk}"
            return await api_base_fixed._make_post_request(url=url, data=params, cookies=cookies_str)
        except Exception as e:
            logger.error(f"发送说说评论失败: {e}")
            return None
