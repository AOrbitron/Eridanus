import asyncio
import hashlib
import json
import re
import secrets
import httpx
import threading
import time as time_module
import urllib.parse
from typing import Any, List, Union, Optional, Iterable, Dict
from pydantic import BaseModel
from framework_common.manshuo_draw import *
from ..api import BaseGameSign
from ..api import BaseMission, get_missions_state
from ..api.common import genshin_note, get_game_record, starrail_note
from ..model import (MissionStatus, PluginDataManager, plugin_config, UserData, CommandUsage, GenshinNoteNotice,
                     StarRailNoteNotice)
import pprint
from developTools.utils.logger import get_logger
logger=get_logger('MiHoYo')
from developTools.message.message_components import Text, Image, At
import traceback
import copy
import os
from datetime import datetime, timedelta, time
from .config import game_name_list, game_all_list
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase, cache_get, cache_save, cache_init
db=asyncio.run(AsyncSQLiteDatabase.get_instance())

DEFAULT_SIGN_API_BASE = "https://api-takumi.mihoyo.com/event/luna"
RECORD_URL = "https://api-takumi-record.mihoyo.com/game_record/card/wapi/getGameRecordCard"
DS_SALT_IOS = "9ttJY72HxbjwWRNHJvn0n2AYue47nYsK"
MIYOUSHE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) miHoYoBBS/2.63.1"
)
MIYOUSHE_GAMES = {
    2: {
        "key": "genshin",
        "name": "原神",
        "en_name": "GenshinImpact",
        "act_id": "e202311201442471",
        "sign_game": "hk4e",
    },
    1: {
        "key": "honkai3",
        "name": "崩坏3",
        "en_name": "HonkaiImpact3",
        "act_id": "e202306201626331",
    },
    3: {
        "key": "houkai2",
        "name": "崩坏学园2",
        "en_name": "HoukaiGakuen2",
        "act_id": "e202203291431091",
    },
    4: {
        "key": "themis",
        "name": "未定事件簿",
        "en_name": "TearsOfThemis",
        "act_id": "e202202251749321",
    },
    6: {
        "key": "starrail",
        "name": "崩坏：星穹铁道",
        "en_name": "StarRail",
        "act_id": "e202304121516551",
    },
    8: {
        "key": "zzz",
        "name": "绝区零",
        "en_name": "ZenlessZoneZero",
        "act_id": "e202406242138391",
        "sign_game": "zzz",
        "api_base": "https://act-nap-api.mihoyo.com/event/luna/zzz",
    },
}
SIGN_RESULT_LABELS = {
    "success": "签到成功",
    "already-done": "已签到",
    "auth-expired": "登录失效",
    "risk-control": "触发验证码",
    "retryable": "暂时失败",
    "permanent-failure": "签到失败",
}


def _create_sign_ds() -> str:
    timestamp = str(int(time_module.time()))
    random_text = secrets.token_hex(4)[:6]
    checksum = hashlib.md5(
        f"salt={DS_SALT_IOS}&t={timestamp}&r={random_text}".encode("utf-8")
    ).hexdigest()
    return f"{timestamp},{random_text},{checksum}"


def _account_cookie_dict(account) -> Dict[str, str]:
    cookies = account.cookies
    cookie_data: Dict[str, str] = {}
    for key in (
        "stuid", "ltuid", "account_id", "login_uid", "cookie_token", "cookie_token_v2",
        "aliyungf_tc", "login_ticket", "ltoken", "ltoken_v2", "mid",
    ):
        value = getattr(cookies, key, None)
        if value:
            cookie_data[key] = str(value)
    if cookies.bbs_uid:
        cookie_data.setdefault("stuid", str(cookies.bbs_uid))
        cookie_data.setdefault("ltuid", str(cookies.bbs_uid))
        cookie_data.setdefault("account_id", str(cookies.bbs_uid))
        cookie_data.setdefault("login_uid", str(cookies.bbs_uid))
    if cookies.stoken_v2 or cookies.stoken_v1:
        cookie_data["stoken"] = str(cookies.stoken_v2 or cookies.stoken_v1)
    if cookies.cookie_token_v2 and cookies.bbs_uid:
        cookie_data.setdefault("account_id_v2", str(cookies.bbs_uid))
        cookie_data.setdefault("ltuid_v2", str(cookies.bbs_uid))
    if cookies.mid:
        cookie_data.setdefault("account_mid_v2", str(cookies.mid))
        cookie_data.setdefault("ltmid_v2", str(cookies.mid))
    return cookie_data


