import re
import asyncio
import aiohttp
import subprocess
import zipfile
from pathlib import Path

from developTools.utils.logger import get_logger

from framework_common.framework_util.yamlLoader import YAMLManager


# ==================================
# 核心配置区域
# ==================================
# 1. 填入你在 @BotFather 申请的 Token
logger=get_logger(__name__)

config=YAMLManager.get_instance()
# 2. 如果服务器在国内，请务必填写代理地址；如果在海外，请填 None
PROXY =config.common_config.basic_config["proxy"]["http_proxy"] if config.common_config.basic_config["proxy"].get("http_proxy") else None
TG_BOT_TOKEN=config.common_cofig.basic_config["telegram"]["bot_token"]

CACHE_DIR = Path("data/pictures/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def tg_api_request(session: aiohttp.ClientSession, method: str, params: dict = None):
    """请求 TG 官方 Bot API"""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}"
    try:
        async with session.get(url, params=params, proxy=PROXY,ssl=False,timeout=60) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except Exception as e:
        print(f"TG API 请求异常: {e}")
        return None


def convert_image_sync(input_file: Path, output_file: Path, is_video: bool):
    """使用标准 subprocess.run 同步执行 ffmpeg，捕获真实报错"""
    if is_video:
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(input_file),
            "-vf", "fps=15,scale=512:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            str(output_file)
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(input_file),
            str(output_file)
        ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg执行失败，错误码 {result.returncode}: {result.stderr.strip()}")


def create_zip_sync(file_paths: list, zip_out_path: Path):
    """将下载好的贴纸打包为ZIP压缩包"""
    with zipfile.ZipFile(zip_out_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in file_paths:
            # 仅使用文件名作为压缩包内的路径，去掉前面长长的绝对路径
            arcname = Path(file_path).name
            zipf.write(file_path, arcname)


async def download_and_convert_task(session: aiohttp.ClientSession, sticker: dict, index: int,sem: asyncio.Semaphore) -> str:
    """并发下载与转换的单个任务"""
    async with sem:
        file_id = sticker.get("file_id")
        file_unique_id = sticker.get("file_unique_id", f"idx_{index}")

        is_animated = sticker.get("is_animated", False)
        is_video = sticker.get("is_video", False)

        if is_animated:
            logger.warning(f"贴纸 {file_unique_id} 是 TGS(Lottie) 格式，暂时跳过。")
            return None

        # 1. 向官方换取真实下载路径
        file_info = await tg_api_request(session, "getFile", {"file_id": file_id})
        if not file_info or not file_info.get("ok"):
            return None

        file_path = file_info["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}"

        temp_ext = ".webm" if is_video else ".webp"
        out_ext = ".gif" if is_video else ".png"

        temp_path = CACHE_DIR / f"temp_{file_unique_id}{temp_ext}"
        out_path = CACHE_DIR / f"sticker_{file_unique_id}{out_ext}"

        # 2. 异步下载文件
        try:
            async with session.get(download_url, proxy=PROXY,ssl=False,timeout=60) as resp:
                if resp.status == 200:
                    with open(temp_path, 'wb') as f:
                        f.write(await resp.read())
                else:
                    return None
        except Exception as e:
            logger.error(f"贴纸下载失败: {e}")
            return None

        # 3. 放入线程池进行转换
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, convert_image_sync, temp_path, out_path, is_video)
        except Exception as e:
            logger.error(f"贴纸转换失败 {file_unique_id}: {repr(e)}")
            out_path = None
        finally:
            if temp_path.exists():
                temp_path.unlink()

        if out_path and out_path.exists():
            return str(out_path.absolute())
        return None
