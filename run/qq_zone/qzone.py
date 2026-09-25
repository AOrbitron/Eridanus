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


def calc_bkn(p_skey: str) -> int:
    hash_val = 5381
    for c in str(p_skey):
        hash_val += (hash_val << 5) + ord(c)
    return hash_val & 0x7FFFFFFF


def main(bot: ExtendBot, config: YAMLManager):
    logger = bot.logger
    qzone_login = NativeQzoneLogin()
    login_result = None
    login_task = None
    qzone = QzoneApiFixed()
    qzone_status = False
    cookie_invalid_notified = False

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
    # 本地 Cookie 缓存管理与 OneBot 接口无感免密获取
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

    async def fetch_cookie_from_onebot() -> Optional[Dict[str, Any]]:
        nonlocal login_result, cookie_invalid_notified
        try:
            call_api = getattr(bot, "_call_api", None) or getattr(bot, "call_api", None)
            if not call_api:
                logger.warning("[Qzone] bot 未暴露 _call_api 无法直接调用 OneBot 凭证接口")
                return None

            res = await call_api("get_cookies", {"domain": "qzone.qq.com"})
            if not res:
                return None

            data = res.get("data", {}) if isinstance(res, dict) else {}
            cookie_str = data.get("cookies", "") if isinstance(data, dict) else ""
            if not cookie_str and isinstance(res, dict) and "cookies" in res:
                cookie_str = res.get("cookies", "")

            if not cookie_str:
                logger.warning("[Qzone OneBot] 获取到的 cookies 为空")
                return None

            cookies_dict = {}
            for item in cookie_str.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    cookies_dict[k.strip()] = v.strip()

            uin_str = cookies_dict.get("uin") or cookies_dict.get("p_uin") or ""
            uin_clean = str(uin_str).replace("o", "").strip()
            if not uin_clean:
                bot_qq = getattr(bot, "uin", None) or getattr(bot, "qq", None) or config.common_config.basic_config.get("bot_qq")
                if bot_qq:
                    uin_clean = str(bot_qq).replace("o", "").strip()

            p_skey = cookies_dict.get("p_skey") or cookies_dict.get("skey") or ""
            bkn = calc_bkn(p_skey) if p_skey else 0

            auth_data = {
                "code": 0,
                "msg": "success_from_onebot",
                "qq": uin_clean,
                "bkn": bkn,
                "cookies": cookies_dict,
                "raw_cookie_str": cookie_str,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            login_result = auth_data
            save_cookie_cache(auth_data)
            cookie_invalid_notified = False
            logger.info(f"[Qzone OneBot] 成功自动同步最新 QQ 空间凭证! QQ: {uin_clean}, bkn: {bkn}")
            return auth_data
        except Exception as e:
            logger.warning(f"[Qzone OneBot] 调用 OneBot get_cookies 异常: {e}")
            return None

    def check_resp_for_expired(resp: Any) -> bool:
        if not resp:
            return False
        resp_str = str(resp)
        expired_patterns = [
            "-3000",
            '"code": -3000',
            '"code":-3000',
            '"ret": -100',
            '"ret":-100',
            "'ret': -100'",
            "'ret':-100",
            "need login",
            "请先登录空间",
            "登录失败，请重新登录",
            "登录超时",
            '"subcode":-4001',
            '"subcode": -4001',
        ]
        return any(p in resp_str for p in expired_patterns)

    async def handle_cookie_expired(reason: str = "Cookie失效"):
        nonlocal login_result, cookie_invalid_notified
        logger.warning(f"[Qzone] 凭证异常: {reason}，尝试通过 OneBot 重新拉取...")

        fresh = await fetch_cookie_from_onebot()
        if fresh:
            logger.info("[Qzone] 通过 OneBot 成功刷新空间凭据，无需人工介入！")
            return

        if not cookie_invalid_notified:
            cookie_invalid_notified = True
            logger.warning(f"[Qzone] 通知管理员: {reason}，需重新授权")
            master_id = config.common_config.basic_config.get("master", {}).get("id")
            if master_id:
                try:
                    await bot.send_friend_message(
                        master_id,
                        [Text(f"⚠️【QQ空间】登录凭证可能已失效\n原因：{reason}\n请向Bot发送 /qzone login 重新扫码登录")]
                    )
                except Exception as e:
                    logger.error(f"[Qzone] 通知管理员异常: {e}")

    if load_cookie_cache():
        login_result = load_cookie_cache()
        logger.info("[Qzone] 使用本地 Cookie 登录 QQ 空间")

    # ---------------------------------------------------------
    # 登录流程（仅通过显式触发或管理员命令执行，防止风控）
    # ---------------------------------------------------------
    async def login_task_wrapper(event=None):
        nonlocal login_result, login_task

        async def _do_login():
            nonlocal login_result
            logger.info("[Qzone] 优先尝试通过 OneBot 静默获取空间 Cookie...")
            ob_res = await fetch_cookie_from_onebot()
            if ob_res:
                succ_msg = [Text("✅【QQ空间】已成功通过协议免扫码直接拉取空间凭证！")]
                if event:
                    await bot.send(event, succ_msg)
                return

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
                cookie_invalid_notified = False
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
            await fetch_cookie_from_onebot()
        if not login_result:
            logger.warning("[Qzone] 尚未登录，尝试读取本地 Cookie...")
            login_result = load_cookie_cache()
            if not login_result:
                logger.error("[Qzone] 无有效登录凭证，请管理员发送 /qzone login 扫码登录")
                await handle_cookie_expired("无有效登录凭证")
                return None

        target_qq_str = str(login_result.get("qq", "")).replace("o", "")
        if not target_qq_str:
            logger.error("[Qzone] 登录凭证中缺失 QQ 号")
            return None
        target_qq = int(target_qq_str)

        cookies = login_result.get("cookies", {})
        g_tk = login_result.get("bkn", "")

        content = content or ""
        res = None
        if pic_paths:
            pic_path = pic_paths[0]
            logger.info(f"[Qzone] 正在发送带图说说: {content[:30]}... 配图: {pic_path}")
            res = await qzone._send_zone_with_pic(
                target_qq=target_qq,
                pic_path=pic_path,
                content=content,
                cookies=cookies,
                g_tk=g_tk,
            )
        else:
            logger.info(f"[Qzone] 正在发送纯文字说说: {content[:30]}...")
            cookies_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            res = await qzone._send_zone(
                target_qq=target_qq,
                content=content,
                cookies=cookies_str,
                g_tk=g_tk,
            )

        if check_resp_for_expired(res):
            fresh = await fetch_cookie_from_onebot()
            if fresh:
                logger.info("[Qzone] 发送说说捕获凭证过期，已通过 OneBot 重新刷新凭证并自动重试一次...")
                target_qq = int(str(fresh.get("qq", "")).replace("o", ""))
                cookies = fresh.get("cookies", {})
                g_tk = fresh.get("bkn", "")
                if pic_paths:
                    res = await qzone._send_zone_with_pic(
                        target_qq=target_qq,
                        pic_path=pic_paths[0],
                        content=content,
                        cookies=cookies,
                        g_tk=g_tk,
                    )
                else:
                    cookies_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
                    res = await qzone._send_zone(
                        target_qq=target_qq,
                        content=content,
                        cookies=cookies_str,
                        g_tk=g_tk,
                    )
            if check_resp_for_expired(res):
                await handle_cookie_expired(f"发布动态失败，登录凭证失效({str(res)[:60]})")
        return res
    # ---------------------------------------------------------
    # Stable Diffusion 绘画服务端调用 (针对 SDXL 模型调优)
    # ---------------------------------------------------------
    async def call_sd_generate(prompt: str) -> Optional[str]:
        sd_cfg = config.qq_zone.config.get("sd绘画设置", {})
        base_url = sd_cfg.get("sdUrl", "http://apollodorus.xyz:3530")
        if not base_url:
            base_url = "http://apollodorus.xyz:3530"
        base_url = base_url.rstrip("/")
        txt2img_url = f"{base_url}/sdapi/v1/txt2img"

        steps = int(sd_cfg.get("steps", 28))
        cfg_scale = float(sd_cfg.get("cfg_scale", 4.5))
        width = int(sd_cfg.get("width", 1024))
        height = int(sd_cfg.get("height", 1024))
        sampler_name = sd_cfg.get("sampler_name", "Euler a")
        scheduler = sd_cfg.get("scheduler", "Automatic")
        negative_prompt = (
            "blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, "
            "jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, "
            "multiple views, gigantic breasts, nsfw"
        )

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "batch_size": 1,
            "n_iter": 1,
            "save_images": False,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        apikey = str(sd_cfg.get("apikey", "") or "").strip()
        if apikey:
            headers["Authorization"] = f"Bearer {apikey}"
        timeout_val = int(sd_cfg.get("timeout", 120))

        try:
            logger.info(f"[Qzone SD] 请求生图: {txt2img_url}, prompt: {prompt[:80]}...")
            async with httpx.AsyncClient(timeout=timeout_val, headers=headers, trust_env=False) as client:
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
    # 重做温和低频保活（结合 OneBot 静默刷新与空间状态探测）
    # ---------------------------------------------------------
    async def check_cookie_alive() -> bool:
        nonlocal login_result
        if not login_result:
            await fetch_cookie_from_onebot()
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
            if r and '"code":0' in str(r):
                return True
            logger.warning(f"[Qzone 保活] 探测返回未包含 code:0: {str(r)[:120]}")
            # 探测失效时直接调用 OneBot 刷新一次
            fresh = await fetch_cookie_from_onebot()
            if fresh:
                return True
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

        while True:
            await asyncio.sleep(interval)
            try:
                alive = await check_cookie_alive()
                if alive:
                    logger.info("[Qzone 保活] Cookie 状态有效，空间在线")
                else:
                    logger.warning("[Qzone 保活] 检测到 QQ 空间 Cookie 可能已失效！")
                    await handle_cookie_expired("空间保活探测失效")

                    if cookie_cfg.get("失效时自动重新登陆", False):
                        logger.warning("[Qzone 保活] 配置开启了自动重新登陆，尝试拉起登录二维码...")
                        await login_task_wrapper()
            except Exception as e:
                logger.error(f"[Qzone 保活] 监控循环异常: {e}")
    def get_chara_drawing_rules() -> dict:
        """获取人设卡中的绘图规则"""
        _, chara_text = get_bot_persona_info()
        rules = {
            "base": "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2)",
            "art": "(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
            "outfit": "hair ornament,detached sleeves, hair bow, flower, off shoulder,layered dress, virtual youtuber,lace rim, ornaments sleeves, lolita sleeves,white pantyhose",
            "full_section": ""
        }
        if chara_text:
            m = re.search(r"#\s*.*?(?:视觉与绘图|绘图规则)(.*)", chara_text, re.DOTALL)
            if m:
                section = m.group(1)
                rules["full_section"] = section.strip()
                base_m = re.search(r"1\.\s*基础(?:形象)?设定[^\n]*\n+([^\n#]+)", section)
                if base_m and base_m.group(1).strip():
                    rules["base"] = base_m.group(1).strip()
                art_m = re.search(r"2\.\s*画风与模型设定[^\n]*\n+([^\n#]+)", section)
                if art_m and art_m.group(1).strip():
                    rules["art"] = art_m.group(1).strip()
                outfit_m = re.search(r"3\.\s*默认服装[^\n]*\n+([^\n#]+)", section)
                if outfit_m and outfit_m.group(1).strip():
                    rules["outfit"] = outfit_m.group(1).strip()
        return rules

    def get_chara_visual_anchor() -> str:
        """获取角色基础形象视觉锚点"""
        rules = get_chara_drawing_rules()
        return rules.get("base", "")

    async def build_sd_prompt_for_post(post_text: str, theme_desc: str) -> str:
        bot_name, _ = get_bot_persona_info()
        rules = get_chara_drawing_rules()
        base_anchor = rules.get("base", "")
        art_anchor = rules.get("art", "")
        default_outfit = rules.get("outfit", "")
        full_rules_text = rules.get("full_section", "")

        dynamic_scene_tags = ""
        try:
            if mai_llm:
                prompt_generator = (
                    f"你是一名专业动漫 Stable Diffusion 提示词专家。角色是：{bot_name}。\n"
                    f"根据角色动态文案，仅提取【当前情绪与表情】+【当前动作/场景/日常服装变体】的纯英文 tags。\n"
                    f"角色卡绘图规则参考：\n{full_rules_text if full_rules_text else '日常场景参考: casual clothes, sitting on sofa, cozy room. 视角表情: slight blush, upper body'}\n"
                    f"当前主题建议：{theme_desc}\n"
                    f"当前动态文案：{post_text}\n\n"
                    f"要求：\n"
                    f"1. 绝对不要重复生成发色、发型、眼睛等基础面部特征设定（系统已全局保留）。\n"
                    f"2. 仅输出情绪状态、服饰、动作和场景（如 casual clothes, messy room, sleepy, holding mug 或 loose oversized hoodie, soft smile 等）。\n"
                    f"3. 仅输出纯英文 tags，用逗号分隔，不要解释，不要输出任何中文。"
                )
                sd_tags = await mai_llm.chat(
                    messages=[{"role": "user", "content": prompt_generator}],
                    system_prompt="You are an expert prompt engineer specializing in anime Stable Diffusion tags.",
                )
                if sd_tags:
                    cleaned_tags = sd_tags.strip().replace("\n", ", ")
                    cleaned_tags = cleaned_tags.strip("\"'[] \n\r\t")
                    dynamic_scene_tags = cleaned_tags
        except Exception as e:
            logger.error(f"[Qzone] LLM 提取场景 tags 失败: {e}")

        if not dynamic_scene_tags:
            dynamic_scene_tags = theme_desc

        prompt_elements = []
        # 注入高质量与美学通用标签
        quality_anchor = "rating:general, best quality, very aesthetic, absurdres"
        prompt_elements.append(quality_anchor)

        if base_anchor:
            prompt_elements.append(base_anchor)
        cloth_keywords = ["pajamas", "dress", "clothes", "hoodie", "shirt", "skirt", "jacket", "outfit", "robe", "apron", "sweater", "cardigan"]
        if default_outfit and not any(ck in dynamic_scene_tags.lower() for ck in cloth_keywords):
            prompt_elements.append(default_outfit)
        if dynamic_scene_tags:
            prompt_elements.append(dynamic_scene_tags)
        if art_anchor:
            prompt_elements.append(art_anchor)

        final_prompt = ", ".join([p.strip(", ") for p in prompt_elements if p and p.strip(", ")])
        logger.info(f"[Qzone SD] 组合完成 SD Prompt: {final_prompt}")
        return final_prompt

    # ---------------------------------------------------------
    # 定时早晚发空间任务
    # ---------------------------------------------------------
    async def task_executor(task_name: str, task_info: dict):
        logger.info(f"[Qzone 任务] 开始执行定时发空间任务: {task_name}")
        bot_name, chara_text = get_bot_persona_info()
        festival_or_term = await get_almanac_info()

        current_global_mem = mai_context.get_global_memory() if mai_context else ""

        morning_themes = [
            "厨房早餐微小日常：煎蛋边缘微微焦脆、烤焦的面包片涂草莓果酱、或者冲泡热可可/抹茶牛奶打出绵密奶泡",
            "晨间清爽感官：推开窗户微凉的晨风吹醒额头、窗台绿植叶尖滚动的露珠、空气里清新的早晨味道",
            "出门或梳妆小碎念：在镜子前挑选发夹、和头顶翘起来倔强的呆毛搏斗、或者纠结今天穿哪件柔软的大毛衣",
            "晨光中的片刻放空：坐在窗边捧着热乎乎的马克杯看清晨阳光一点点漫进房间，耳机里单曲循环喜欢的旋律",
            "元气与今日微小期待：今天打算去书店/文具店淘新贴纸、顺路买刚出炉的黄油可颂、或者期待晚上回家追番",
        ]
        night_themes = [
            "白日可爱见闻偶遇：路过花坛时和一只圆滚滚的野猫对视了三秒、面包房门口闻到刚烤好的黄油香、或者下班/放学时看见粉紫色的晚霞",
            "便利店夜游觅食：深夜便利店暖黄色的灯光、买到了最后一串热腾腾的关东煮魔芋丝、或者挑了期间限定的布丁",
            "少女桌面手账与心爱之物：窝在暖光台灯下拆盲盒开到了隐藏款、在手账本上贴满亮晶晶的贴纸和随笔涂鸦",
            "真实可爱的小牢骚与小心情：小脚趾不小心踢到桌脚委屈哼唧、手机快没电了趴在床边充着电看、感叹时间过得太快今天还有想玩的事情",
            "深夜神游与心满意足：抱着心爱的大抱枕坐在地毯上发呆神游、房间里点着淡淡的香薰、安安静静享受只属于自己的放松时光",
        ]

        if task_name == "早安":
            selected_theme = random.choice(morning_themes)
            sd_theme_hint = "morning, sunrise, soft sunlight, holding warm mug, kitchen or window, casual cozy clothes, cute expression"
        else:
            selected_theme = random.choice(night_themes)
            sd_theme_hint = "night, warm ambient light, cozy room, relaxed sitting posture, desk or armchair, cute gentle expression"

        fest_tip = f"（今天是{festival_or_term}，如有兴趣可轻描淡写提一句）" if festival_or_term else ""

        sys_prompt = (
            f"你是{bot_name}。\n"
            f"你的人设信息如下：\n{chara_text}\n\n"
            f"你现在要发一条 QQ 空间动态（{task_name}的说说）。\n"
            f"风格完全参考 Twitter/X 真实可爱的生活系 Vtuber（参考 @moonjelly0、@jellyhoshiumi 的生活碎念与手账日记感）：\n"
            f"【核心禁令】：严格杜绝千篇一律的“被窝好软”、“被子封印我”、“赖床”、“钻进被窝”这种套话！\n"
            f"【本次微小灵感切入点】：{selected_theme}。{fest_tip}\n"
            f"1. 极简、微小生活碎片感、少女心情日记，像真人女孩子随手敲出来的生活小确幸或真实日常。\n"
            f"2. 口气自然灵动，带一点女孩子的真实俏皮与微小心情，可以偶尔带一两个波浪号~或可爱标点，杜绝AI总结腔。\n"
            f"3. 严格限制字数在 15 ~ 45 字之间，点到即止，短小精炼。\n"
            f"4. 直接输出说说正文，严禁携带任何多余解释、引号或格式。"
        )

        user_prompt = f"请写一条你的{task_name}说说。"
        if current_global_mem:
            user_prompt += f" 你最近的生活碎片记录（可自然呼应）：\n{current_global_mem}"

        post_content = ""
        try:
            if mai_llm:
                resp = await mai_llm.chat(
                    messages=[{"role": "user", "content": user_prompt}],
                    system_prompt=sys_prompt,
                )
                post_content = resp.strip() if resp else ""
                post_content = post_content.strip("\"'[] \n\r\t")
        except Exception as e:
            logger.error(f"[Qzone] LLM 生成说说文案异常: {e}")

        if not post_content:
            post_content = f"{task_name}！窗台上的阳光刚刚好，今天也要打起精神呀~" if task_name == "早安" else f"{task_name}！深夜的便利店热牛奶好治愈，大家也都早点休息做个好梦呀~"

        logger.info(f"[Qzone] 生成说说内容: {post_content}")

        # 提炼极简日常存入全局记忆（严格限制在25字以内，杜绝冗余污染）
        if mai_context and mai_llm:
            try:
                mem_prompt = (
                    f"根据这条Bot动态内容，提炼成一句话极简日常事实（严格在25字以内，杜绝'今天也'等套话，客观记录少女日常行为，如'烤吐司涂果酱吃了美味早餐'或'下班路上偶遇可爱的胖橘猫'），若无实质日常则回复空：\n"
                    f"动态：{post_content}\n"
                    f"只输出提炼后的极简短句：\n"
                )
                refined_mem = await mai_llm.chat(
                    messages=[{"role": "user", "content": mem_prompt}],
                    system_prompt="你是一个极简日常信息提炼助手。",
                )
                if refined_mem and len(refined_mem.strip()) > 0:
                    clean_mem = refined_mem.strip().replace("\n", " ")[:30]
                    clean_mem = clean_mem.strip("\"'[] \n\r\t")
                    mai_context.update_global_memory(f"[{datetime.datetime.now().strftime('%m-%d %H:%M')}] {clean_mem}")
                    logger.info(f"[Qzone 全局记忆] 录入极简日常: {clean_mem}")
            except Exception as e:
                logger.error(f"[Qzone] 记忆更新异常: {e}")

        # 判断是否需要 SD 绘图
        pic_paths = []
        if task_info.get("绘制图片", True):
            theme_desc = sd_theme_hint
            sd_prompt = await build_sd_prompt_for_post(post_content, theme_desc)
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
    # Vtuber 风格活人感日常互动动态机制
    # ---------------------------------------------------------
    vtuber_post_count_today = 0
    vtuber_last_post_date = datetime.date.today()

    async def vtuber_daily_task():
        nonlocal vtuber_post_count_today, vtuber_last_post_date
        today = datetime.date.today()
        if today != vtuber_last_post_date:
            vtuber_last_post_date = today
            vtuber_post_count_today = 0

        vcfg = config.qq_zone.config.get("vtuber日常互动", {})
        if not vcfg.get("enable", True):
            return

        max_daily = int(vcfg.get("每日最大发送次数", 3))
        if vtuber_post_count_today >= max_daily:
            return

        # 检查时间段
        active_hours = vcfg.get("活跃时间段", "10-21")
        try:
            h_start, h_end = [int(x.strip()) for x in str(active_hours).split("-")]
        except Exception:
            h_start, h_end = 10, 21
        cur_hour = datetime.datetime.now().hour
        if not (h_start <= cur_hour <= h_end):
            return

        # 触发概率判断
        prob = float(vcfg.get("触发概率", 0.35))
        if random.random() > prob:
            logger.debug(f"[Qzone Vtuber日常] 巡检未命中触发概率({prob})")
            return

        logger.info("[Qzone Vtuber日常] 触发条件满足，开始生成日常动态...")
        bot_name, chara_text = get_bot_persona_info()
        current_global_mem = mai_context.get_global_memory() if mai_context else ""

        # 提取群聊近期有趣片段或灵感 (兼容 ctx:gwin:* 数据格式)
        group_snippet = ""
        if mai_context:
            try:
                gkeys = mai_context._ctx_keys("group_window:*") or mai_context._ctx_keys("ctx:gwin:*")
                if gkeys:
                    chosen_key = random.choice(gkeys)
                    raw = mai_context._ctx_get(chosen_key)
                    if raw:
                        w_list = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(w_list, list) and w_list:
                            lines = []
                            for it in w_list[-4:]:
                                s_name = it.get("sender", {}).get("card") or it.get("sender", {}).get("nickname") or it.get("sender", "群友")
                                text_msg = it.get("raw_message") or it.get("text", "")
                                if text_msg and len(text_msg) < 60:
                                    lines.append(f"{s_name}: {text_msg}")
                            if lines:
                                group_snippet = "\n".join(lines)
            except Exception as e:
                logger.debug(f"[Qzone Vtuber日常] 提取群聊灵感异常: {e}")

        styles = [
            "抛出一个简短可爱/无厘头的日常提问（比如询问大家在喝什么奶茶/今天天气如何）",
            "分享一个生活中呆呆的、可爱的小瞬间/刚刚发生的趣事",
            "单纯轻度无厘头地卖个萌、撒个娇或抒发一句此刻的小情绪",
            "吐槽一句天气、困意或想要偷懒的小心思",
        ]
        chosen_style = random.choice(styles)

        sys_vtuber_prompt = (
            f"你是{bot_name}。\n"
            f"人设：\n{chara_text}\n\n"
            f"你现在要在自己的社交主页/QQ空间发一条简短动态。\n"
            f"风格完全参考 Twitter/X 真实可爱的生活系 Vtuber（如 @moonjelly0、@jellyhoshiumi）：\n"
            f"本次动态风格偏向：【{chosen_style}】。\n"
            f"要求：\n"
            f"1. 像真人女孩随手敲出来的文字，严禁AI翻译腔、严禁报幕式套话。\n"
            f"2. 保持真实呼吸感，偶尔用一两个波浪号或日常标点，不要堆砌废话。\n"
            f"3. 严格限制字数在 15 ~ 45 字之间，短小自然，点到即止。\n"
            f"4. 直接输出动态正文，不要包含任何多余文字或引号。"
        )
        user_vtuber_prompt = "请发一条日常动态。"
        if group_snippet:
            user_vtuber_prompt += f"\n刚才群里大家聊到这些：\n{group_snippet}\n可以顺着其中某个有趣话题随手吐槽或发问，也可以自说自话。"
        elif current_global_mem:
            user_vtuber_prompt += f"\n你最近的日常片段：{current_global_mem}"

        daily_content = ""
        try:
            if mai_llm:
                resp = await mai_llm.chat(
                    messages=[{"role": "user", "content": user_vtuber_prompt}],
                    system_prompt=sys_vtuber_prompt,
                )
                daily_content = resp.strip() if resp else ""
                daily_content = daily_content.strip("\"'[] \n\r\t")
        except Exception as e:
            logger.error(f"[Qzone Vtuber日常] 生成动态失败: {e}")

        if not daily_content:
            daily_content = "今天也是慢吞吞晃过去的一天，大家都在干嘛呢？~"

        logger.info(f"[Qzone Vtuber日常] 生成内容: {daily_content}")

        # 概率配图
        pic_paths = []
        pic_prob = float(vcfg.get("绘制图片概率", 0.5))
        if random.random() < pic_prob:
            sd_prompt = await build_sd_prompt_for_post(daily_content, "casual daily, relaxed posture, cute expression, high quality")
            img_file = await call_sd_generate(sd_prompt)
            if img_file:
                pic_paths.append(img_file)

        # 发送说说
        try:
            res = await send_to_qzone(daily_content, pic_paths)
            logger.info(f"[Qzone Vtuber日常] 发布动态完成: {res}")
            vtuber_post_count_today += 1
        except Exception as e:
            logger.error(f"[Qzone Vtuber日常] 发送异常: {e}")

    async def start_vtuber_daily_monitor():
        vcfg = config.qq_zone.config.get("vtuber日常互动", {})
        if not vcfg.get("enable", True):
            return
        interval_min = max(10, int(vcfg.get("巡检间隔_分钟", 60)))
        logger.info(f"[Qzone Vtuber日常] 启动日常巡检监控，轮询间隔: {interval_min} 分钟")
        while True:
            await asyncio.sleep(interval_min * 60)
            try:
                await vtuber_daily_task()
            except Exception as e:
                logger.error(f"[Qzone Vtuber日常] 巡检异常: {e}")
    # ---------------------------------------------------------
    # 空间好友评论自动拟人化互动回复
    # ---------------------------------------------------------
    def is_comment_too_old(comment: dict, max_hours: int = 24) -> bool:
        """判断评论是否超过指定小时数（默认24小时前），超过则跳过不回复"""
        import time
        from datetime import datetime
        now = time.time()
        max_seconds = max_hours * 3600

        raw_ts = comment.get("create_time") or comment.get("createTime") or comment.get("time")
        if raw_ts:
            try:
                ts = float(raw_ts)
                if ts > 1e11:
                    ts /= 1000.0
                if (now - ts) > max_seconds:
                    return True
                if (now - ts) >= 0:
                    return False
            except Exception:
                pass

        time_str = str(comment.get("createTime2", "")).strip()
        if time_str:
            if any(k in time_str for k in ["前天", "天前", "月前", "年前"]):
                return True
            now_year = datetime.now().year
            for y in range(2000, now_year):
                if str(y) in time_str:
                    return True
            try:
                now_dt = datetime.now()
                parts = time_str.split("-")
                if len(parts) == 3:
                    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                    if (now_dt - dt).total_seconds() > max_seconds:
                        return True
                elif len(parts) == 2:
                    dt = datetime.strptime(f"{now_year}-{time_str}", "%Y-%m-%d %H:%M")
                    if (now_dt - dt).total_seconds() > max_seconds:
                        return True
            except Exception:
                pass

        return False

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
            l = list(s)[-2000:]
            replied_comments_file.write_text(json.dumps(l, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[Qzone] 保存评论回复缓存失败: {e}")

    replied_comment_ids = load_replied_comments()

    async def check_and_reply_comments():
        nonlocal login_result, replied_comment_ids
        if not login_result:
            await fetch_cookie_from_onebot()
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
            if check_resp_for_expired(resp_str):
                await handle_cookie_expired(f"评论巡检拉取说说失败，Cookie已失效({str(resp_str)[:60]})")
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
                cid = str(c.get("tid") or c.get("id") or "").strip()
                comment_uid = c.get("uin", 0)
                comment_name = c.get("name", "空间好友")
                comment_content = (c.get("content", "") or "").strip()

                # 排除自己发布的评论和已经回复过的评论
                if int(comment_uid) == target_qq:
                    continue
                unique_key = f"{tid}_{cid}"
                if unique_key in replied_comment_ids:
                    continue

                # 过滤超过24小时的古早评论，直接记录已处理，避免反复打扰
                if is_comment_too_old(c, max_hours=24):
                    logger.debug(f"[Qzone 评论互动] 评论时间超过24小时(古早评论)，自动跳过: {comment_name} -> {comment_content[:20]}")
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                    continue

                # 过滤语音消息或空消息，避免对非文字内容回复
                if not comment_content or comment_content in ["［语音］", "[语音]", "[图片]", "［图片］"]:
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                    continue

                logger.info(f"[Qzone 评论互动] 发现新评论 来自: {comment_name}({comment_uid}) -> {comment_content}")

                # 获取用户在 mai_reply 的对话历史与用户印象
                user_impression = ""
                recent_chat_snippet = ""
                if mai_context:
                    try:
                        user_impression = mai_context.get_impression(int(comment_uid))
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
                    f"要求与人际分寸感规范：\n"
                    f"1. 结合你的说说主题和对方的评论，自然、亲切地像在空间好友动态下互动一样进行回复。\n"
                    f"2. 【重要分寸感约束】：当前处于所有人可见的公开动态评论区！绝对不要表现得过度亲密、过度撒娇、暧昧或调情（不要叫'老公'、'宝贝'、'主人'或做亲昵身体接触描写等），以免其他用户吃醋或显得你到处和人调情！\n"
                    f"3. 保持健康、自然、元气可爱的朋友/Vtuber博主互动边界感，风趣机智地回应或友善吐槽即可。\n"
                    f"4. 若有对他的印象或聊天经历，自然流露熟络感，不要刻意背诵。\n"
                    f"5. 长度严格控制在 15~50 字以内，轻松口语化，绝对不要包含任何系统标记或多余引号，不要自己在回复开头写@谁（系统会自动添加标准艾特标签）。"
                )

                reply_text = ""
                try:
                    if mai_llm:
                        res = await mai_llm.chat(
                            messages=[{"role": "user", "content": f"{comment_name} 评论了你的说说：\"{comment_content}\"，请回复他："}],
                            system_prompt=sys_reply_prompt,
                        )
                        reply_text = res.strip() if res else ""
                        reply_text = reply_text.strip("\"'[] \n\r\t")
                except Exception as e:
                    logger.error(f"[Qzone] 生成评论回复失败: {e}")

                if not reply_text:
                    reply_text = f"谢谢{comment_name}的评论！记得天天开心哦~"

                # 发送空间评论回复 (传递 comment_id 确保楼中楼准确回复)
                try:
                    logger.info(f"[Qzone 评论回复] 正在回复 {comment_name}: {reply_text}")
                    res = await qzone._send_comments(
                        target_qq=target_qq,
                        uin=int(comment_uid),
                        content=reply_text,
                        cookies=cookies_str,
                        g_tk=g_tk,
                        fid=tid,
                        comment_id=str(cid) if cid else None,
                        comment_name=comment_name
                    )
                    logger.info(f"[Qzone 评论回复结果]: {res}")
                    if check_resp_for_expired(res):
                        await handle_cookie_expired(f"回复评论失败，Cookie已失效({str(res)[:60]})")
                        return

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

        # 启动时先拉取一次 OneBot 凭据
        try:
            await fetch_cookie_from_onebot()
        except Exception as e:
            logger.warning(f"[Qzone] 启动同步 OneBot 凭证提示: {e}")

        create_dynamic_jobs()
        scheduler.start()
        logger.info("[Qzone] 定时发空间调度器已启动")

        asyncio.create_task(start_keepalive_monitor())
        asyncio.create_task(start_comment_monitor())
        asyncio.create_task(start_vtuber_daily_monitor())

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
            cookie_invalid_notified = False
            await set_cache(event)
        elif event.pure_text in ["测试早安", "发送早安"] and is_master:
            await bot.send(event, [Text("正在测试发送早安说说...")])
            task_info = scheduledTasks.get("早安", {"绘制图片": True})
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = scheduledTasks.get("晚安", {"绘制图片": True})
            await task_executor("晚安", task_info)
        elif event.pure_text in ["测试日常", "发送日常"] and is_master:
            await bot.send(event, [Text("正在测试生成并发送Vtuber风格日常互动说说...")])
            await vtuber_daily_task()
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
            cookie_invalid_notified = False
            await set_cache(event)
        elif event.pure_text in ["测试早安", "发送早安"] and is_master:
            await bot.send(event, [Text("正在测试发送早安说说...")])
            task_info = scheduledTasks.get("早安", {"绘制图片": True})
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = scheduledTasks.get("晚安", {"绘制图片": True})
            await task_executor("晚安", task_info)
        elif event.pure_text in ["测试日常", "发送日常"] and is_master:
            await bot.send(event, [Text("正在测试生成并发送Vtuber风格日常互动说说...")])
            await vtuber_daily_task()
        elif event.pure_text == "测试空间互动" and is_master:
            await bot.send(event, [Text("正在立即检查空间评论并回复...")])
            await check_and_reply_comments()