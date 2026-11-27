from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text, Image, At
from framework_common.manshuo_draw import *
from run.anime_game_service.service.skland import *


def main(bot, config):


    #绑定森空岛
    @bot.on(GroupMessageEvent)
    async def bind_sklandid(event: GroupMessageEvent):
        context, userid=event.pure_text, str(event.sender.user_id)
        order_list = ['sklandbind', '森空岛绑定', '森空岛登录']
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context in order_list:
            await qrcode_get(userid, bot, event)

    #抽卡记录：与米游社入口一样，按游戏别名和“抽卡记录”后缀分派
    @bot.on(GroupMessageEvent)
    async def skland_card_order(event: GroupMessageEvent):
        context, userid = event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not context.rstrip().endswith('抽卡记录'):
            return
        proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
        await handle_skland_card_command(context, userid, bot, event, proxy=proxy)

    #图鉴、基质与资源更新，沿用米游社攻略的游戏前缀形式。
    @bot.on(GroupMessageEvent)
    async def skland_guide_order(event: GroupMessageEvent):
        context, userid = event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if not any(word in context for word in ('图鉴', '资源', '攻略')):
            return
        proxy = config.common_config.basic_config['proxy']['http_proxy'] or None
        await handle_skland_guide_command(context, userid, bot, event, proxy=proxy)

    #森空岛签到
    @bot.on(GroupMessageEvent)
    async def sing_sklandid(event: GroupMessageEvent):
        order_list=['sklandsign','森空岛签到','方舟签到','终末地签到','明日方舟签到']
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context in order_list:await skland_signin(userid, bot, event)

    #明日方舟信息查询
    @bot.on(GroupMessageEvent)
    async def ark_info_order(event: GroupMessageEvent):
        order_list=['我的明日方舟','我的方舟','我的方舟z','明日方舟信息','明日方舟便签','方舟便签']
        context, userid=event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.strip() in order_list:
            proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
            recall_id = await bot.send(event, '开始查询您的明日方舟信息，请耐心等待喵')
            try:
                await skland_info(userid, bot, event, proxy=proxy)
            finally:
                await bot.recall(recall_id['data']['message_id'])

    #终末地信息查询
    @bot.on(GroupMessageEvent)
    async def endfield_info_order(event: GroupMessageEvent):
        context, userid = event.pure_text, str(event.sender.user_id)
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        if context.strip() in ['终末地信息', '我的终末地', '终末地便笺', ]:
            proxy = config.common_config.basic_config['proxy']['http_proxy'] if config.common_config.basic_config['proxy']['http_proxy'] else None
            recall_id = await bot.send(event, '开始查询您的终末地信息，请耐心等待喵')
            try:
                await endfield_info(userid, bot, event, proxy=proxy)
            finally:
                await bot.recall(recall_id['data']['message_id'])

    #森空岛肉鸽战绩查询
    @bot.on(GroupMessageEvent)
    async def sing_rouge_info(event: GroupMessageEvent):
        order_list=['sklandrogue','sklandrg','肉鸽信息']
        context, userid, flag=event.pure_text, str(event.sender.user_id), True
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        for order_check in order_list:
            if order_check in context:
                flag=False
                context = context.replace(' ', '').replace(order_check, '')
        if flag is True or context not in ["傀影","水月", "萨米", "萨卡兹",'界园']:return
        recall_id = await bot.send(event, f'开始查询您的{context}肉鸽信息，请耐心等待喵')
        await rouge_info(userid, context,bot=bot, event=event)
        await bot.recall(recall_id['data']['message_id'])

    ##森空岛肉鸽详细战绩查询
    @bot.on(GroupMessageEvent)
    async def sing_sklandid(event: GroupMessageEvent):
        order_list=['sklandrogueinfo','sklandrginfo','肉鸽查询','查询肉鸽']
        context, userid, flag, game_count = event.pure_text, str(event.sender.user_id), True, None
        if event.message_chain.has(At) and event.message_chain.has(Text):
            userid, context = event.message_chain.get(At)[0].qq, event.message_chain.get(Text)[0].text
        for order_check in order_list:
            if order_check in context:
                flag=False
                context = context.replace(order_check, '').replace(' ', '')
        if flag is True :return
        flag=True
        for check in ["傀影","水月", "萨米", "萨卡兹",'界园']:
            if check in context:
                flag = False
                rg_type = check
                try:game_count=int(context.replace(check,''))
                except:pass
        if flag is True :return
        recall_id = await bot.send(event, f'开始查询您的{rg_type}肉鸽信息，请耐心等待喵')
        await rouge_detailed_info(userid, rg_type,game_count,bot=bot, event=event)
        await bot.recall(recall_id['data']['message_id'])


    #菜单
    @bot.on(GroupMessageEvent)
    async def menu_steamid(event: GroupMessageEvent):
        order_list=['sklandhelp','森空岛帮助','森空岛help','明日方舟帮助','明日方舟help','终末地帮助']
        if event.pure_text in order_list:
            draw_json=[
            {'type': 'basic_set', 'img_name_save': None, 'img_path_save': 'data/pictures/cache'},
            {'type': 'avatar', 'subtype': 'common', 'img': [f"https://q1.qlogo.cn/g?b=qq&nk={event.self_id}&s=640"],'upshift_extra':15,
             'content': [f"[name]森空岛帮助菜单[/name]\n[time]各位博士们，欢迎使用森空岛功能～～[/time]"]},
            '[title]指令菜单：[/title]'
            '\n- 绑定森空岛账号：sklandbind, 森空岛绑定\n- 森空岛签到：sklandsign, 森空岛签到\n'
            '- 明日方舟信息：我的明日方舟、我的方舟、我的方舟z、明日方舟信息\n'
            '- 终末地信息：终末地信息、我的终末地、终末地便笺\n'
            '- 干员图鉴/攻略：明日方舟干员图鉴能天使、方舟干员攻略能天使\n'
            '- 模组图鉴/攻略：明日方舟模组图鉴能天使、方舟模组攻略能天使\n'
            '- 武器图鉴/攻略：终末地武器图鉴落草、终末地武器攻略落草 不知归\n'
            '- 图鉴与基质资源更新：明日方舟更新资源、终末地更新资源\n'
            '- 抽卡记录：明日方舟抽卡记录、终末地抽卡记录（首次查询自动获取）\n'
            '- 增量更新：明日方舟更新抽卡记录、终末地更新抽卡记录\n'
            '- 全量更新：明日方舟全量更新抽卡记录、终末地全量更新抽卡记录\n'
            '- 森空岛肉鸽战绩查询：sklandrogue, sklandrg、肉鸽信息 + 傀影or水月or萨米or萨卡兹or界园\n'
            '- 森空岛肉鸽详细战绩查询：sklandrogueinfo, sklandrginfo、肉鸽查询、查询肉鸽 + 傀影or水月or萨米or萨卡兹or界园 + 你想查询的最近场次\n'
            'eg: 水月肉鸽查询1 or 肉鸽查询水月3\n'
            '等待开发，欢迎催更（咕咕咕\n'
            '[des]                                             function by manshuo[/des]'
                       ]
            await bot.send(event, Image(file=(await manshuo_draw(draw_json))))




