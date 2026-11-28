import asyncio
import threading
from typing import Union, Optional, Iterable, Dict
from pydantic import BaseModel
from ..api import BaseGameSign
from ..api import BaseMission, get_missions_state
from ..api.common import genshin_note, get_game_record, hi3_note, starrail_note, zzz_note
from ..model import (MissionStatus, PluginDataManager, plugin_config, UserData, CommandUsage, GenshinNoteNotice,
                     StarRailNoteNotice)
import pprint
from developTools.utils.logger import get_logger
logger=get_logger('MiHoYo')
from developTools.message.message_components import Text, Image, At
import traceback
from .config import game_name_list, game_all_list
from ..utils.draw_note import draw_genshin_note, draw_starrail_note, draw_zzz_note

#米游币签到
async def mys_note_check(user_id,bot=None,event=None,target='星铁',draw_type: bool=False):
    """查看便签；draw_type=True 时将原神、崩铁、绝区零便签绘制为图片。"""
    #pprint.pprint(PluginDataManager.plugin_data.users)
    user = PluginDataManager.plugin_data.users.get(str(user_id))
    if not user or not user.accounts:
        msg = '此用户还未绑定，请发送 ‘米游社帮助’ 查看菜单'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return
    #开始进行米游币签到
    for item in game_name_list:
        if target in game_name_list[item]:
            target = item
            break
    if target not in ['原神', '崩坏：星穹铁道', '绝区零', '崩坏3']:
        msg = '当前便签支持原神、崩铁、绝区零与崩坏3查看哦'
        if bot and event: await bot.send(event, msg)
        else: print(msg)
        return
    try:
        if target == '原神':
            await genshin_note_check(user, user_id, bot=bot, event=event, draw_type=draw_type)
        elif target == '崩坏：星穹铁道':
            await starrail_note_check(user, user_id, bot=bot, event=event, draw_type=draw_type)
        elif target == '绝区零':
            await zzz_note_check(user, user_id, bot=bot, event=event, draw_type=draw_type)
        elif target == '崩坏3':
            await hi3_note_check(user, user_id, bot=bot, event=event)

    except Exception as e:
        print(e)
        traceback.print_exc()
        msg = '便签查看失败，请稍后重试喵'
        if bot: await bot.send(event, msg)
        else:print(msg)



async def genshin_note_check(user, user_id, bot=None, event=None, draw_type: bool=False):
    """
    查看原神实时便笺函数，并发送给用户任务执行消息。

    :param user: 用户对象
    :param user_ids: 发送通知的所有用户ID
    :param matcher: 事件响应器
    """
    for account in user.accounts.values():
        if account.enable_resin and 'GenshinImpact' in account.game_sign_games:
            genshin_board_status, note = await genshin_note(account)
            if not genshin_board_status:
                if genshin_board_status.login_expired:
                    msg = ' 登录失效，请重新登录'
                elif genshin_board_status.no_genshin_account:
                    msg = ' 没有绑定任何原神账户，请绑定后再重试'
                elif genshin_board_status.need_verify:
                    msg = ' 获取实时便笺时被人机验证阻拦'
                else:
                    msg = ' 获取原神实时便签失败，请稍后重试'
                if bot: await bot.send(event, msg)
                else: print(msg)
                continue

            if draw_type:
                role = note.game_role
                uid_list = (account.game_uids or {}).get('GenshinImpact', [])
                game_uid = role.game_role_id if role else (uid_list[0] if uid_list else None)
                img_path = await draw_genshin_note(
                    note, user_id=str(user_id), game_uid=game_uid, role=role)
                if bot: await bot.send(event, [At(qq=user_id), Image(file=img_path)])
                else: print(img_path)
                continue

            msg = "  \n❖原神·实时便笺❖" \
                   f"\n账户 {account.display_name}" \
                   f"\n树脂数量：{note.current_resin} / 200" \
                   f"\n树脂{note.resin_recovery_text}" \
                   f"\n探索派遣：{note.current_expedition_num} / {note.max_expedition_num}" \
                   f"\n每日委托：{4 - note.finished_task_num} 个任务未完成" \
                   f"\n洞天财瓮：{note.current_home_coin} / {note.max_home_coin}" \
                   f"\n参量质变仪：{note.transformer_text if note.transformer else 'N/A'}"
            if bot:
                await bot.send(event, [At(qq=user_id), msg])
            else:
                print(msg)


async def starrail_note_check(user, user_id, bot=None, event=None, draw_type: bool=False):
    """
    查看星铁实时便笺函数，并发送给用户任务执行消息。

    :param user: 用户对象
    :param user_ids: 发送通知的所有用户ID
    :param matcher: 事件响应器
    """
    for account in user.accounts.values():
        if account.enable_resin and 'StarRail' in account.game_sign_games:
            starrail_board_status, note = await starrail_note(account)
            if not starrail_board_status:
                if starrail_board_status.login_expired:
                    msg = ' 登录失效，请重新登录'
                elif starrail_board_status.no_starrail_account:
                    msg = ' 没有绑定任何星铁账户，请绑定后再重试'
                elif starrail_board_status.need_verify:
                    msg = ' 获取实时便笺时被人机验证阻拦'
                else:
                    msg = ' 获取崩铁实时便签失败，请稍后重试'
                if bot: await bot.send(event, msg)
                else: print(msg)
                continue

            if draw_type:
                role = note.game_role
                uid_list = (account.game_uids or {}).get('StarRail', [])
                game_uid = role.game_role_id if role else (uid_list[0] if uid_list else None)
                img_path = await draw_starrail_note(
                    note, user_id=str(user_id), game_uid=game_uid, role=role)
                if bot: await bot.send(event, [At(qq=user_id), Image(file=img_path)])
                else: print(img_path)
                continue

            msg = "  \n❖星穹铁道·实时便笺❖" \
                   f"\n账户 {account.display_name}" \
                   f"\n开拓力数量：{note.current_stamina} / {note.max_stamina}" \
                   f"\n开拓力{note.stamina_recover_text}" \
                   f"\n每日实训：{note.current_train_score} / {note.max_train_score}" \
                   f"\n每日委托：{note.accepted_expedition_num} / 4" \
                   f"\n模拟宇宙：{note.current_rogue_score} / {note.max_rogue_score}"

            if bot:
                await bot.send(event, [At(qq=user_id), msg])
            else:
                print(msg)


