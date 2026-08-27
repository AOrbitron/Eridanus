import asyncio
import json
import re
import uuid
import httpx
import pprint
from typing import Any, Dict, Optional, Union
from framework_common.manshuo_draw import *
import traceback
from ..api.common import get_ltoken_by_stoken, get_cookie_token_by_stoken, get_device_fp, fetch_game_token_qrcode, \
    query_game_token_qrcode, \
    get_token_by_game_token, get_cookie_token_by_game_token
from ..model import PluginDataManager, plugin_config, UserAccount, UserData, CommandUsage, BBSCookies, \
    QueryGameTokenQrCodeStatus, GetCookieStatus
from ..utils import read_blacklist, read_whitelist, generate_device_id, generate_qr_img
from developTools.utils.logger import get_logger
logger=get_logger('MiHoYo')
import base64
from developTools.message.message_components import Text, Image, At
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase, cache_get, cache_save, cache_delete
db=asyncio.run(AsyncSQLiteDatabase.get_instance())

MIYOUSHE_QR_CREATE_URL = "https://passport-api.mihoyo.com/account/ma-cn-passport/web/createQRLogin"
MIYOUSHE_QR_QUERY_URL = "https://passport-api.mihoyo.com/account/ma-cn-passport/web/queryQRLoginStatus"
MIYOUSHE_PASSPORT_APP_ID = "bll8iq97cem8"
MIYOUSHE_PASSPORT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


def _collect_set_cookies(headers, fallback_cookies=None) -> str:
    cookies: Dict[str, str] = {}
    raw_values = []
    if hasattr(headers, "get_list"):
        raw_values = headers.get_list("set-cookie")
    if not raw_values and hasattr(headers, "get"):
        raw_value = headers.get("set-cookie")
        raw_values = [raw_value] if raw_value else []

    for raw_value in raw_values:
        if not raw_value:
            continue
        for match in re.finditer(r"(?:^|,\s*)([^=;,\s]+)=([^;,]*)", raw_value):
            cookies[match.group(1)] = match.group(2)

    if fallback_cookies:
        for key, value in dict(fallback_cookies).items():
            if value:
                cookies.setdefault(str(key), str(value))
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _parse_cookie_string(cookie: str) -> Dict[str, str]:
    cookie_data: Dict[str, str] = {}
    for part in str(cookie or "").split(";"):
        item = part.strip()
        if not item:
            continue
        name, separator, value = item.partition("=")
        if separator:
            cookie_data[name.strip()] = value.strip()
    return cookie_data


def _miyoushe_account_uid(cookie_data: Dict[str, Any]) -> Optional[str]:
    for key in ("account_id", "stuid", "ltuid", "login_uid", "account_id_v2", "ltuid_v2", "ltmid_v2"):
        value = cookie_data.get(key)
        if value:
            return str(value)
    return None


def _build_bbs_cookies(cookie_data: Dict[str, str], bbs_uid: str) -> BBSCookies:
    cookies = BBSCookies()
    cookies.bbs_uid = bbs_uid
    if cookie_data.get("stoken"):
        cookies.stoken = cookie_data["stoken"]
    cookies.stoken_v1 = cookie_data.get("stoken_v1") or cookies.stoken_v1
    cookies.stoken_v2 = cookie_data.get("stoken_v2") or cookies.stoken_v2
    cookies.cookie_token = cookie_data.get("cookie_token")
    cookies.cookie_token_v2 = cookie_data.get("cookie_token_v2")
    cookies.ltoken = cookie_data.get("ltoken")
    cookies.ltoken_v2 = cookie_data.get("ltoken_v2")
    cookies.login_ticket = cookie_data.get("login_ticket")
    cookies.mid = cookie_data.get("mid") or cookie_data.get("account_mid_v2") or cookie_data.get("ltmid_v2")
    cookies.aliyungf_tc = cookie_data.get("aliyungf_tc")
    cookies.account_id = cookie_data.get("account_id") or cookie_data.get("account_id_v2") or bbs_uid
    cookies.ltuid = cookie_data.get("ltuid") or cookie_data.get("ltuid_v2") or bbs_uid
    cookies.stuid = cookie_data.get("stuid") or bbs_uid
    cookies.login_uid = cookie_data.get("login_uid") or bbs_uid
    return cookies


