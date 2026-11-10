import re
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Optional
from datetime import datetime, timezone
import pprint
from developTools.utils.logger import get_logger
logger=get_logger("SteamSnooping")

STEAM_ID_OFFSET = 76561197960265728


def get_steam_id(steam_id_or_steam_friends_code: str) -> str:
    if not steam_id_or_steam_friends_code.isdigit():
        return None

    id_ = int(steam_id_or_steam_friends_code)

    if id_ < STEAM_ID_OFFSET:
        return str(id_ + STEAM_ID_OFFSET)

    return steam_id_or_steam_friends_code


async def get_steam_users_info(
    steam_ids, steam_api_key, bot ,proxy: str = None
):
    if len(steam_ids) == 0:
        return {"response": {"players": []}}

    if len(steam_ids) > 100:
        # 分批获取
        result = {"response": {"players": []}}
        for i in range(0, len(steam_ids), 100):
            batch_result = await get_steam_users_info(
                steam_ids[i : i + 100], steam_api_key, bot=bot, proxy=proxy
            )
            result["response"]["players"].extend(batch_result["response"]["players"])
        return result
    #print(steam_ids)
    for api_key in steam_api_key:
        try:
            async with httpx.AsyncClient(proxy=proxy) as client:
                response = await client.get(
                    f'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={api_key}&steamids={",".join(steam_ids)}'
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"API key {api_key} failed to get steam users info.")
        except httpx.RequestError as exc:
            logger.error(f"API key {api_key} encountered an error: {exc}")
    logger.error("All API keys failed to get steam users info.")
    return {"response": {"players": []}}


async def _fetch(
    url: str, default: bytes, cache_file: Optional[Path] = None, proxy: str = None
) -> bytes:
    if cache_file is not None and cache_file.exists():
        return cache_file.read_bytes()
    try:
        async with httpx.AsyncClient(proxy=proxy) as client:
            response = await client.get(url)
            if response.status_code == 200:
                if cache_file is not None:
                    cache_file.write_bytes(response.content)
                return response.content
            else:
                response.raise_for_status()
    except Exception as exc:
        return default


