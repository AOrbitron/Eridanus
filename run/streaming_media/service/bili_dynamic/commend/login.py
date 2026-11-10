from bilibili_api import login_v2, sync, Credential, user, select_client
from bilibili_api.login_v2 import QrCodeLoginEvents
from bilibili_api.user import create_subscribe_group, set_subscribe_group,get_self_info
import asyncio
import os
import tempfile
from urllib.parse import parse_qs, quote, urlparse
from ..data import *
from ..utils import *
import requests
import httpx
from .monitor import loop_cache, check_credential
import datetime
from developTools.utils.logger import get_logger
logger=get_logger('bili_dynamic')
select_client("httpx")


_BILI_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
_BILI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
_BILI_QR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def _bili_new_read_response_cookies(response):
    """Extract cookies from both the response cookie jar and Set-Cookie headers."""
    cookies = dict(response.cookies.items())
    for header in response.headers.get_list("set-cookie"):
        cookie = header.split(";", 1)[0]
        if "=" in cookie:
            name, value = cookie.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies


def _bili_new_cookies_from_url(url):
    """Read credentials from the legacy crossDomain URL format, if present."""
    if not url:
        return {}
    query = parse_qs(urlparse(url).query)
    names = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
    cookies = {name: query[name][0] for name in names if query.get(name)}
    if cookies.get("SESSDATA"):
        cookies["SESSDATA"] = quote(cookies["SESSDATA"], safe="%")
    return cookies


def _bili_new_normalize_cookies(cookies):
    """Normalize cookie names from either Credential or browser-cookie format."""
    cookies = cookies or {}

    def get_value(*names):
        for name in names:
            value = cookies.get(name)
            if value not in (None, ""):
                return str(value)
        return ""

    return {
        "SESSDATA": get_value("SESSDATA", "sessdata"),
        "bili_jct": get_value("bili_jct", "BILI_JCT"),
        "buvid3": get_value("buvid3", "BUVID3"),
        "buvid4": get_value("buvid4", "BUVID4"),
        "DedeUserID": get_value("DedeUserID", "dedeuserid"),
        "ac_time_value": get_value("ac_time_value"),
    }


def _bili_new_cookie_header(cookies):
    return "; ".join(
        f"{key}={quote(str(value), safe='%') if key == 'SESSDATA' else value}"
        for key, value in cookies.items()
        if value not in (None, "")
    )