def _account_cookie_text(account) -> str:
    cookie_data = _account_cookie_dict(account)
    return "; ".join(f"{key}={value}" for key, value in cookie_data.items() if value)


def _record_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": MIYOUSHE_USER_AGENT,
        "Origin": "https://webstatic.mihoyo.com",
        "Referer": "https://webstatic.mihoyo.com/",
    }


def _sign_headers(account, metadata: Dict[str, Any]) -> Dict[str, str]:
    headers = {
        **_record_headers(),
        "Content-Type": "application/json;charset=utf-8",
        "x-rpc-app_version": "2.63.1",
        "x-rpc-channel": "appstore",
        "x-rpc-client_type": "5",
        "x-rpc-device_id": str(account.device_id_ios or account.device_id_android),
        "x-rpc-device_model": "iPhone10,2",
        "x-rpc-device_name": "iPhone",
        "x-rpc-platform": "ios",
        "x-rpc-sys_version": "16.2",
        "DS": _create_sign_ds(),
        "Cookie": _account_cookie_text(account),
    }
    if metadata.get("sign_game"):
        headers["x-rpc-signgame"] = str(metadata["sign_game"])
    if metadata.get("key") in ("genshin", "zzz"):
        headers["Origin"] = "https://act.mihoyo.com"
        headers["Referer"] = "https://act.mihoyo.com/"
    if metadata.get("key") == "zzz":
        headers["Host"] = "act-nap-api.mihoyo.com"
    return headers


def _reward_headers(account, metadata: Dict[str, Any]) -> Dict[str, str]:
    headers = {**_record_headers(), "Cookie": _account_cookie_text(account)}
    if metadata.get("sign_game"):
        headers["x-rpc-signgame"] = str(metadata["sign_game"])
    if metadata.get("key") in ("genshin", "zzz"):
        headers["Origin"] = "https://act.mihoyo.com"
        headers["Referer"] = "https://act.mihoyo.com/"
    if metadata.get("key") == "zzz":
        headers["Host"] = "act-nap-api.mihoyo.com"
    return headers


def _is_auth_expired(payload: Dict[str, Any]) -> bool:
    message = str(payload.get("message") or "")
    return payload.get("retcode") in (-100, 10001) or bool(re.search(r"登录失效|尚未登录", message))


def _api_failure(payload: Dict[str, Any]) -> bool:
    return payload.get("retcode") not in (0, 1) and payload.get("message") != "OK"


def _classify_failure(payload: Dict[str, Any]) -> Dict[str, Any]:
    reason = payload.get("message") or f"米游社返回错误 {payload.get('retcode')}"
    if payload.get("retcode") in (429, -110, -5003) or re.search(r"频繁|稍后|繁忙", str(reason)):
        return {"kind": "retryable", "reason": reason}
    return {"kind": "permanent-failure", "reason": reason}


def _normalize_target(target, user=None) -> List[str]:
    if target in ['all']:
        return list(game_all_list)
    if target in ['daily_sign']:
        return list(game_all_list)
    if isinstance(target, str):
        for item in game_name_list:
            if target in game_name_list[item] or target == item:
                return [item]
        try:
            parsed = json.loads(target.replace("'", '"'))
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except Exception:
            pass
        return [target]
    if isinstance(target, (list, tuple, set)):
        result = []
        for value in target:
            result.extend(_normalize_target(value, user))
        return result
    return [str(target)]


async def _discover_targets(account) -> List[Dict[str, Any]]:
    uid = account.bbs_uid
    if not uid:
        return []
    params = {"uid": str(uid)}
    headers = {**_record_headers(), "Cookie": _account_cookie_text(account)}
    async with httpx.AsyncClient(timeout=plugin_config.preference.timeout) as client:
        response = await client.get(f"{RECORD_URL}?{urllib.parse.urlencode(params)}", headers=headers)
    payload = response.json()
    if _is_auth_expired(payload):
        raise RuntimeError("米游社登录已失效，请重新绑定")
    if (payload.get("retcode") not in (0, 1) and payload.get("message") != "OK") or not isinstance((payload.get("data") or {}).get("list"), list):
        raise RuntimeError(payload.get("message") or "无法获取米游社游戏角色")

    targets = []
    for record in (payload.get("data") or {}).get("list") or []:
        metadata = MIYOUSHE_GAMES.get(int(record.get("game_id") or 0))
        if not metadata:
            continue
        targets.append({
            "metadata": metadata,
            "region": record.get("region"),
            "uid": str(record.get("game_role_id")),
            "nickname": record.get("nickname") or record.get("game_role_id"),
            "level": record.get("level"),
            "display_name": f"{metadata['name']} · {record.get('nickname') or record.get('game_role_id')}",
        })
    return targets


