import asyncio
import random
import shutil
import traceback
import pprint
from framework_common.utils.install_and_import import install_and_import
import subprocess
from concurrent.futures.thread import ThreadPoolExecutor

from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Image, Node, Text, File, Card
from developTools.utils.logger import get_logger
from framework_common.database_util.User import get_user
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.PDFEncrypt import AsyncPDFEncryptor
from run.resource_collector.service.asmr.asmr100 import random_asmr_100, latest_asmr_100, choose_from_latest_asmr_100, \
    choose_from_hotest_asmr_100
from run.resource_collector.service.jmComic.jmComic import (
    JM_search, JM_search_week, JM_search_month,
    JM_ranking_week, JM_ranking_today,get_jm_name,
    download_covers_concurrent,OpenListClient,check_jm_multiple,
    downloadComic, downloadALLAndToPdf, JM_search_id, JM_search_with_covers,
)
from run.resource_collector.service.zLibrary.zLib import search_book, download_book
from run.resource_collector.service.zLibrary.zLibrary import Zlibrary
from framework_common.utils.random_str import random_str
from framework_common.utils.utils import download_file, merge_audio_files, download_img, delay_recall
import os

logger=get_logger()
module_config=YAMLManager.get_instance()
proxy = module_config.common_config.basic_config["proxy"]["http_proxy"]
if proxy != "":
    proxies = {
        "http": proxy,
        "https": proxy
    }
else:
    proxies = None
if module_config.resource_collector.config["z_library"]["email"] != "" and module_config.resource_collector.config["z_library"][
    "password"] != "":
    global Z
    try:
        Z = Zlibrary(email=module_config.resource_collector.config["z_library"]["email"],
                     password=module_config.resource_collector.config["z_library"]["password"], proxies=proxies)
        logger.info("✅ z_library 登陆成功")
    except Exception as e:
        logger.error(f"❌ z_library login error:{e}")

global operating
operating = {}  #jm文件共享的维护列表

async def search_book_info(bot,event,config,info):
    global Z
    user_info = await get_user(event.user_id)
    if user_info.permission >= config.resource_collector.config["z_library"]["search_operate_level"]:

        await bot.send(event, "正在搜索中，请稍候...")
        result =await search_book(Z, info, config.resource_collector.config["z_library"]["search_num"])
        forward_list = []
        for r in result:
            forward_list.append(Node(content=[Text(r[0]), Image(file=r[1])]))
        #print(forward_list)
        await bot.send(event, forward_list)
        # await bot.send(event,Image(file=p)])
        # print(r)
    else:
        await bot.send(event, "你没有权限使用该功能")
async def call_download_book(bot,event,config,book_id: str,hash:str):
    global Z
    user_info = await get_user(event.user_id)
    if user_info.permission >= config.resource_collector.config["z_library"]["download_operate_level"]:
        await bot.send(event, "正在下载中，请稍候...")
        loop = asyncio.get_running_loop()
        try:
            with ThreadPoolExecutor() as executor:
                path = await loop.run_in_executor(executor,download_book,Z,book_id.strip(),hash.strip())
            await bot.send(event, File(file=path))
            await bot.send(event, "下载成功，请查看文件",True)
        except Exception as e:
            bot.logger.error(f"download_book error:{e}")
            await bot.send(event, "下载失败，请稍后再试",True)
    else:
        await bot.send(event, "你没有权限使用该功能")

