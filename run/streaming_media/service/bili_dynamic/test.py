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
    #pprint.pprint(data_info['dynamic_info']['275734421'])

    #info = await bili_up_dynamic_monitor_add(275734421,326183226,)
    #pprint.pprint(info)

    #await data_delete(7071924)
    info = await bili_login_new(is_save=False)
    # info = await data_init()

    pprint.pprint(info)
    # print(await check_credential())
    # print(await upgrade_credential())


    # ccokies = {'SESSDATA':'a0369fd3%2C1794366130%2Ca6767%2A52CjDXXD_gmCn5uwkgLJ_RqFBj22uy91gpJ1J_UAAoOEcrDk7l89ddmzx50q8_8hlSoOISVkNfX3NnS216VkZJQmN4NjVZeFUtLVNRbmVOVkVsSmlXeDZadTNhWjlWUkhnbDN3X0YxdkktY3ZBcTdFN0Z0Ty0yeVhfZzlpYkFPUXQ2R21menlqaUVRIIEC',
    #            'bili_jct':'dccc31708ce794120e511016be8b91a2',
    #            'buvid3':'89C2F9EF-D0FB-D8B9-AB6E-DEDEF242F79317738infoc',
    #            'DedeUserID':'3493087821170873',
    #            'ac_time_value':'d81741fdf0c39ceb679db8604dd87452'}:
    # await bili_login(cookies=ccokies)





if __name__ == '__main__':
    asyncio.run(test())