async def _request_sign_api(action: str, account, target: Dict[str, Any], method: str) -> Dict[str, Any]:
    metadata = target["metadata"]
    base = metadata.get("api_base") or DEFAULT_SIGN_API_BASE
    params = {
        "act_id": metadata.get("act_id"),
        "region": target.get("region"),
        "uid": target.get("uid"),
        "lang": "zh-cn",
    }
    if action == "info":
        url = f"{base}/info?{urllib.parse.urlencode(params)}"
        body = None
    else:
        url = f"{base}/sign"
        body = {
            "act_id": metadata.get("act_id"),
            "region": target.get("region"),
            "uid": target.get("uid"),
        }

    async with httpx.AsyncClient(timeout=plugin_config.preference.timeout) as client:
        if method == "GET":
            response = await client.get(url, headers=_sign_headers(account, metadata))
        else:
            response = await client.post(url, headers=_sign_headers(account, metadata), json=body)
    return response.json()


async def _reward_summary(account, target: Dict[str, Any], day: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(day, int) or day < 1:
        return None
    metadata = target["metadata"]
    base = metadata.get("api_base") or DEFAULT_SIGN_API_BASE
    params = {"act_id": metadata.get("act_id"), "lang": "zh-cn"}
    try:
        async with httpx.AsyncClient(timeout=plugin_config.preference.timeout) as client:
            response = await client.get(
                f"{base}/home?{urllib.parse.urlencode(params)}",
                headers=_reward_headers(account, metadata),
            )
        awards = (response.json().get("data") or {}).get("awards") or []
        award = awards[day - 1] if len(awards) >= day else None
    except Exception:
        return None
    if not award:
        return None
    return {
        "name": award.get("name"),
        "cnt": award.get("cnt"),
        "icon": award.get("icon"),
    }


async def _check_in(account, target: Dict[str, Any]) -> Dict[str, Any]:
    try:
        info = await _request_sign_api("info", account, target, "GET")
        if _is_auth_expired(info):
            return {"kind": "auth-expired", "reason": info.get("message") or "登录失效"}
        if not _api_failure(info) and (info.get("data") or {}).get("is_sign"):
            day = (info.get("data") or {}).get("total_sign_day")
            reward = await _reward_summary(account, target, day)
            return {"kind": "already-done", "reward": reward, "total_sign_day": day}

        signed = await _request_sign_api("sign", account, target, "POST")
        if _is_auth_expired(signed):
            return {"kind": "auth-expired", "reason": signed.get("message") or "登录失效"}

        risk_code = int((signed.get("data") or {}).get("risk_code") or 0)
        if risk_code != 0 or re.search(r"验证码|风控", str(signed.get("message") or "")):
            return {
                "kind": "risk-control",
                "reason": signed.get("message") or "触发米游社人机验证",
            }
        if _api_failure(signed):
            return _classify_failure(signed)

        refreshed = {}
        try:
            refreshed = await _request_sign_api("info", account, target, "GET")
        except Exception:
            pass
        day = ((refreshed or {}).get("data") or {}).get("total_sign_day")
        reward = await _reward_summary(account, target, day)
        return {"kind": "success", "reward": reward, "total_sign_day": day}
    except Exception as error:
        return {"kind": "retryable", "reason": f"网络请求失败：{error}"}

#判断是否应该刷新了
async def date_check(user_id = None, cache_info = None):
    if user_id is None:
        current_date = datetime.now()
        timestamp = int(current_date.timestamp())
        current_year = current_date.year
        current_month = current_date.month
        current_day = current_date.day
        day = f'{current_year}_{current_month}_{current_day}'
        month = f'{current_year}_{current_month}'
        year = f'{current_year}'
        return_json = {'day':day, 'month':month, 'year':year,'today':current_date,'time':timestamp}
        return return_json
    else:
        if cache_info is None:
            cache_info = await cache_get(db,'mihuyo')
        if user_id not in cache_info:
            return False
        sign_time = cache_info[user_id]['sign_time']
        dt = datetime.fromtimestamp(sign_time)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)  # 当天零点
        tomorrow = today + timedelta(days=1)  # 明天零点
        return today <= dt < tomorrow