async def _bili_new_qr_login(bot=None, event=None):
    """Log in through the current web QR flow and capture the returned cookies."""
    recall_id = None
    qr_path = None
    try:
        async with httpx.AsyncClient(
            headers=_BILI_QR_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                _BILI_QR_GENERATE_URL,
                params={"source": "main-fe-header"},
            )
            response.raise_for_status()
            payload = response.json()
            qr_data = payload.get("data") or {}
            if payload.get("code") != 0 or not qr_data.get("url") or not qr_data.get("qrcode_key"):
                raise RuntimeError(f"二维码生成失败：{payload.get('message') or payload}")

            qr_url = qr_data["url"]
            qrcode_key = qr_data["qrcode_key"]
            try:
                import qrcode

                cache_dir = os.path.join("data", "pictures", "cache")
                os.makedirs(cache_dir, exist_ok=True)
                fd, generated_qr_path = tempfile.mkstemp(
                    prefix="bili_login_", suffix=".png", dir=cache_dir
                )
                os.close(fd)
                try:
                    qrcode.make(qr_url).save(generated_qr_path)
                    qr_path = generated_qr_path
                except Exception:
                    os.remove(generated_qr_path)
                    raise
            except Exception as exc:
                logger.warning(f"B站二维码图片生成失败，将仅显示二维码地址：{exc}")
                qr_path = None

            try:
                import qrcode_terminal

                qr_terminal = qrcode_terminal.qr_terminal_str(qr_url)
            except Exception:
                qr_terminal = qr_url

            if bot and event:
                message = ["请扫描下方二维码登录喵"]
                # message.append(Image(file=qr_path) if qr_path else qr_url)
                # recall_id = await bot.send(event, message)
                if qr_path is None: qr_path = qr_url
                recall_id = await bot.send(event, ['请扫描下方二维码登录喵', Image(file=qr_path)])
            else:
                print(qr_terminal)
                print(qr_path)
                print(qr_url)

            confirmed = False
            while True:
                response = await client.get(
                    _BILI_QR_POLL_URL,
                    params={"qrcode_key": qrcode_key, "source": "main-fe-header"},
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") or {}
                status = int(data.get("code", -1))
                logger.info_func(f"B站二维码状态：{status}")

                if status == 86101:
                    pass
                elif status == 86090:
                    if not confirmed:
                        confirmed = True
                        logger.info("B站二维码已扫码，等待确认登录")
                elif status == 86038:
                    msg = "B站登录二维码超时，请重新尝试喵"
                    if bot and event:
                        await bot.send(event, msg)
                    else:
                        print(msg)
                    return None, recall_id
                elif status == 0:
                    response_cookies = _bili_new_cookies_from_url(data.get("url", ""))
                    response_cookies.update(_bili_new_read_response_cookies(response))
                    response_cookies.update(dict(client.cookies.items()))

                    # New responses may contain only a cross-domain ticket. Follow
                    # that URL to receive the actual credentials via Set-Cookie.
                    if not response_cookies.get("SESSDATA") and data.get("url"):
                        try:
                            follow_response = await client.get(data["url"])
                            response_cookies.update(_bili_new_read_response_cookies(follow_response))
                            response_cookies.update(dict(client.cookies.items()))
                        except Exception as exc:
                            logger.warning(f"跟随 B 站跨域登录链接失败：{exc}")

                    normalized = _bili_new_normalize_cookies({
                        **response_cookies,
                        "ac_time_value": data.get("refresh_token", ""),
                    })
                    if not all((normalized["SESSDATA"], normalized["bili_jct"], normalized["DedeUserID"])):
                        raise RuntimeError("登录完成但未获取到完整的 SESSDATA、bili_jct 或 DedeUserID")
                    if not normalized["buvid3"]:
                        try:
                            from bilibili_api.utils.network import get_buvid

                            normalized["buvid3"], normalized["buvid4"] = await get_buvid()
                        except Exception as exc:
                            logger.warning(f"未能补充 buvid cookie：{exc}")
                    return normalized, recall_id
                else:
                    raise RuntimeError(f"B站二维码登录失败，状态码：{status}，响应：{payload}")

                await asyncio.sleep(2)
    finally:
        if qr_path:
            try:
                os.remove(qr_path)
            except OSError:
                pass


async def bili_login_new(bot=None, event=None, cookies=None, is_save=True):
    """新版 B 站二维码登录；is_save=False 时只登录并返回 cookie，不访问业务数据库。"""
    global loop_cache
    recall_id = None

    if cookies is None:
        try:
            cookies, recall_id = await _bili_new_qr_login(bot, event)
        except Exception as exc:
            logger.error(f"B站二维码登录失败：{exc}")
            msg = f"B站登录失败：{exc}"
            if bot and event:
                await bot.send(event, msg)
            else:
                print(msg)
            return None
        if cookies is None:
            return None
    else:
        cookies = _bili_new_normalize_cookies(cookies)
        if not all((cookies["SESSDATA"], cookies["bili_jct"], cookies["DedeUserID"])):
            msg = "传入的 B 站 cookies 字段不完整，请重新尝试喵"
            if bot and event:
                await bot.send(event, msg)
            else:
                print(msg)
            return None
        try:
            response = requests.get(
                "https://api.bilibili.com/x/relation/tags",
                headers={"Cookie": _bili_new_cookie_header(cookies), "User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            if response.json().get("code") == -101:
                msg = "您手动传入cookies无效，请重新尝试喵"
                if bot and event:
                    await bot.send(event, msg)
                else:
                    print(msg)
                return None
        except Exception as exc:
            logger.error(f"B站手动 cookies 检查失败：{exc}")
            msg = "B站 cookies 检查失败，请重新尝试喵"
            if bot and event:
                await bot.send(event, msg)
            else:
                print(msg)
            return None

    day_info = await date_get()
    info = await data_init()
    info["cookies"]["sessdata"] = cookies["SESSDATA"]
    info["cookies"]["bili_jct"] = cookies["bili_jct"]
    info["cookies"]["buvid3"] = cookies["buvid3"]
    info["cookies"]["dedeuserid"] = cookies["DedeUserID"]
    info["cookies"]["ac_time_value"] = cookies["ac_time_value"]
    info["cookies"]["subscribe_group_id"] = ""
    info["cookies"]["login_time"] = day_info["time"]
    loop_cache["is_refresh_data"] = True

    msg = "登录成功喵，正在处理相关数据喵"
    if bot and event:
        if recall_id:
            await bot.recall(recall_id["data"]["message_id"])
        recall_id = await bot.send(event, msg)
    logger.info(msg)
    msg = ''
    credential = Credential(
        sessdata=cookies["SESSDATA"],
        bili_jct=cookies["bili_jct"],
        buvid3=cookies["buvid3"],
        dedeuserid=cookies["DedeUserID"],
        ac_time_value=cookies["ac_time_value"],
    )
    try:
        response = requests.get(
            "https://api.bilibili.com/x/relation/tags",
            headers={"Cookie": _bili_new_cookie_header(credential.get_cookies()), "User-Agent": "Mozilla/5.0"},
            params={"csrf": cookies["bili_jct"]},
            timeout=30,
        )
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"接口返回码：{result.get('code')}")
        for group in result.get("data") or []:
            if group.get("name") == "Bot关注":
                info["cookies"]["subscribe_group_id"] = group["tagid"]
        if info["cookies"]["subscribe_group_id"] == "":
            subscribe_group_info = await create_subscribe_group("Bot关注", credential)
            info["cookies"]["subscribe_group_id"] = subscribe_group_info["tagid"]
            msg = "已成功创建 “Bot关注” 分组，"
        logger.info("相关分组已确认")
    except Exception as exc:
        msg = "用户关注分组创建失败，订阅up请手动关注喵"
        logger.error(f"用户关注分组创建失败: {exc}")
        if bot and event:
            await bot.send(event, msg)
        if is_save:
            await data_save(info)
        return cookies

    up_lists = [
        int(item) for item in info["dynamic_info"]
        if item.isdigit()
        and info["dynamic_info"][item]["enable"]
        and str(item) != str(info["cookies"]["dedeuserid"])
    ]
    if not up_lists:
        if bot and event:
            await bot.send(event, msg + "您此后所有订阅up都将分入此组喵")
        if is_save: await data_save(info)
        return cookies

    try:
        update_flag = False
        for up in up_lists:
            up_info = user.User(up, credential)
            relation = await up_info.get_relation()
            #print(relation)
            if relation["relation"]["attribute"] not in [2, 6]:
                update_flag = True
                await up_info.modify_relation(user.RelationType(1))
        if update_flag: await asyncio.sleep(5)
        await set_subscribe_group(up_lists, [info["cookies"]["subscribe_group_id"]], credential)
    except Exception as exc:
        msg += "\n相关up关注失败喵，bot订阅up请手动关注喵"
        logger.error(f"用户up主批量关注失败: {exc}")
        if bot and event:
            await bot.send(event, msg)
        if is_save: await data_save(info)
        return cookies

    if bot and event:
        await bot.send(event, msg + "所有订阅up都已完成关注并分组喵")
    if is_save: await data_save(info)
    return cookies


async def bili_login(bot = None, event = None, cookies = None) -> None:
    global loop_cache
    recall_id, cookies_check = None, ''
    day_info = await date_get()
    if cookies is None:
        qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB) # 生成二维码登录实例，平台选择网页端
        await qr.generate_qrcode()                                          # 生成二维码
        if not (bot and event):
            print(qr.get_qrcode_terminal())                                     # 生成终端二维码文本，打印
            print(qr.get_qrcode_picture().url)
        if bot and event:
            recall_id = await bot.send(event, ['请扫描下方二维码登录喵',Image(file=qr.get_qrcode_picture().url)])
        while not qr.has_done():                                            # 在完成扫描前轮询
            qr_status = await qr.check_state()
            if qr_status == QrCodeLoginEvents.TIMEOUT:
                msg = 'B站登录二维码超时，请重新尝试喵'
                if bot and event: await bot.send(event, msg)
                else: print(msg)
                return
            #print(await qr.check_state())                                   # 检查状态
            logger.info_func(f'B站二维码状态：{qr_status}')
            await asyncio.sleep(4)
        cookies = qr.get_credential().get_cookies()
    else:
        #若直接传入了cookies，则检测该cookies是否有效
        for item in cookies:
            cookies_check += f'{item}={cookies[item]};'
        resp = requests.get("https://api.bilibili.com/x/relation/tags",
                            headers={'Cookie': cookies_check, 'User-Agent': 'Mozilla/5.0'})
        res = resp.json()
        if res['code'] == -101:
            msg = '您手动传入cookies无效，请重新尝试喵'
            if bot and event: await bot.send(event, msg)
            else: print(msg)
            return

    info = await data_init()
    if not (bot and event): pprint.pprint(cookies)
    info['cookies']['sessdata'] = cookies['SESSDATA']
    info['cookies']['bili_jct'] = cookies['bili_jct']
    info['cookies']['buvid3'] = cookies['buvid3']
    info['cookies']['dedeuserid'] = cookies['dedeuserid']
    info['cookies']['ac_time_value'] = cookies['ac_time_value']
    info['cookies']['subscribe_group_id'] = ''
    info['cookies']['login_time'] = day_info['time']
    #await data_save(info)
    loop_cache['is_refresh_data'] = True
    msg = '登录成功喵，正在处理相关数据喵'
    if bot and event:
        if recall_id: await bot.recall(recall_id['data']['message_id'])
        recall_id = await bot.send(event, msg)
    logger.info(msg)
    #return
    msg = ''
    #获取对应up分组并创建一个保存的关注分组
    credential = Credential(sessdata=cookies['SESSDATA'], bili_jct=cookies['bili_jct'],
                            buvid3=cookies['buvid3'], dedeuserid=cookies['DedeUserID'])
    cookies_info = credential.get_cookies()
    for item in cookies_info:
        cookies_check += f'{item}={cookies_info[item]};'
    try:
        resp = requests.get("https://api.bilibili.com/x/relation/tags",
                            headers={'Cookie': cookies_check, 'User-Agent': 'Mozilla/5.0'},
                            params={'csrf': cookies['bili_jct'] })
        res = resp.json()
        for group in res['data']:
            if group['name'] == 'Bot关注':
                info['cookies']['subscribe_group_id'] = group['tagid']
        if info['cookies']['subscribe_group_id'] == '':
            subscribe_group_info = await create_subscribe_group('Bot关注', credential)
            info['cookies']['subscribe_group_id'] = subscribe_group_info['tagid']
            msg = '已成功创建 “Bot关注” 分组，'
        logger.info('相关分组已确认')
    except Exception as e:
        #创建失败，发出提醒后返回
        msg = '用户关注分组创建失败，订阅up请手动关注喵'
        logger.error(f'用户关注分组创建失败: {e}')
        if bot and event:
            await bot.send(event, msg)
        await data_save(info)
        return

    #新版要求在此处就要对所有bot的订阅up进行关注并分组
    #获取所有订阅的up主
    up_lists = [int(item) for item in info['dynamic_info'] if item.isdigit() and info['dynamic_info'][item]['enable'] and str(item) != str(info['cookies']['dedeuserid'])]
    if not up_lists:
        if bot and event:
            msg += '您此后所有订阅up都将分入此组'
            await bot.send(event, msg)
        await data_save(info)
        return
    # 这里将所有订阅up保证关注上
    try:
        for up in up_lists:
            up_info = user.User(up, credential)
            info_get_relation = await up_info.get_relation()
            if info_get_relation['relation']['attribute'] not in [2,6]:
                await up_info.modify_relation(user.RelationType(1))
            del up_info
        # 将所有订阅up主都添加到相应分组中
        await set_subscribe_group(up_lists, [info['cookies']['subscribe_group_id']], credential)
    except Exception as e:
        #关注分组失败，发出提醒后返回
        msg += '\n相关up关注失败喵，bot订阅up请手动关注喵'
        logger.error(f'用户up主批量关注失败: {e}')
        if bot and event:
            await bot.send(event, msg)
        await data_save(info)
        return
    #操作完成，发送信息
    if bot and event:
        msg += '所有订阅up都已完成关注并分组喵'
        await bot.send(event, msg)
    await data_save(info)
    return


#简易查询当前账号的状态
async def bili_up_status_check():
    global loop_cache
    data_info = await data_init()
    day_info = await date_get()
    #计算账号登录时间
    time_tamp = day_info['time'] - data_info['cookies']['login_time']
    days = time_tamp // 86400
    time_tamp %= 86400
    hours = time_tamp // 3600
    time_tamp %= 3600
    minutes = time_tamp // 60
    time_tamp %= 60
    user_info = data_info['dynamic_info'][f'up_info']
    user_info['time_msg'] = f"{days}天 {hours}时 {minutes}分 {time_tamp}秒"
    #计算上次检测的时间
    if user_info['check_time'] != '':
        user_info['check_time'] = datetime.datetime.fromtimestamp(int(user_info['check_time']))
    else:
        user_info['check_time'] = '未知'
    if loop_cache['check_time'] != '':
        user_info['monitor_time'] = datetime.datetime.fromtimestamp(int(loop_cache['check_time']))
    else:
        user_info['monitor_time'] = '未知'

    #检测其默认账号
    if data_info['cookies']['dedeuserid'] == '':
        user_info['status'] = False
        user_info['up_name'] = ''
        return user_info
    user_info['status'] = True
    up_info = user.User(int(data_info['cookies']['dedeuserid']))
    info = await up_info.get_user_info()
    user_info['up_name'] = info['name']
    credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
                            buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    # 检测credential需不需要刷新，此处缺少相关值无法自动刷新，只能重新登录
    if await check_credential(credential):
        #print(await check_credential(credential))
        user_info['status'] = False
    return user_info

if __name__ == '__main__':
    sync(bili_login())