async def call_asmr(bot,event,config,try_again=False,mode="random"):
    user_info = await get_user(event.user_id)
    if user_info.permission >= config.resource_collector.config["asmr"]["asmr_level"]:
        bot.logger.info("asmr start")
        try:
            if mode=="random":
                r=await random_asmr_100(proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            elif mode=="latest":
                r=await choose_from_latest_asmr_100(proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            elif mode=="hotest":
                r = await choose_from_hotest_asmr_100(proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            i = random.choice(r['media_urls'])

            await bot.send(event, Card(audio=i[0], title=i[1], image=r['mainCoverUrl']))
            try:
                img=await download_img(r['mainCoverUrl'],f"data/pictures/cache/{random_str()}.png",config.resource_collector.config["asmr"]["gray_layer"],proxy=config.common_config.basic_config["proxy"]["http_proxy"])
            except Exception as e:
                bot.logger.error(f"download_img error:{e}")
                img=r['mainCoverUrl']
            forward_list = []
            if config.resource_collector.config["asmr"]["with_url"]:
                forward_list.append(Node(content=[Text(f"随机asmr\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}"), Image(file=img)]))
            else:
                await bot.send(event,[Text(f"随机asmr\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}"), Image(file=img)])
            file_paths=[]
            main_path = f"data/voice/cache/{r['title']}.{r['media_urls'][0][1].split('.')[-1]}"

            metype = r['media_urls'][0][1].split('.')[-1]

            for i in r['media_urls']:
                if i[1].split('.')[-1] != metype or len(file_paths) >= config.resource_collector.config["asmr"]["max_merge_file_num"]:
                    bot.logger.error(f"audio type change:{i[1]}")
                    break
                if config.resource_collector.config["asmr"]["with_file"]:
                    path=f"data/voice/cache/{i[1]}"
                    file=await download_file(i[0],path,config.common_config.basic_config["proxy"]["http_proxy"])
                    file_paths.append(file)
                text=f"音频名称: {i[1]}\n音频url: {i[0]}"
                forward_list.append(Node(content=[Text(text)]))
            if config.resource_collector.config["asmr"]["with_url"]:
                await bot.send(event, forward_list)
            if config.resource_collector.config["asmr"]["with_file"]:
                loop = asyncio.get_running_loop()
                try:
                    await bot.send(event, "正在合并音频文件，请等待完成...")
                    bot.logger.info(f"asmr file merge and upload start: path:{main_path},merge_files:{file_paths}")
                    with ThreadPoolExecutor() as executor:
                        path = await loop.run_in_executor(executor, merge_audio_files, file_paths, main_path)
                    await bot.send(event, File(file=path))
                except Exception as e:
                    bot.logger.error(f"asmr file merge and upload error:{e}")

        except Exception as e:
            bot.logger.error(f"asmr error:{e}")
            if not try_again:
                bot.logger.warning("asmr try again!")
                await call_asmr(bot,event,config,try_again=True)
            if try_again:
                await bot.send(event, "失败了！要不再试一次？")
    else:
        await bot.send(event, "你没有权限使用该功能")

async def check_latest_asmr(bot,event,config):
    bot.logger.info_func("开始监测 asmr.one 更新")
    try:
        r=await latest_asmr_100(proxy=config.common_config.basic_config["proxy"]["http_proxy"])
        if r["id"]!=config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["nightASMR"]["latest_asmr_id"]:
            bot.logger.info_func(f"最新asmr id:{r['id']} {r['title']} 开始推送")
            group_list = config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["nightASMR"]["groups"]
            for group_id in group_list:
                try:
                    i = random.choice(r['media_urls'])
                    await bot.send_group_message(group_id, Card(audio=i[0], title=i[1], image=r['mainCoverUrl']))
                    try:
                        img = await download_img(r['mainCoverUrl'], f"data/pictures/cache/{random_str()}.png", config.resource_collector.config["asmr"]["gray_layer"],
                                                 proxy=config.common_config.basic_config["proxy"]["http_proxy"])
                    except Exception as e:
                        bot.logger.error(f"download_img error:{e}")
                        img = r['mainCoverUrl']
                    forward_list = []
                    if config.resource_collector.config["asmr"]["with_url"]:
                        forward_list.append(Node(
                            content=[Text(f"asmr更新啦\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}"),
                                     Image(file=img)]))
                    else:
                        await bot.send_group_message(group_id,
                                       [Text(f"asmr更新啦\n标题: {r['title']}\nnsfw: {r['nsfw']}\n源: {r['source_url']}"),
                                        Image(file=img)])
                    file_paths = []
                    main_path = f"data/voice/cache/{r['title']}.{r['media_urls'][0][1].split('.')[-1]}"
                    for i in r['media_urls']:
                        if config.resource_collector.config["asmr"]["with_file"]:
                            path = f"data/voice/cache/{i[1]}"
                            file = await download_file(i[0], path, config.common_config.basic_config["proxy"]["http_proxy"])
                            file_paths.append(file)
                        text = f"音频名称: {i[1]}\n音频url: {i[0]}"
                        forward_list.append(Node(content=[Text(text)]))
                    if config.resource_collector.config["asmr"]["with_url"]:
                        await bot.send_group_message(group_id, forward_list)
                    if config.resource_collector.config["asmr"]["with_file"]:
                        loop = asyncio.get_running_loop()
                        try:
                            bot.logger.info(
                                f"asmr file merge and upload start: path:{main_path},merge_files:{file_paths}")
                            with ThreadPoolExecutor() as executor:
                                path = await loop.run_in_executor(executor, merge_audio_files, file_paths, main_path)
                            await bot.send_group_message(group_id, File(file=path))
                            await bot.send_group_message(group_id, "完整音频文件已上传", True)
                        except Exception as e:
                            bot.logger.error(f"asmr file merge and upload error:{e}")
                except Exception as e:
                    bot.logger.error(f"latest_asmr_push error:{e}")
            bot.logger.info_func(f"最新asmr id:{r['id']} {r['title']} 推送完成")
            config.scheduled_tasks.sheduled_tasks_push_groups_ordinary["nightASMR"]["latest_asmr_id"]=r["id"]
            config.save_yaml("sheduled_tasks_push_groups_ordinary",plugin_name="scheduled_tasks")
        else:
            bot.logger.info_func("asmr.one 无更新")
    except Exception as e:
        bot.logger.error(f"check_latest_asmr error:{e}")


# ──────────────────────────────────────────────────────────────────────────────
# JM 排行榜图文展示
# ──────────────────────────────────────────────────────────────────────────────

async def call_jm_ranking(bot, event, config, mode: str = "week"):
    """
    发送 JM 排行榜图文合并转发。

    mode:
        "week"  - 本周热门榜
        "today" - 今日热门榜

    流程：
      1. 拉取排行榜列表（有缓存，速度快）
      2. 在线程池中并发下载封面并做反 NSFW 处理
      3. 组装成 [Node, Node, ...] 发送，避免刷屏
    """
    jm_cfg = config.resource_collector.config["JMComic"]
    anti_nsfw = jm_cfg.get("anti_nsfw", "black_and_white")
    limit = jm_cfg.get("ranking_limit", 10)          # 榜单条数，默认 10
    cover_workers = jm_cfg.get("cover_workers", 5)   # 并发封面下载线程数

    # ── 1. 鉴权 ──────────────────────────────────────────────
    user_info = await get_user(event.user_id)
    if user_info.permission < jm_cfg.get("jm_comic_search_level", 0):
        await bot.send(event, "你没有权限使用该功能")
        return

    title_text = "📅 今日JM热门榜" if mode == "today" else "📆 本周JM热门榜"
    await bot.send(event, f"{title_text} 正在加载，请稍候...", True)

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
        await bot.send(event, "获取榜单失败，请稍后再试", True)
        return

    if not id_title_list:
        await bot.send(event, "暂时没有获取到榜单数据，请稍后再试", True)
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
        await bot.send(event, "封面下载失败，请稍后再试", True)
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
    print(cm_list)
    await bot.send(event, cm_list)


# ──────────────────────────────────────────────────────────────────────────────
# JM 验车 / 下载（原有逻辑，保持不变）
# ──────────────────────────────────────────────────────────────────────────────
async def jm_search(bot,event,config,search_topic):
    user_info = await get_user(event.user_id)
    if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_search_level"]:
        await bot.send(event, "你没有权限使用该功能")
        return {"status": "failed", "message": "你没有权限使用该功能"}
    async def _call_search():
        global operating

        bot.logger.info(f"JM搜索: {search_topic}")
        keyword = search_topic
        if keyword.startswith((':', '：', ' ')):
            keyword = keyword[1:]
        keyword = keyword.strip()

        if not keyword:
            await bot.send(event, "请输入搜索关键字")
            return

        await bot.send(event, f"正在搜索「{keyword}」，请稍候...", True)

        jm_cfg = config.resource_collector.config["JMComic"]
        anti_nsfw = jm_cfg.get("anti_nsfw", "obfuscate")
        limit = jm_cfg.get("ranking_limit", 10)
        cover_workers = jm_cfg.get("cover_workers", 5)

        loop = asyncio.get_running_loop()
        try:
            with ThreadPoolExecutor() as executor:
                results = await loop.run_in_executor(
                    executor,
                    JM_search_with_covers,
                    keyword,
                    limit,
                    anti_nsfw,
                    cover_workers,
                )
        except Exception as e:
            logger.error(f"jm搜索失败: {e}")
            await bot.send(event, "搜索失败，请稍后再试", True)
            return

        if not results:
            await bot.send(event, "好像没有找到你说的本子呢~~~")
            return

        cm_list = [
            Node(content=[Text(
                f"「{keyword}」的搜索结果，共 {len(results)} 部\n"
                f"发送「验车+车牌号」可查看预览，「jm下载+车牌号」可下载完整PDF"
            )])
        ]
        for rank, (aid, title, cover_path) in enumerate(results, start=1):
            info_text = f"第 {rank} 条\n车牌号：{aid}\n标题：{title}"
            if cover_path:
                cm_list.append(Node(content=[Text(info_text), Image(file=cover_path)]))
            else:
                cm_list.append(Node(content=[Text(f"{info_text}\n（封面加载失败）")]))

        try:
            await bot.send(event, cm_list)
        except Exception as e:
            logger.error(f"jm搜索结果发送失败: {e}")
            await bot.send(event, "结果发送失败", True)

    asyncio.create_task(_call_search())
    return {"status": "running", "message": "任务已在后台启动，请耐心等待结果"}
async def jm_download(bot,event,config,comic_id):
    user_info = await get_user(event.user_id)
    if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_download_level"]:
        await bot.send(event, "你没有权限使用该功能")
        return {"status": "failed", "message": "你没有权限使用该功能"}

    async def _call_download():
        global operating
        if comic_id in config.resource_collector.config["JMComic"]["jm_ban"]:
            answers = config.resource_collector.config["JMComic"]["ban_answer"]
            await bot.send(event, answers[random.randint(0, len(answers) - 1)], True)
            return


        if hasattr(event, "group_id"):
            temp_id = event.group_id
        else:
            temp_id = event.user_id
        if comic_id in operating:
            if temp_id not in operating[comic_id]:
                operating[comic_id].append(temp_id)
                await bot.send(event, "相关文件占用中，请等待...", True)
            else:
                await bot.send(event, "本群已有相关文件占用，请稍等", True)
            return
        operating[comic_id] = [temp_id]
        try:
            msg = await bot.send(event, "已启用线程,请等待下载完成", True)
            await delay_recall(bot, msg)
            #新增一个判断，当下载的本子有多个时直接拒绝
            if await check_jm_multiple(comic_id):
                msg = await bot.send(event, "检测到该jm包含多个本子，拒绝下载喵", True)
                #await delay_recall(bot, msg)
                return

            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor() as executor:
                r = await loop.run_in_executor(
                    executor, downloadALLAndToPdf, comic_id,
                    config.resource_collector.config["JMComic"]["savePath"],
                )
            bot.logger.info(
                f"下载完成，车牌号：{comic_id} \n保存路径：{config.resource_collector.config['JMComic']['savePath']} {comic_id} "
            )
        except Exception as e:
            bot.logger.error(e)
            await bot.send(event, "下载失败", True)
        try:
            if config.resource_collector.config['JMComic']["autoEncrypt"]:
                encryptor = AsyncPDFEncryptor()
                try:
                    await encryptor.encrypt_pdf_file(
                        f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}.pdf",
                        f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}_encrypted.pdf",
                        f"{comic_id}",
                    )
                    pdf_path = f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}_encrypted.pdf"
                except Exception as e:
                    bot.logger.error(f"encrypt_pdf_file error:{e}")
                    traceback.print_exc()
                    pdf_path = f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}.pdf"
            else:
                pdf_path = f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}.pdf"

            msg_pdf = f"加密成功喵，密码：{comic_id}"
            # 这里压缩PDF，以免过大
            if config.resource_collector.config["JMComic"]["pdg_compress"] is True:
                # 首先检查该库有无正确安装
                Ghostscript_installed_check = False
                cmds = ['gs', 'gswin64c', 'gswin32c']  # 常见Ghostscript命令
                for cmd in cmds:
                    try:
                        result = subprocess.run([cmd, '--version'], capture_output=True, text=True)
                        if result.returncode == 0:
                            bot.logger.info(f"Ghostscript 已安装，版本号: {result.stdout.strip()}，命令: {cmd}")
                            Ghostscript_installed_check = True
                    except FileNotFoundError:
                        pass
                if Ghostscript_installed_check:
                    bot.logger.info('开始压缩下载的pdf文件')
                    pdf_path_cache = f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}_cache.pdf"
                    dpi = 72
                    cmd = [
                        'gs',
                        '-sDEVICE=pdfwrite',
                        '-dCompatibilityLevel=1.4',
                        '-dPDFSETTINGS=/screen',
                        '-dNOPAUSE',
                        '-dQUIET',
                        '-dBATCH',
                        '-dDownsampleColorImages=true',
                        f'-dColorImageResolution={dpi}',
                        '-dDownsampleGrayImages=true',
                        f'-dGrayImageResolution={dpi}',
                        '-dDownsampleMonoImages=true',
                        f'-dMonoImageResolution={dpi}',
                        f'-sOutputFile={pdf_path_cache}',
                        pdf_path
                    ]
                    subprocess.run(cmd, check=True)
                    pdf_path = pdf_path_cache
                else:
                    bot.logger.error("Ghostscript 未安装或命令未添加到环境变量。")
            # #重命名文件
            if config.resource_collector.config["JMComic"]["is_rename"] is True:
                bot.logger.info('开始重命名本子')
                jm_name = await get_jm_name(comic_id)
                pdf_path_rename = f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}_{jm_name}.pdf"
                shutil.copy(pdf_path, pdf_path_rename)
                pdf_path = pdf_path_rename

            # 新增Openlist上传方式
            for group_id in operating[comic_id]:
                event.group_id = group_id
                if config.resource_collector.config["JMComic"]["openlist"]["enable"] is True:
                    bot.logger.info('使用Openlist上传喵')
                    OpenList = OpenListClient(
                        config.resource_collector.config["JMComic"]["openlist"]["base_url"],
                        config.resource_collector.config["JMComic"]["openlist"]["username"],
                        config.resource_collector.config["JMComic"]["openlist"]["password"])
                    info = await OpenList.login()
                    bot.logger.info('Openlist登录成功，开始上传')
                    if info['status'] is False:
                        await bot.send(event, info['msg'])
                        return
                    info = await OpenList.upload_file(pdf_path,
                                                      config.resource_collector.config["JMComic"]["openlist"][
                                                          "upload_dir"])
                    if info['status'] is False:
                        await bot.send(event, info['msg'])
                        return
                    base_url = config.resource_collector.config["JMComic"]["openlist"]["base_url"] + \
                               config.resource_collector.config["JMComic"]["openlist"]["upload_dir"]
                    msg_pdf = f"请前往此网址查看：\n{base_url}"
                    await bot.send(event, msg_pdf)
                    await OpenList.logout()
                else:
                    msg = await bot.send(event, "下载完成了( >ρ< )。请等待上传完成。")
                    if not os.path.exists('/mnt/video_disk/temp/JM'):
                        await bot.send(event, File(file=pdf_path))
                    if config.resource_collector.config["JMComic"]["autoEncrypt"]:
                        await bot.send(event, msg_pdf)
                    await delay_recall(bot, msg)
            bot.logger.info("移除预览缓存")
            operating.pop(comic_id)
            if config.resource_collector.config['JMComic']["autoClearPDF"]:
                await wait_and_delete_file(
                    bot,
                    file_path=f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}.pdf",
                )
                if config.resource_collector.config['JMComic']["autoEncrypt"]:
                    await wait_and_delete_file(
                        bot,
                        file_path=f"{config.resource_collector.config['JMComic']['savePath']}/{comic_id}_encrypted.pdf",
                    )
        except Exception as e:
            bot.logger.error(e)
        finally:
            if comic_id in operating:
                operating.pop(comic_id)


    asyncio.create_task(_call_download())
    return {"status": "running", "message": "任务已在后台启动，请耐心等待结果"}
