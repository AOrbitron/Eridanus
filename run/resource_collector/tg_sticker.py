import re
import asyncio
import aiohttp
import subprocess
import zipfile
from pathlib import Path

# 引入你框架的相关组件
from developTools.event.events import GroupMessageEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from developTools.message.message_components import Image, Node, Text, File, Card
from run.resource_collector.service.telegram_operator import tg_api_request, download_and_convert_task, create_zip_sync

# ==================================
# 核心配置区域
# ==================================
# 1. 填入你在 @BotFather 申请的 Token


config=YAMLManager.get_instance()
# 2. 如果服务器在国内，请务必填写代理地址；如果在海外，请填 None
PROXY =config.common_config.basic_config["proxy"]["http_proxy"] if config.common_config.basic_config["proxy"].get("http_proxy") else None
TG_BOT_TOKEN=config.common_config.basic_config["telegram"]["bot_token"]

CACHE_DIR = Path("data/pictures/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def main(bot: ExtendBot, config: YAMLManager):
    @bot.on(GroupMessageEvent)
    async def handle_group_message(event: GroupMessageEvent):
        text = event.pure_text.strip()

        if text.startswith("下载tg贴纸"):
            if TG_BOT_TOKEN == "在此处填入你的_TG_BOT_TOKEN":
                await bot.send(event, "⚠️ 开发者尚未配置 Telegram Bot Token。")
                return

            match = re.search(r"addstickers/([^/]+)", text)
            if not match:
                await bot.send(event,
                               "参数错误！请发送完整的链接，例如：下载tg贴纸 https://t.me/addstickers/moe_sticker_bot")
                return

            pack_name = match.group(1)
            await bot.send(event, f"🕒 正在向 Telegram 官方请求贴纸包 `{pack_name}` 的数据，请稍候...")

            # 1. 获取包数据
            async with aiohttp.ClientSession() as session:
                pack_data = await tg_api_request(session, "getStickerSet", {"name": pack_name})

                if not pack_data or not pack_data.get("ok"):
                    await bot.send(event, "❌ 获取贴纸数据失败，包名不存在或网络不通（国内机器请检查代理）。")
                    return

                stickers = pack_data["result"].get("stickers", [])
                title = pack_data["result"].get("title", pack_name)

                if not stickers:
                    await bot.send(event, f"「{title}」贴纸包为空！")
                    return

                await bot.send(event, f"✅ 读取到「{title}」，共 {len(stickers)} 张，开始下载转换...")

                # 2. 并发下载与转换 (限制5个并发)
                sem = asyncio.Semaphore(5)
                tasks = [
                    download_and_convert_task( session, st, idx, sem)
                    for idx, st in enumerate(stickers)
                ]
                results = await asyncio.gather(*tasks)

            valid_paths = [path for path in results if path is not None]

            if not valid_paths:
                await bot.send(event, "⚠️ 全部贴纸下载或转换失败！")
                return

            bot.logger.info(f"成功转换完成贴纸: {valid_paths}")
            await bot.send(event, f"🎉 处理完成，成功转换 {len(valid_paths)} 张，正在生成压缩包和折叠消息...")

            # =========================================
            # 3. 构造合并转发消息 (折叠聊天记录)
            # =========================================
            '''cmList = []
            for path in valid_paths:
                cmList.append(Node(content=[Image(file=path)]))

            try:
                # 提示：如果贴纸多于 100 张，部分平台可能会限制单条合并转发的节点数，一般情况可以直接发
                await bot.send(event, cmList)
            except Exception as e:
                bot.logger.error(f"发送折叠消息失败: {e}")
                await bot.send(event, "发送折叠消息失败，可能是单次转发图片数量过多被风控。")'''

            # =========================================
            # 4. 生成 ZIP 压缩包并作为文件发送
            # =========================================
            zip_path = CACHE_DIR / f"{pack_name}.zip"
            try:
                loop = asyncio.get_running_loop()
                # 放入线程池执行压缩，防止阻塞主线程
                await loop.run_in_executor(None, create_zip_sync, valid_paths, zip_path)

                if zip_path.exists():
                    await bot.send(event, File(file=str(zip_path.absolute())))
            except Exception as e:
                bot.logger.error(f"打包发送压缩文件失败: {e}")
                await bot.send(event, "打包发送压缩文件失败，请检查运行日志。")