async def change_default_sign_game(user_id,target,bot=None,event=None):
    user = PluginDataManager.plugin_data.users[str(user_id)]
    if not user or not user.accounts:
        msg = '此用户还未绑定，请发送 ‘米游社帮助’ 查看菜单'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
    #print(user.target_sign_game)
    for item in game_name_list:
        if target in game_name_list[item]:
            target = item
            break
    user.target_sign_game = target
    PluginDataManager.write_plugin_data()
    if bot: await bot.send(event, f'您的默认签到游戏已更改为 {target}')


async def mys_game_sign(user_id,bot=None,event=None,target='all',type='game'):
    return await mys_game_sign_new(user_id=user_id, bot=bot, event=event, target=target, type=type)


async def mys_game_sign_new(user_id,bot=None,event=None,target='all',type='game'):
    user_id = str(user_id)
    user = PluginDataManager.plugin_data.users.get(str(user_id))
    return_json = {'message':'test','img_list':[],'text_list':[],'status':False,'text':'','manshuo_draw':[],'sign_status':False}
    if not user or not user.accounts:
        msg = '此用户还未绑定，请发送 ‘米游社帮助’ 查看菜单'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return_json['message'] = msg
        return return_json
    recall_id = None
    if bot and target == 'all': recall_id = await bot.send(event, '签到时间较长，请耐心等待喵')
    try:
        sign_info = await perform_game_sign_new(user_id=user_id,bot=bot, user=user, event=event, target=target, type=type)
        return_json['img_list'], return_json['text_list'] = sign_info['img_list'], sign_info['text_list']

        if sign_info['status']:
            for item in sign_info['text_list']:
                return_json['text'] += f'{item}\n'
        else:
            return_json['text'] = '已尝试签到，但未获得签到数据，可自行前往米游社查看'
        return_json['text'] += '[des]ps:一次签到米游社所有游戏耗时很长，请耐心等待喵[/des]'
        return_json['status'] = True
        return_json['sign_status'] = sign_info['sign_status']
        return_json['manshuo_draw'] = sign_info['manshuo_draw']
    except Exception as e:
        print(e)
        traceback.print_exc()
        msg = '签到失败，请稍后重试喵'
        return_json['message'] = msg
    finally:
        if recall_id: await bot.recall(recall_id['data']['message_id'])
        return return_json


