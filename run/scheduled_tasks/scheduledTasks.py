# -*- coding: utf-8 -*-
import datetime
import random
from asyncio import sleep
from concurrent.futures.thread import ThreadPoolExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Image, Text, Card, Node
from framework_common.database_util.User import get_users_with_permission_above, get_user
from framework_common.database_util.llmDB import delete_user_history
from framework_common.framework_util.any_event import AnyEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.manshuo_draw import RedisDatabase, manshuo_draw
from framework_common.utils.random_str import random_str
from framework_common.utils.utils import download_img
from run.ai_llm.service.aiReplyCore import aiReplyCore
from run.anime_game_service.service.epicfree import epic_free_game_get
from run.basic_plugin.service.life_service import bingEveryDay, danxianglii
from run.basic_plugin.service.nasa_api import get_nasa_apod
from run.basic_plugin.service.weather_query import free_weather_query
from run.group_fun.service.lex_burner_Ninja import Lexburner_Ninja
from run.mai_reply.service.reply_engine import ReplyEngine
from run.mai_reply.service.simple_chat import simplified_chat
from run.resource_collector.service.asmr.asmr100 import random_asmr_100
from run.resource_collector.service.jmComic.jmComic import (
    JM_ranking_today, JM_ranking_week,
    download_covers_concurrent,
)
from run.streaming_media.service.Link_parsing.Link_parsing import bangumi_PILimg
from run.system_plugin.func_collection import trigger_tasks
from framework_common.database_util.ManShuoDrawCompatibleDataBase import AsyncSQLiteDatabase

# ──────────────────────────────────────────────────────────────
# 模块级 Scheduler 单例
#
# 问题根源：每次插件热重载或 LifecycleMetaEvent 触发都会重新调用
# main()，产生新的 AsyncIOScheduler 实例并注册新的 job，而旧的
# scheduler 既没有 shutdown() 又游离在外，导致同一任务被多次触发。
#
# 解法：将 scheduler 提升为模块级变量。同一进程生命周期内只有一个
# scheduler 实例；main() 被重新调用时先 shutdown 旧实例再重建，
# 确保 job 集合始终与当前配置保持一致、不重复累积。
# ──────────────────────────────────────────────────────────────
_scheduler: AsyncIOScheduler | None = None
_lifecycle_started = False