async def get_user_data(steam_id: int, proxy='http://127.0.0.1:20172'):
    url = f"https://steamcommunity.com/profiles/{steam_id}"
    default_background = (Path(__file__).parent / "res/bg_dots.png")
    default_avatar = (Path(__file__).parent / "res/unknown_avatar.jpg")
    default_achievement_image = (
        Path(__file__).parent / "res/default_achievement_image.png"
    )
    default_header_image = (
        Path(__file__).parent / "res/default_header_image.jpg"
    )

    result = {
        'status': False,
        "description": "No information given.",
        "background": default_background,
        "avatar": default_avatar,
        "player_name": "Unknown",
        "recent_2_week_play_time": None,
        "game_data": [],
    }

    local_time = datetime.now(timezone.utc).astimezone()
    utc_offset_minutes = int(local_time.utcoffset().total_seconds())
    timezone_cookie_value = f"{utc_offset_minutes},0"

    try:
        async with httpx.AsyncClient(
            proxy=proxy,
            headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6"
            },
            cookies={"timezoneOffset": timezone_cookie_value},
        ) as client:
            response = await client.get(url)
            if response.status_code == 200:
                html = response.text
            elif response.status_code == 302:
                url = response.headers["Location"]
                response = await client.get(url)
                if response.status_code == 200:
                    html = response.text
            else:
                response.raise_for_status()
    except httpx.RequestError as exc:
        print(exc)
        return result
    result['status'] = True
    # player name
    player_name = re.search(r"<title>Steam 社区 :: (.*?)</title>", html)
    if player_name:
        result["player_name"] = player_name.group(1)

    # description t<div class="profile_summary">\r\n\t\t\t\t\t\t\t\t風が雨が激しくても<br>思いだすんだ 僕らを照らす光があるよ<br>今日もいっぱい<br>明日もいっぱい 力を出しきってみるよ\t\t\t\t\t\t\t</div>
    description = re.search(
        r'<div class="profile_summary">(.*?)</div>', html, re.DOTALL | re.MULTILINE
    )
    if description:
        description = description.group(1)
        description = re.sub(r"<br>", "\n", description)
        description = re.sub(r"\t", "", description)
        result["description"] = description.strip()

    # remove emoji
    result["description"] = re.sub(r"ː.*?ː", "", result["description"])

    # remove xml
    result["description"] = re.sub(r"<.*?>", "", result["description"])

    # background
    background_url = re.search(r"background-image: url\( \'(.*?)\' \)", html)
    if background_url:
        background_url = background_url.group(1)
        result["background"] = await _fetch(
            background_url, default_background, proxy=proxy
        )

    # avatar
    # \t<link rel="image_src" href="https://avatars.akamai.steamstatic.com/3ade30f61c3d2cc0b8c80aaf567b573cd022c405_full.jpg">
    avatar_url = re.search(r'<link rel="image_src" href="(.*?)"', html)
    result["avatar_url"] = 'https://gal.manshuo.ink/usr/uploads/2025/01/1664675676.png'
    if avatar_url:
        result["avatar_url"] = avatar_url.group(1)

    # recent 2 week play time
    # \t<div class="recentgame_quicklinks recentgame_recentplaytime">\r\n\t\t\t\t\t\t\t\t\t<div>15.5 小时（过去 2 周）</div>
    play_time_text = re.search(
        r'<div class="recentgame_quicklinks recentgame_recentplaytime">\s*<div>(.*?)</div>',
        html,
    )
    if play_time_text:
        play_time_text = play_time_text.group(1)
        result["recent_2_week_play_time"] = play_time_text

    # game data
    soup = BeautifulSoup(html, "html.parser")
    game_data = []
    recent_games = soup.find_all("div", class_="recent_game")

    for game in recent_games:
        game_info = {}
        game_info["game_name"] = game.find("div", class_="game_name").text.strip()
        game_info["game_image_url"] = game.find("img", class_="game_capsule")["src"]


        play_time_text = game.find("div", class_="game_info_details").text.strip()
        play_time = re.search(r"总时数\s*(.*?)\s*小时", play_time_text)
        if play_time is None:
            game_info["play_time"] = ""
        else:
            game_info["play_time"] = play_time.group(1)

        last_played = re.search(r"最后运行日期：(.*) 日", play_time_text)
        if last_played is not None:
            game_info["last_played"] = "最后运行日期：" + last_played.group(1) + " 日"
        else:
            game_info["last_played"] = "当前正在游戏"
        achievements = []
        achievement_elements = game.find_all("div", class_="game_info_achievement")
        for achievement in achievement_elements:
            if "plus_more" in achievement["class"]:
                continue
            achievement_info = {}
            achievement_info["name"] = achievement["data-tooltip-text"]
            achievement_info["image_url"] = achievement.find("img")["src"]
            achievements.append(achievement_info)
        game_info["achievements"] = achievements
        try:
            game_info_achievement_summary = game.find(
                "span", class_="game_info_achievement_summary"
            )
            if game_info_achievement_summary is None:
                game_data.append(game_info)
                continue
            #pprint.pprint(game_info_achievement_summary)
            remain_achievement_text = game_info_achievement_summary.find(
                "span", class_="ellipsis"
            ).text
            game_info["completed_achievement_number"] = int(
                remain_achievement_text.split("/")[0].strip()
            )
            game_info["total_achievement_number"] = int(
                remain_achievement_text.split("/")[1].strip()
            )
        except:
            #上文获取失败，此处数据似乎并未用到，设定为0
            game_info["completed_achievement_number"] = 0
            game_info["total_achievement_number"] = 0

        game_data.append(game_info)

    result["game_data"] = game_data

    return result

async def date_get():
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

async def test():

    proxies = {
        "http://": "http://127.0.0.1:20172",
        "https://": "http://127.0.0.1:20172"
    }
    # async with httpx.AsyncClient(proxies=proxies) as client:
    #     r = await client.get("https://avatars.steamstatic.com/9cf396a0da9cb87d7faefe58feeae7acf6e2b363_full.jpg", timeout=10.0)
    #     print(r.status_code)

    info = await get_steam_users_info(['76561199025034455'],['A3780E7FA6FEB3C9E0A17DE6E2A51CFF'],None,"http://127.0.0.1:20172")
    pprint.pprint(info)

if __name__ == "__main__":
    import asyncio
    asyncio.run(test())

    # data = asyncio.run(get_user_data(76561199025034455))
    # pprint.pprint(data)
    # for item in data:print(item,data[item])
    # print(data['avatar_url'])

    #data = asyncio.run(get_steam_users_info(76561199025034455))


