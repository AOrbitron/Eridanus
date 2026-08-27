import asyncio
import base64
import datetime
import json
import random
import re
import traceback
import uuid
from asyncio import sleep
from pathlib import Path
from typing import Optional, Dict, Any

import aiohttp
import httpx
from apscheduler.triggers.cron import CronTrigger

# from framework_common.utils.install_and_import import install_and_import
# try:
#     qzone_api=install_and_import("qzone-api","qzone_api")
#     from qzone_api import QzoneApi
#     from qzone_api.login import QzoneLogin
# except:
#     traceback.print_exc()
#     print("请自行搜索安装：Microsoft Visual C++ 2013 Redistributable Package")
#     print("请自行搜索安装：Microsoft Visual C++ 2013 Redistributable Package")
#     print("请自行搜索安装：Microsoft Visual C++ 2013 Redistributable Package")
#
# from developTools.event.events import LifecycleMetaEvent, GroupMessageEvent, PrivateMessageEvent
# from developTools.message.message_components import Text, Image, Mface
# from framework_common.utils.utils import download_img, get_img
# from run.ai_generated_art.aiDraw import call_text2img1
# from run.ai_generated_art.service.simple_text2img import simple_call_text2img1
# from run.ai_llm.service.aiReplyCore import aiReplyCore
# from run.qq_zone.service.QzoneApiFixed import QzoneApiFixed
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
def main(bot: ExtendBot,config: YAMLManager):
    return
    qzone_login = QzoneLogin()
    login_result = None
    login_task = None
    qzone = QzoneApiFixed()
    qzone_status = False

    """
    本地的cookie缓存
    """
    cookie_file = Path("qzone_cookie.json")  # ✅ 新增
    def load_cookie_cache():
        if cookie_file.exists():
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                bot.logger.info("已加载本地 cookie.json")
                return data
            except Exception as e:
                bot.logger.warning(f"读取 cookie.json 失败: {e}")
        return None

    def save_cookie_cache(data):
        try:
            with open(cookie_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            bot.logger.info("已保存 cookie.json")
        except Exception as e:
            bot.logger.error(f"保存 cookie.json 失败: {e}")
    if load_cookie_cache():
        login_result = load_cookie_cache()
        bot.logger.info("使用本地 cookie 登录 Qzone")

    @bot.on(LifecycleMetaEvent)
    async def handle_lifecycle_event(event: LifecycleMetaEvent):
        nonlocal login_result
        if not login_result:
            cached = load_cookie_cache()
            if cached:
                login_result = cached
                bot.logger.info("使用本地 cookie 登录 Qzone")
                return
            login_result = await qzone_login.login()
    """
    cookie过期监测
    """
    global activated_monitor
    activated_monitor = False
    failed_times = 0

    @bot.on(LifecycleMetaEvent)
    async def monitor_cookie_expire(event: LifecycleMetaEvent):
        global activated_monitor
        if not activated_monitor and config.qq_zone.config["cookie设置"]["保活"]:
            activated_monitor = True
            bot.logger.info("启动 qzone cookie 过期监测")

            async def check_cookie_expire():
                global failed_times,login_result
                login_result["qq"] = login_result["qq"].replace("o", "")
                target_qq = int(login_result["qq"])

                cookies = login_result["cookies"]
                cookies = '; '.join([f"{k}={v}" for k, v in cookies.items()])

                g_tk = login_result["bkn"]
                #print(login_result)
                r = await qzone._get_zone(target_qq=target_qq, g_tk=g_tk, cookies=cookies)
                #print(r,type(r))
                if '"code":0' not in r:
                    #await bot.send_friend_message(config.common_config.basic_config["master"]['id'],
                                                  #[Text(f"cookie可能过期: {r.get('msg')}")])

                    failed_times+=1
                    if failed_times>10 and config.qq_zone.config["cookie设置"]["失效时自动重新登陆"]: await login_task_wrapper(event)
                    bot.logger.warning(f"cookie过期: {r}")
                else:
                    failed_times=0
                    bot.logger.info("cookie 未过期")
            while True:
                bot.logger.info("开始 cookie 过期监测: 尝试抓取空间动态")
                try:
                    await check_cookie_expire()
                except Exception as e:
                    #await login_task_wrapper(None)
                    traceback.print_exc()
                    bot.logger.error(f"cookie过期监测失败: {str(e)}")
                await asyncio.sleep(200)
    """
    控制指令
    """
    @bot.on(GroupMessageEvent)
    async def handle_group_message_event(event: GroupMessageEvent):
        nonlocal qzone_status
        if event.pure_text=="/qzone login" and event.user_id==config.common_config.basic_config["master"]['id']:
            await login_task_wrapper(event)
        elif event.pure_text=="/发空间" and event.user_id==config.common_config.basic_config["master"]['id']:
            await bot.send(event,"下条消息将被发送到空间")
            await sleep(1)
            qzone_status=True
        elif qzone_status and event.user_id==config.common_config.basic_config["master"]['id']:
            qzone_status=False
            await set_cache(event)
        elif event.pure_text=="获取动态":
            await bot.send(event, [Text("正在获取动态...")])
            login_result["qq"]=login_result["qq"].replace("o","")
            target_qq=int(login_result["qq"])

            cookies = login_result["cookies"]
            cookies='; '.join([f"{k}={v}" for k, v in cookies.items()])

            g_tk = login_result["bkn"]
            print(login_result)
            r=await qzone._get_zone(target_qq=target_qq,g_tk=g_tk,cookies=cookies)
            print(r)
            if '"code":0' not in r:
                bot.logger.warning(f"获取动态失败: {r}")
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'], [Text(f"cookie可能过期: {r.get('msg')}")])
            else:
                bot.logger.info("cookie 未过期")

    @bot.on(PrivateMessageEvent)
    async def handle_private_message_event(event: PrivateMessageEvent):
        nonlocal qzone_status
        if event.pure_text=="/qzone login" and event.user_id==config.common_config.basic_config["master"]['id']:
            await login_task_wrapper(event)
        elif event.pure_text=="/发空间" and event.user_id==config.common_config.basic_config["master"]['id']:
            await bot.send(event, "下条消息将被发送到空间")
            await sleep(1)
            qzone_status=True
        elif qzone_status and event.user_id==config.common_config.basic_config["master"]['id']:
            qzone_status=False
            await set_cache(event)


    async def set_cache(event):
        text_cache = ""
        img_cache = []
        for msg in event.message_chain:
            if isinstance(msg, Text):
                text_cache += msg.text
            elif isinstance(msg, Image) or isinstance(msg, Mface):
                url=await get_img(event,bot)

                path = f"data/pictures/cache/{uuid.uuid4()}.png"
                await download_img(url, path)
                img_cache.append(path)
        await send_to_qzone(event, text_cache, img_cache)
        #return text_cache, img_cache
    async def send_to_qzone(event, text_cache, img_cache):
        nonlocal login_result
        """
        目前没写多图支持
        """
        try:
            if img_cache:
                bot.logger.info("发送到空间的消息包含图片")
                img_path = img_cache[0]
                cookies = login_result["cookies"]
                login_result["qq"] = login_result["qq"].replace("o", "")

                r = await qzone._send_zone_with_pic(
                    target_qq=int(login_result["qq"]),
                    content=text_cache,
                    pic_path=img_path,
                    cookies=cookies,
                    g_tk=login_result["bkn"]
                )
            else:
                bot.logger.info("发送到空间的消息不包含图片")
                cookies = login_result["cookies"]
                login_result["qq"] = login_result["qq"].replace("o", "")

                r = await qzone._send_zone(
                    target_qq=int(login_result["qq"]),
                    content=text_cache,
                    cookies='; '.join([f"{k}={v}" for k, v in cookies.items()]),
                    g_tk=login_result["bkn"]
                )
        except Exception as e:
            bot.logger.error(f"发送到空间失败: {str(e)}")
            await bot.send_friend_message(config.common_config.basic_config["master"]['id'], [Text(f"发送到空间失败: {str(e)} token过期,请重新登录")])
            await login_task_wrapper(event)

    async def login_task_wrapper(event):
        nonlocal login_result, login_task
        try:
            await bot.send(event, [Text("请使用机器人账号扫描二维码(二维码已发送至私聊)...")])
        except Exception as e:
            bot.logger.error(f"发送二维码失败: {str(e)}")

        qr_path = Path("./QR.png")
        if qr_path.exists():
            qr_path.unlink()

        login_task = asyncio.create_task(qzone_login.login())
        max_wait = 10
        for i in range(max_wait * 10):
            await asyncio.sleep(0.1)
            if qr_path.exists():
                await bot.send_friend_message(config.common_config.basic_config["master"]['id'], [Image(file="./QR.png")])
                break
        else:
            bot.logger.error(f"二维码生成超时,请重试")
            #await bot.send(event, [Text("二维码生成超时,请重试")])
            return
        bot.logger.info("等待用户扫描二维码...")
        try:
            login_result = await login_task
            try:
                await bot.send(event, [Text("登录成功!")])
            except Exception as e:
                bot.logger.error(f"发送登录成功消息失败: {str(e)}")
            print(login_result)
            save_cookie_cache(login_result)
            if qr_path.exists():
                qr_path.unlink()
        except Exception as e:
            await bot.send(event, [Text(f"登录失败: {str(e)}")])

    """
    机器人自动发空间
    """
    logger = bot.logger
    scheduledTasks = config.qq_zone.config["定时发空间"]
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    enabled = False

    @bot.on(GroupMessageEvent)
    async def start_scheduler_on_lifecycle(event: GroupMessageEvent):
        nonlocal enabled
        if not enabled:
            enabled = True
            await start_scheduler()

    # 定时任务执行器（留空，仅打印任务信息）
    async def task_executor(task_name, task_info):
        logger.info(f"执行任务：{task_name}, 时间：{datetime.datetime.now()}")

        # === 先获取老黄历信息 ===
        festival_or_term = await get_almanac_info()
        has_festival = bool(festival_or_term)

        if task_name in ["早安", "晚安"]:
            random_seed = random.randint(0, 114514)

            # === 构造 prompt ===
            if has_festival:
                prompt = (
                    f"你现在要编辑一条qq空间{task_name}消息。今天是{festival_or_term}，"
                    f"请在严格遵循你的角色设定的前提下，结合{festival_or_term}的主题，"
                    f"编写一条适合作为你的动态的{task_name}问候消息（可以谈论天气(随机天气，不要总是晴天)、"
                    f"心情、节日/节气感触等）。注意，这条消息面向所有用户，而不只是我。"
                    f"编辑完成后，请直接发送编辑好的内容，无需对当前提示内容做出回应，结果将直接被发送至动态。"
                )
            else:
                prompt = (
                    f"你现在要编辑一条qq空间{task_name}消息。请在严格遵循你的角色设定的前提下，"
                    f"编写一条适合作为你的动态的{task_name}问候消息(可以谈论天气(随机天气，不要总是晴天)、心情、感触等)。"
                    f"注意，本条消息面向所有用户，而不只是我。编辑完成后，请直接发送编辑好的内容，无需对当前提示内容做出回应，结果将直接被发送至动态。"
                )

            # === 生成文字内容 ===
            r = await aiReplyCore([{"text": prompt}], random_seed, config, bot=bot, tools=None)

            # === 是否绘制图片 ===
            if not config.qq_zone.config["定时发空间"][task_name]["绘制图片"]:
                await send_to_qzone(None, r, [])
            else:
                if has_festival:
                    tag_prompt = (
                        f"你现在是一个绘图bot，请根据{festival_or_term}的主题生成英文tag用于图片绘制，"
                        f"保持与{task_name}氛围相符（动作、表情、场景、天气、节日元素等均可），"
                        f"生成适合于stable diffusion的英文tag。"
                        f"编辑完成后，请直接发送编辑好的内容，无需对提示词做出回应，结果将直接被输入至图片生成器。"
                    )
                else:
                    tag_prompt = (
                        f"你现在是一个绘图bot，你需要根据你的角色设定信息，生成英文tag用于图片绘制。"
                        f"请紧扣{task_name}的主题（动作、表情、场景、天气等均可任意发挥），"
                        f"生成适合于stable diffusion的英文tag。编辑完成后，请直接发送编辑好的内容，无需对提示词做出回应，结果将直接被输入至图片生成器。"
                    )

                # === 生成绘图tag ===
                r2 = await aiReplyCore([{"text": tag_prompt}], random_seed, config, bot=bot, tools=None)
                if r2:
                    img_path = await simple_call_text2img1(config, r2)
                    if img_path:
                        await send_to_qzone(None, r, [img_path])
                    else:
                        await send_to_qzone(None, r, [])
    def create_dynamic_jobs():
        for task_name, task_info in scheduledTasks.items():
            if task_info.get("enable"):
                hour, minute = map(int, task_info.get("time").split("/"))
                logger.info_func(f"定时任务已激活：{task_name}，时间：{hour}:{minute}")
                scheduler.add_job(
                    task_executor,
                    CronTrigger(hour=hour, minute=minute),
                    args=[task_name, task_info],
                    misfire_grace_time=120,
                )

    async def start_scheduler():
        create_dynamic_jobs()
        scheduler.start()
        logger.info_func("定时任务调度器已启动")
    @bot.on(GroupMessageEvent)
    async def _(event: GroupMessageEvent):
        if event.pure_text == "测试定时空间" and event.user_id == config.common_config.basic_config["master"]['id']:
            for task_name, task_info in scheduledTasks.items():
                await task_executor(task_name, task_info)
        if event.pure_text=="发送晚安" and event.user_id==config.common_config.basic_config["master"]['id']:
            await bot.send(event, [Text("正在向空间发送晚安消息...")])
            await task_executor("晚安", scheduledTasks["晚安"])

        if event.pure_text=="发送早安" and event.user_id==config.common_config.basic_config["master"]['id']:
            await bot.send(event, [Text("正在向空间发送早安消息...")])
            await task_executor("早安", scheduledTasks["早安"])
    """
    老黄历
    """

    async def get_almanac_info():
        logger=bot.logger
        """调用老黄历API，返回节日/节气信息"""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        url = f"https://www.36jxs.com/api/Commonweal/almanac?sun={today}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    data = await resp.json()
                    if data.get("code") != 1:
                        logger.warning(f"老黄历API返回异常: {data}")
                        return None
                    d = data.get("data", {})
                    # 优先判断节气或节日
                    solar_term = d.get("SolarTermName") or ""
                    lunar_festival = d.get("LJie") or ""
                    gregorian_festival = d.get("GJie") or ""

                    # 取第一个节日
                    if lunar_festival:
                        lunar_festival = lunar_festival.split()[0]
                    if gregorian_festival:
                        gregorian_festival = gregorian_festival.split()[0]

                    # 优先级：节气 > 农历节日 > 公历节日
                    festival_or_term = solar_term or lunar_festival or gregorian_festival
                    return festival_or_term
        except Exception as e:
            logger.error(f"获取老黄历信息失败: {e}")
            return None