async def jm_preview(bot, event, config, comic_id=607279,mode_check='preview'):
    async def _call_jm():
        global operating
        if comic_id in config.resource_collector.config["JMComic"]["jm_ban"]:
            answers = config.resource_collector.config["JMComic"]["ban_answer"]
            await bot.send(event, answers[random.randint(0, len(answers) - 1)], True)
            return
        if hasattr(event, "group_id"):
            temp_id = event.group_id
        else:
            temp_id = event.user_id
        if comic_id in operating:
            if event.group_id not in operating[comic_id]:
                operating[comic_id].append(event.group_id)
                await bot.send(event, "相关文件占用中，请等待...", True)
            else:
                await bot.send(event, "已有相关文件占用，请稍等", True)
            return
        event.group_id = temp_id
        operating[comic_id] = [event.group_id]
        bot.logger.info(f"JM验车 {comic_id}")
        if mode_check in ['preview']:
            msg = await bot.send(event, "下载中...稍等喵", True)
            await delay_recall(bot, msg)
        if config.resource_collector.config["JMComic"]["openlist"]["enable"] is True:
            anti_nsfw = 'no_censor'
        else:
            # 主bot接入公开平台需对图片脱敏；副bot(webui/live2d 等内部通道)无需，直接返回原图。
            anti_nsfw = config.resource_collector.config["JMComic"]["anti_nsfw"]
            if getattr(event, "from_secondary", False):
                anti_nsfw = "no_censor"
                bot.logger.info("JM预览：来源为副bot，跳过图片混淆，返回原图")
        try:
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor() as executor:
                png_files = await loop.run_in_executor(
                    executor, downloadComic, comic_id, 1,
                    config.resource_collector.config["JMComic"]["previewPages"],
                    anti_nsfw,
                    config.resource_collector.config["JMComic"]["gif_compress"],
                )
        except Exception as e:
            bot.logger.error(e)
            await bot.send(event, "下载失败", True)
            operating.pop(comic_id)
            return
        if config.resource_collector.config["JMComic"]["openlist"]["enable"] is True:
            bot.logger.info('使用Openlist上传喵')
            OpenList = OpenListClient(
                config.resource_collector.config["JMComic"]["openlist"]["base_url"],
                config.resource_collector.config["JMComic"]["openlist"]["username"],
                config.resource_collector.config["JMComic"]["openlist"]["password"])
            info = await OpenList.login()
            bot.logger.info('Openlist登录成功，开始上传')
            if info['status'] is False:
                await bot.send(event, info['msg'])
                return
            # msg = await bot.send(event, "下载完成了，请等待上传完成喵。")
            folder_path = config.resource_collector.config["JMComic"]["openlist"]["upload_dir"] + f'/cache/{comic_id}'
            for img_path in png_files:
                info = await OpenList.upload_file(img_path, folder_path)
                if info['status'] is False:
                    await bot.send(event, info['msg'])
                    return
            base_url = config.resource_collector.config["JMComic"]["openlist"]["base_url"] + folder_path
            msg_pdf = f"请前往此网址查看：\n{base_url}"
            await bot.send(event, msg_pdf)
            # await delay_recall(bot, msg)
            await OpenList.logout()
        else:
            cmList = []
            bot.logger.info(png_files)
            cmList.append(Node(content=[Text(
                f"车牌号：{comic_id} \nbot仅提供本子部分页面预览。\n图片已经过处理，但不保证百分百不被吞。预览是黑色是正常的，点进去查看"
            )]))
            shutil.rmtree(f"data/pictures/benzi/temp{comic_id}")

            for path in png_files:
                cmList.append(Node(content=[Image(file=path)]))
            for group_id in operating[comic_id]:
                event.group_id = group_id
                await bot.send(event, cmList)
        operating.pop(comic_id)


    user_info = await get_user(event.user_id)
    if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_search_level"]:
        await bot.send(event, "你没有权限使用该功能")
        return {"status": "failed", "message": "你没有权限使用该功能"}
    asyncio.create_task(_call_jm())
    return {"status": "running", "message": "任务已在后台启动，请耐心等待结果"}