def _update_bbs_cookies(target: BBSCookies, source: BBSCookies) -> BBSCookies:
    for key in source.__fields__:
        value = getattr(source, key, None)
        if value is not None:
            setattr(target, key, value)
    return target


def _passport_qr_headers(device_id: str) -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": MIYOUSHE_PASSPORT_UA,
        "x-rpc-app_id": MIYOUSHE_PASSPORT_APP_ID,
        "x-rpc-device_id": device_id,
    }


async def mys_login_new(user_id,bot=None,event=None,config=None):
    recall_id = None
    await cache_delete(db, 'skland', str(user_id))
    user_id = str(user_id)
    user_num = len(set(PluginDataManager.plugin_data.users.values()))
    if user_num > plugin_config.preference.max_user and plugin_config.preference.max_user not in [-1, 0]:
        if bot: await bot.send(event, '⚠️目前可支持使用用户数已经满啦~')
        else: print('⚠️目前可支持使用用户数已经满啦~')
        return False

    PluginDataManager.plugin_data.users.setdefault(user_id, UserData())
    user = PluginDataManager.plugin_data.users[user_id]
    if config is not None and bot:
        if config.common_config.basic_config["master"]["id"] == 1270858640:
            from run.manshuo_test.core import bot_http
            await bot_http.set_msg_emoji_like(event, 282)
        else:
            recall_id = await bot.send(event, '正在获取登录二维码，请稍后喵')
    else:
        print('正在获取登录二维码，请稍后喵')

    device_id = generate_device_id()
    headers = _passport_qr_headers(device_id)
    try:
        async with httpx.AsyncClient(timeout=plugin_config.preference.timeout) as client:
            response = await client.post(url=MIYOUSHE_QR_CREATE_URL, headers=headers, json={})
        data = response.json()
        if data.get("retcode") != 0:
            msg = data.get("message") or "无法创建米游社登录二维码"
            if bot: await bot.send(event, [At(qq=user_id), f" 登录失败喵：{msg}"])
            else: print(f"登录失败喵：{msg}")
            return False

        qrcode_url = (data.get("data") or {}).get("url")
        qrcode_ticket = (data.get("data") or {}).get("ticket")
        if not qrcode_url or not qrcode_ticket:
            msg = "米游社未返回完整的二维码信息"
            if bot: await bot.send(event, [At(qq=user_id), f" 登录失败喵：{msg}"])
            else: print(f"登录失败喵：{msg}")
            return False

        image_bytes = generate_qr_img(qrcode_url)
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        img_path = await manshuo_draw([{'type': 'img', 'img': [base64_data]}])
        if recall_id and bot:
            await bot.recall(recall_id['data']['message_id'])
            recall_id = None
        if bot and event:
            msg = [At(qq=user_id),
                   " 请用米游社App扫描下面的二维码进行登录\n二维码有效时间两分钟，请不要扫描他人的登录二维码进行绑定~",
                   Image(file=img_path)]
            recall_id = await bot.send(event, msg)
        else:
            print(img_path)

        qrcode_query_times = round(
            plugin_config.preference.qrcode_wait_time / plugin_config.preference.qrcode_query_interval
        )
        scanned = False
        cookie_text = ""
        for _ in range(max(1, qrcode_query_times)):
            async with httpx.AsyncClient(timeout=plugin_config.preference.timeout) as client:
                response = await client.post(
                    url=MIYOUSHE_QR_QUERY_URL,
                    headers=headers,
                    json={"ticket": qrcode_ticket}
                )
            data = response.json()
            retcode = data.get("retcode")
            message = str(data.get("message") or "")
            status = (data.get("data") or {}).get("status")
            if retcode != 0:
                if retcode in (-3501, -106, -1002) or "过期" in message:
                    if bot: await bot.send(event, [At(qq=user_id), " 扫码超时喵，请重新绑定喵 "])
                    else: print(" 扫码超时喵，请重新绑定喵 ")
                    return False
                if retcode == -3505:
                    if bot: await bot.send(event, [At(qq=user_id), " 您已取消扫码喵"])
                    else: print(" 您已取消扫码喵")
                    return False
                raise RuntimeError(message or f"米游社扫码状态异常：{retcode}")
            if status in ("Created", "Init"):
                await asyncio.sleep(plugin_config.preference.qrcode_query_interval)
                continue
            if status == "Scanned":
                if not scanned:
                    logger.info(f"{plugin_config.preference.log_head}米游社二维码已扫描，等待确认")
                    scanned = True
                await asyncio.sleep(plugin_config.preference.qrcode_query_interval)
                continue
            if status != "Confirmed":
                raise RuntimeError(f"未知的米游社扫码状态：{status or '空'}")

            cookie_text = _collect_set_cookies(response.headers, response.cookies)
            break

        if not cookie_text:
            if bot: await bot.send(event, [At(qq=user_id), " 等待扫码确认超时，请重新绑定喵"])
            else: print(" 等待扫码确认超时，请重新绑定喵")
            return False

        cookie_data = _parse_cookie_string(cookie_text)
        bbs_uid = _miyoushe_account_uid(cookie_data)
        if not bbs_uid or not (cookie_data.get("cookie_token") or cookie_data.get("cookie_token_v2")):
            msg = "扫码已确认，但米游社未返回完整登录态"
            if bot: await bot.send(event, [At(qq=user_id), f" 登录失败喵：{msg}"])
            else: print(f"登录失败喵：{msg}")
            return False

        cookies_save = _build_bbs_cookies(cookie_data, bbs_uid)
        account = user.accounts.get(bbs_uid)
        if not account or not account.cookies:
            user.accounts.update({
                bbs_uid: UserAccount(
                    phone_number=None,
                    cookies=cookies_save,
                    device_id_ios=device_id,
                    device_id_android=generate_device_id())
            })
            account = user.accounts[bbs_uid]
        else:
            _update_bbs_cookies(account.cookies, cookies_save)
            account.device_id_ios = device_id
            account.device_id_android = account.device_id_android or generate_device_id()

        fp_status, account.device_fp = await get_device_fp(account.device_id_ios or device_id)
        if fp_status:
            logger.info(f"用户 {bbs_uid} 成功获取 device_fp: {account.device_fp}")
        PluginDataManager.write_plugin_data()
        await cache_delete(db, 'mihuyo', str(user_id))
        logger.info(f"{plugin_config.preference.log_head}米游社账户 {bbs_uid} 绑定成功")
        if bot: await bot.send(event, [At(qq=user_id), f" 欢迎，米游社用户： （{bbs_uid}） "])
        else: print(f"欢迎，米游社用户： （{bbs_uid}）")
        return True
    except Exception as e:
        logger.error(f"{plugin_config.preference.log_head}米游社扫码登录失败: {e}")
        traceback.print_exc()
        msg = f"登录失败喵：{e}"
        if bot: await bot.send(event, [At(qq=user_id), msg])
        else: print(msg)
        return False
    finally:
        if recall_id and bot:
            await bot.recall(recall_id['data']['message_id'])

