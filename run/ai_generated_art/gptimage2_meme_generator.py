# -*- coding: utf-8 -*-
import traceback
import aiofiles
import httpx
import os
import asyncio
import numpy as np
import uuid
import io

from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Image, Text, Mface
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.install_and_import import install_and_import
from framework_common.utils.utils import get_img

cv2 = install_and_import("opencv-python", "cv2")


async def download_img_from_url(url: str) -> str:
    cache_dir = "data/pictures/cache"
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{uuid.uuid4().hex[:8]}.png")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url)
        async with aiofiles.open(path, "wb") as f:
            await f.write(r.content)
    return path


# --- 核心 3x3 稳健网格切分逻辑 ---
def split_grid_3x3(image_bytes: bytes, output_folder: str) -> list:
    """
    最稳健的 3x3 网格切分逻辑：基于统计投影的区域划分与贴纸轮廓精修
    完美保留每个表情贴纸的白色粗描边边框与特效元素
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    h, w = img.shape[:2]
    # 背景为白色 (>252 为背景 0，彩色角色和线条为 255)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 252, 255, cv2.THRESH_BINARY_INV)

    row_sum = np.sum(binary, axis=1)

    def get_split_points(projection, count=3):
        points = [0]
        step = len(projection) // count
        for i in range(1, count):
            search_start = max(0, i * step - step // 2)
            search_end = min(len(projection), i * step + step // 2)
            valley = search_start + int(np.argmin(projection[search_start:search_end]))
            points.append(valley)
        points.append(len(projection))
        return points

    row_points = get_split_points(row_sum, 3)

    saved_paths = []
    batch_id = uuid.uuid4().hex[:6]
    idx = 1
    os.makedirs(output_folder, exist_ok=True)

    for i in range(3):
        r_s, r_e = row_points[i], row_points[i + 1]
        row_img = img[r_s:r_e, :]
        row_bin = binary[r_s:r_e, :]

        col_sum = np.sum(row_bin, axis=0)
        col_points = get_split_points(col_sum, 3)

        for j in range(3):
            c_s, c_e = col_points[j], col_points[j + 1]

            sub_bin = row_bin[:, c_s:c_e]
            coords = cv2.findNonZero(sub_bin)

            pad = 10
            if coords is not None:
                x, y, sw, sh = cv2.boundingRect(coords)
                y1 = max(r_s, r_s + y - pad)
                y2 = min(r_e, r_s + y + sh + pad)
                x1 = max(c_s, c_s + x - pad)
                x2 = min(c_e, c_s + x + sw + pad)
                roi = img[y1:y2, x1:x2]
            else:
                roi = row_img[:, c_s:c_e]

            path = os.path.join(output_folder, f"sticker_{batch_id}_{idx}.png")
            is_success, buffer = cv2.imencode(".png", roi)
            if is_success:
                with open(path, "wb") as f_out:
                    f_out.write(buffer)
                saved_paths.append(path)
            idx += 1

    return saved_paths


# 别名兼容
split_stickers = split_grid_3x3


# --- 插件主类 ---
def main(bot: ExtendBot, config: YAMLManager):
    # 存储格式: {user_id: {"image": [path1], "text": [prompt1]}}
    sticker_user_dict = {}

    CACHE_DIR = "data/pictures/cache"
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    @bot.on(GroupMessageEvent)
    async def handle_sticker_maker(event: GroupMessageEvent):
        nonlocal sticker_user_dict
        uid = event.user_id

        # 1. 进入制作模式
        if event.pure_text in ["/制作表情包", "/表情包制作"]:
            sticker_user_dict[uid] = {"image": [], "text": []}
            await bot.send(
                event,
                "🎨 已进入表情包制作模式\n"
                "请发送：\n"
                "1. 参考角色图片（1张）\n"
                "2. 描述文字（可选，如：生气的、可爱的）\n"
                "全部发送后，发送 /end 开始制作"
            )
            return

        # 2. 提交并处理
        elif event.pure_text == "/end" and uid in sticker_user_dict:
            data_store = sticker_user_dict[uid]

            if not data_store["image"]:
                await bot.send(event, "❌ 你还没有发送参考图片呢。")
                return

            await bot.send(event, "🚀 正在为您生成 3x3（共9张）萌系表情包矩阵并切分，请稍候...")

            # 配置获取
            api_config = config.ai_generated_art.config.get("gptimage2", {})
            base_url = api_config.get("base_url", "http://api.apollodorus.xyz/v1")
            apikey = api_config.get("apikey", "")
            model = api_config.get("model", "gpt-image-2.5-flare")
            resolution = api_config.get("sticker_resolution") or api_config.get("resolution") or "2K"
            style_ref_path = api_config.get("sticker_style_ref") or "data/system/sticker_style_ref.png"
            max_retry = api_config.get("max_retry", 5)

            # 兼容不同相对路径解析风格参考图
            if style_ref_path and not os.path.exists(style_ref_path):
                candidates = [
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), style_ref_path),
                    os.path.join(os.path.dirname(__file__), "assets", "sticker_style_ref.png"),
                    os.path.join("data", "system", os.path.basename(style_ref_path)),
                ]
                for c in candidates:
                    if os.path.exists(c):
                        style_ref_path = c
                        break

            # 构造 Prompt（完全对齐 test_result_1.png 核心提示词与画风）
            user_prompt = " ".join(data_store["text"]).strip() if data_store["text"] else ""
            user_extra = f"\n附加需求与偏好：{user_prompt}" if user_prompt else ""

            # 准备图片
            img_path = data_store["image"][0]
            try:
                async with aiofiles.open(img_path, "rb") as f:
                    char_content = await f.read()

                files = [("images", (os.path.basename(img_path), io.BytesIO(char_content), "image/png"))]
                has_style_ref = False

                if style_ref_path and os.path.exists(style_ref_path):
                    async with aiofiles.open(style_ref_path, "rb") as f_ref:
                        style_content = await f_ref.read()
                    files.append(("images", (os.path.basename(style_ref_path), io.BytesIO(style_content), "image/png")))
                    has_style_ref = True

                if has_style_ref:
                    final_prompt = (
                        "角色严格参考图1中的人物外貌特征（发型发色、眼睛、服装等要素）。\n"
                        "艺术风格完全参考图2：\n"
                        "1. 风格特点：极简萌系Q版（Chibi / SD）、可爱二头身动漫贴纸表情包、大头小身体。\n"
                        "2. 边框质感：每个表情角色周围均带有白色粗贴纸轮廓（die-cut white sticker border），纯白色背景。\n"
                        "3. 线条色彩：柔和清晰的描线，简约平涂赛璐璐色块，清新柔和的色调，可爱腮红。\n"
                        "4. 排版构图：生成 3x3 矩阵排列的 9 个不同动作与神态的表情包贴纸，排列整齐，贴纸之间必须有清晰的白色空白间隔（wide white gaps）。\n"
                        "5. 包含丰富的日常表情（如无语发呆带省略号气泡、开心大笑、生气气鼓鼓、委屈大哭、打瞌睡、傲娇斜眼、比心可爱、疑惑问号、震惊目瞪口呆等）。"
                        f"{user_extra}"
                    )
                else:
                    final_prompt = (
                        "将参考图中的角色绘制为 3x3 矩阵排列的 9 张日系萌系Q版表情包贴纸：\n"
                        "1. 风格特点：极简萌系二头身Q版（Chibi / SD）、可爱二头身动漫贴纸表情包、大头小身体。\n"
                        "2. 边框质感：每个表情角色周围均带有白色粗贴纸轮廓（die-cut white sticker border），纯白色背景。\n"
                        "3. 线条色彩：柔和清晰的描线，简约平涂赛璐璐色块，清新柔和的色调，可爱腮红。\n"
                        "4. 排版构图：生成 3x3 矩阵排列的 9 个不同动作与神态的表情包贴纸，排列整齐，贴纸之间必须有清晰的白色空白间隔（wide white gaps）。\n"
                        "5. 包含丰富的日常表情（如无语发呆带省略号气泡、开心大笑、生气气鼓鼓、委屈大哭、打瞌睡、傲娇斜眼、比心可爱、疑惑问号、震惊目瞪口呆等）。\n"
                        f"{user_extra}"
                    )

                headers = {"Authorization": f"Bearer {apikey}"}
                data = {
                    "prompt": final_prompt,
                    "aspect_ratio": "1:1",
                    "model": model,
                    "resolution": resolution
                }

                # 提交后清理当前用户状态
                saved_images = list(sticker_user_dict[uid]["image"])
                sticker_user_dict.pop(uid, None)

                async def request_api(current_retry=0):
                    try:
                        retry_files = []
                        retry_files.append(("images", (os.path.basename(img_path), io.BytesIO(char_content), "image/png")))
                        if has_style_ref:
                            retry_files.append(("images", (os.path.basename(style_ref_path), io.BytesIO(style_content), "image/png")))

                        async with httpx.AsyncClient() as client:
                            resp = await client.post(
                                f"{base_url}/images/edits",
                                headers=headers,
                                files=retry_files,
                                data=data,
                                timeout=None
                            )
                            if resp.status_code != 200:
                                raise Exception(f"API HTTP {resp.status_code}: {resp.text}")
                            return resp
                    except Exception as e:
                        bot.logger.error(f"表情包绘图出现错误: {e}")
                        if current_retry < max_retry:
                            await asyncio.sleep(2)
                            return await request_api(current_retry + 1)
                        else:
                            raise e

                resp = await request_api(0)
                if resp.status_code != 200:
                    await bot.send(event, f"❌ 生成失败: {resp.text}")
                    return

                # 下载生成的网格大图
                res_json = resp.json()
                grid_img_url = res_json["data"][0]["url"]

                async with httpx.AsyncClient() as client:
                    img_resp = await client.get(grid_img_url, timeout=None)
                    grid_img_bytes = img_resp.content

                # 在线程池中执行 OpenCV 切分，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                sticker_paths = await loop.run_in_executor(
                    None, split_grid_3x3, grid_img_bytes, CACHE_DIR
                )

                if not sticker_paths:
                    await bot.send(event, "❌ 切分失败，未能识别到表情区域。")
                else:
                    msg_list = [Text(f"✅ 成功制作 {len(sticker_paths)} 张表情包：")]
                    for p in sticker_paths:
                        msg_list.append(Image(file=f"file:///{os.path.abspath(p)}"))
                    await bot.send(event, msg_list)

            except Exception as e:
                bot.logger.error(traceback.format_exc())
                await bot.send(event, f"❌ 发生错误: {str(e)}")
            finally:
                if uid in sticker_user_dict:
                    for p in sticker_user_dict[uid]["image"]:
                        if os.path.exists(p):
                            try: os.remove(p)
                            except: pass
                    sticker_user_dict.pop(uid, None)
                if "saved_images" in locals():
                    for p in saved_images:
                        if os.path.exists(p):
                            try: os.remove(p)
                            except: pass
            return

        # 3. 收集模式
        elif uid in sticker_user_dict:
            found = False
            for mes in event.message_chain:
                if isinstance(mes, Text):
                    t = mes.text.strip()
                    if t:
                        sticker_user_dict[uid]["text"].append(t)
                        found = True

                elif isinstance(mes, Image) or isinstance(mes, Mface):
                    url = mes.url if hasattr(mes, "url") and mes.url else mes.file
                    if url:
                        path = await download_img_from_url(url)
                        sticker_user_dict[uid]["image"].append(path)
                        found = True
                elif get_img(event, bot):
                    path = await download_img_from_url(get_img(event, bot))
                    sticker_user_dict[uid]["image"].append(path)
                    found = True

            if found:
                await bot.send(event, "已添加", True)