async def perform_game_sign_new(user, user_id=None, bot = None, event = None, target='all',type='game'):
    """
    执行新版米游社游戏签到，并保持旧 mys_game_sign 返回结构。
    """
    return_json = {'status':False,'img_list':[],'text_list':[],'manshuo_draw':[]}
    target_list = _normalize_target(target, user)
    cache_info = None
    use_cache = set(target_list) == set(game_all_list)
    if use_cache:
        cache_info = await cache_get(db, 'mihuyo') or {}
        if await date_check(user_id,cache_info):
            if target in ['daily_sign']:
                logger.info('命中当前缓存，直接返回')
                return cache_info[user_id]['return_json']
            elif type in ['inner','auto']:
                logger.info('命中当前缓存，直接返回')
                return cache_info[user_id]['return_json']
            elif type in ['game']:
                img_path = cache_info[user_id].get('img_path', None)
                draw_list = cache_info[user_id].get('draw_list', None)
                if img_path is None and draw_list is not None:
                    logger.info('命中当前缓存，直接开始绘制图片')
                    img_path = await manshuo_draw(draw_list)
                    if bot and event:
                        await bot.send(event, [At(qq=user_id), f" 您当天的米游社签到如下", Image(file=img_path)])
                    else:
                        print(img_path)
                    cache_info[user_id]['img_path'] = img_path
                    await cache_save(db, 'mihuyo', cache_info)
                    return cache_info[user_id]['return_json']
                if img_path is not None and os.path.isfile(img_path):
                    logger.info('命中当前缓存，直接返回')
                    if bot and event:
                        await bot.send(event, [At(qq=user_id), f" 您当天的米游社签到如下", Image(file=img_path)])
                    else:
                        print(img_path)
                    return cache_info[user_id]['return_json']
        elif user_id in cache_info:
            cache_info.pop(user_id)

    img_list, image_text_list, text_list, pure_text_list, text_only_list, UID = [], [], [], [], [], '无法获取'
    sign_status_check = False
    for account in user.accounts.values():
        if type == 'auto' and not account.enable_game_sign:
            continue
        UID = account.display_name
        try:
            discovered_targets = await _discover_targets(account)
        except Exception as e:
            msg = f" 获取游戏账号信息失败，请重新尝试：{e}"
            if bot: await bot.send(event, [At(qq=user_id), msg])
            else: print(msg)
            text_list.append(msg.strip())
            pure_text_list.append(msg.strip())
            text_only_list.append(msg.strip())
            continue

        selected_targets = []
        games_has_record = []
        for sign_target in discovered_targets:
            metadata = sign_target["metadata"]
            if metadata["name"] not in target_list:
                continue
            games_has_record.append(sign_target)
            if metadata["en_name"] not in account.game_sign_games:
                continue
            selected_targets.append(sign_target)

        if not games_has_record:
            msg = f"⚠️您的米游社账户 {account.display_name} 下不存在任何游戏账号，已跳过签到"
            if bot: await bot.send(event, [At(qq=user_id), msg])
            else: print(msg)
            text_list.append(msg)
            pure_text_list.append(msg)
            text_only_list.append(msg)
            continue
        if not selected_targets:
            msg = f"⚠️米游社账户 {account.display_name} 未开启目标游戏签到，已跳过"
            text_list.append(msg)
            pure_text_list.append(msg)
            text_only_list.append(msg)
            continue

        for sign_target in selected_targets:
            metadata = sign_target["metadata"]
            outcome = await _check_in(account, sign_target)
            kind = outcome.get("kind")
            label = SIGN_RESULT_LABELS.get(kind, kind or "未知状态")
            reward = outcome.get("reward")
            total_sign_day = outcome.get("total_sign_day")
            nickname = sign_target.get("nickname") or sign_target.get("uid")
            level = sign_target.get("level")
            level_text = f"Lv{level}" if level not in (None, "") else "Lv未知"

            if kind in ("success", "already-done"):
                sign_status_check = True
                reward_name = (reward or {}).get("name") or "奖励获取失败"
                reward_cnt = (reward or {}).get("cnt")
                reward_text = f"{reward_name} * {reward_cnt}" if reward_cnt not in (None, "") else reward_name
                day_text = total_sign_day if total_sign_day not in (None, "") else "未知"
                rich_text = (f'[title]『{metadata["name"]}』[/title]  {nickname}·{level_text}\n'
                             f'签到奖励：({label}，本月签到次数：{day_text})\n{reward_text}\n')
                pure_text = (f'『{metadata["name"]}』\n{nickname}·{level_text}\n'
                             f'签到状态：{label}\n{reward_text}\n'
                             f'本月签到次数：{day_text}')
                text_list.append(rich_text)
                pure_text_list.append(pure_text)
                if reward and reward.get("icon"):
                    img_list.append(reward["icon"])
                    image_text_list.append(rich_text)
                else:
                    text_only_list.append(rich_text)
            else:
                reason = outcome.get("reason") or ""
                per_msg = f'『{metadata["name"]}』 {nickname}·{level_text} {label}'
                if reason:
                    per_msg += f'：{reason}'
                if kind == "auth-expired":
                    per_msg += "，请尝试重新登录绑定账户"
                elif kind == "risk-control":
                    per_msg += "，请手动前往米游社签到"
                text_list.append(per_msg)
                pure_text_list.append(per_msg)
                text_only_list.append(per_msg)
            await asyncio.sleep(plugin_config.preference.sleep_time)

    if user_id is None:
        user_id = '1270858640'
    draw_list = [
        {'type': 'basic_set', 'img_width': 1500},
        {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"],
         'upshift_extra': 15,
         'content': [f"[name]米游社签到[/name]\n[time]米游社id: {UID}[/time]"]},
    ]
    if img_list:
        draw_list.append({'type': 'img', 'subtype': 'common_with_des_right', 'img': img_list,
                          'content': image_text_list,'number_per_row':2})
    if text_only_list:
        draw_list.append({'type': 'text','content': text_only_list})

    manshuo_draw_list = [
        {'type': 'avatar', 'subtype': 'common',
         'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"],
         'upshift_extra': 15,'background':'run/manshuo_test/data/img/米游社.png',
         'content': [f"[name]米游社签到[/name]\n[time]米游社id: {UID}[/time]"]},
    ]
    if img_list:
        manshuo_draw_list.append({'type': 'img', 'subtype': 'common_with_des_right', 'img': img_list,
                                  'content': image_text_list,'number_per_row': 1})
    if text_only_list:
        manshuo_draw_list.append({'type': 'text','content': text_only_list})

    return_json = {'status':bool(text_list),'img_list':img_list,'text_list':text_list,'sign_status':sign_status_check,
                   'pure_text_list':pure_text_list,'manshuo_draw':manshuo_draw_list }

    if cache_info is not None and user_id not in cache_info and sign_status_check:
        day_info = await date_check()
        cache_info[user_id] = {'sign_time':day_info['time'],'return_json':copy.deepcopy(return_json),
                               'img_path':None,'draw_list':copy.deepcopy(draw_list)}
        await cache_save(db, 'mihuyo', cache_info)
    if target == 'daily_sign':
        return return_json
    if type == 'game':
        if img_list:
            img_path = await manshuo_draw(draw_list)
            if cache_info is not None and user_id in cache_info:
                cache_info[user_id]['img_path'] = img_path
                await cache_save(db, 'mihuyo', cache_info)
            if bot and event:
                await bot.send(event, [At(qq=user_id),f" 您当天的米游社签到如下", Image(file=img_path)])
            else:
                print(img_path)
        else:
            msg = "\n\n".join(pure_text_list) if pure_text_list else '已尝试签到，但未获得签到数据，可自行前往米游社查看'
            if bot and event:
                await bot.send(event,msg)
            else:
                print(msg)
    return return_json