async def zzz_note_check(user, user_id, bot=None, event=None, draw_type: bool=True):
    """查看绝区零实时便签，按 draw_type 选择图片或文字。"""
    for account in user.accounts.values():
        if account.enable_resin and 'ZenlessZoneZero' in account.game_sign_games:
            zzz_board_status, note = await zzz_note(account)
            if not zzz_board_status:
                if zzz_board_status.missing_stoken:
                    msg = ' 绝区零便签缺少 Stoken，请发送“米游社登录”重新登录'
                elif zzz_board_status.missing_mid:
                    msg = ' 绝区零便签登录凭据不完整，请发送“米游社登录”重新登录'
                elif zzz_board_status.login_expired:
                    msg = ' 登录失效，请重新登录'
                elif zzz_board_status.no_zzz_account:
                    msg = ' 没有绑定任何绝区零账户，请绑定后再重试'
                elif zzz_board_status.need_verify:
                    msg = ' 获取实时便签时被人机验证阻拦'
                else:
                    msg = ' 获取实时便签请求失败，请稍后重试'
                if bot: await bot.send(event, msg)
                else: print(msg)
                continue

            if draw_type:
                uid_list = account.game_uids.get('ZenlessZoneZero', [])
                role_status, role_records = await get_game_record(account, retry=False)
                role = next((record for record in role_records or []
                             if record.game_id == 8 and (not uid_list or record.game_role_id in uid_list)), None)
                game_uid = role.game_role_id if role else (uid_list[0] if uid_list else None)
                img_path = await draw_zzz_note(note, account.display_name, user_id=str(user_id),
                                               game_uid=game_uid, role=role if role_status else None)
                if bot: await bot.send(event, [At(qq=user_id), Image(file=img_path)])
                else: print(img_path)
                return
            msg = "  \n❖绝区零·实时便签❖" \
                  f"\n账户 {account.display_name}" \
                  f"\n电量数量：{note.current_energy} / {note.max_energy}" \
                  f"\n电量{note.energy_recover_text}" \
                  f"\n今日活跃度：{note.current_vitality} / {note.max_vitality}" \
                  f"\n刮刮卡：{note.card_sign_text}" \
                  f"\n录像店经营：{note.vhs_sale_text}" \
                  f"\n悬赏委托：{note.bounty_num} / {note.bounty_total}" \
                  f"\n丽都周纪：{note.weekly_num} / {note.weekly_total}"
            if bot: await bot.send(event, [At(qq=user_id), msg])
            else: print(msg)


async def hi3_note_check(user, user_id, bot=None, event=None):
    """查看崩坏3实时便签。"""
    for account in user.accounts.values():
        if not account.enable_resin or 'HonkaiImpact3' not in account.game_sign_games:
            continue
        status, note = await hi3_note(account)
        if not status:
            if status.login_expired or status.missing_stoken:
                msg = '崩坏3便签登录凭据失效，请重新发送“米游社登录”'
            elif status.no_hi3_account:
                msg = '没有绑定任何崩坏3账户，请绑定后再重试'
            elif status.need_verify:
                msg = '获取崩坏3实时便签时被人机验证阻拦'
            else:
                msg = '获取崩坏3实时便签失败，请稍后重试'
            if bot: await bot.send(event, msg)
            else: print(msg)
            continue

        def item(data, name, current_key, max_key):
            current, maximum = data.get(current_key), data.get(max_key)
            return f"{name}：{current if current is not None else '-'} / {maximum if maximum is not None else '-'}"

        msg = "  \n❖崩坏3·实时便签❖" \
              f"\n账户 {account.display_name}" \
              f"\n体力：{note.current_stamina if note.current_stamina is not None else '-'} / {note.max_stamina if note.max_stamina is not None else '-'}" \
              f"\n体力{note.stamina_recover_text}" \
              f"\n每日任务：{note.current_train_score if note.current_train_score is not None else '-'} / {note.max_train_score if note.max_train_score is not None else '-'}"
        for label, data in (("深渊", note.greedy_endless), ("超弦空间", note.ultra_endless),
                            ("战场", note.battle_field), ("往世乐土", note.god_war)):
            if not data:
                continue
            current = data.get("current") or data.get("cur_reward") or data.get("challenge_score")
            maximum = data.get("max") or data.get("max_reward")
            if current is not None:
                msg += f"\n{label}：{current}" + (f" / {maximum}" if maximum is not None else "")
        if bot: await bot.send(event, [At(qq=user_id), msg])
        else: print(msg)