def _shutdown_existing_scheduler():
    """若已有 scheduler 在运行则安全停止它。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
    _scheduler = None


def main(bot: ExtendBot, config):
    # ── 插件热重载时先销毁旧 scheduler ──────────────────────────
    _shutdown_existing_scheduler()

    global _scheduler, _lifecycle_started
    _lifecycle_started = False
    logger = bot.logger
    scheduledTasks = config.scheduled_tasks.config["scheduledTasks"]
    _scheduler = AsyncIOScheduler()
    db = asyncio.run(AsyncSQLiteDatabase.get_instance())
    engine = ReplyEngine(config)

    # ── WS 重连防重入标志 ──────────────────────────────────────
    # 用 asyncio.Event 替代普通 bool：
    #   - 热重载后模块重新执行，_started 随之重置，但 _scheduler
    #     已被上方 shutdown，所以不会重复注册 job。
    #   - 同一插件实例内 LifecycleMetaEvent 可能因 WS 断线重连多次
    #     触发，Event 确保 start_scheduler() 只执行一次。
    _started = asyncio.Event()

    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(_):
        global _lifecycle_started
        if _started.is_set():
            logger.info("scheduledTasks: 已启动，跳过重复的 LifecycleMetaEvent")
            return
        _started.set()
        if _lifecycle_started or (_scheduler is not None and _scheduler.running):
            logger.info("scheduledTasks: 检测到调度器已运行，跳过重复启动")
            return
        _lifecycle_started = True
        await sleep(3)
        await bot.send_friend_message(
            config.common_config.basic_config["master"]["id"],
            "初次使用请发送\"/clear\"或\"/clearall\"以初始化对话功能"
        )
        await _start_scheduler()

    # ──────────────────────────────────────────────────────────
    # 任务执行器
    # ──────────────────────────────────────────────────────────
    async def task_executor(task_name, task_info):
        logger.info_func(f"执行任务：{task_name}, 信息:{task_info}")

        if task_name == "晚安问候":
            friend_list = (await bot.get_friend_list())["data"]
            if config.scheduled_tasks.config["scheduledTasks"]["晚安问候"]["onlyTrustUser"]:
                user_ids = await get_users_with_permission_above(
                    config.scheduled_tasks.config["scheduledTasks"]["晚安问候"]["trustThreshold"])
                filtered_users = [u for u in friend_list if u["user_id"] in user_ids]
            else:
                filtered_users = friend_list
            for user in filtered_users:
                try:
                    if not config.mai_reply.config["enable"]:
                        r = await aiReplyCore(
                            [{"text": "道晚安，直接发送结果，无需对此条提示做出应答。"}],
                            int(user["user_id"]), config, bot=bot)
                    else:
                        event = AnyEvent()
                        event.user_id = int(user["user_id"])
                        await engine.handle(
                            bot, event,
                            "现在是睡前时间。请像你自己想起这位用户一样，自然地道一声晚安，保持平时的角色和说话习惯，可以结合最近的对话表达关心。不要提及定时任务、系统提示或要求用户回复。")
                        await sleep(6)
                        continue
                    await bot.send_friend_message(int(user["user_id"]), r)
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向{user['nickname']}发送晚安问候失败，原因：{e}")
            logger.info_func("晚安问候任务执行完毕")

        elif task_name == "早安问候":
            friend_list = (await bot.get_friend_list())["data"]
            if config.scheduled_tasks.config["scheduledTasks"]["早安问候"]["onlyTrustUser"]:
                user_ids = await get_users_with_permission_above(
                    config.scheduled_tasks.config["scheduledTasks"]["早安问候"]["trustThreshold"])
                filtered_users = [u for u in friend_list if u["user_id"] in user_ids]
            else:
                filtered_users = friend_list
            for user in filtered_users:
                try:
                    user_info = await get_user(int(user["user_id"]))
                    city = (user_info.city or "").strip()
                    if not city or city == "通辽":
                        prompt = ("请像你自己主动想起这位用户一样发送一条自然的早安消息，保持平时的角色和说话习惯。"
                                  "你还不知道用户所在的城市，请自然地询问对方所在城市，并说明之后可以为他播报天气。"
                                  "不要提及定时任务或系统提示。")
                    else:
                        weather = await free_weather_query(city)
                        prompt = (f"请像你自己主动想起这位用户一样发送一条自然的早安消息，保持平时的角色和说话习惯。"
                                  f"顺便播报{city}今天的天气并给出贴心建议：{weather}"
                                  "不要提及定时任务或系统提示。")
                    if not config.mai_reply.config["enable"]:
                        r = await aiReplyCore([{"text": prompt}],
                                              int(user["user_id"]), config, bot=bot)
                    else:
                        event = AnyEvent()
                        event.user_id = int(user["user_id"])
                        await engine.handle(bot, event, prompt)
                        await sleep(6)
                        continue
                    await bot.send_friend_message(int(user["user_id"]), r)
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向{user['nickname']}发送早安问候失败，原因：{e}")
            logger.info_func("早安问候任务执行完毕")

        elif task_name == "新闻":
            pass

        elif task_name == "免费游戏喜加一":
            pass

        elif task_name == "每日天文":
            logger.info_func("获取今日nasa天文信息推送")
            img, text = await get_nasa_apod(
                config.basic_plugin.config["nasa_api"]["api_key"],
                config.common_config.basic_config["proxy"]["http_proxy"])
            if config.mai_reply.config["enable"]:
                model = config.mai_reply.config["trigger_llm"]["model"]
                api_key = config.mai_reply.config["trigger_llm"]["api_key"]
                base_url = config.mai_reply.config["trigger_llm"]["base_url"]
                text = await simplified_chat(
                    base_url,
                    [{"role": "user", "content": f"翻译下面的文本，直接发送结果，不要发送'好的'之类的命令应答提示。要翻译的文本为：{text}"}],
                    model=model, api_key=api_key,
                    system_prompt="你是一个严谨的翻译。")
            else:
                text = await aiReplyCore(
                    [{"text": f"翻译下面的文本，直接发送结果，不要发送'好的'之类的命令应答提示。要翻译的文本为：{text}"}],
                    random.randint(1000000, 99999999), config, bot=bot, tools=None,
                    system_instruction="你是一个翻译机器人，请完成高效且准确的翻译。我给你文本，你需要直接给出翻译结果")
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["每日天文"]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id, [Text(text), Image(file=img)])
                except Exception as e:
                    logger.error(f"向群{group_id}推送每日天文失败，原因：{e}")
                await sleep(6)
            logger.info_func("每日天文任务执行完毕")

        elif task_name == "摸鱼人日历":
            logger.info_func("获取摸鱼人日历")

        elif task_name == "bing每日图像":
            text, p = await bingEveryDay()
            logger.info_func("推送bing每日图像")
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["bing每日图像"]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id, [Text(text), Image(file=p)])
                except Exception as e:
                    logger.error(f"向群{group_id}推送bing每日图像失败，原因：{e}")
                await sleep(6)
            logger.info_func("bing每日图像任务执行完毕")

        elif task_name == "单向历":
            logger.info_func("获取单向历")
            path = await danxianglii()
            logger.info_func("推送单向历")
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["单向历"]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id, [Image(file=path)])
                except Exception as e:
                    logger.error(f"向群{group_id}推送单向历失败，原因：{e}")
                await sleep(6)
            logger.info_func("单向历推送执行完毕")

        elif task_name == "bangumi":
            logger.info_func("获取bangumi每日推送")
            weekday = datetime.datetime.today().weekday()
            weekdays = ["一", "二", "三", "四", "五", "六", "日"]
            bangumi_json = await bangumi_PILimg(
                filepath='data/pictures/cache/',
                type_soft=f'bangumi 周{weekdays[weekday]}放送',
                name=f'bangumi 周{weekdays[weekday]}放送',
                type='calendar', bot_id=None)
            if bangumi_json['status']:
                logger.info_func("推送bangumi每日番剧")
                for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["bangumi"]["groups"]:
                    text = config.scheduled_tasks.config['scheduledTasks']['bangumi']['text']
                    if group_id == 0:
                        continue
                    try:
                        await bot.send_group_message(group_id,
                                                     [Text(text), Image(file=bangumi_json['pic_path'])])
                    except Exception as e:
                        logger.error(f"向群{group_id}推送bangumi失败，原因：{e}")
                    await sleep(6)
            logger.info_func("bangumi推送执行完毕")

        elif task_name == "nightASMR":
            logger.info_func("获取晚安ASMR")

            async def get_random_asmr():
                try:
                    r = await random_asmr_100(
                        proxy=config.common_config.basic_config["proxy"]["http_proxy"])
                    i = random.choice(r['media_urls'])
                    return i, r
                except Exception as e:
                    logger.error(f"获取晚安ASMR失败，原因：{e}")
                    return await get_random_asmr()

            i, r = await get_random_asmr()
            try:
                img = await download_img(
                    r['mainCoverUrl'],
                    f"data/pictures/cache/{random_str()}.png",
                    config.resource_collector.config["asmr"]["gray_layer"],
                    proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            except Exception as e:
                bot.logger.error(f"download_img error:{e}")
                img = None
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["nightASMR"]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id,
                                                 Card(audio=i[0], title=i[1], image=r['mainCoverUrl']))
                    if img:
                        await bot.send_group_message(group_id, [
                            Text(f"随机asmr\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}"),
                            Image(file=img)])
                    else:
                        await bot.send_group_message(group_id, [
                            Text(f"随机asmr\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}")])
                except Exception as e:
                    logger.error(f"向群{group_id}推送nightASMR失败，原因：{e}")
                await sleep(6)
            logger.info_func("nightASMR推送执行完毕")

        elif task_name in ["早安", "晚安", "午安"]:
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary[task_name]["groups"]:
                if group_id == 0:
                    continue
                try:
                    fake_id = random.randint(1000000, 99999999)
                    if config.mai_reply.config["enable"]:
                        model = config.mai_reply.config["trigger_llm"]["model"]
                        api_key = config.mai_reply.config["trigger_llm"]["api_key"]
                        base_url = config.mai_reply.config["trigger_llm"]["base_url"]
                        r = await simplified_chat(
                            base_url,
                            [{"role": "user", "content": f"你现在是一个群机器人，向群内所有人道{task_name}，直接发送结果，不要发送多余内容"}],
                            model=model, api_key=api_key,
                            system_prompt="你处于群聊环境中。")
                    else:
                        r = await aiReplyCore(
                            [{"text": f"你现在是一个群机器人，向群内所有人道{task_name}，直接发送结果，不要发送多余内容"}],
                            fake_id, config, bot=bot)
                    await delete_user_history(fake_id)
                    await bot.send_group_message(group_id, r)
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向群{group_id}推送{task_name}失败，原因：{e}")
                    continue

        elif task_name == "忍术大学习":
            logger.info_func("获取忍术大学习")

            async def get_random_renshu():
                from run.group_fun.service.lex_burner_Ninja import Lexburner_Ninja
                ninja = Lexburner_Ninja()
                ninjutsu = await ninja.random_ninjutsu()
                tags = "".join(tag['name'] for tag in ninjutsu['tags'])
                parse_message = (f"忍术名称: {ninjutsu['name']}\n忍术介绍: {ninjutsu['description']}\n"
                                 f"忍术标签: {tags}\n忍术教学: {ninjutsu['videoLink']}\n"
                                 f"更多忍术请访问: https://wsfrs.com/")
                if not ninjutsu['imageUrl']:
                    return [Image(file="run/group_fun/service/img.png"), Text("啊没图使\n"), Text(parse_message)]
                return [Image(file=ninjutsu['imageUrl']), Text(parse_message)]

            messages = await get_random_renshu()
            logger.info_func("推送忍术大学习")
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary[task_name]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id, messages)
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向群{group_id}推送{task_name}失败，原因：{e}")
                    continue

        elif task_name == "每日壁画王":
            logger.info(f"获取到发言排行榜查询需求")
            all_users = await db.read_all_users()
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary[task_name]["groups"]:
                if group_id == 0:
                    continue
                try:
                    today = datetime.datetime.now()
                    current_day = f'{today.year}_{today.month}_{today.day}'
                    number_speeches_check_list = []
                    for user in all_users:
                        if ('number_speeches' in all_users[user]
                                and f'{group_id}' in all_users[user]['number_speeches']
                                and current_day in all_users[user]['number_speeches'][f'{group_id}']):
                            target_name = (await bot.get_group_member_info(group_id, user))['data']['nickname']
                            number_speeches_check_list.append({
                                'name': user, 'nicknime': target_name,
                                'number_speeches_count': all_users[user]['number_speeches'][f'{group_id}'][current_day]
                            })
                    number_speeches_check_list = sorted(
                        number_speeches_check_list,
                        key=lambda x: x["number_speeches_count"], reverse=True)[:16]
                    for idx, item in enumerate(number_speeches_check_list, start=1):
                        item["rank"] = idx
                    bot.logger.info("进入图片制作")
                    number_speeches_check_draw_list = [
                        {'type': 'basic_set', 'img_width': 1200, 'auto_line_change': False},
                        {'type': 'avatar', 'subtype': 'common',
                         'img': [f"https://q1.qlogo.cn/g?b=qq&nk={bot.id}&s=640"],
                         'content': [f"[name]发言排行榜[/name]\n[time]{datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M')}[/time]"]},
                        {'type': 'avatar', 'subtype': 'common',
                         'img': [f"https://q1.qlogo.cn/g?b=qq&nk={item['name']}&s=640"
                                 for item in number_speeches_check_list],
                         'content': [f"[name]{item['nicknime']}[/name]\n[time]发言次数：{item['number_speeches_count']}次 排名：{item['rank']}[/time]"
                                     for item in number_speeches_check_list],
                         'number_per_row': 2,
                         'background': [f"https://q1.qlogo.cn/g?b=qq&nk={item['name']}&s=640"
                                        for item in number_speeches_check_list]},
                    ]
                    await bot.send_group_message(
                        group_id, Image(file=(await manshuo_draw(number_speeches_check_draw_list))))
                    await bot.send_group_message(group_id, "今日壁画王")
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向群{group_id}推送{task_name}失败，原因：{e}")
                    continue

        elif task_name == "epic喜加一":
            proxy = config.common_config.basic_config['proxy']['http_proxy'] or None
            path = await epic_free_game_get(bot=bot, proxy_for_draw=proxy)
            logger.info_func("推送epic喜加一")
            for group_id in config.scheduled_tasks.sheduled_tasks_push_groups_ordinary[task_name]["groups"]:
                if group_id == 0:
                    continue
                try:
                    await bot.send_group_message(group_id, Image(file=path))
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向群{group_id}推送{task_name}失败，原因：{e}")
                    continue

        # ── JM 每日推送 ─────────────────────────────────────────
        elif task_name == "jm每日推送":
            """
            每日定时向订阅群推送今日 JM 排行榜（图文合并转发）。
            使用 JM_ranking_today + download_covers_concurrent，
            与 resource_search.py 中 call_jm_ranking() 的实现保持
            一致，但以纯文本降级方式兜底，避免封面下载失败导致整体
            任务崩掉。
            """
            logger.info_func("开始推送 JM 每日排行")
            push_cfg = config.scheduled_tasks.sheduled_tasks_push_groups_ordinary.get(
                "jm每日推送", {})
            groups = push_cfg.get("groups", [])


            jm_cfg = config.resource_collector.config["JMComic"]
            anti_nsfw = jm_cfg.get("anti_nsfw", "obfuscate")
            limit = jm_cfg.get("ranking_limit", 10)  # 榜单条数，默认 10
            cover_workers = jm_cfg.get("cover_workers", 5)  # 并发封面下载线程数

            mode="today"
            title_text = "📅 今日JM热门榜" if mode == "today" else "📆 本周JM热门榜"
            bot.logger.info(f"{title_text} 正在加载，请稍候...")

            # ── 2. 获取榜单列表（同步，有缓存基本秒返回）────────────
            loop = asyncio.get_running_loop()
            try:
                with ThreadPoolExecutor() as executor:
                    if mode == "today":
                        id_title_list = await loop.run_in_executor(
                            executor, JM_ranking_today, limit
                        )
                    else:
                        id_title_list = await loop.run_in_executor(
                            executor, JM_ranking_week, limit
                        )
            except Exception as e:
                bot.logger.error(f"jm_ranking fetch error: {e}")
                #await bot.send(event, "获取榜单失败，请稍后再试", True)
                return

            if not id_title_list:
                #await bot.send(event, "暂时没有获取到榜单数据，请稍后再试", True)
                return

            # ── 3. 并发下载封面（在线程池中执行，不阻塞事件循环）────
            try:
                with ThreadPoolExecutor() as executor:
                    ranked_items = await loop.run_in_executor(
                        executor,
                        download_covers_concurrent,
                        id_title_list,
                        anti_nsfw,
                        cover_workers,
                    )
            except Exception as e:
                bot.logger.error(f"jm_ranking cover download error: {e}")
                bot.logger.error("封面下载失败，请稍后再试")
                return

            # ── 4. 组装合并转发消息 ────────────────────────────────
            cm_list = [
                Node(content=[Text(
                    f"{title_text}\n共 {len(ranked_items)} 部\n"
                    f"发送「验车+车牌号」可查看预览，「jm下载+车牌号」可下载完整PDF"
                )])
            ]

            for rank, (aid, title, cover_path) in enumerate(ranked_items, start=1):
                info_text = f"🏅 第 {rank} 名\n车牌号：{aid}\n标题：{title}"
                if cover_path:
                    print(cover_path)
                    cm_list.append(Node(content=[Text(info_text), Image(file=cover_path)]))
                else:
                    # 封面下载失败时退化为纯文字，不中断整体输出
                    cm_list.append(Node(content=[Text(f"{info_text}\n（封面加载失败）")]))
            bot.logger.info(f"向{len(groups)}个群推送")
            intro=config.scheduled_tasks.config["scheduledTasks"]["jm每日推送"]["text"]
            for group_id in groups:
                if group_id == 0:
                    continue
                try:
                    #print(group_id)
                    #print(intro)
                    await bot.send_group_message(group_id, intro)
                    #print(cm_list)
                    await bot.send_group_message(group_id, cm_list)
                    await sleep(6)
                except Exception as e:
                    logger.error(f"向群{group_id}推送 jm每日推送 失败，原因：{e}")
                    continue
            logger.info_func("JM 每日推送执行完毕")

    # ──────────────────────────────────────────────────────────
    # 动态注册 job
    # ──────────────────────────────────────────────────────────
    def create_dynamic_jobs():
        for task_name, task_info in scheduledTasks.items():
            if task_info.get('enable'):
                hour, minute = map(int, task_info['time'].split('/'))
                logger.info_func(f"定时任务已激活：{task_name}，时间：{hour}:{minute}")
                _scheduler.add_job(
                    task_executor,
                    CronTrigger(hour=hour, minute=minute),
                    args=[task_name, task_info],
                    misfire_grace_time=120,
                )

    async def _start_scheduler():
        global _lifecycle_started
        if _scheduler is None or _scheduler.running:
            return
        create_dynamic_jobs()
        _scheduler.start()

    # ──────────────────────────────────────────────────────────
    # 订阅管理与手动触发
    # ──────────────────────────────────────────────────────────
    allow_args = [
        "忍术大学习", "每日天文", "bing每日图像", "单向历", "bangumi",
        "nightASMR", "摸鱼人日历", "新闻", "免费游戏喜加一",
        "早安", "晚安", "午安", "每日壁画王", "epic喜加一", "jm每日推送",
    ]

    @bot.on(GroupMessageEvent)
    async def _test_task(event: GroupMessageEvent):
        if (event.pure_text == "测试定时任务"
                and event.user_id == config.common_config.basic_config["master"]['id']):
            for task_name, task_info in scheduledTasks.items():
                if task_name!="jm每日推送":
                    continue
                await task_executor(task_name, task_info)

    @bot.on(GroupMessageEvent)
    async def _cron_add(event: GroupMessageEvent):
        if not event.pure_text.startswith("/cron add "):
            return
        args = event.pure_text.split("/cron add ")

        async def check_and_add_group_id(arg):
            if arg and arg in allow_args:
                push_data = config.scheduled_tasks.sheduled_tasks_push_groups_ordinary
                if arg not in push_data:
                    push_data[arg] = {"groups": [], "users": []}
                if event.group_id in push_data[arg]["groups"]:
                    if args[1] != "all":
                        await bot.send(event, f"本群已经订阅过了{arg}")
                    return
                push_data[arg]["groups"].append(event.group_id)
                config.save_yaml("sheduled_tasks_push_groups_ordinary", plugin_name="scheduled_tasks")
                if args[1] != "all":
                    await bot.send(event, f"{arg}订阅成功")
            else:
                if args[1] != "all":
                    await bot.send(event, f"不支持的任务，可选任务有：{allow_args}")

        if args[1] == "all":
            for allow_arg in allow_args:
                await check_and_add_group_id(allow_arg)
            await bot.send(event, "所有订阅已更新")
        else:
            await check_and_add_group_id(args[1])

    @bot.on(GroupMessageEvent)
    async def _cron_remove(event: GroupMessageEvent):
        if not event.pure_text.startswith("/cron remove "):
            return
        args = event.pure_text.split("/cron remove ")

        async def remove_group_id(arg):
            if arg and arg in allow_args:
                push_data = config.scheduled_tasks.sheduled_tasks_push_groups_ordinary
                if arg not in push_data:
                    if args[1] != "all":
                        await bot.send(event, "本群没有订阅过")
                    return
                if event.group_id in push_data[arg]["groups"]:
                    push_data[arg]["groups"].remove(event.group_id)
                    config.save_yaml("sheduled_tasks_push_groups_ordinary",
                                     plugin_name="scheduled_tasks")
                    if args[1] != "all":
                        await bot.send(event, f"取消{arg}订阅成功")
                else:
                    if args[1] != "all":
                        await bot.send(event, "本群没有订阅过")
            else:
                if args[1] != "all":
                    await bot.send(event, f"不支持的任务，可选任务有：{allow_args}")

        if args[1] == "all":
            for allow_arg in allow_args:
                await remove_group_id(allow_arg)
            await bot.send(event, "所有订阅已取消")
        else:
            await remove_group_id(args[1])

    @bot.on(GroupMessageEvent)
    async def _on_demand(event: GroupMessageEvent):
        if event.pure_text == "今日天文":
            data = await trigger_tasks(bot, event, config, "nasa_daily")
            img = data["要发送的图片"]
            text = data["将下列文本翻译后发送"]
            text = await aiReplyCore(
                [{"text": f"翻译下面的文本，直接发送结果，不要发送'好的'之类的命令应答提示。要翻译的文本为：{text}"}],
                random.randint(1000000, 99999999), config, bot=bot, tools=None)
            await bot.send(event, [Text(text), Image(file=img)])
        elif event.pure_text == "单向历":
            await trigger_tasks(bot, event, config, "单向历")
