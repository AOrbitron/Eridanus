"""森空岛抽卡指令：查询读缓存，首次查询自动获取，更新增量，全量更新补历史。"""
from __future__ import annotations

import asyncio
import re

from developTools.message.message_components import At, Image
from developTools.utils.logger import get_logger
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase

from ..utils.draw_gacha import GAME_NAMES, render_cards
from ..utils.gacha import GachaError, load_cache, numeric, record_counts, refresh_records, save_cache

logger = get_logger("skland")
GAME_ALIASES = {
    "endfield": ("明日方舟：终末地", "明日方舟:终末地", "明日方舟终末地", "终末地", "endfield", "byd", "zmd"),
    "arknights": ("明日方舟", "方舟", "arknights", "mrfz", "ark"),
}
ACTIONS = {
    "抽卡记录": ("show", False),
    "查看抽卡记录": ("show", False),
    "更新抽卡记录": ("refresh", False),
    "刷新抽卡记录": ("refresh", False),
    "全量更新抽卡记录": ("refresh", True),
    "全量刷新抽卡记录": ("refresh", True),
}
_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


def parse_card_command(context: str) -> tuple[str, str, str | None, bool] | None:
    text = re.sub(r"\s+", "", context or "")
    aliases = sorted(((alias, game) for game, names in GAME_ALIASES.items() for alias in names), key=lambda item: len(item[0]), reverse=True)
    for alias, game in aliases:
        if text.casefold().startswith(alias.casefold()):
            text = text[len(alias):]
            break
    else:
        return None
    matches = list(re.finditer(r"(?:uid[:：]?)?([0-9]{1,20})", text, re.IGNORECASE))
    uid = None
    if matches:
        if len(matches) != 1:
            return None
        match = matches[0]
        uid = match.group(1)
        text = text[:match.start()] + text[match.end():]
    action = ACTIONS.get(text)
    return (game, action[0], uid, action[1]) if action else None


def resolve_role(skland: dict, game: str, requested_uid: str | None = None) -> tuple[dict, str, str]:
    characters = skland.get("character_info") or {}
    role = characters.get(game)
    # 兼容早期仅保存一个明日方舟角色的扁平结构。
    if not isinstance(role, dict) and characters.get("app_code") == game:
        role = characters
    if not isinstance(role, dict) or not role.get("uid"):
        raise GachaError(f"未找到{GAME_NAMES[game]}角色，请发送“森空岛登录”更新角色绑定喵")
    uid = numeric(role.get("roleid") if game == "endfield" else role.get("uid"))
    server = numeric(role.get("serverid", "1"), "服务器编号")
    if requested_uid is not None and uid != requested_uid:
        raise GachaError(f"当前绑定的{GAME_NAMES[game]}角色 UID 为 {uid}，与指定 UID 不一致")
    if game == "endfield" and server != "1":
        raise GachaError("当前仅支持国服终末地寻访记录")
    return dict(role), uid, server


async def _send(bot, event, user_id: str, text: str, recall=False) -> None:
    if bot is not None and event is not None:
        recall_id = await bot.send(event, [At(qq=user_id), " " + text])
        if recall and recall_id:
            await asyncio.sleep(50)
            await bot.recall(recall_id['data']['message_id'])
    else:
        print(text)


async def handle_skland_card_command(context: str, user_id: str, bot=None, event=None, proxy: str | None = None) -> bool:
    parsed = parse_card_command(context)
    if parsed is None:
        return False
    game, action, requested_uid, full_refresh = parsed
    user_id = str(user_id)
    try:
        db = await AsyncSQLiteDatabase.get_instance()
        skland = (await db.read_user(user_id)).get("skland") or {}
        if not skland:
            raise GachaError("此用户还未绑定森空岛喵，请先发送“森空岛登录”")
        role, uid, server = resolve_role(skland, game, requested_uid)
        payload = await asyncio.to_thread(load_cache, game, uid, server)
        lock = _LOCKS.setdefault((game, uid, server), asyncio.Lock())
        needs_fetch = action == "refresh" or not payload.get("initialized")
        if needs_fetch:
            if lock.locked():
                await _send(bot, event, user_id, f"{GAME_NAMES[game]}抽卡记录正在更新，请稍后再试",recall=True)
                return True
            async with lock:
                # 等待锁期间可能已有另一次首次查询完成保存。
                payload = await asyncio.to_thread(load_cache, game, uid, server)
                if action == "refresh" or not payload.get("initialized"):
                    description = "全量更新" if full_refresh else "更新" if action == "refresh" else "首次获取"
                    await _send(bot, event, user_id, f"正在{description}{GAME_NAMES[game]}抽卡记录，请耐心等待喵",recall=True)
                    async with asyncio.timeout(600):
                        payload, added, gifts, warnings = await refresh_records(game, skland.get("user_info") or {}, role, payload, proxy=proxy, full_refresh=full_refresh)
                    await asyncio.to_thread(save_cache, payload, full_refresh)
                    if action == "refresh":
                        total, _ = record_counts(payload)
                        text = f"{GAME_NAMES[game]}抽卡记录更新完成：新增 {added} 抽，共保存 {total} 抽"
                        if gifts:
                            text += f"，新增附加奖励 {gifts} 条"
                        if warnings:
                            text += "\n部分数据未更新，已保留对应历史：\n" + "\n".join(warnings)
                        await _send(bot, event, user_id, text)
                        return True
        if payload.get("warnings"):
            await _send(bot, event, user_id, "上次更新有部分接口未成功，以下统计基于已保存数据：\n" + "\n".join(payload["warnings"]))
        total, gifts = record_counts(payload)
        if not total:
            await _send(bot, event, user_id, f"{GAME_NAMES[game]} 暂无可查询的抽卡记录" + (f"，已保存附加奖励 {gifts} 条" if gifts else ""))
            return True
        payload.setdefault("profile", {"nickname": role.get("nickname"), "level": role.get("level")})
        paths = await render_cards(payload, proxy)
        if bot is not None and event is not None:
            for path in paths:
                await bot.send(event, [At(qq=user_id), Image(file=str(path))])
        else:
            for path in paths:
                print(path)
    except GachaError as error:
        await _send(bot, event, user_id, str(error))
    except TimeoutError:
        await _send(bot, event, user_id, "抽卡记录更新超时，已保留本地数据，请稍后重试")
    except Exception as error:
        # HTTP 异常可能在 URL 内携带 token，日志仅记录类型。
        logger.warning(f"森空岛抽卡操作失败：{type(error).__name__}")
        await _send(bot, event, user_id, "抽卡记录处理失败，已保留本地数据，请稍后重试")
    return True