async def _mys_game_sign_old(user_id,bot=None,event=None,target='all',type='game'):
    #pprint.pprint(PluginDataManager.plugin_data.users)
    user_id = str(user_id)
    user = PluginDataManager.plugin_data.users.get(str(user_id))
    return_json = {'message':'test','img_list':[],'text_list':[],'status':False,'text':'','manshuo_draw':[]}
    if not user or not user.accounts:
        msg = '此用户还未绑定，请发送 ‘米游社帮助’ 查看菜单'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return_json['message'] = msg
        return return_json
    recall_id = None
    if bot and target == 'all': recall_id = await bot.send(event, '签到时间较长，请耐心等待喵')
    try:
        for item in game_name_list:
            if target in game_name_list[item]:
                target = [item]
                break
        sign_info = await perform_game_sign(user_id=user_id,bot=bot, user=user, event=event, target=str(target), type=type)

        return_json['img_list'], return_json['text_list'] = sign_info['img_list'], sign_info['text_list']

        if sign_info['status']:
            for item in sign_info['text_list']:
                return_json['text'] += f'{item}\n'
        else:
            return_json['text'] = '已尝试签到，但未获得签到数据，可自行前往米游社查看'
        #return_json['text'] += '[des]ps:为避签到时间过长，签到模块只会签到一个游戏\n请在菜单中自行更换默认签到游戏的说[/des]'
        return_json['text'] += '[des]ps:一次签到米游社所有游戏耗时很长，请耐心等待喵[/des]'
        return_json['status'] = True
        return_json['manshuo_draw'] = sign_info['manshuo_draw']
    except Exception as e:
        print(e)
        traceback.print_exc()
        msg = '签到失败，请稍后重试喵'
        #if bot: await bot.send(event, msg)
        return_json['message'] = msg
    finally:
        if recall_id: await bot.recall(recall_id['data']['message_id'])
        return return_json



async def perform_game_sign(user, user_id=None, bot = None, event = None, target='all',type='game'):
    return await perform_game_sign_new(user=user, user_id=user_id, bot=bot, event=event, target=target, type=type)


