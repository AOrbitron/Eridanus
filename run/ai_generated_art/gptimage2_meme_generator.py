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


def build_sticker_prompt(has_style_ref: bool, user_prompt: str = "") -> str:
    """构建对齐 sticker_style_ref_16 灵动瘦脸漫画风的纯白底 3x3 贴纸表情包提示词"""
    user_extra = f"\n附加需求与偏好：{user_prompt.strip()}" if user_prompt and user_prompt.strip() else ""
    if has_style_ref:
        style_ref_clause = (
            "【严格分图参考规则】：\n"
            "- 图1是目标角色设定图：角色外貌、发型、发色、渐变、呆毛、发饰、瞳色与服装特征必须 100% 严格遵循图1（绝对不要把图2的猫耳、黑发夹或深色衣服套给图1角色！）。\n"
            "- 图2仅作为画风与漫画表现力参考：请学习图2那种**清秀灵动、漫画感极强的日系 Q 版表情包画风**。\n\n"
            "【必须精准复刻的视觉特征】：\n"
        )
    else:
        style_ref_clause = (
            "将图1中的角色绘制为 3×3 矩阵排列的 9 张“漫画夸张表现力极强”的日系 Q 版贴纸表情包（外貌特征严格遵循图1）：\n"
        )
    return (
        f"{style_ref_clause}"
        "1. 体型与脸型（极端重要）：采用**纤细灵动的日系 Q 版比例**——保留清秀小巧的瓜子/鹅蛋下巴与瘦削脸颊，**严禁把脸画得圆鼓鼓或把身材画得臃肿肥胖**！四肢与肩颈纤细灵活，富有动感。\n"
        "2. 线条与色彩对比：采用**清晰有力、略带漫画笔锋的深紫灰/深蓝黑动漫描线**（crisp expressive anime ink outline），搭配色彩明快清亮、对比鲜明的干净平涂赛璐璐色块（不要发灰发白，也不要任何鱼鳞纹、噪点、网点或油画肌理）。\n"
        "3. 漫画式夸张颜艺与小道具（核心灵魂）：不要画千篇一律的乖巧微笑！必须画出像图2那样戏剧化、情绪拉满的夸张动作与搞笑道具，9 格分别为：\n"
        "   - (1) 黑化阴沉：额头压下大块紫黑阴影，面无表情掏出亮晶晶小刀（气泡 `...`）\n"
        "   - (2) 哭成水滩：委屈到整个人瘫扁融化在一滩浅蓝眼泪水洼里\n"
        "   - (3) 狂喜欢呼：`> <` 闭眼张大嘴高举双臂欢呼，飘红心与红色手写 `Suki!!`\n"
        "   - (4) 呆萌吃瓜：双手捧着一大块红西瓜，`w` 嘴圆眼专心啃\n"
        "   - (5) 羞耻/气急喷蒸汽：脸颊爆红，双手捂脸或抱拳，头顶左右喷出漫画白气\n"
        "   - (6) 晕头转向：两眼变成 `@ @` 螺旋蚊香眼，头发乱翘冒小星星\n"
        "   - (7) 死鱼眼无语：半睁冷漠死鱼眼放空，旁带蓝色省略号气泡\n"
        "   - (8) 元气大笑：开心眨眼或张嘴大笑，双手比耶/比心，旁带音符或闪光\n"
        "   - (9) 墙角暗中观察：从左侧竖直门框边缘探出半个脑袋和一只小手偷偷张望\n"
        "4. 纯白底与贴纸白边：背景必须为纯白色（#FFFFFF，不要黑底！），3×3 整齐排列 9 个贴纸，每个贴纸外围带有粗细均匀的白色剪纸轮廓与清晰浅灰外框，贴纸之间保留宽阔干净的纯白间隔。"
        f"{user_extra}"
    )


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
            resolution = api_config.get("sticker_resolution") or "1K"
            style_ref_path = api_config.get("sticker_style_ref") or "data/system/sticker_style_ref_16.png"
            max_retry = api_config.get("max_retry", 5)

            # 兼容不同相对路径解析风格参考图（优先使用 sticker_style_ref_16.png 作为软萌团子风参考）
            if not style_ref_path or not os.path.exists(style_ref_path):
                candidates = [
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), style_ref_path) if style_ref_path else "",
                    os.path.join("data", "system", "sticker_style_ref_16.png"),
                    os.path.join(os.path.dirname(__file__), "assets", "test_result_1.png"),
                    os.path.join("data", "system", os.path.basename(style_ref_path)) if style_ref_path else "",
                    os.path.join(os.path.dirname(__file__), "assets", "sticker_style_ref.png"),
                ]
                for c in candidates:
                    if c and os.path.exists(c):
                        style_ref_path = c
                        break

            # 构造 Prompt（对齐 test_result_1.png 干净平涂半身大头贴纸风格，消除鱼鳞纹）
            user_prompt = " ".join(data_store["text"]).strip() if data_store["text"] else ""

            # 准备图片
            img_path = data_store["image"][0]
            try:
                src_images = [img_path]
                has_style_ref = False
                if style_ref_path and os.path.exists(style_ref_path):
                    src_images.append(style_ref_path)
                    has_style_ref = True

                final_prompt = build_sticker_prompt(has_style_ref=has_style_ref, user_prompt=user_prompt)

                # 提交后清理当前用户状态
                saved_images = list(sticker_user_dict[uid]["image"])
                sticker_user_dict.pop(uid, None)

                from run.ai_generated_art.service.gptimage2_client import gptimage2_edit
                grid_img_path = await gptimage2_edit(
                    src_images,
                    final_prompt,
                    config,
                    aspect_ratio="1:1",
                    resolution=resolution,
                    max_retries=max_retry,
                )
                async with aiofiles.open(grid_img_path, "rb") as f_grid:
                    grid_img_bytes = await f_grid.read()

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