def main(bot, config):

    logger = bot.logger

    asmr_task_activated = False

    @bot.on(GroupMessageEvent)
    async def book_resource_search(event):
        if str(event.pure_text).startswith("搜书"):
            book_name = str(event.pure_text).split("搜书")[1]
            await search_book_info(bot, event, config, book_name)

    @bot.on(GroupMessageEvent)
    async def book_resource_download(event):
        if str(event.pure_text).startswith("下载书"):
            try:
                book_id = str(event.pure_text).split("下载书")[1].split(" ")[0]
                hash = str(event.pure_text).split("下载书")[1].split(" ")[1]
                await call_download_book(bot, event, config, book_id, hash)
            except Exception as e:
                bot.logger.error(f"book_resource_download error:{e}")
                await bot.send(event, "指令格式错误，请使用'下载书{book_id} {hash}'")
        elif event.pure_text == "随机奥术" or event.pure_text == "随机asmr" or event.pure_text == "随机奥数":
            await call_asmr(bot, event, config)
        elif event.pure_text == "最新asmr" or event.pure_text == "最新奥术" or event.pure_text == "最新奥数":
            await call_asmr(bot, event, config, mode="latest")
        elif event.pure_text == "最热asmr" or event.pure_text == "最热奥术" or event.pure_text == "热门asmr":
            await call_asmr(bot, event, config, mode="hotest")

    @bot.on(LifecycleMetaEvent)
    async def _(event):
        nonlocal asmr_task_activated
        if not asmr_task_activated:
            asmr_task_activated = True
            asyncio.create_task(asmr_monitor_loop(bot, event, config))

    async def asmr_monitor_loop(bot, event, config):
        """ASMR监控循环"""
        while True:
            try:
                await check_latest_asmr(bot, event, config)
            except Exception as e:
                bot.logger.error(e)
            await asyncio.sleep(700)

    """
    以下为jm的功能实现
    """

    @bot.on(GroupMessageEvent)
    async def querycomic(event: GroupMessageEvent):
        if event.pure_text.startswith("jm搜") or event.pure_text.startswith("JM搜"):
            user_info = await get_user(event.user_id)
            if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_search_level"]:
                await bot.send(event, "你没有权限使用该功能")
                return

            index = event.pure_text.find("搜")
            if index == -1:
                await bot.send(event, "指令格式错误，请使用'jm搜{关键字}'")
                return
            keyword = event.pure_text[index + 1:]
            if keyword.startswith((':', '：', ' ')):
                keyword = keyword[1:]
            keyword = keyword.strip()

            if not keyword:
                await bot.send(event, "请输入搜索关键字")
                return

            await bot.send(event, f"正在搜索「{keyword}」，请稍候...", True)

            jm_cfg = config.resource_collector.config["JMComic"]
            anti_nsfw = jm_cfg.get("anti_nsfw", "obfuscate")
            limit = jm_cfg.get("ranking_limit", 10)
            cover_workers = jm_cfg.get("cover_workers", 5)

            loop = asyncio.get_running_loop()
            try:
                with ThreadPoolExecutor() as executor:
                    results = await loop.run_in_executor(
                        executor,
                        JM_search_with_covers,
                        keyword,
                        limit,
                        anti_nsfw,
                        cover_workers,
                    )
            except Exception as e:
                logger.error(f"jm搜索失败: {e}")
                await bot.send(event, "搜索失败，请稍后再试", True)
                return

            if not results:
                await bot.send(event, "好像没有找到你说的本子呢~~~")
                return

            cm_list = [
                Node(content=[Text(
                    f"「{keyword}」的搜索结果，共 {len(results)} 部\n"
                    f"发送「验车+车牌号」可查看预览，「jm下载+车牌号」可下载完整PDF"
                )])
            ]
            for rank, (aid, title, cover_path) in enumerate(results, start=1):
                info_text = f"第 {rank} 条\n车牌号：{aid}\n标题：{title}"
                if cover_path:
                    cm_list.append(Node(content=[Text(info_text), Image(file=cover_path)]))
                else:
                    cm_list.append(Node(content=[Text(f"{info_text}\n（封面加载失败）")]))

            try:
                await bot.send(event, cm_list)
            except Exception as e:
                logger.error(f"jm搜索结果发送失败: {e}")
                await bot.send(event, "结果发送失败", True)

    @bot.on(GroupMessageEvent)
    async def ranking_comic(event: GroupMessageEvent):
        """今日jm / 本周jm：图文并茂的排行榜合并转发"""
        text = event.pure_text
        if text in ('今日jm', '今日JM'):
            asyncio.create_task(call_jm_ranking(bot, event, config, mode="today"))
        elif text in ('本周jm', '本周JM'):
            asyncio.create_task(call_jm_ranking(bot, event, config, mode="week"))

    @bot.on(GroupMessageEvent)
    async def download(event: GroupMessageEvent):
        if event.pure_text.startswith("验车") or event.pure_text.lower().startswith("jm验车") or event.pure_text == "随机本子":
            user_info = await get_user(event.user_id)
            if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_random_level"]:
                await bot.send(event, "你没有权限使用该功能")
                return
            mode_check = 'preview'
            try:
                if event.pure_text.startswith("验车"):
                    comic_id = int(event.pure_text.replace("验车", ""))
                elif event.pure_text.lower().startswith("jm验车"):
                    comic_id = int(event.pure_text.lower().replace("jm验车", ""))
                else:
                    context = ['正在随机ing，请稍等喵~~', '正在翻找好看的本子喵~', '嘿嘿，JM，启动！！！！', '正在翻找JM.jpg',
                               '有色色！我来了', 'hero来了喵~~', '了解~', '全力色色ing~']
                    await bot.send(event, random.choice(context))
                    context = JM_search_month()
                    comic_id = context[random.randint(1, len(context)) - 1]
                    mode_check = 'random'
            except Exception as e:
                logger.error(e)
                await bot.send(event, "无效输入 int，指令格式如下\n验车【车牌号】\n如：验车604142", True)
                return
            await jm_preview(bot,event,config,comic_id,mode_check)
            #await jm_search(bot, event, config, comic_id)
            #await call_jm(bot, event, config, mode="preview", comic_id=comic_id)

    @bot.on(GroupMessageEvent)
    async def downloadAndToPdf(event: GroupMessageEvent):
        if event.pure_text.lower().startswith("jm下载"):
            user_info = await get_user(event.user_id)
            if user_info.permission < config.resource_collector.config["jmcomic"]["jm_comic_download_level"]:
                await bot.send(event, "你没有权限使用该功能")
                return
            try:
                comic_id = int(event.pure_text.lower().replace("jm下载", ""))
                logger.info(f"JM下载启动 aim: {comic_id}")
            except:
                await bot.send(event, "非法参数，指令示例 JM下载601279")
                return
            await jm_download(bot, event, config, comic_id)
            #await call_jm(bot, event, config, mode="download", comic_id=comic_id)


async def wait_and_delete_file(bot, file_path, interval=60):
    await asyncio.sleep(1800)  # 30min后自动删除
    for _ in range(10):
        try:
            shutil.os.remove(file_path)
            bot.logger.info(f"文件 {file_path} 已成功删除")
            return
        except PermissionError:
            bot.logger.warning(f"文件 {file_path} 被占用，等待重试...")
            await asyncio.sleep(interval)
        except FileNotFoundError:
            bot.logger.warning(f"文件 {file_path} 已不存在")
            return
        except Exception as e:
            bot.logger.error(f"删除文件时出现错误: {e}")
            return