async def _perform_game_sign_old(user, user_id=None, bot = None, event = None, target='all',type='game'):
    """
    执行游戏签到函数，并发送给用户签到消息。
    target = [原神,崩坏：星穹铁道,绝区零,崩坏3]
    :param user: 用户数据
    :param event: 事件
    """
    return_json = {'status':False,'img_list':[],'text_list':[],'manshuo_draw':[]}
    if target in ['all']:target_list = game_all_list
    elif target in ['daily_sign']:
        if not user.target_sign_game: target_list = ['崩坏：星穹铁道']
        else:
            print(user.target_sign_game)
            target_list = [user.target_sign_game]
        # 直接签到所有
        target_list = game_all_list
    else:target_list = target

    cache_info = None
    if target_list == game_all_list:
        # 判断是否应该刷新当天签到
        cache_info = await cache_get(db, 'mihuyo')
        if await date_check(user_id,cache_info):
            #pprint.pprint(cache_info[user_id]['return_json'])
            if target in ['daily_sign']:
                logger.info('命中当前缓存，直接返回')
                return cache_info[user_id]['return_json']
            elif type in ['game','inner']:
                img_path = cache_info[user_id].get('img_path', None)
                draw_list = cache_info[user_id].get('draw_list', None)
                if img_path is None and draw_list is not None:
                    logger.info('命中当前缓存，直接开始绘制图片')
                    img_path = await manshuo_draw(draw_list)
                    if bot and event:
                        await bot.send(event, [At(qq=user_id), f" 您当天的米游社签到如下", Image(file=img_path)])
                    else:
                        print(img_path)
                    cache_info[user_id]['img_path'] = img_path
                    await cache_save(db, 'mihuyo', cache_info)
                    return cache_info[user_id]['return_json']
                if img_path is not None and os.path.isfile(img_path):
                    logger.info('命中当前缓存，直接返回')
                    if bot and event:
                        await bot.send(event, [At(qq=user_id), f" 您当天的米游社签到如下", Image(file=img_path)])
                    else:
                        print(img_path)
                    return cache_info[user_id]['return_json']
        else:
            if user_id in cache_info:
                cache_info.pop(user_id)
    #print('开始签到')

    failed_accounts, img_list, text_list, pure_text_list, UID = [], [], [], [], '无法获取'
    sign_status_check = False
    for account in user.accounts.values():
        signed = False
        """是否已经完成过签到"""
        game_record_status, records = await get_game_record(account)
        UID = account.display_name
        if not game_record_status:
            msg = f" 获取游戏账号信息失败，请重新尝试"
            if bot: await bot.send(event, [At(qq=user_id), msg])
            else:print(msg)
            continue
        games_has_record = []

        for class_type in BaseGameSign.available_game_signs:
            signer = class_type(account, records)
            if signer.name not in target_list:continue
            if not signer.has_record:
                continue
            else:
                games_has_record.append(signer)
                #print(class_type.en_name)
                #print(account.game_sign_games)
                if class_type.en_name not in account.game_sign_games:
                    continue
            get_info_status, info = await signer.get_info(account.platform)
            if not get_info_status:
                msg = f" 获取签到记录失败"
                #if bot: await bot.send(event, msg)
                #else:  print(msg)
            else:
                signed = info.is_sign

            # 若没签到，则进行签到功能；若获取今日签到情况失败，仍可继续
            if (get_info_status and not info.is_sign) or not get_info_status:
                sign_status, mmt_data = await signer.sign(account.platform)
                #失败后重新延迟后重新签一次
                # if not sign_status:
                #     if not (sign_status.login_expired or sign_status.need_verify):
                #         logger.info('第一次签到失败，延迟后第二次签到')
                #         await asyncio.sleep(plugin_config.preference.sleep_time)
                #         game_record_status, records = await get_game_record(account)
                #         signer = class_type(account, records)
                #         sign_status, mmt_data = await signer.sign(account.platform)


                #第二次签后获取不到数据则继续
                if not sign_status and user.enable_notice:
                    if sign_status.login_expired:
                        message = f" 签到时服务器返回登录失效，请尝试重新登录绑定账户"
                        per_msg = f'{signer.record.nickname} 签到时服务器返回登录失效，请尝试重新登录绑定账户'
                    elif sign_status.is_signed:
                        message = f" 今天已签到了喵"
                        per_msg = f'{signer.record.nickname} 今天已签到了喵'
                    elif sign_status.need_verify:
                        message = (f" 『{signer.name}』签到时可能遇到验证码拦截，"
                                   "请尝试使用命令『/账号设置』更改设备平台，若仍失败请手动前往米游社签到")
                        per_msg = f'{signer.record.nickname} 签到时可能遇到验证码拦截'
                    else:
                        message = f" 签到失败，请稍后再试"
                        per_msg = f'{signer.record.nickname} 签到失败，请稍后再试'
                    if bot: await bot.send(event, [At(qq=user_id), message])
                    else: print(message)
                    #await asyncio.sleep(plugin_config.preference.sleep_time)
                    return_json['text_list'].append(per_msg)
                    return_json['manshuo_draw'] = [
                       {'type': 'avatar', 'subtype': 'common',
                        'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"],
                        'upshift_extra': 15,'background':'run/manshuo_test/data/img/米游社.png',
                        'content': [f"[name]米游社签到[/name]\n[time]米游社id: {UID}[/time]"]},
                       {'type': 'text','content': [per_msg]}
                   ]
                    return return_json

                # asyncio.sleep(plugin_config.preference.sleep_time)

            if user.enable_notice:
                onebot_img_msg, saa_img, qq_guild_img_msg = "", "", ""
                get_info_status, info = await signer.get_info(account.platform)
                get_award_status, awards = await signer.get_rewards()
                if not get_info_status or not get_award_status:
                    msg = f"⚠️账户 {account.display_name} 🎮『{signer.name}』获取签到结果失败！请手动前往米游社查看"
                    #logger.error(msg)
                else:
                    award = awards[info.total_sign_day - 1]
                    #logger.info(f'{account.display_name} {signer.name} 访问成功！')
                    if info.is_sign:
                        sign_status_check = True
                        status = "签到成功！" if not signed else "已签到"
                        msg = f"🪪账户 {account.display_name}" \
                              f"\n🎮『{signer.name}』" \
                              f"\n🎮状态: {status}" \
                              f"\n{signer.record.nickname}·{signer.record.level}" \
                              "\n\n🎁今日签到奖励：" \
                              f"\n{award.name} * {award.cnt}" \
                              f"\n\n📅本月签到次数：{info.total_sign_day}"
                        #img_file = await get_file(award.icon)
                        #print(img_file)
                        img_list.append(award.icon)
                        # text_list.append(f'[title]『{signer.name}』[/title]  {signer.record.nickname}·Lv{signer.record.level}\n'
                        #                       f'签到奖励：({status})\n{award.name} * {award.cnt}\n'
                        #                       f'本月签到次数：{info.total_sign_day}')
                        text_list.append(f'[title]『{signer.name}』[/title]  {signer.record.nickname}·Lv{signer.record.level}\n'
                                              f'签到奖励：(本月签到次数：{info.total_sign_day})\n{award.name} * {award.cnt}\n')
                        pure_text_list.append(f'『{signer.name}』\n{signer.record.nickname}·Lv{signer.record.level}\n'
                                              f'签到奖励：({status})\n{award.name} * {award.cnt}\n'
                                              f'本月签到次数：{info.total_sign_day}')
                    else:
                        msg = (f"⚠️账户 {account.display_name} 🎮『{signer.name}』签到失败！请尝试重新签到，"
                               "若多次失败请尝试重新登录绑定账户")
                    #print(msg)

            #await asyncio.sleep(plugin_config.preference.sleep_time)

        if not games_has_record:
            msg = f"⚠️您的米游社账户 {account.display_name} 下不存在任何游戏账号，已跳过签到"
            if bot: await bot.send(event, [At(qq=user_id), msg])
            else: print(msg)
    #print(target)

    if user_id is None:
        user_id = '1270858640'
    draw_list = [
        {'type': 'basic_set', 'img_width': 1500},
        {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"],
         'upshift_extra': 15,
         'content': [f"[name]米游社签到[/name]\n[time]米游社id: {UID}[/time]"]},
         {'type': 'img', 'subtype': 'common_with_des_right', 'img': img_list, 'content': text_list,'number_per_row':2}
         ]
    #pprint.pprint(draw_list)
    return_json = {'status':True,'img_list':img_list,'text_list':text_list,
                   'manshuo_draw':[
                       {'type': 'avatar', 'subtype': 'common',
                        'img': [f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"],
                        'upshift_extra': 15,'background':'run/manshuo_test/data/img/米游社.png',
                        'content': [f"[name]米游社签到[/name]\n[time]米游社id: {UID}[/time]"]},
                       {'type': 'img', 'subtype': 'common_with_des_right', 'img': img_list, 'content': text_list,
                        'number_per_row': 1}
                   ]}

    #将签到结果存入全局缓存
    if cache_info is not None and user_id not in cache_info and sign_status_check:
        day_info = await date_check()
        #print('将数据存入缓存')
        #cache_info = await cache_get(db, 'mihuyo')
        cache_info[user_id] = {'sign_time':day_info['time'],'return_json':copy.deepcopy(return_json),'img_path':None,'draw_list':copy.deepcopy(draw_list)}
        await cache_save(db, 'mihuyo', cache_info)
        #pprint.pprint(g_sign_cache)
    #若是每日签到则直接返回
    if target == 'daily_sign':
        return return_json
    if type == 'game':
        if len(img_list) not in [0,1]:
            img_path = await manshuo_draw(draw_list)
            if cache_info is not None and user_id in cache_info:
                cache_info[user_id]['img_path'] = img_path
                await cache_save(db, 'mihuyo', cache_info)
            if bot and event:
                await bot.send(event, [At(qq=user_id),f" 您当天的米游社签到如下", Image(file=img_path)])
            else:
                print(img_path)
        else:
            if bot and event and pure_text_list:
                await bot.send(event,pure_text_list[0])
            else:
                pprint.pprint(pure_text_list[0])
    return return_json