async def _mys_login_new_old1(user_id,bot=None,event=None):
    recall_id = None
    # 清除相关缓存
    await cache_delete(db, 'skland', str(user_id))
    user_num = len(set(PluginDataManager.plugin_data.users.values()))  # 由于加入了用户数据绑定功能，可能存在重复的用户数据对象，需要去重
    if user_num <= plugin_config.preference.max_user or plugin_config.preference.max_user in [-1, 0]:
        # 获取用户数据对象
        PluginDataManager.plugin_data.users.setdefault(user_id, UserData())
        user = PluginDataManager.plugin_data.users[user_id]
        if bot:recall_id = await bot.send(event, '正在获取登录二维码，请稍后喵')
        # 1. 获取 GameToken 登录二维码
        device_id = generate_device_id()
        #print(device_id, plugin_config.preference.game_token_app_id)
        login_status, fetch_qrcode_ret = await fetch_game_token_qrcode(
            device_id,
            plugin_config.preference.game_token_app_id
        )
        #print(login_status, fetch_qrcode_ret)
        if fetch_qrcode_ret:
            qrcode_url, qrcode_ticket = fetch_qrcode_ret
            image_bytes = generate_qr_img(qrcode_url)
            base64_data = base64.b64encode(image_bytes).decode("utf-8")
            img_path = await manshuo_draw([{'type': 'img', 'img': [base64_data]}])
            if recall_id: await bot.recall(recall_id['data']['message_id'])
            if bot and event:
                msg = [At(qq=user_id),
                       " 请用米游社App扫描下面的二维码进行登录\n二维码有效时间两分钟，请不要扫描他人的登录二维码进行绑定~",
                       Image(file=img_path)]
                recall_id = await bot.send(event, msg)
            else:
                recall_id = None
                print(img_path)

            # 2. 从二维码登录获取 GameToken
            qrcode_query_times = round(
                plugin_config.preference.qrcode_wait_time / plugin_config.preference.qrcode_query_interval
            )
            bbs_uid, game_token = None, None
            for _ in range(qrcode_query_times):
                login_status, query_qrcode_ret = await query_game_token_qrcode(
                    qrcode_ticket,
                    device_id,
                    plugin_config.preference.game_token_app_id
                )
                #print(login_status, query_qrcode_ret)
                if query_qrcode_ret:
                    bbs_uid, game_token = query_qrcode_ret
                    logger.info(f"用户 {bbs_uid} 成功获取 game_token: {game_token}")
                    break
                elif login_status.qrcode_expired:
                    if bot: await bot.send(event, "⚠️二维码已过期，登录失败")
                    break
                elif not login_status:
                    await asyncio.sleep(plugin_config.preference.qrcode_query_interval)
                    continue

            if recall_id: await bot.recall(recall_id['data']['message_id'])

            if bbs_uid and game_token:
                cookies = BBSCookies()
                cookies.bbs_uid = bbs_uid
                account = PluginDataManager.plugin_data.users[user_id].accounts.get(bbs_uid)
                """当前的账户数据对象"""
                if not account or not account.cookies:
                    user.accounts.update({
                        bbs_uid: UserAccount(
                            phone_number=None,
                            cookies=cookies,
                            device_id_ios=device_id,
                            device_id_android=generate_device_id())
                    })
                    account = user.accounts[bbs_uid]
                else:
                    account.cookies.update(cookies)
                fp_status, account.device_fp = await get_device_fp(device_id)
                if fp_status:
                    logger.info(f"用户 {bbs_uid} 成功获取 device_fp: {account.device_fp}")
                PluginDataManager.write_plugin_data()

                if login_status:
                    # 3. 通过 GameToken 获取 stoken_v2
                    login_status, cookies = await get_token_by_game_token(bbs_uid, game_token)
                    if login_status:
                        logger.info(f"用户 {bbs_uid} 成功获取 stoken_v2: {cookies.stoken_v2}")
                        account.cookies.update(cookies)
                        PluginDataManager.write_plugin_data()

                        if account.cookies.stoken_v2:
                            # 5. 通过 stoken_v2 获取 ltoken
                            login_status, cookies = await get_ltoken_by_stoken(account.cookies, device_id)
                            if login_status:
                                logger.info(f"用户 {bbs_uid} 成功获取 ltoken: {cookies.ltoken}")
                                account.cookies.update(cookies)
                                PluginDataManager.write_plugin_data()

                            # 6.1. 通过 stoken_v2 获取 cookie_token
                            login_status, cookies = await get_cookie_token_by_stoken(account.cookies, device_id)
                            if login_status:
                                logger.info(f"用户 {bbs_uid} 成功获取 cookie_token: {cookies.cookie_token}")
                                account.cookies.update(cookies)
                                PluginDataManager.write_plugin_data()
                                logger.info(
                                    f"{plugin_config.preference.log_head}米游社账户 {bbs_uid} 绑定成功")
                                if bot: await bot.send(event, [At(qq=user_id),f" 欢迎，米游社用户： （{bbs_uid}） "])
                        else:
                            # 6.2. 通过 GameToken 获取 cookie_token
                            login_status, cookies = await get_cookie_token_by_game_token(bbs_uid, game_token)
                            if login_status:
                                logger.info(f"用户 {bbs_uid} 成功获取 cookie_token: {cookies.cookie_token}")
                                account.cookies.update(cookies)
                                PluginDataManager.write_plugin_data()
            else:
                logger.error("获取二维码扫描状态超时，请尝试重新登录")
                #if bot: await bot.send(event, "获取二维码扫描状态超时，请尝试重新登录")

        if not login_status:
            notice_text = "登录失败喵："
            if isinstance(login_status, QueryGameTokenQrCodeStatus):
                if login_status.qrcode_expired:
                    notice_text += "登录二维码已过期！"
            if isinstance(login_status, GetCookieStatus):
                if login_status.missing_bbs_uid:
                    notice_text += "Cookies缺少 bbs_uid（例如 ltuid, stuid）"
                elif login_status.missing_login_ticket:
                    notice_text += "Cookies缺少 login_ticket！"
                elif login_status.missing_cookie_token:
                    notice_text += "Cookies缺少 cookie_token！"
                elif login_status.missing_stoken:
                    notice_text += "Cookies缺少 stoken！"
                elif login_status.missing_stoken_v1:
                    notice_text += "Cookies缺少 stoken_v1"
                elif login_status.missing_stoken_v2:
                    notice_text += "Cookies缺少 stoken_v2"
                elif login_status.missing_mid:
                    notice_text += "Cookies缺少 mid"
            if login_status.login_expired:
                notice_text += "登录失效！"
            elif login_status.incorrect_return:
                notice_text += "服务器返回错误！"
            elif login_status.network_error:
                notice_text += "网络连接失败！"
            else:
                notice_text += "未知错误！"
            #notice_text += " 如果部分步骤成功，你仍然可以尝试获取收货地址、兑换等功能"
            if bot: await bot.send(event, notice_text)
            else:print(notice_text)
    else:
        if bot: await bot.send(event, '⚠️目前可支持使用用户数已经满啦~')


