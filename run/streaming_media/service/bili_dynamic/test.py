from run.streaming_media.service.bili_dynamic.commend import *
from run.streaming_media.service.bili_dynamic.data import *
import asyncio
import pprint
from bilibili_api import Credential,dynamic,user
from bilibili_api.user import create_subscribe_group, set_subscribe_group
from framework_common.manshuo_draw import *

async def test():
    data_info = await data_init()
    pprint.pprint(data_info['cookies'])
    #await data_delete(7071924)
    # await bili_login()
    # info = await data_init()

    #pprint.pprint(info)
    # print(await check_credential())
    # print(await upgrade_credential())


    # ccokies = {'SESSDATA':'463b26c8%2C1794365986%2C876d4%2A52CjDxgTHlKdaFsGqeX-v-fBPYXZCa8rCCI_vhI1C-yXq8a44efxe2RuwpY2lQ_JuxfPwSVkhvaVlnVlZkSnJTMTNsakZPRFd1LTVuenZ0alBNc3ctZXEteHRSYXNzcHZuNEI1czRjQVFtSzNBQ1BxV3lVdTNyZUdDN0d3Y0VGbmhsdGtfcW9NNjJBIIEC',
    #            'bili_jct':'ff5e105f80c5fad516603af667d69c1a',
    #            'buvid3':'89C2F9EF-D0FB-D8B9-AB6E-DEDEF242F79317738infoc',
    #            'DedeUserID':'3493087821170873',
    #            'ac_time_value':'3c98e48025ae85c16cca738d2a7d5352'}#ps:
    # await bili_login(cookies=ccokies)
    # data_info = await data_init()
    # credential = Credential(sessdata=data_info['cookies']['sessdata'], bili_jct=data_info['cookies']['bili_jct'],
    #                         buvid3=data_info['cookies']['buvid3'], dedeuserid=data_info['cookies']['dedeuserid'])
    # cookies_info = credential.get_cookies()
    # cookies_check = ''
    # for item in cookies_info:
    #     cookies_check += f'{item}={cookies_info[item]};'
    # pprint.pprint(cookies_info)
    # pprint.pprint(cookies_check)

    # await data_save(info)
    # info = await bili_up_dynamic_monitor_add(3546896452815007)
    # pprint.pprint(info)
    # info = await bili_followers_live_get()
    # pprint.pprint(info)

    # info = await bili_followers_live_get()
    # pprint.pprint(info)


if __name__ == '__main__':
    asyncio.run(test())
