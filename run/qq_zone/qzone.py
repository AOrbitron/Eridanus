# -*- coding: utf-8 -*-
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from run.qq_zone.service.native_login import NativeQzoneLogin

from developTools.event.events import LifecycleMetaEvent, GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Text, Image, Mface

from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import get_img, download_img
from run.qq_zone.service.QzoneApiFixed import QzoneApiFixed


def main(bot: ExtendBot, config: YAMLManager):
    logger = bot.logger
    qzone_login = NativeQzoneLogin()
    login_result = None
    login_task = None
    qzone = QzoneApiFixed()
    qzone_status = False

    # ---------------------------------------------------------
    # 尝试加载 mai_reply 的 ContextManager 和 LLMClient
    # ---------------------------------------------------------
    mai_context = None
    mai_llm = None
    try:
        from run.mai_reply.service.context_manager import ContextManager
        from run.mai_reply.service.llm_client import LLMClient
        mai_context = ContextManager(config)
        mai_llm = LLMClient(config)
        logger.info("[Qzone] 成功连接 mai_reply 记忆管理与 LLMClient")
    except Exception as e:
        logger.warning(f"[Qzone] 加载 mai_reply 组件失败: {e}")

    # ---------------------------------------------------------
    # 本地 Cookie 缓存管理
    # ---------------------------------------------------------
    cookie_file = Path("data/qzone_cookie.json")
    cookie_file.parent.mkdir(parents=True, exist_ok=True)

    def load_cookie_cache():
        if cookie_file.exists():
            try:
                data = json.loads(cookie_file.read_text(encoding="utf-8"))
                logger.info("[Qzone] 成功加载本地 QQ 空间 Cookie")
                return data
            except Exception as e:
                logger.error(f"[Qzone] 读取本地 Cookie 失败: {e}")
        return None

    def save_cookie_cache(data):
        try:
            cookie_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("[Qzone] QQ 空间 Cookie 已持久化保存")
        except Exception as e:
            logger.error(f"[Qzone] 保存本地 Cookie 失败: {e}")

    if load_cookie_cache():
        login_result = load_cookie_cache()
        logger.info("[Qzone] 使用本地 Cookie 登录 QQ 空间")

    # ---------------------------------------------------------
    # 登录流程（仅通过显式触发或管理员命令执行，防止风控）
    # ---------------------------------------------------------
    async def login_task_wrapper(event=None):
        nonlocal login_result, login_task
        if login_task and not login_task.done():
            logger.warning("[Qzone] 登录任务正在进行中，跳过重复请求")
            if event:
                await bot.send(event, [Text("QQ空间登录任务正在进行中，请扫码...")])
            return

        async def _do_login():
            nonlocal login_result
            logger.info("[Qzone] 开始获取登录二维码并等待扫码...")
            master_id = config.common_config.basic_config.get("master", {}).get("id")

            qr_info = await qzone_login.get_qrcode()
            if not qr_info:
                logger.error("[Qzone] 获取登录二维码失败！")
                if event:
                    await bot.send(event, [Text("获取 QQ 空间登录二维码失败，请检查网络后重试。")])
                elif master_id:
                    try:
                        await bot.send_friend_message(master_id, [Text("获取 QQ 空间登录二维码失败，请检查网络后重试。")])
                    except Exception:
                        pass
                return

            qrsig, qr_img_path = qr_info
            # 发送二维码图片给触发者或管理员
            msg_chain = [Text("【QQ空间登录】请使用手机QQ扫描下方二维码完成空间授权登录（有效期约2分钟）："), Image(file=str(qr_img_path))]
            if event:
                await bot.send(event, msg_chain)
            elif master_id:
                try:
                    await bot.send_friend_message(master_id, msg_chain)
                except Exception as e:
                    logger.error(f"[Qzone] 发送二维码图片消息异常: {e}")

            res = await qzone_login.wait_for_login(qrsig, timeout_seconds=120)
            if res and res.get("code") == 0:
                login_result = res
                save_cookie_cache(res)
                logger.info("[Qzone] QQ空间扫码登录成功！")
                succ_msg = [Text("✅【QQ空间】扫码授权登录成功，凭证已安全持久化！")]
                if event:
                    await bot.send(event, succ_msg)
                elif master_id:
                    try:
                        await bot.send_friend_message(master_id, succ_msg)
                    except Exception:
                        pass
            else:
                fail_msg = f"❌【QQ空间】登录未成功: {res.get('msg', '未知原因')}"
                logger.error(f"[Qzone] QQ空间登录失败: {res}")
                if event:
                    await bot.send(event, [Text(fail_msg)])
                elif master_id:
                    try:
                        await bot.send_friend_message(master_id, [Text(fail_msg)])
                    except Exception:
                        pass

        login_task = asyncio.create_task(_do_login())

    # ---------------------------------------------------------
    # 动态与图片发送辅助方法
    # ---------------------------------------------------------
    async def send_to_qzone(content: Optional[str] = None, pic_paths: Optional[list] = None):
        nonlocal login_result
        if not login_result:
            logger.warning("[Qzone] 尚未登录，尝试读取本地 Cookie...")
            login_result = load_cookie_cache()
            if not login_result:
                logger.error("[Qzone] 无有效登录凭证，请管理员发送 /qzone login 扫码登录")
                return None

        target_qq_str = str(login_result.get("qq", "")).replace("o", "")
        if not target_qq_str:
            logger.error("[Qzone] 登录凭证中缺失 QQ 号")
            return None
        target_qq = int(target_qq_str)

        cookies = login_result.get("cookies", {})
        g_tk = login_result.get("bkn", "")

        content = content or ""
        if pic_paths:
            pic_path = pic_paths[0]
            logger.info(f"[Qzone] 正在发送带图说说: {content[:30]}... 配图: {pic_path}")
            return await qzone._send_zone_with_pic(
                target_qq=target_qq,
                pic_path=pic_path,
                content=content,
                cookies=cookies,
                g_tk=g_tk,
            )
        else:
            logger.info(f"[Qzone] 正在发送纯文字说说: {content[:30]}...")
            cookies_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            return await qzone._send_zone(
                target_qq=target_qq,
                content=content,
                cookies=cookies_str,
                g_tk=g_tk,
            )

    # ---------------------------------------------------------
    # Stable Diffusion 绘画服务端调用
    # ---------------------------------------------------------
    async def call_sd_generate(prompt: str) -> Optional[str]:
        sd_cfg = config.qq_zone.config.get("sd绘画设置", {})
        base_url = sd_cfg.get("sdUrl", "http://apollodorus.xyz:3530").rstrip("/")
        txt2img_url = f"{base_url}/sdapi/v1/txt2img"

        payload = {
            "prompt": prompt,
            "negative_prompt": "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, nsfw",
            "steps": int(sd_cfg.get("steps", 25)),
            "cfg_scale": float(sd_cfg.get("cfg_scale", 7.0)),
            "width": int(sd_cfg.get("width", 1024)),
            "height": int(sd_cfg.get("height", 1024)),
            "sampler_name": "Euler a",
            "batch_size": 1,
            "n_iter": 1,
        }
        headers = {
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        timeout_val = int(sd_cfg.get("timeout", 120))

        try:
            logger.info(f"[Qzone SD] 请求生图: {txt2img_url}, prompt: {prompt[:60]}...")
            async with httpx.AsyncClient(timeout=timeout_val, headers=headers) as client:
                resp = await client.post(txt2img_url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    images = data.get("images", [])
                    if images:
                        raw_b64 = images[0]
                        if "," in raw_b64:
                            raw_b64 = raw_b64.split(",", 1)[1]
                        img_bytes = base64.b64decode(raw_b64)
                        out_dir = Path("data/pictures/cache")
                        out_dir.mkdir(parents=True, exist_ok=True)
                        save_path = out_dir / f"qzone_sd_{uuid.uuid4().hex[:8]}.png"
                        save_path.write_bytes(img_bytes)
                        logger.info(f"[Qzone SD] 生图成功并保存至: {save_path}")
                        return str(save_path)
                logger.error(f"[Qzone SD] 接口状态码异常: {resp.status_code}, 内容: {resp.text[:120]}")
        except Exception as e:
            logger.error(f"[Qzone SD] 生图请求失败: {e}")
        return None

    # ---------------------------------------------------------
    # 老黄历辅助方法
    # ---------------------------------------------------------
    async def get_almanac_info() -> Optional[str]:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        url = f"https://www.36jxs.com/api/Commonweal/almanac?sun={today}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    data = await resp.json()
                    if data.get("code") != 1:
                        return None
                    d = data.get("data", {})
                    solar_term = d.get("SolarTermName") or ""
                    lunar_festival = d.get("LJie") or ""
                    gregorian_festival = d.get("GJie") or ""
                    if lunar_festival:
                        lunar_festival = lunar_festival.split()[0]
                    if gregorian_festival:
                        gregorian_festival = gregorian_festival.split()[0]
                    return solar_term or lunar_festival or gregorian_festival
        except Exception as e:
            logger.warning(f"[Qzone] 老黄历获取失败: {e}")
            return None

    def get_bot_persona_info() -> tuple[str, str]:
        bot_name = config.common_config.basic_config.get("bot", "小助手")
        chara_text = ""
        try:
            pcfg = config.mai_reply.config.get("persona", {})
            chara_file_name = pcfg.get("chara_file", "").strip()
            if not chara_file_name:
                chara_cfg = config.mai_reply.config.get("chara", {})
                cur = chara_cfg.get("current", "")
                if cur:
                    chara_file_name = f"{cur}.txt" if not cur.endswith(".txt") else cur

            if chara_file_name:
                chara_path = Path("data/system/chara") / chara_file_name
                if chara_path.exists():
                    chara_text = chara_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[Qzone] 读取人设文件失败: {e}")
        return bot_name, chara_text

    # ---------------------------------------------------------
    # 重做温和低频保活（防止风控，绝对杜绝循环后台扫码）
    # ---------------------------------------------------------
    async def check_cookie_alive() -> bool:
        nonlocal login_result
        if not login_result:
            login_result = load_cookie_cache()
            if not login_result:
                return False

        target_qq_str = str(login_result.get("qq", "")).replace("o", "")
        if not target_qq_str:
            return False
        target_qq = int(target_qq_str)

        cookies = login_result.get("cookies", {})
        cookies_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        g_tk = login_result.get("bkn", "")

        try:
            r = await qzone._get_zone(target_qq=target_qq, g_tk=g_tk, cookies=cookies_str, count=1)
            if r and '"code":0' in r:
                return True
            logger.warning(f"[Qzone 保活] 探测返回未包含 code:0: {str(r)[:120]}")
            return False
        except Exception as e:
            logger.error(f"[Qzone 保活] 探测异常: {e}")
            return False

    async def start_keepalive_monitor():
        cookie_cfg = config.qq_zone.config.get("cookie设置", {})
        if not cookie_cfg.get("保活", True):
            logger.info("[Qzone 保活] 保活机制未开启")
            return

        interval = max(600, int(cookie_cfg.get("保活间隔_秒", 1800)))
        logger.info(f"[Qzone 保活] 启动温和保活监控，轮询间隔: {interval} 秒")

        has_notified = False
        while True:
            await asyncio.sleep(interval)
            try:
                alive = await check_cookie_alive()
                if alive:
                    logger.info("[Qzone 保活] Cookie 状态有效，空间在线")
                    has_notified = False
                else:
                    logger.warning("[Qzone 保活] 检测到 QQ 空间 Cookie 可能已失效！")
                    master_id = config.common_config.basic_config.get("master", {}).get("id")
                    if cookie_cfg.get("失效通知", True) and master_id and not has_notified:
                        try:
                            await bot.send_friend_message(
                                master_id,
                                [Text("⚠️【QQ空间提醒】空间 Cookie 已失效或探测失败。为避免频繁扫码风控，请在私聊或管理群输入 /qzone login 手动重新扫码登录！")]
                            )
                            has_notified = True
                        except Exception as e:
                            logger.error(f"[Qzone 保活] 发送失效通知失败: {e}")

                    # 如果配置中强行打开了自动重新登陆（默认关闭防风控）
                    if cookie_cfg.get("失效时自动重新登陆", False):
                        logger.warning("[Qzone 保活] 配置开启了自动重新登陆，尝试拉起登录二维码...")
                        await login_task_wrapper()
            except Exception as e:
                logger.error(f"[Qzone 保活] 监控循环异常: {e}")

    # ---------------------------------------------------------
    # 定时早晚发空间任务
    # ---------------------------------------------------------
    async def task_executor(task_name: str, task_info: dict):
        logger.info(f"[Qzone 任务] 开始执行定时发空间任务: {task_name}")
        bot_name, chara_text = get_bot_persona_info()
        festival_or_term = await get_almanac_info()

        current_global_mem = mai_context.get_global_memory() if mai_context else ""

        desc_task = "用清晨活力、期待新一天的语气打招呼，分享早安感悟" if task_name == "早安" else "回顾总结今天的一天、感慨夜晚与休息，祝大家晚安"
        desc_fest = f"3. 今日节日/节气：{festival_or_term}，可自然提及融入" if festival_or_term else "3. 贴合真实时间与日常生活氛围"

        sys_prompt = (
            f"你是{bot_name}。\n"
            f"你的角色设定：\n{chara_text}\n\n"
            f"你现在要发布一条 QQ 空间的【{task_name}】说说动态。\n"
            f"要求：\n"
            f"1. 完全保持自身人设语气与口吻，生动真实、自然生活化，绝不要带有任何AI感或机械套话。\n"
            f"2. {desc_task}\n"
            f"{desc_fest}\n"
            f"4. 篇幅适中（50~120字），像发朋友圈/空间说说一样亲切。\n"
            f"5. 严禁输出任何解释或格式标记，仅直接输出说说文字。"
        )

        user_prompt = f"请写一条你的{task_name}说说。"
        if current_global_mem:
            user_prompt += f" 你最近的日常记忆有：{current_global_mem}"

        post_content = ""
        try:
            if mai_llm:
                resp = await mai_llm.chat(
                    messages=[{"role": "user", "content": user_prompt}],
                    system_prompt=sys_prompt,
                )
                post_content = resp.strip() if resp else ""
        except Exception as e:
            logger.error(f"[Qzone] LLM 生成说说文案异常: {e}")

        if not post_content:
            post_content = f"{task_name}！新的一天也要开开心心呀~" if task_name == "早安" else f"{task_name}！今天辛苦啦，早点休息，做个好梦~"

        logger.info(f"[Qzone] 生成说说内容: {post_content}")

        # 提炼日常精炼记忆存入全局记忆层（控制在50字以内，不滥用）
        if mai_context and mai_llm:
            try:
                mem_prompt = (
                    f"请将以下这段Bot的说说内容提炼为一条极度精炼的日常状态或事件摘要（不要超过40个字，只保留最核心的日常行为/心情，不要无病呻吟）：\n"
                    f"说说：{post_content}\n"
                    f"直接输出极简摘要，无任何标点废话："
                )
                refined_mem = await mai_llm.chat(
                    messages=[{"role": "user", "content": mem_prompt}],
                    system_prompt="你是一个信息精炼助手。",
                )
                if refined_mem and len(refined_mem.strip()) > 0:
                    clean_mem = refined_mem.strip()[:50]
                    mai_context.update_global_memory(f"[{datetime.datetime.now().strftime('%m-%d %H:%M')}] {clean_mem}")
                    logger.info(f"[Qzone 全局记忆更新] 已录入精炼日常: {clean_mem}")
            except Exception as e:
                logger.error(f"[Qzone] 提取精炼记忆失败: {e}")

        # 判断是否需要 SD 绘图
        pic_paths = []
        if task_info.get("绘制图片", True):
            sd_prompt = ""
            try:
                if mai_llm:
                    prompt_generator = (
                        f"你是 Stable Diffusion 提示词专家。根据角色【{bot_name}】的人设与今天的【{task_name}】动态：\n"
                        f"说说内容：{post_content}\n"
                        f"角色设定：{chara_text[:300]}\n"
                        f"请生成一段高质量的适合画出角色自己形象的 SD 英文提示词 (Tags)。\n"
                        f"包含：1girl/1boy (匹配人设), 角色外观特征(发色、瞳色、服装), 动作姿态, 场景氛围(日出/清晨/夜晚/卧室/窗边), 杰作画质(masterpiece, best quality, ultra-detailed)。\n"
                        f"只输出英文逗号分隔的 tag 列表，不要有任何多余文字或引号："
                    )
                    sd_tags = await mai_llm.chat(
                        messages=[{"role": "user", "content": prompt_generator}],
                        system_prompt="You are a prompt engineer for Stable Diffusion.",
                    )
                    if sd_tags:
                        sd_prompt = sd_tags.strip().replace("\n", ", ")
            except Exception as e:
                logger.error(f"[Qzone] 生成生图 prompt 失败: {e}")

            if not sd_prompt:
                theme_tag = "morning, sunrise, window, stretching, gentle smile" if task_name == "早安" else "night, bedroom, moonlight, pajamas, cozy, sleepy"
                sd_prompt = f"1girl, cute, masterpiece, best quality, highly detailed, {theme_tag}"

            img_file = await call_sd_generate(sd_prompt)
            if img_file:
                pic_paths.append(img_file)

        # 发布至 QQ 空间
        try:
            res = await send_to_qzone(post_content, pic_paths)
            logger.info(f"[Qzone] 发布动态完成: {res}")
        except Exception as e:
            logger.error(f"[Qzone] 发布动态异常: {e}")

    # ---------------------------------------------------------
    # 空间好友评论自动拟人化互动回复
    # ---------------------------------------------------------
    replied_comments_file = Path("data/qzone_replied_comments.json")
    replied_comments_file.parent.mkdir(parents=True, exist_ok=True)

    def load_replied_comments() -> set:
        if replied_comments_file.exists():
            try:
                return set(json.loads(replied_comments_file.read_text(encoding="utf-8")))
            except Exception:
                pass
        return set()

    def save_replied_comments(s: set):
        try:
            # 最多保留最新 2000 条
            l = list(s)[-2000:]
            replied_comments_file.write_text(json.dumps(l, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[Qzone] 保存评论回复缓存失败: {e}")

    replied_comment_ids = load_replied_comments()

    async def check_and_reply_comments():
        nonlocal login_result, replied_comment_ids
        if not login_result:
            login_result = load_cookie_cache()
            if not login_result:
                return

        target_qq_str = str(login_result.get("qq", "")).replace("o", "")
        if not target_qq_str:
            return
        target_qq = int(target_qq_str)

        cookies = login_result.get("cookies", {})
        cookies_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        g_tk = login_result.get("bkn", "")

        # 获取自己最近的说说列表
        try:
            resp_str = await qzone._get_messages_list(target_qq=target_qq, g_tk=g_tk, cookies=cookies_str, pos=0, num=5)
            if not resp_str:
                return
            
            clean_str = re.sub(r'^[^(]*\(|\);?\s*$', '', resp_str.strip())
            feed_json = json.loads(clean_str)
            msg_list = feed_json.get("msglist") or []
        except Exception as e:
            logger.debug(f"[Qzone 评论互动] 获取说说列表解析异常: {e}")
            return

        bot_name, chara_text = get_bot_persona_info()

        for msg in msg_list:
            tid = msg.get("tid", "")
            shuoshuo_text = msg.get("content", "")
            comments = msg.get("commentlist") or []

            for c in comments:
                cid = c.get("id", "")
                comment_uid = c.get("uin", 0)
                comment_name = c.get("name", "空间好友")
                comment_content = c.get("content", "")

                # 排除自己发布的评论和已经回复过的评论
                if int(comment_uid) == target_qq:
                    continue
                unique_key = f"{tid}_{cid}"
                if unique_key in replied_comment_ids:
                    continue

                logger.info(f"[Qzone 评论互动] 发现新评论 来自: {comment_name}({comment_uid}) -> {comment_content}")

                # 获取用户在 mai_reply 的对话历史与用户印象
                user_impression = ""
                recent_chat_snippet = ""
                if mai_context:
                    try:
                        user_impression = mai_context.get_impression(int(comment_uid))
                        # 查找历史对话记录
                        pattern = f"*{comment_uid}*"
                        keys = mai_context._ctx_keys(pattern)
                        for k in keys:
                            hist = mai_context._load_history(k)
                            if hist:
                                recent_lines = []
                                for h in hist[-6:]:
                                    role = "用户" if h.get("role") == "user" else bot_name
                                    content_str = h.get("content", "")
                                    if isinstance(content_str, str):
                                        recent_lines.append(f"{role}: {content_str[:50]}")
                                if recent_lines:
                                    recent_chat_snippet = "\n".join(recent_lines)
                                    break
                    except Exception as e:
                        logger.warning(f"[Qzone] 读取 mai_reply 对话上下文失败: {e}")

                # LLM 生成贴合人设与说说主题的回复
                sys_reply_prompt = (
                    f"你是{bot_name}。\n"
                    f"人设信息：\n{chara_text}\n\n"
                    f"你在 QQ 空间发布了一条动态说说，好友正在你的说说下发表了评论。请以你的角色性格回复对方。\n"
                    f"动态说说内容：【{shuoshuo_text}】\n"
                )
                if user_impression:
                    sys_reply_prompt += f"你对该好友({comment_name})的印象与记忆：\n{user_impression}\n"
                if recent_chat_snippet:
                    sys_reply_prompt += f"你们近期的对话上下文片段：\n{recent_chat_snippet}\n"

                sys_reply_prompt += (
                    f"要求：\n"
                    f"1. 结合你的说说主题和对方的评论，自然、亲切地像在空间好友动态下互动一样进行回复。\n"
                    f"2. 若有对他的印象或聊天经历，自然流露熟络感，不要刻意背诵。\n"
                    f"3. 长度控制在 15~60 字以内，轻松口语化，不要包含任何系统标记。"
                )

                reply_text = ""
                try:
                    if mai_llm:
                        res = await mai_llm.chat(
                            messages=[{"role": "user", "content": f"{comment_name} 评论了你的说说：\"{comment_content}\"，请回复他："}],
                            system_prompt=sys_reply_prompt,
                        )
                        reply_text = res.strip() if res else ""
                except Exception as e:
                    logger.error(f"[Qzone] 生成评论回复失败: {e}")

                if not reply_text:
                    reply_text = f"谢谢{comment_name}的评论！记得天天开心哦~"

                # 发送空间评论回复
                try:
                    logger.info(f"[Qzone 评论回复] 正在回复 {comment_name}: {reply_text}")
                    res = await qzone._send_comments(
                        target_qq=target_qq,
                        uin=int(comment_uid),
                        content=reply_text,
                        cookies=cookies_str,
                        g_tk=g_tk,
                        fid=tid,
                    )
                    logger.info(f"[Qzone 评论回复结果]: {res}")
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                except Exception as e:
                    logger.error(f"[Qzone] 调用 _send_comments 失败: {e}")

                await asyncio.sleep(2)

    async def start_comment_monitor():
        inter_cfg = config.qq_zone.config.get("动态互动", {})
        if not inter_cfg.get("enable_comment_reply", True):
            return

        interval = max(60, int(inter_cfg.get("check_interval_秒", 180)))
        logger.info(f"[Qzone 评论互动] 启动评论监控，轮询间隔: {interval} 秒")
        while True:
            await asyncio.sleep(interval)
            try:
                await check_and_reply_comments()
            except Exception as e:
                logger.error(f"[Qzone 评论巡检] 异常: {e}")

    # ---------------------------------------------------------
    # 定时调度器
    # ---------------------------------------------------------
    scheduledTasks = config.qq_zone.config.get("定时发空间", {})
    scheduler = AsyncIOScheduler()

    def create_dynamic_jobs():
        for task_name, task_info in scheduledTasks.items():
            if task_info.get("enable"):
                time_str = str(task_info.get("time", "8/30"))
                parts = time_str.split("/")
                if len(parts) == 2:
                    hour, minute = int(parts[0]), int(parts[1])
                    logger.info(f"[Qzone 任务] 定时空间任务已注册: {task_name} -> 每天 {hour:02d}:{minute:02d}")
                    scheduler.add_job(
                        task_executor,
                        CronTrigger(hour=hour, minute=minute),
                        args=[task_name, task_info],
                        misfire_grace_time=180,
                    )

    bg_started = False

    async def init_background_services():
        nonlocal bg_started
        if bg_started:
            return
        bg_started = True

        create_dynamic_jobs()
        scheduler.start()
        logger.info("[Qzone] 定时发空间调度器已启动")

        asyncio.create_task(start_keepalive_monitor())
        asyncio.create_task(start_comment_monitor())

    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(event: LifecycleMetaEvent):
        await init_background_services()

    async def set_cache(event):
        text_cache = ""
        img_cache = []
        for msg in event.message_chain:
            if isinstance(msg, Text):
                text_cache += msg.text
            elif isinstance(msg, Image) or isinstance(msg, Mface):
                url = await get_img(event, bot)
                path = f"data/pictures/cache/{uuid.uuid4()}.png"
                await download_img(url, path)
                img_cache.append(path)
        await send_to_qzone(text_cache, img_cache)

    @bot.on(GroupMessageEvent)
    async def handle_group_message(event: GroupMessageEvent):
        nonlocal qzone_status
        await init_background_services()

        master_id = config.common_config.basic_config.get("master", {}).get("id")
        is_master = (event.user_id == master_id)

        if event.pure_text == "/qzone login" and is_master:
            await login_task_wrapper(event)
        elif event.pure_text == "/发说说" and is_master:
            await bot.send(event, "请发送要发布的说说内容：")
            await sleep(1)
            qzone_status = True
        elif qzone_status and is_master:
            qzone_status = False
            await set_cache(event)
        elif event.pure_text in ["测试早安", "发送早安"] and is_master:
            await bot.send(event, [Text("正在测试发送早安说说...")])
            task_info = scheduledTasks.get("早安", {"绘制图片": True})
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = scheduledTasks.get("晚安", {"绘制图片": True})
            await task_executor("晚安", task_info)
        elif event.pure_text == "测试空间互动" and is_master:
            await bot.send(event, [Text("正在立即检查空间评论并回复...")])
            await check_and_reply_comments()

    @bot.on(PrivateMessageEvent)
    async def handle_private_message(event: PrivateMessageEvent):
        nonlocal qzone_status
        await init_background_services()

        master_id = config.common_config.basic_config.get("master", {}).get("id")
        is_master = (event.user_id == master_id)

        if event.pure_text == "/qzone login" and is_master:
            await login_task_wrapper(event)
        elif event.pure_text == "/发说说" and is_master:
            await bot.send(event, "请发送要发布的说说内容：")
            await sleep(1)
            qzone_status = True
        elif qzone_status and is_master:
            qzone_status = False
            await set_cache(event)
        elif event.pure_text in ["测试早安", "发送早安"] and is_master:
            await bot.send(event, [Text("正在测试发送早安说说...")])
            task_info = scheduledTasks.get("早安", {"绘制图片": True})
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = scheduledTasks.get("晚安", {"绘制图片": True})
            await task_executor("晚安", task_info)