async def _mys_login_new_old2(user_id,bot=None,event=None,config=None):
    recall_id = None
    # 清除相关缓存
    await cache_delete(db, 'skland', str(user_id))
    user_num = len(set(PluginDataManager.plugin_data.users.values()))  # 由于加入了用户数据绑定功能，可能存在重复的用户数据对象，需要去重
    if user_num <= plugin_config.preference.max_user or plugin_config.preference.max_user in [-1, 0]:
        # 获取用户数据对象
        PluginDataManager.plugin_data.users.setdefault(user_id, UserData())
        user = PluginDataManager.plugin_data.users[user_id]
        if config is not None and bot:
            if config.common_config.basic_config["master"]["id"] == 1270858640:
                from run.manshuo_test.core import bot_http
                await bot_http.set_msg_emoji_like(event, 282)
            else:
                recall_id = await bot.send(event, '正在获取登录二维码，请稍后喵')
        else:print('正在获取登录二维码，请稍后喵')
        uuid_d = uuid.uuid4()
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
            "x-rpc-app_id": "bll8iq97cem8",
            'x-rpc-device_fp': f'38d80bb76ee47',
            "x-rpc-device_id": f"{uuid_d}"
        }
        creat_qr_url = "https://passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin"
        async with httpx.AsyncClient() as client:
            r = await client.post(url=creat_qr_url, headers=headers)
            data = r.json()
            #await create_qr(data["data"]['url'], user_id)
            qrcode_url, qrcode_ticket = data["data"]['url'], data["data"]["ticket"]
            image_bytes = generate_qr_img(qrcode_url)
            base64_data = base64.b64encode(image_bytes).decode("utf-8")
            img_path = await manshuo_draw([{'type': 'img', 'img': [base64_data]}])
            #print(img_path)
            if bot and event:
                msg = [At(qq=user_id),
                       " 请用米游社App扫描下面的二维码进行登录\n二维码有效时间两分钟，请不要扫描他人的登录二维码进行绑定~",
                       Image(file=img_path)]
                recall_id = await bot.send(event, msg)
            else:
                recall_id = None
                print(img_path)

        while True:
            check_qr_url = "https://passport-api.miyoushe.com/account/ma-cn-passport/web/queryQRLoginStatus"
            async with httpx.AsyncClient() as client:
                r = await client.post(url=check_qr_url, headers=headers, json={"ticket": qrcode_ticket})
                cookies_check = r.cookies
                data: dict = r.json()
                cookies_json = json.dumps(dict(r.cookies), indent=4)
                record = data["retcode"]
                status_data: dict = data.get("data", {})
                if status_data == None:
                    status = None
                else:
                    status = status_data.get("status", None)
                #print(status)
                if record == -3501:
                    if bot: await bot.send(event, [At(qq=user_id), f" 扫码超时喵，请重新绑定喵 "])
                    else:print(f" 扫码超时喵，请重新绑定喵 ")
                    break
                elif record == -3505:
                    if bot: await bot.send(event, [At(qq=user_id), f" 您已取消扫码喵"])
                    break
                if status != "Confirmed":
                    await asyncio.sleep(1)
                    continue
            if recall_id: await bot.recall(recall_id['data']['message_id'])
            #print('扫码成功，开始创建游戏数据')
            cookies = json.loads(cookies_json)
            #pprint.pprint(cookies)

            #开始创建保存数据
            bbs_uid = cookies['account_id']
            cookies_save = BBSCookies()
            cookies_save.bbs_uid = bbs_uid
            account = PluginDataManager.plugin_data.users[str(user_id)].accounts.get(bbs_uid)
            """当前的账户数据对象"""
            if not account or not account.cookies:
                user.accounts.update({
                    bbs_uid: UserAccount(
                        phone_number=None,
                        cookies=cookies_save,
                        device_id_ios=str(uuid_d),
                        device_id_android=generate_device_id())
                })
                account = user.accounts[bbs_uid]
            else:
                account.cookies.update(cookies_save)

            fp_status, account.device_fp = await get_device_fp(uuid_d)
            if fp_status:
                logger.info(f"用户 {bbs_uid} 成功获取 device_fp: {account.device_fp}")
            #开始获取Stoken
            # mihoyobbs_version = '2.99.1'
            # mihoyobbs_Client_type_web = '5'
            # Stoken_headers = {
            #     'Accept': 'application/json, text/plain, */*',
            #     'DS': "",
            #     "x-rpc-channel": "miyousheluodi",
            #     'Origin': 'https://webstatic.mihoyo.com',
            #     'x-rpc-app_version': mihoyobbs_version,
            #     'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Unspecified Device) AppleWebKit/537.36 (KHTML, like Gecko) '
            #                   f'Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{mihoyobbs_version}',
            #     'x-rpc-client_type': mihoyobbs_Client_type_web,
            #     'Referer': '',
            #     'Accept-Encoding': 'gzip, deflate',
            #     'Accept-Language': 'zh-CN,en-US;q=0.8',
            #     'X-Requested-With': 'com.mihoyo.hyperion',
            #     "Cookie": f'{cookies_check}',
            #     'x-rpc-device_id': f"{uuid_d}"
            # }
            # Stoken_url = f"https://api-takumi.mihoyo.com/auth/api/getMultiTokenByLoginTicket"
            # async with httpx.AsyncClient() as client:
            #     r = await client.get(url=Stoken_url, headers=Stoken_headers,params={"login_ticket": qrcode_ticket, "token_types": "3", "uid": bbs_uid})
            #     stoken_data = r.json()
            #
            # pprint.pprint(stoken_data)
            # if stoken_data["retcode"] == 0:
            #     return data["data"]["list"][0]["token"]

            cookies_save.cookie_token, cookies_save.cookie_token_v2 = cookies.get('cookie_token',None), cookies.get('cookie_token_v2',None)
            #cookies_save.stoken_v2 = cookies['ltoken_v2']
            cookies_save.ltoken, cookies_save.ltoken_v2 = cookies.get('ltoken',None), cookies.get('ltoken_v2',None)
            cookies_save.stuid, cookies_save.ltuid, cookies_save.account_id, cookies_save.login_uid = bbs_uid, bbs_uid, bbs_uid, bbs_uid
            cookies_save.mid = cookies.get('account_mid_v2',None)
            cookies_save.aliyungf_tc = cookies.get('aliyungf_tc',None)
            account.cookies.update(cookies_save)
            PluginDataManager.write_plugin_data()
            if bot: await bot.send(event, [At(qq=user_id), f" 欢迎，米游社用户： （{bbs_uid}） "])
            break
