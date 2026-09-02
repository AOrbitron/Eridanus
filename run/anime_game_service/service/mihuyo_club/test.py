from run.anime_game_service.service.mihuyo_club.command import *
import asyncio

from framework_common.database_util.ManShuoDrawCompatibleDataBase import cache_init

if __name__ == '__main__':
    #asyncio.run(cache_init())
    #asyncio.run(mys_login_new_Stoken('1270858641'))
    #asyncio.run(mys_login_new('1270858640'))
    #asyncio.run(mys_game_sign('1270858640'))
    asyncio.run(mys_note_check('1270858640'))