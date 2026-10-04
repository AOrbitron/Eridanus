import traceback
import aiofiles
import httpx
import os
import asyncio

import numpy as np
import uuid
import io
from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Image, Text, Mface, Node
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.install_and_import import install_and_import
from framework_common.utils.utils import  get_img

cv2=install_and_import("opencv-python","cv2")
async def download_img_from_url(url:str):
    async with httpx.AsyncClient() as client:
        r=await client.get(url)
        path="data/pictures/cache/"+uuid.uuid4().hex[:6]+".png"
        with open(path, "wb") as f:
            f.write(r.content)
        return path
# --- 核心切分逻辑 (同步函数) ---
def split_grid_3x3(image_bytes, output_folder):
    """
    最稳健的 3x3 网格切分逻辑：基于统计直方图的区域划分
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return []

    h, w = img.shape[:2]
    # 1. 深度清洗：背景彻底黑化(0)，内容白化(255)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 252, 255, cv2.THRESH_BINARY_INV)

    # 2. 横向投影找行
    row_sum = np.sum(binary, axis=1)

    # 将分布分成3个主要区间
    def get_split_points(projection, count=3):
        # 寻找波谷来切分
        points = [0]
        step = len(projection) // count
        for i in range(1, count):
            search_start = i * step - step // 2
            search_end = i * step + step // 2
            # 在预期切分线附近寻找像素最少的行/列
            valley = search_start + np.argmin(projection[search_start:search_end])
            points.append(valley)
        points.append(len(projection))
        return points

    row_points = get_split_points(row_sum, 3)

    saved_paths = []
    batch_id = uuid.uuid4().hex[:6]
    idx = 1

    # 3. 嵌套切分
    for i in range(3):
        r_s, r_e = row_points[i], row_points[i + 1]
        row_img = img[r_s:r_e, :]
        row_bin = binary[r_s:r_e, :]

        # 纵向投影找列
        col_sum = np.sum(row_bin, axis=0)
        col_points = get_split_points(col_sum, 3)

        for j in range(3):
            c_s, c_e = col_points[j], col_points[j + 1]

            # 此时得到了 1/9 的格子区域，进一步精修边界（去掉格子里多余的白边）
            sub_bin = row_bin[:, c_s:c_e]
            coords = cv2.findNonZero(sub_bin)
            if coords is not None:
                x, y, sw, sh = cv2.boundingRect(coords)
                # 在原图切片上根据内容重心再次对齐
                pad = 10
                y1 = max(r_s, r_s + y - pad)
                y2 = min(r_e, r_s + y + sh + pad)
                x1 = max(c_s, c_s + x - pad)
                x2 = min(c_e, c_s + x + sw + pad)

                roi = img[y1:y2, x1:x2]
                path = os.path.join(output_folder, f"sticker_{batch_id}_{idx}.png")
                cv2.imwrite(path, roi)
                saved_paths.append(path)
            idx += 1

    return saved_paths


# --- 插件主类 ---
def main(bot: ExtendBot, config: YAMLManager):
    # 存储格式: {user_id: {"image": [path1], "text": [prompt1]}}
    sticker_user_dict = {}

    # 确保缓存目录存在
    CACHE_DIR = "data/pictures/cache"
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    @bot.on(GroupMessageEvent)
    async def handle_sticker_maker(event: GroupMessageEvent):
        nonlocal sticker_user_dict
        uid = event.user_id

        # 1. 进入制作模式
        if event.pure_text in ["/制作表情包","/表情包制作"]:
            sticker_user_dict[uid] = {"image": [], "text": []}
            await bot.send(event,
                           "🎨 已进入表情包制作模式\n请发送：\n1. 参考图片（1张）\n2. 描述文字（如：猫咪、生气的）\n全部发送后，发送 /end 开始制作")
            return

        # 2. 提交并处理
        elif event.pure_text == "/end" and uid in sticker_user_dict:
            data_store = sticker_user_dict[uid]

            if not data_store["image"]:
                await bot.send(event, "❌ 你还没有发送参考图片呢。")
                return

            await bot.send(event, "🚀 正在为您生成 3x3 表情包矩阵并切分，请稍候...")

            # 配置获取
            api_config = config.ai_generated_art.config.get("gptimage2", {})
            base_url = api_config.get("base_url", "http://api.apollodorus.xyz/v1")
            apikey = api_config.get("apikey", "")
            model = api_config.get("model", "")
            resolution=api_config.get("resolution")

            # 构造 Prompt
            user_prompt = " ".join(data_store["text"]) if data_store["text"] else "可爱Q版"
            final_prompt = (
                "要求：做成9张line风格的Q版表情包贴纸。必须是 3x3 矩阵，每个表情之间必须有非常宽的空白间隙 (very wide white gutters)，"
                "日漫画风，平涂、简约、q版，纯白背景。作为Line表情包，应当具有“漫画感”，动态丰富，主题丰富，且有适当的配字"
                f"以下为附加要求：{user_prompt}"
            )

            try:
                # 准备图片
                img_path = data_store["image"][0]
                async with aiofiles.open(img_path, "rb") as f:
                    content = await f.read()

                headers = {"Authorization": f"Bearer {apikey}"}
                files = [("images", (os.path.basename(img_path), io.BytesIO(content), "image/png"))]
                data = {
                    "prompt": final_prompt,
                    "aspect_ratio": "1:1",
                    "model": model,
                    "resolution": resolution
                }
                if uid in sticker_user_dict:
                    for p in sticker_user_dict[uid]["image"]:
                        if os.path.exists(p): os.remove(p)
                    sticker_user_dict.pop(uid)
                retries=0

                async def request_api(retries=0):
                    try:
                        # 请求 API
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(
                                f"{base_url}/images/edits",
                                headers=headers,
                                files=files,
                                data=data,
                                timeout=None
                            )
                            if resp.status_code != 200:
                                #await bot.send(event, f"❌ 生成失败: {resp.text}")
                                raise Exception(resp.text)
                            return resp
                    except Exception as e:
                        bot.logger.error(traceback.format_exc())
                        if retries < 3:
                            retries += 1
                            return await request_api(retries)
                            bot.logger.error("绘图出现错误，即将重试")
                        else:
                            raise Exception(e)

                resp=await request_api(retries)
                if resp.status_code != 200:
                    await bot.send(event, f"❌ 生成失败: {resp.text}")
                    return

                # 下载生成的网格大图
                res_json = resp.json()
                grid_img_url = res_json["data"][0]["url"]

                async with httpx.AsyncClient() as client:
                    img_resp = await client.get(grid_img_url, timeout=None)
                    grid_img_bytes = img_resp.content

                # 在线程池中执行 OpenCV 切分，避免阻塞
                loop = asyncio.get_event_loop()
                sticker_paths = await loop.run_in_executor(
                    None, split_grid_3x3, grid_img_bytes, CACHE_DIR
                )

                if not sticker_paths:
                    await bot.send(event, "❌ 切分失败，未能识别到表情区域。")
                else:
                    # 发送所有切分后的图片
                    msg_list = [Text(f"✅ 成功制作 {len(sticker_paths)} 张表情包：")]
                    for p in sticker_paths:
                        msg_list.append(Image(file=f"file:///{os.path.abspath(p)}"))


                    await bot.send(event, msg_list)

            except Exception as e:
                traceback.print_exc()
                await bot.send(event, f"❌ 发生错误: {str(e)}")
            finally:
                # 清理
                if uid in sticker_user_dict:
                    for p in sticker_user_dict[uid]["image"]:
                        if os.path.exists(p): os.remove(p)
                    sticker_user_dict.pop(uid)
            return

        # 3. 收集模式
        elif uid in sticker_user_dict:
            found = False
            print("表情包制作：",event.message_chain)
            for mes in event.message_chain:
                if isinstance(mes, Text):
                    sticker_user_dict[uid]["text"].append(mes.text.strip())
                    found = True

                elif isinstance(mes, Image) or isinstance(mes, Mface):
                    print("触发分支")
                    url = mes.url if hasattr(mes, 'url') and mes.url else mes.file

                    if url:
                        print(url)
                        path = await download_img_from_url(url)
                        sticker_user_dict[uid]["image"].append(path)
                        found = True
                elif get_img(event,bot):
                    path=await download_img_from_url(get_img(event,bot))
                    sticker_user_dict[uid]["image"].append(path)
                    found = True
            if found:
                await bot.send(event, "已添加",True)