# -*- coding: utf-8 -*-
import asyncio
import sys
import base64
import datetime
import json
import random
import re
from run.wardrobe.qzone_outfits import select_post_outfit, render_post_outfit, select_post_theme, commit_post_outfit, post_scene_instruction
import traceback
import uuid
from asyncio import sleep
from pathlib import Path
from typing import Optional, Dict, Any

import aiohttp
import httpx
from framework_common.schedule_service import DynamicScheduler, get_scheduler, TimezoneHelper

from run.qq_zone.service.native_login import NativeQzoneLogin
try:
    from run.qq_zone import qzone_themes
except ImportError:
    import qzone_themes

try:
    from run.qq_zone.chinese_calendar_helper import get_chinese_calendar_info, get_season_info, get_season_name
except ImportError:
    from chinese_calendar_helper import get_chinese_calendar_info, get_season_info, get_season_name

from developTools.event.events import LifecycleMetaEvent, GroupMessageEvent, PrivateMessageEvent
try:
    from run.wardrobe import get_wardrobe_manager
except Exception:
    get_wardrobe_manager = None
from developTools.message.message_components import Text, Image, Mface

from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.utils import get_img, download_img
from run.qq_zone.service.QzoneApiFixed import QzoneApiFixed

FIXED_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, normal "
    "quality, jpeg artifacts, signature, watermark, username, blurry"
)


def calc_bkn(p_skey: str) -> int:
    hash_val = 5381
    for c in str(p_skey):
        hash_val += (hash_val << 5) + ord(c)
    return hash_val & 0x7FFFFFFF


# -------------------------------------------------------------
# 跨热重载全局单例生命周期与运行态管理
# -------------------------------------------------------------
_GLOBAL_QZONE_INSTANCE = None


def _get_runtime_state() -> dict:
    """获取进程级单例运行时状态字典，热重载或跨模块调用时共享"""
    if not hasattr(sys, "_qzone_runtime_state") or not isinstance(sys._qzone_runtime_state, dict):
        sys._qzone_runtime_state = {
            "active_instance": None,
            "bg_started": False,
            "in_progress_comments": set(),
            "replied_comment_ids_cache": None,
            "task_history_cache": None,
            "send_lock": None,
            "comment_reply_lock": None,
            "bg_start_lock": None,
            "bot_loop": None,
        }
    return sys._qzone_runtime_state


def _get_lock(lock_key: str) -> asyncio.Lock:
    """获取或初始化绑定在当前运行事件循环上的共享异步锁"""
    state = _get_runtime_state()
    lock = state.get(lock_key)
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = state.get("bot_loop")

    if lock is None:
        lock = asyncio.Lock()
        state[lock_key] = lock
    else:
        lock_loop = getattr(lock, "_loop", None)
        if lock_loop is not None and lock_loop.is_closed():
            lock = asyncio.Lock()
            state[lock_key] = lock
        elif lock_loop is not None and current_loop is not None and lock_loop is not current_loop:
            lock = asyncio.Lock()
            state[lock_key] = lock
    return lock


class QzoneLifecycleManager:
    """QQ空间后台任务与调度器生命周期管理器"""

    def __init__(self, bot_loop=None, logger=None):
        self.bot_loop = bot_loop
        self.logger = logger
        self.scheduler = None
        self.background_tasks: list = []
        self.last_scheduled_execution: dict = {}
        self.stopped = False

    @property
    def send_lock(self) -> asyncio.Lock:
        return _get_lock("send_lock")

    @property
    def comment_reply_lock(self) -> asyncio.Lock:
        return _get_lock("comment_reply_lock")

    @property
    def in_progress_comments(self) -> set:
        return _get_runtime_state()["in_progress_comments"]

    async def stop(self):
        if self.stopped:
            return
        self.stopped = True
        log = self.logger
        if log:
            log.info("[Qzone 生命周期] 开始停止旧实例后台服务...")
        else:
            print("[Qzone 生命周期] 开始停止旧实例后台服务...")

        if self.scheduler:
            try:
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)
                    if log:
                        log.info("[Qzone 生命周期] 旧调度器已停止")
            except Exception as e:
                if log:
                    log.warning(f"[Qzone 生命周期] 停止旧调度器异常: {e}")

        tasks_to_cancel = list(self.background_tasks)
        self.background_tasks.clear()
        for t in tasks_to_cancel:
            try:
                if not t.done():
                    t.cancel()
            except Exception:
                pass
        if tasks_to_cancel:
            try:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            except Exception:
                pass

        # 同步更新全局运行标记
        state = _get_runtime_state()
        if state.get("active_instance") is self:
            state["active_instance"] = None
            state["bg_started"] = False

        if log:
            log.info("[Qzone 生命周期] 旧后台监控协程已全部取消")

    def stop_threadsafe(self):
        """跨线程安全同步停止（应对 PluginManager 线程池中执行 main 时旧实例的清理）"""
        if self.stopped:
            return

        # 1. 尝试直接停掉 scheduler
        if self.scheduler:
            try:
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)
            except Exception as e:
                print(f"[Qzone 生命周期] 跨线程停止旧调度器异常: {e}")

        # 2. 取消旧协程任务
        loop = self.bot_loop
        if not loop or loop.is_closed():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

        if loop and loop.is_running():
            try:
                try:
                    current_running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_running_loop = None

                if current_running_loop is loop:
                    for t in list(self.background_tasks):
                        try:
                            if not t.done():
                                t.cancel()
                        except Exception:
                            pass
                    self.background_tasks.clear()
                    self.stopped = True
                else:
                    fut = asyncio.run_coroutine_threadsafe(self.stop(), loop)
                    fut.result(timeout=5)
            except Exception as e:
                print(f"[Qzone 生命周期] 跨线程调度 stop() 异常: {e}")
                for t in list(self.background_tasks):
                    try:
                        if not t.done():
                            loop.call_soon_threadsafe(t.cancel)
                    except Exception:
                        pass
                self.stopped = True
        else:
            for t in list(self.background_tasks):
                try:
                    if not t.done():
                        t.cancel()
                except Exception:
                    pass
            self.background_tasks.clear()
            self.stopped = True

        state = _get_runtime_state()
        if state.get("active_instance") is self:
            state["active_instance"] = None
            state["bg_started"] = False


async def plugin_cleanup():
    """供框架 unload_plugin 或热重载前调用的清理钩子"""
    global _GLOBAL_QZONE_INSTANCE
    runtime_state = _get_runtime_state()
    active_inst = runtime_state.get("active_instance") or _GLOBAL_QZONE_INSTANCE
    if active_inst:
        try:
            await active_inst.stop()
        except Exception as e:
            print(f"[Qzone] plugin_cleanup 清理异常: {e}")
    runtime_state["active_instance"] = None
    runtime_state["bg_started"] = False
    in_prog = runtime_state.get("in_progress_comments")
    if isinstance(in_prog, set):
        in_prog.clear()
    _GLOBAL_QZONE_INSTANCE = None


def main(bot: ExtendBot, config: YAMLManager):
    logger = bot.logger
    qzone_login = NativeQzoneLogin()
    login_result = None
    login_task = None
    qzone = QzoneApiFixed()
    qzone_status = False
    cookie_invalid_notified = False

    # ---------------------------------------------------------
    # 模块实例与后台任务生命周期控制器
    # ---------------------------------------------------------
    global _GLOBAL_QZONE_INSTANCE

    bot_loop = getattr(bot, "loop", None)
    if bot_loop is None:
        try:
            bot_loop = asyncio.get_running_loop()
        except RuntimeError:
            bot_loop = None

    runtime_state = _get_runtime_state()
    runtime_state["bot_loop"] = bot_loop

    # 若之前已有实例存活（例如非标准卸载场景），先优雅停止
    old_instance = runtime_state.get("active_instance") or _GLOBAL_QZONE_INSTANCE
    if old_instance:
        try:
            logger.warning("[Qzone] 检测到已存在运行中的旧 Qzone 实例，正在接管并停止旧任务...")
            old_instance.stop_threadsafe()
        except Exception as e:
            logger.warning(f"[Qzone] 停止旧实例异常: {e}")

    current_instance = QzoneLifecycleManager(bot_loop=bot_loop, logger=logger)
    runtime_state["active_instance"] = current_instance
    _GLOBAL_QZONE_INSTANCE = current_instance

    # ---------------------------------------------------------
    # 尝试加载 core_reply 的 ContextManager 和 LLMClient
    # ---------------------------------------------------------
    mai_context = None
    mai_llm = None
    try:
        from run.core_reply.service.llm_client import LLMClient
        mai_llm = LLMClient(config)
        logger.info("[Qzone] 成功连接已配置的 LLMClient")
    except Exception as e:
        logger.warning(f"[Qzone] 加载 LLMClient 失败: {e}")
    try:
        from run.core_reply.service.context_manager import ContextManager
        mai_context = ContextManager(config)
    except Exception as e:
        logger.warning(f"[Qzone] 加载记忆管理失败: {e}")

    # ---------------------------------------------------------
    # 本地 Cookie 缓存管理与 OneBot 接口无感免密获取
    # ---------------------------------------------------------
    base_data_dir = Path(__file__).resolve().parent / "data"
    base_data_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = base_data_dir / "qzone_cookie.json"
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
        send_lock = _get_lock("send_lock")
        async with send_lock:
            return await _send_to_qzone_locked(content, pic_paths)

    async def _send_to_qzone_locked(content: Optional[str] = None, pic_paths: Optional[list] = None):
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
        if not prompt:
            return None
        sd_cfg = config.qq_zone.config.get("sd绘画设置", {})
        base_url = sd_cfg.get("sdUrl", "http://api.apollodorus.xyz")
        if not base_url:
            base_url = "http://api.apollodorus.xyz"
        base_url = base_url.rstrip("/")
        txt2img_url = f"{base_url}/sdapi/v1/txt2img"

        steps = int(sd_cfg.get("steps", 28))
        cfg_scale = float(sd_cfg.get("cfg_scale", 4.5))
        width = int(sd_cfg.get("width", 1024))
        height = int(sd_cfg.get("height", 1024))
        sampler_name = sd_cfg.get("sampler_name", "Euler a")
        scheduler = sd_cfg.get("scheduler", "Automatic")

        payload = {
            "prompt": prompt,
            "negative_prompt": FIXED_NEGATIVE_PROMPT,
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

        # 重试机制：支持配置重试次数与间隔延迟（支持 retry_delay_seconds / retry_delay_minutes / retry_delay，默认10分钟即600秒）
        max_retries = int(sd_cfg.get("max_retries", 3))
        if "retry_delay_seconds" in sd_cfg:
            retry_delay = float(sd_cfg.get("retry_delay_seconds", 600))
        elif "retry_delay_minutes" in sd_cfg:
            retry_delay = float(sd_cfg.get("retry_delay_minutes", 10)) * 60.0
        elif "retry_delay" in sd_cfg:
            retry_delay = float(sd_cfg.get("retry_delay", 600))
        else:
            retry_delay = 600.0  # 默认 10 分钟 (600秒)
        total_attempts = 1 + max(0, max_retries)

        for attempt in range(1, total_attempts + 1):
            attempt_str = f"[{attempt}/{total_attempts}]" if total_attempts > 1 else ""
            err_msg = ""
            try:
                logger.info(f"[Qzone SD] 请求生图 {attempt_str}: {txt2img_url}, prompt: {prompt[:80]}...")
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
                        else:
                            err_msg = "响应中未包含图片数据 (images 列表为空)"
                    else:
                        err_msg = f"接口状态码异常: {resp.status_code}, 内容: {resp.text[:120]}"
            except Exception as e:
                err_msg = f"网络请求异常: {e}"

            if attempt < total_attempts:
                logger.warning(
                    f"[Qzone SD] 第 {attempt}/{total_attempts} 次生图失败 ({err_msg})，"
                    f"将在 {retry_delay}s 后进行第 {attempt + 1} 次重试..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"[Qzone SD] 生图已重试 {max_retries} 次仍未成功，最终放弃: {err_msg}")

        return None

    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # 中国节假日与二十四节气辅助方法（纯本地离线高精度计算）
    # ---------------------------------------------------------
    async def get_almanac_info() -> Optional[str]:
        """
        获取中国节假日与节气信息（纯本地离线高精度计算，无需脆弱外部接口）
        支持农历传统节日（除夕、春节、元宵、端午、中秋等）、二十四节气天文视黄经计算、公历重要节日。
        """
        try:
            today = datetime.date.today()
            info = get_chinese_calendar_info(today)
            if info:
                logger.info(f"[Qzone 日历] 今日命中节日/节气: {info}")
            return info
        except Exception as e:
            logger.warning(f"[Qzone 日历] 节假日计算异常: {e}")
            return None

    def get_current_season() -> dict:
        """
        获取当前季节与时令信息（纯本地离线高精度计算）
        包含季节、当前亚季（初/仲/暮/隆）、气候特征描述等
        """
        try:
            today = datetime.date.today()
            return get_season_info(today)
        except Exception as e:
            logger.warning(f"[Qzone 日历] 季节时令计算异常: {e}")
            return {
                "season": "四季",
                "sub_season": "",
                "full_name": "当前时令",
                "description": "",
                "solar_longitude": 0.0
            }

    def get_bot_persona_info() -> tuple[str, str]:
        bot_name = config.common_config.basic_config.get("bot", "小助手")
        chara_text = ""
        try:
            pcfg = config.core_reply.config.get("persona", {})
            chara_file_name = pcfg.get("chara_file", "").strip()
            if not chara_file_name:
                chara_cfg = config.core_reply.config.get("chara", {})
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

    # [已重构接入 DynamicScheduler] 原 start_keepalive_monitor 由调度器统一按间隔驱动，此处保留空定义兼容历史调用
    async def start_keepalive_monitor():
        pass
    def get_chara_drawing_rules() -> dict:
        """从 run/qq_zone/config.yaml 读取用户配置的角色绘图规则与外观设定，留空时使用默认形象提示词"""
        default_base = "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2)"
        default_art = "(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>"
        default_outfit = "hair ornament,detached sleeves, hair bow, flower, off shoulder,layered dress, virtual youtuber,lace rim, ornaments sleeves, lolita sleeves,white pantyhose"

        chara_draw_cfg = config.qq_zone.config.get("角色绘图设置", {})
        base_prompt = str(chara_draw_cfg.get("基础形象设定", "") or "").strip() or default_base
        art_prompt = str(chara_draw_cfg.get("画风与模型设定", "") or "").strip() or default_art
        outfit_prompt = str(chara_draw_cfg.get("默认服装设定", "") or "").strip() or default_outfit

        # 组合成说明段落，供 LLM 提取场景变体 tags 时参考
        full_section = (
            f"基础形象: {base_prompt}\n"
            f"画风模型: {art_prompt}\n"
            f"默认服装参考: {outfit_prompt}（注：仅作为外出标准装束参考，非固定常驻饰品；室内/睡衣场景不戴帽子）"
        )

        return {
            "base": base_prompt,
            "art": art_prompt,
            "outfit": outfit_prompt,
            "negative": FIXED_NEGATIVE_PROMPT,
            "full_section": full_section
        }

    def get_chara_visual_anchor() -> str:
        """获取角色基础形象视觉锚点"""
        rules = get_chara_drawing_rules()
        return rules.get("base", "")

    async def build_sd_prompt_for_post(post_text: str, theme_desc: str, selection=None, task_name="日常") -> str:
        rules = get_chara_drawing_rules()
        manager = get_wardrobe_manager() if get_wardrobe_manager else None
        if manager and not manager.is_enabled():
            manager = None
        try:
            chosen = await select_post_outfit(
                manager, mai_llm, post_text, theme_desc,
                get_current_season().get("full_name", ""), task_name=task_name,
                character_anchor=rules.get("base", ""), art_anchor=rules.get("art", ""))
            chosen = await render_post_outfit(mai_llm, chosen, post_text, theme_desc, task_name=task_name)
        except Exception as exc:
            logger.warning(f"[Qzone SD] LLM穿搭决策失败，跳过本次配图: {exc}")
            return ""
        base_anchor = (manager.get_character_anchor() if manager else "") or rules.get("base", "")
        art_anchor = (manager.get_art_anchor() if manager else "") or rules.get("art", "")
        outfit = chosen["clothing_tags"]
        background = chosen["scene_tags"]
        native_hint = chosen["native_hint_tags"]
        native_hint = f"({native_hint}:1.2)" if native_hint else ""
        prompt = ", ".join(value.strip(", ") for value in (
            "rating:general, best quality, very aesthetic, absurdres",
            base_anchor, outfit, native_hint, background, art_anchor) if value and value.strip(", "))
        if selection is not None:
            selection.update(chosen, clothing_tags=outfit)
        logger.info(f"[Qzone SD] LLM最终穿搭: {chosen['name']}, style={chosen['design_seeds']['style']['id']}, palette={chosen['design_seeds']['palette']['id']} (no_hat={chosen['no_hat']})")
        return prompt

    # ---------------------------------------------------------
    # 动态历史与去重记忆管理（防题材重复、强化时间流动感）
    # ---------------------------------------------------------
    post_history_file = base_data_dir / "qzone_post_history.json"
    post_history_file.parent.mkdir(parents=True, exist_ok=True)

    def load_post_history() -> list:
        if post_history_file.exists():
            try:
                data = json.loads(post_history_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception as e:
                logger.error(f"[Qzone] 读取动态历史记录失败: {e}")
        return []

    def record_post_history(entry: dict):
        try:
            history = load_post_history()
            history.append(entry)
            history = history[-30:]
            post_history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[Qzone] 记录动态历史失败: {e}")

    def get_recent_history_constraints(task_type: str, limit: int = 5) -> tuple[set, list, list]:
        history = load_post_history()
        recent = [h for h in history if h.get("type") == task_type][-limit:]
        used_theme_ids = {h.get("theme_id") for h in recent if h.get("theme_id")}
        recent_elements = []
        for h in recent:
            recent_elements.extend(h.get("elements", []))
        recent_posts = [h.get("content", "") for h in recent if h.get("content")]
        return used_theme_ids, list(dict.fromkeys(recent_elements)), recent_posts

    def get_current_time_context() -> str:
        now = TimezoneHelper.get_user_local_time('Asia/Shanghai')
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_str = weekday_names[now.weekday()]
        season_meta = get_current_season()
        season_full = season_meta.get("full_name", "当季")
        hour = now.hour
        if 5 <= hour < 9:
            period_str = "清晨刚起不久"
        elif 9 <= hour < 12:
            period_str = "上午工作/学习或清闲时光"
        elif 12 <= hour < 14:
            period_str = "中午午休或用餐时分"
        elif 14 <= hour < 18:
            period_str = "下午茶或慢节奏时光"
        elif 18 <= hour < 22:
            period_str = "傍晚回家/夜幕初降"
        elif 22 <= hour or hour < 2:
            period_str = "深夜准备洗漱休息时分"
        else:
            period_str = "凌晨夜深人静夜猫子时段"
        return f"{now.strftime('%Y年%m月%d日')} {weekday_str} {now.strftime('%H:%M')}（当前时令：{season_full}，时段：{period_str}）"

    # 接入丰富主题库（超 120 种精心设计的场景与日常少女心情）
    morning_theme_pool = getattr(qzone_themes, 'MORNING_THEME_POOL', [])
    night_theme_pool = getattr(qzone_themes, 'NIGHT_THEME_POOL', [])
    daily_theme_pool = getattr(qzone_themes, 'DAILY_VTUBER_THEMES', [])
    theme_mutation_directives = getattr(qzone_themes, 'THEME_MUTATION_DIRECTIVES', [])
    post_archetypes = getattr(qzone_themes, 'POST_STRUCTURE_ARCHETYPES', [])

    async def pick_next_theme(task_name: str) -> dict:
        if task_name == "早安":
            pools = [morning_theme_pool]
        elif task_name == "晚安":
            bedroom_pool = getattr(qzone_themes, 'NIGHT_BEDROOM_THEMES', [])
            bedroom_weight = getattr(qzone_themes, 'NIGHT_BEDROOM_PROBABILITY', 0.40)
            pools = [bedroom_pool if bedroom_pool and random.random() < bedroom_weight else night_theme_pool]
        else:
            # Offer every time-of-day source; the LLM uses the actual clock context.
            pools = [daily_theme_pool, morning_theme_pool,
                     night_theme_pool + getattr(qzone_themes, 'NIGHT_BEDROOM_THEMES', [])]

        # 防重窗口扩大到最近 15 次，确保长期运营不出现近期重复主题
        used_ids, _, _ = get_recent_history_constraints(task_name, limit=15)
        candidates = []
        for pool in pools:
            available = [t for t in pool if t.get("id") not in used_ids] or pool
            count = min(4 if len(pools) > 1 else 12, len(available))
            candidates.extend(random.sample(available, count))
        candidates = list({item["id"]: item for item in candidates}.values())
        _, _, recent_posts = get_recent_history_constraints(task_name, limit=5)
        return await select_post_theme(mai_llm, candidates, task_name,
                                       get_current_time_context(), recent_posts)

    # ---------------------------------------------------------
    # 定时早晚发空间任务
    # ---------------------------------------------------------
    async def sync_post_to_global_memory(content_text: str):
        """提炼动态日常存入 core_reply 的全局独立生活记忆层（严格限制在25字内）"""
        if mai_context and mai_llm:
            try:
                mem_prompt = (
                    f"根据这条Bot动态内容，提炼成一句话极简日常事实（严格在25字以内，杜绝'今天也'等套话，客观记录少女日常行为，如'烤吐司涂果酱吃了美味早餐'或'下班路上偶遇可爱的胖橘猫'），若无实质日常则回复空：\n"
                    f"动态：{content_text}\n"
                    f"只输出提炼后的极简短句：\n"
                )
                refined_mem = await mai_llm.chat(
                    messages=[{"role": "user", "content": mem_prompt}],
                    system_prompt="你是一个极简日常信息提炼助手。",
                )
                if refined_mem and len(refined_mem.strip()) > 0:
                    clean_mem = refined_mem.strip().replace("\n", " ")[:30]
                    clean_mem = re.sub(r"^[\'\"\s\[\]]+|[\'\"\s\[\]]+$", "", clean_mem)
                    now_str = datetime.datetime.now().strftime("%m-%d %H:%M")
                    mai_context.update_global_memory(f"[{now_str}] {clean_mem}")
                    logger.info(f"[Qzone 全局记忆] 成功录入Bot日常生活记忆: [{now_str}] {clean_mem}")
            except Exception as e:
                logger.error(f"[Qzone] 全局记忆更新异常: {e}")

    task_history_file = base_data_dir / "qzone_task_history.json"

    def load_task_history() -> dict:
        if task_history_file.exists():
            try:
                return json.loads(task_history_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save_task_history(history: dict):
        try:
            task_history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[Qzone] 保存任务执行历史失败: {e}")

    def get_task_history() -> dict:
        state = _get_runtime_state()
        history = state.get("task_history_cache")
        if history is None:
            history = load_task_history()
            state["task_history_cache"] = history
        return history

    current_instance.last_scheduled_execution = get_task_history()

    async def task_executor(task_name: str, task_info: dict):
        today_str = TimezoneHelper.get_user_local_time('Asia/Shanghai').strftime('%Y-%m-%d')
        history = get_task_history()
        last_date = history.get(task_name)
        is_force_test = task_info.get("_force_test", False)
        if last_date == today_str and not is_force_test:
            logger.warning(f"[Qzone 任务] 定时任务 [{task_name}] 今日({today_str})已经执行过，跳过重复触发！")
            return

        # 仅在非强制测试的正常定时触发时记录执行历史，避免手动“测试早安/晚安”后污染执行标记导致正规定时被跳过
        if not is_force_test:
            history[task_name] = today_str
            current_instance.last_scheduled_execution = history
            save_task_history(history)

        logger.info(f"[Qzone 任务] 开始执行定时发空间任务: {task_name}")
        bot_name, chara_text = get_bot_persona_info()
        festival_or_term = await get_almanac_info()
        time_context = get_current_time_context()
        season_meta = get_current_season()
        season_full = season_meta.get("full_name", "当季")
        season_name = season_meta.get("season", "当季")
        season_desc = season_meta.get("description", "")

        current_global_mem = mai_context.get_global_memory() if mai_context else ""

        # 智能挑选基础主题种子（Seed）与去重约束
        theme_obj = await pick_next_theme(task_name)
        base_theme = theme_obj["theme"]
        sd_theme_hint = theme_obj["sd_hint"]
        selected_theme_id = theme_obj["id"]
        selected_elements = theme_obj.get("elements", [])

        # 随机抽取一种行文句式骨架原型（彻底打破三段论/交代式固定句式，创造真实活人感）
        chosen_archetype = random.choice(post_archetypes) if post_archetypes else {
            "name": "即时随手碎念",
            "description": "【即时碎碎念与生活切片】：像随手发在小号或备忘录的一两句自言自语，有具体的生活细节或场景，语调轻快随意，自然停下，不强行升华或总结。",
            "examples": "“微波炉热牛奶转到最后一秒跳停的声音，莫名有点解压。” / “路过花店被刚剪枝的青草味呛了一下，但还挺好闻的。”"
        }
        logger.info(f"[Qzone 句式原型] {task_name} 采用行文形态: 【{chosen_archetype['name']}】")

        # 变体衍生机制：将已选主题作为种子(Seed)，每次按 70% 概率引入变体引导词发散演绎全新切面（发挥LLM创造力）
        mutation_hint = ""
        if theme_mutation_directives and random.random() < 0.70:
            directive_obj = random.choice(theme_mutation_directives)
            m_type = directive_obj.get("type", "生活切面发散")
            m_text = directive_obj.get("directive", "")
            mutation_hint = (
                f"\n【变体发散（发挥创造力）】（类型：{m_type}）：\n"
                f"{m_text}\n"
                f"请以此种子切面为灵感跳板，结合当前【{season_full}】气候与时令，自由发散演绎出属于你的真实小插曲或微妙心境，不必死板拘泥于种子原话！"
            )
            logger.info(f"[Qzone 变体激发] {task_name} 触发变体衍生: [{m_type}]，基底种子: {base_theme[:30]}")
        else:
            mutation_hint = (
                f"\n【当季变体发散提示】：请以该种子切面为灵感基础，顺应当前【{season_full}】的气候与时令自然展开演绎，展现鲜活真实的日常。"
            )
            logger.info(f"[Qzone 主题选择] {task_name} 采用原始种子切面并融入当季引导: {base_theme[:30]}")

        _, recent_elements, recent_posts = get_recent_history_constraints(task_name, limit=3)

        # 节日提醒与 AI 季节变体引导（免除对静态主题库的繁琐分类，让 AI 自主在变体生成时化解反季节冲突，如大冬天去采茶等）
        season_reminder = (
            f"当前正值【{season_full}】（气候体感：{season_desc}）。"
            f"【AI季节变体引导（关键）】：生活动态与体感描写必须完全符合当前【{season_full}】的季节常理！"
            f"若抽中的种子切面含有反季节元素（例如在冬天抽中茶园采茶/摘新茶、吃冰镇西瓜、盛夏海滩等），"
            f"严禁生搬硬套或违背时令强行描写！请发挥 AI 创造力，在生成变体时自主将其自然转化为符合当前【{season_name}】的生活切面"
            f"（例如：冬天抽中采茶种子，可自主化用为在温暖暖气房里冲泡一杯热茶暖手发呆、翻出春天封存的茶叶罐怀念春天、或路过冬日静默茶山感叹寒风凛冽等；"
            f"夏天抽中围炉烤火，可化用为在空调房贪凉或吃冰棒等）。"
        )
        if festival_or_term:
            fest_tip = f"（今天是【{festival_or_term}】，如有兴趣可轻描淡写提一句。{season_reminder}）"
        else:
            fest_tip = f"（{season_reminder}）"

        negative_constraints = ""
        if recent_elements:
            negative_constraints += f"【严禁重复近期已发元素】：上一条/近期已发过有关【{'、'.join(recent_elements[:8])}】，本次说说严禁再出现上述相同物品或动作！必须展现新一天的全新生活切面！\n"
        if recent_posts:
            negative_constraints += f"【近期已发参考避重】：\n" + "\n".join([f"- {p}" for p in recent_posts[:2]]) + "\n"

        sys_prompt = (
            f"你是{bot_name}。\n"
            f"你的人设信息如下：\n{chara_text}\n\n"
            f"你现在要在自己的社交空间发一条随手动态（{task_name}的说说）。\n"
            f"当前时间：{time_context}\n"
            f"【本次动态场景规则】：{post_scene_instruction(task_name)}\n"
            f"当前季节与时令：{season_full}（气候特征：{season_desc}）\n"
            f"【整体基调与情绪自由】：像真实女孩子在小号随手记下的心情碎片（参考 @moonjelly0、@jellyhoshiumi）。情绪可以极丰富多变——可以超级无聊、emo阴郁、满心雀跃、平淡松弛、干劲满满，甚至带点小恶魔式的调皮戏耍！拒绝单一刻板的人设，展现最鲜活真实的活人感。\n"
            f"【小女友调皮心动感而非低俗】：如果触发调皮搞怪或微撩恶作剧主题，展现的是像古灵精怪、傲娇真实的小女友因为觉得好玩而跟水友开玩笑搞恶作剧；严禁福利姬/低俗卖肉/纯身体部位或露骨描写！\n\n"
            f"【核心禁令与破除AI套路】：\n"
            f"1. 严禁编造复杂的舞台剧剧情与做作转折（如'推开无人花房门铜铃哑响、昙花慢慢张开、连打三个喷嚏'这种毫无日常感的生硬虚构小短文）！普通人发动态绝不是在写小说！\n"
            f"2. 严禁使用括号动作表情（如'（目移）'、'（叹气）'、'（揉脸）'）！\n"
            f"3. 严禁句尾机械式打卡问候（逢早必说'大家早安呀'、逢晚必说'晚安好梦'）！\n"
            f"4. 杜绝'被窝好软'、'被子封印我'、'赖床'等陈词滥调！\n"
            f"5. 【严禁违背季节常识（核心）】：必须严格符合当前【{season_full}】的真实体感与季节常识，坚决杜绝反季节违和现象（如严冬寒风天跑去茶园采摘嫩茶、盛夏暴晒烤火等）！遇到非当季种子，由 AI 自主变体化用为当季合情合理的真实生活细节。\n"
            f"6. 【字数与篇幅】：控制在 1 ~ 30 字左右（通常一两句话即可，绝不超过 35 字！）。\n"
            f"   - 遇到低能量、不想说话或发呆时，几个字到十几字足够（如“电量归零，谁也别跟我说话…”、“只想静静当一株植物”）；\n"
            f"   - 遇到生活随手碎念或小吐槽，一两句讲完自然收尾，绝不长篇大论，绝不画蛇添足。\n"
            f"7. 【严禁机械搬运灵感与动词起手流水账】：\n"
            f"   - 提供的灵感种子（Seed）仅作为发散信号，【严禁在正文直接粘贴Seed原句】，更严禁以'闭着眼睛...'、'大口嚼着...'、'小火慢煎...'等动词起手流水账格式开头！\n"
            f"   - 必须像真实女孩子的社交平台动态一样开口：可以用象声词、内心独白/OS、倒叙悬疑、细节的情绪甩出直接开篇！\n"
            f"   - 如果抽中了变异发散指令（Mutation），请大胆颠覆重构该灵感种子，写出有温度、有呼吸感的生活切片！\n"
            f"{negative_constraints}"
            f"【本次行文切入形态建议】：\n"
            f"{chosen_archetype['description']}\n"
            f"质感示范：{chosen_archetype['examples']}\n\n"
            f"【本次切入种子（Seed）】：{base_theme}。{fest_tip}{mutation_hint}\n\n"
            f"直接输出说说正文，严禁携带任何多余解释、引号或格式。"
        )

        user_prompt = f"请写一条你现在（{time_context}）的动态碎片，采用【{chosen_archetype['name']}】的说话方式，写出真实活人呼吸感。"
        if current_global_mem:
            user_prompt += f" 你最近的日常记忆碎片（可自然呼应）：\n{current_global_mem}"

        post_content = ""
        try:
            if mai_llm:
                resp = await mai_llm.chat(
                    messages=[{"role": "user", "content": user_prompt}],
                    system_prompt=sys_prompt,
                )
                post_content = resp.strip() if resp else ""
                post_content = re.sub(r"^[\'\"\s\[\]]+|[\'\"\s\[\]]+$", "", post_content)
        except Exception as e:
            logger.error(f"[Qzone] LLM 生成说说文案异常: {e}")

        if not post_content:
            post_content = f"{task_name}！窗台上的阳光刚刚好，今天也要打起精神呀~" if task_name == "早安" else "床头灯调暗了，今天先到这里。"

        logger.info(f"[Qzone] 生成说说内容: {post_content}")

        # 记录本次发布的历史，供下一次去重
        record_post_history({
            "type": task_name,
            "theme_id": selected_theme_id,
            "elements": selected_elements,
            "content": post_content,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # 提炼极简日常存入全局记忆
        await sync_post_to_global_memory(post_content)

        # 判断是否需要 SD 绘图
        pic_paths = []
        outfit_selection = {}
        if task_info.get("绘制图片", True):
            theme_desc = sd_theme_hint
            sd_prompt = await build_sd_prompt_for_post(post_content, theme_desc, outfit_selection, task_name=task_name)
            img_file = await call_sd_generate(sd_prompt)
            if img_file:
                pic_paths.append(img_file)

        # 发布至 QQ 空间
        try:
            res = await send_to_qzone(post_content, pic_paths)
            commit_post_outfit(get_wardrobe_manager() if get_wardrobe_manager else None,
                               outfit_selection, res, bool(pic_paths))
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
        shanghai_now = TimezoneHelper.get_user_local_time('Asia/Shanghai')
        today = shanghai_now.date()
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
        cur_hour = shanghai_now.hour
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
        time_context = get_current_time_context()
        festival_or_term = await get_almanac_info()
        season_meta = get_current_season()
        season_full = season_meta.get("full_name", "当季")
        season_name = season_meta.get("season", "当季")
        season_desc = season_meta.get("description", "")

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

        # 接入多样化日常灵感与少女心情日记库（避免近期重复），以种子(Seed)驱动发散
        daily_theme_obj = await pick_next_theme("日常")
        chosen_cat = daily_theme_obj.get("id", "daily_mood")
        chosen_style = daily_theme_obj.get("theme", "分享少女日常生活中的真实可爱碎片")
        chosen_sd_hint = daily_theme_obj.get("sd_hint", "casual daily, relaxed posture, cute expression, high quality")

        # 随机抽取一种行文句式骨架原型（打破AI三段论固定结构）
        chosen_daily_archetype = random.choice(post_archetypes) if post_archetypes else {
            "name": "感官现场与微妙瞬间",
            "description": "【感官现场与微妙瞬间】：捕捉此时此刻一个极其具体的感官体验（触感、冷暖、声响、气味），带一点身体的即时反应，真实细腻又充满浸润感。",
            "examples": "“把刘海全束进小青蛙发带里，刚从冰箱拿出来的黄瓜面膜贴上脸那一瞬间整个人直接打了个激灵，彻底清醒了。”"
        }
        logger.info(f"[Qzone 句式原型] 日常动态采用行文形态: 【{chosen_daily_archetype['name']}】")

        # 节日与季节时令变体引导
        daily_season_reminder = (
            f"当前正值【{season_full}】（气候特征：{season_desc}）。"
            f"【AI季节变体引导】：必须严格遵循当前【{season_full}】的时令常识！"
            f"若本次种子切面包含非当季元素（如寒冬抽中采茶/海滩戏水、盛夏抽中围炉烤火等），"
            f"由 AI 在发散时自主化用为符合当前【{season_name}】的真实日常（如冬天采茶化为喝热茶/回忆茶香），严禁反季节描写！"
        )
        if festival_or_term:
            daily_fest_tip = f"（今天是【{festival_or_term}】。{daily_season_reminder}）"
        else:
            daily_fest_tip = f"（{daily_season_reminder}）"

        # 日常变体衍生引导词（按 70% 概率触发深度发散，避免特定小趣事话题反复雷同）
        daily_mutation_hint = ""
        if theme_mutation_directives and random.random() < 0.70:
            directive_obj = random.choice(theme_mutation_directives)
            d_type = directive_obj.get("type", "生活发散")
            d_text = directive_obj.get("directive", "")
            daily_mutation_hint = (
                f"\n【变体衍生发散】（{d_type}）：{d_text}\n"
                f"请以该种子切面为灵感跳板，结合当前【{season_full}】时令气候，发散出具有当季真实生活呼吸感的小记录！"
            )
            logger.info(f"[Qzone Vtuber日常] 触发变体衍生: [{d_type}]，基底种子: {chosen_style[:30]}")
        else:
            daily_mutation_hint = (
                f"\n【当季变体发散提示】：请以该种子为灵感，结合当前【{season_full}】自然展开演绎，不要死板复现原话题。"
            )
            logger.info(f"[Qzone Vtuber日常] 采用基础种子并融入当季引导: {chosen_style[:30]}")

        sys_vtuber_prompt = (
            f"你是{bot_name}。\n"
            f"人设：\n{chara_text}\n\n"
            f"你现在要在自己的社交空间发一条随手生活碎念。\n"
            f"当前时间：{time_context}\n"
            f"当前季节与时令：{season_full}（气候特征：{season_desc}）\n"
            f"【整体基调与多元情绪】：像真实女孩子在小号随手发的日常碎片。情绪完全自由流动——无论当下是极度无聊、放空抑郁、元气开心、波澜不惊，还是发微撩自拍坏心眼逗人，都真实自然，随性松弛。\n"
            f"【小女友调皮心动感而非低俗】：如果触发调皮搞怪或微撩恶作剧主题，展现的是像古灵精怪、傲娇真实的小女友因为觉得好玩而跟水友开玩笑搞恶作剧；严禁福利姬/低俗卖肉/纯身体部位或露骨描写！\n\n"
            f"【核心写作要领】：\n"
            f"1. 拒绝写成做作编造的虚构小故事！不要层层铺垫前因后果，不要为了写细节而堆砌生硬剧情。\n"
            f"2. 严禁使用'（目移）'、'（叹气）'等任何括号动作戏！\n"
            f"3. 严禁逢发必问'大家呢'！拒绝生硬反问套路，点到即止。\n"
            f"4. 【严禁反季节描写（核心）】：必须符合当前【{season_full}】气候常理，若种子涉及非当季元素由 AI 变体自主化用为当季切面。\n"
            f"5. 【字数控制】：严格在 10 ~ 30 字左右（一两句话说清，绝不超过 35 字！）。低能量或不想说话时，哪怕只有五六个字也完全可以，重在自然真实！\n\n"
            f"【本次切入形态建议】：\n"
            f"{chosen_daily_archetype['description']}\n"
            f"示范：{chosen_daily_archetype['examples']}\n\n"
            f"本次生活切入种子（Seed）：【{chosen_style}】。{daily_fest_tip}{daily_mutation_hint}\n"
            f"直接输出动态正文，不要包含任何多余文字或引号。"
        )
        user_vtuber_prompt = f"请发一条日常动态，采用【{chosen_daily_archetype['name']}】结构，写出真实少女生活感。"
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
                daily_content = re.sub(r"^[\'\"\s\[\]]+|[\'\"\s\[\]]+$", "", daily_content)
        except Exception as e:
            logger.error(f"[Qzone Vtuber日常] 生成动态失败: {e}")

        if not daily_content:
            daily_content = "今天也是慢吞吞晃过去的一天，大家都在干嘛呢？~"

        logger.info(f"[Qzone Vtuber日常] 生成内容: {daily_content}")

        # 记录日常动态历史
        record_post_history({
            "type": "日常",
            "theme_id": chosen_cat,
            "elements": [chosen_cat],
            "content": daily_content,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # 提炼日常存入 core_reply 全局独立生活记忆层
        await sync_post_to_global_memory(daily_content)

        # 概率配图
        pic_paths = []
        outfit_selection = {}
        pic_prob = float(vcfg.get("绘制图片概率", 0.5))
        if random.random() < pic_prob:
            sd_prompt = await build_sd_prompt_for_post(daily_content, chosen_sd_hint, outfit_selection, task_name="日常")
            img_file = await call_sd_generate(sd_prompt)
            if img_file:
                pic_paths.append(img_file)

        # 发送说说
        try:
            res = await send_to_qzone(daily_content, pic_paths)
            commit_post_outfit(get_wardrobe_manager() if get_wardrobe_manager else None,
                               outfit_selection, res, bool(pic_paths))
            logger.info(f"[Qzone Vtuber日常] 发布动态完成: {res}")
            vtuber_post_count_today += 1
        except Exception as e:
            logger.error(f"[Qzone Vtuber日常] 发送异常: {e}")

    # [已重构接入 DynamicScheduler] 原 start_vtuber_daily_monitor 由调度器统一按间隔驱动，此处保留空定义兼容历史调用
    async def start_vtuber_daily_monitor():
        pass
    # ---------------------------------------------------------
    # 空间好友评论自动拟人化互动回复
    # ---------------------------------------------------------
    def clean_comment_content(text: str) -> str:
        """清理 QQ 空间评论中的各类 UBB 艾特标签（包含各类自定义扩展属性）以及文本前缀艾特"""
        if not text:
            return ""
        # 1. 匹配所有 UBB @ 标签，如 @{uin:3377428814,nick:nyuyo,who:1,auto:1}
        t = re.sub(r"@\{uin:\d+[^}]*\}\s*", "", text)
        # 2. 匹配开头的 "回复 @xxx: " 或 "回复 xxx: " 或 "回复xxx："
        t = re.sub(r"^回复\s*@?[^:：\s]+[：:]\s*", "", t)
        # 3. 匹配开头的普通 "@xxx " 或 "@xxx:"
        t = re.sub(r"^@[^\s:：]+[:：\s]*", "", t)
        return t.strip()

    def extract_target_uin(text: str) -> Optional[int]:
        """从原始评论文本中提取被艾特/被回复目标的 QQ 号"""
        if not text:
            return None
        m = re.search(r"@\{uin:(\d+)", text)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, TypeError):
                pass
        return None

    def is_comment_too_old(comment: dict, max_days: int = 30) -> bool:
        """判断评论是否超过指定天数（默认3天/72小时前），超过则跳过不回复，3天以内未回复的正常回复"""
        import time
        from datetime import datetime, timedelta
        now = time.time()
        max_seconds = max_days * 86400

        # 优先使用数字时间戳判定
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

        # 文本时间解析
        time_str = str(comment.get("createTime2", "")).strip()
        if time_str:
            # 常见相对时间放行：刚刚、x分钟前、x小时前、昨天、前天（前天为2天前，在3天内）
            if any(k in time_str for k in ["刚刚", "分钟前", "小时前", "昨天", "前天"]):
                return False

            # 形如 "1天前"、"2天前"
            m_days = re.search(r"(\d+)\s*天前", time_str)
            if m_days:
                return int(m_days.group(1)) > max_days

            # 明显过期的相对时间
            if any(k in time_str for k in ["月前", "年前"]):
                return True

            # 尝试绝对时间解析
            now_dt = datetime.now()
            now_year = now_dt.year
            for fmt in ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m-%d %H:%M", "%m/%d %H:%M"]:
                try:
                    if "%Y" not in fmt:
                        dt = datetime.strptime(f"{now_year}-{time_str}", f"%Y-{fmt}")
                        if dt > now_dt + timedelta(days=1):
                            dt = datetime.strptime(f"{now_year - 1}-{time_str}", f"%Y-{fmt}")
                    else:
                        dt = datetime.strptime(time_str, fmt)
                    return (now_dt - dt).total_seconds() > max_seconds
                except Exception:
                    continue

        return False

    replied_comments_file = base_data_dir / "qzone_replied_comments.json"
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

    def get_replied_comment_ids() -> set:
        state = _get_runtime_state()
        cache = state.get("replied_comment_ids_cache")
        if cache is None:
            cache = load_replied_comments()
            state["replied_comment_ids_cache"] = cache
        return cache

    replied_comment_ids = get_replied_comment_ids()

    async def check_and_reply_comments():
        nonlocal login_result
        if current_instance.stopped:
            return
        state = _get_runtime_state()
        if state.get("active_instance") is not current_instance:
            return
        reply_lock = _get_lock("comment_reply_lock")
        if reply_lock.locked():
            logger.debug("[Qzone 评论巡检] 评论回复锁已处于锁定中，跳过本次重入")
            return
        async with reply_lock:
            return await _check_and_reply_comments_locked()

    async def _check_and_reply_comments_locked():
        nonlocal login_result
        replied_comment_ids = get_replied_comment_ids()
        in_prog = _get_runtime_state()["in_progress_comments"]
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
            resp_str = await qzone._get_messages_list(target_qq=target_qq, g_tk=g_tk, cookies=cookies_str, pos=0, num=15)
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

        inter_cfg = config.qq_zone.config.get("动态互动", {})
        custom_reply_guidance = (inter_cfg.get("reply_guidance") or "").strip()
        if not custom_reply_guidance:
            custom_reply_guidance = (
                "口吻生动鲜活，像关系很好的朋友或Vtuber在自己动态下神回复！"
                "严禁车轱辘复读相同的借口或固定句式，针对不同好友的评论给出不同角度的吐槽、反问、接梗、求饶或傲娇反击；"
                "严禁在回复中使用任何括号动作描写如(气呼呼)。"
            )

        # 动态获取当前节假日、周末与时令信息（为评论互动提供真实时间感知）
        festival_or_term = await get_almanac_info()
        time_context = get_current_time_context()
        season_meta = get_current_season()
        season_full = season_meta.get("full_name", "当季")
        now_dt = datetime.datetime.now()
        is_weekend = now_dt.weekday() >= 5
        is_holiday = bool(festival_or_term) or is_weekend
        if festival_or_term:
            holiday_desc = f"当前正值【{festival_or_term}】长假/节日时令"
        elif is_weekend:
            holiday_desc = "当前正值周末休息日（非工作日/非上学日）"
        else:
            holiday_desc = "普通工作日/上学日"

        def check_reply_cliche_or_repetition(candidate_text: str, priors: list[str]) -> tuple[bool, str]:
            """
            智能检测回复是否命中了套路化公式、刻板口头禅或与本动态下已有回复雷同
            """
            c_clean = candidate_text.strip()
            # 1. 生硬看云/天气转移话题套路
            cloud_kw = ["云好白", "天上的云", "外面的云", "像棉花糖", "看天上的云", "看云"]
            meal_kw = ["晚饭", "晚上吃", "晚饭吃啥", "吃什么", "打算吃啥", "打算吃什么", "吃啥", "参谋一下"]
            if any(w in c_clean for w in cloud_kw):
                return True, "生硬扯天上的云/天气转移话题"
            if any(w in c_clean for w in ["天气真好", "今天天气"]) and any(w in c_clean for w in meal_kw):
                return True, "生硬借天气转移话题并问吃什么"

            # 2. 滥用封口费套路
            if "封口费" in c_clean:
                return True, "索要封口费套路"

            # 3. 滥用‘救命’起手与‘留条活路/无事发生’
            help_kw = ["留条活路", "留点活路", "留点面子", "钻地缝", "埋进沙发", "无事发生", "当做无事发生"]
            if any(w in c_clean for w in ["救命", "快闭嘴"]) and any(w in c_clean for w in help_kw):
                return True, "‘救命’起手并求留活路/无事发生套路"
            if any(w in c_clean for w in ["留条活路", "留点活路", "钻地缝", "埋进沙发"]):
                return True, "套路化求饶/留活路借口"

            # 4. 重复索要奶茶/饮品
            beverage_keywords = ["奶茶", "全糖", "冰淇淋", "冰牛奶", "薯条", "冰美式", "可乐", "饮料"]
            if any(w in c_clean for w in beverage_keywords) and any(any(w in p for w in beverage_keywords) for p in priors):
                return True, "重复索要奶茶/饮品"

            # 5. 重复抓壮丁拖地/收拾桌子
            clean_keywords = ["拖地", "把地拖", "拖了", "打扫", "擦桌子", "擦地", "收拾", "收拾桌面", "收拾干净", "收拾残局", "打翻", "洒了", "弄洒"]
            if any(w in c_clean for w in clean_keywords) and any(any(w in p for w in clean_keywords) for p in priors):
                return True, "重复抓壮丁要求拖地/收拾桌面"

            # 6. 假期间不合常理地指责在工位摸鱼
            if is_holiday and any(w in c_clean for w in ["工位", "上班摸鱼", "在工位", "偷摸摸鱼", "摸鱼刷手机", "偷偷摸鱼", "上班时间"]):
                return True, "节假日/周末期间不合逻辑地指责在工位摸鱼"

            # 7. 重复向不同好友询问吃什么
            repeat_meal_kw = ["晚饭", "午饭", "吃啥", "吃什么", "打算吃什么", "打算吃啥"]
            if any(w in c_clean for w in repeat_meal_kw) and any(any(w in p for w in repeat_meal_kw) for p in priors):
                return True, "向不同好友重复询问吃饭/晚饭"

            # 8. 基于 2-gram 判定与本条动态下已有回复的字词相似度
            def get_2grams(s: str) -> set:
                return {s[i:i+2] for i in range(len(s)-1)} if len(s) >= 2 else {s}

            cand_ng = get_2grams(c_clean)
            for p in priors:
                p_ng = get_2grams(p.strip())
                if cand_ng and p_ng:
                    overlap = len(cand_ng & p_ng) / max(len(cand_ng), 1)
                    if overlap > 0.40:
                        return True, f"与已有回复用词重复率过高({overlap:.2f})"

            # 9. 连续句首套路复读 (如都以 '说谁...呢' 或 '笑什么笑' 起手)
            for p in priors:
                if len(c_clean) >= 4 and len(p) >= 4 and c_clean[:4] == p[:4]:
                    return True, f"回复句首起手式与既往回复重复(‘{c_clean[:4]}’)"

            return False, ""

        for msg in msg_list:
            tid = msg.get("tid", "")
            shuoshuo_text = msg.get("content", "")
            comments = msg.get("commentlist") or []

            # 动态汇总 Bot 的所有可能空间昵称与角色名（防漏艾特）
            bot_names = {bot_name} if bot_name else set()
            if login_result and login_result.get("nick"):
                bot_names.add(str(login_result["nick"]).strip())
            for root_c in comments:
                if int(root_c.get("uin", 0)) == target_qq and root_c.get("name"):
                    bot_names.add(str(root_c.get("name")).strip())
                for sub_c in (root_c.get("list_3") or root_c.get("replies") or root_c.get("sublist") or root_c.get("replylist") or []):
                    if int(sub_c.get("uin", 0)) == target_qq and sub_c.get("name"):
                        bot_names.add(str(sub_c.get("name")).strip())

            # 收集当前说说下已有 Bot 历史回复（用于同动态防复读）
            existing_bot_replies = []
            for root_c in comments:
                if int(root_c.get("uin", 0)) == target_qq:
                    c_txt = clean_comment_content(root_c.get("content", "") or "")
                    if c_txt:
                        existing_bot_replies.append(c_txt)
                for sub_c in (root_c.get("list_3") or root_c.get("replies") or root_c.get("sublist") or root_c.get("replylist") or []):
                    if int(sub_c.get("uin", 0)) == target_qq:
                        c_txt = clean_comment_content(sub_c.get("content", "") or "")
                        if c_txt:
                            existing_bot_replies.append(c_txt)

            recent_replies_for_this_post = []

            # 扁平化提取说说下的所有评论（包含根评论与子评论/楼中楼多级回复），并保存兄弟评论序列与层级索引
            all_target_comments = []
            for root_c in comments:
                # 根评论本身
                all_target_comments.append({
                    "raw": root_c,
                    "is_sub": False,
                    "root_c": root_c,
                    "sub_siblings": [],
                    "sub_idx": -1
                })
                # 提取根评论下的子评论/回复列表（QQ空间常见字段为 list_3，也可能为 replies、sublist、replylist）
                sub_list = root_c.get("list_3") or root_c.get("replies") or root_c.get("sublist") or root_c.get("replylist") or []
                for idx, sub_c in enumerate(sub_list):
                    all_target_comments.append({
                        "raw": sub_c,
                        "is_sub": True,
                        "root_c": root_c,
                        "sub_siblings": sub_list,
                        "sub_idx": idx
                    })

            max_comment_age_days = int(inter_cfg.get("max_comment_age_days", 30))

            for item in all_target_comments:
                c = item["raw"]
                is_sub = item["is_sub"]
                root_c = item["root_c"]
                sub_siblings = item.get("sub_siblings", [])
                sub_idx = item.get("sub_idx", -1)

                cid = str(c.get("tid") or c.get("id") or "").strip()
                comment_uid = c.get("uin", 0)
                comment_name = c.get("name") or c.get("nick") or "空间好友"
                raw_comment_content = (c.get("content", "") or "").strip()

                # 清理各类带附加属性的 QQ 空间 UBB 艾特标签与文本艾特前缀，提取实际用户说话内容
                comment_content = clean_comment_content(raw_comment_content)

                # 排除自己发布的评论和已经回复过的评论
                if int(comment_uid) == target_qq:
                    continue
                root_cid = str(root_c.get("tid") or root_c.get("id") or "").strip()
                unique_key = f"{tid}_sub_{root_cid}_{cid}" if is_sub else f"{tid}_root_{cid}"
                if unique_key in replied_comment_ids or unique_key in in_prog:
                    continue

                # 过滤超过指定天数的古早评论，直接记录已处理，避免反复打扰
                if is_comment_too_old(c, max_days=max_comment_age_days):
                    logger.debug(f"[Qzone 评论互动] 评论时间超过{max_comment_age_days}天(古早评论)，自动跳过: {comment_name} -> {comment_content[:20]}")
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                    continue

                # 过滤语音消息或空消息，避免对非文字内容回复
                if not comment_content or comment_content in ["【语音】", "[语音]", "[图片]", "【图片】"]:
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                    continue

                # 判定回复目标和上下文
                root_uid = int(root_c.get("uin", 0))

                # 提取目标 UIN（优先从字段读取，没有则从 UBB @{uin:QQ号...} 正则解析）
                raw_target_uin = (
                    c.get("target_uin") or
                    c.get("targetUin") or
                    c.get("to_uin") or
                    c.get("toUin") or
                    extract_target_uin(raw_comment_content)
                )
                target_uin = None
                if raw_target_uin is not None:
                    try:
                        target_uin = int(raw_target_uin)
                    except (ValueError, TypeError):
                        target_uin = None

                # 是否明确在正文中艾特了 Bot
                bot_at_ubb = f"uin:{target_qq}"
                is_mentioning_bot = bot_at_ubb in raw_comment_content
                if not is_mentioning_bot:
                    for b_name in bot_names:
                        if b_name and (f"@{b_name}" in raw_comment_content or f"回复 {b_name}" in raw_comment_content or f"回复@{b_name}" in raw_comment_content):
                            is_mentioning_bot = True
                            break

                # 解析楼中楼上下文 parent_c (直接被回复的那条评论对象)
                parent_c = None
                if is_sub:
                    if target_uin:
                        for prev in reversed(sub_siblings[:sub_idx]):
                            if int(prev.get("uin", 0)) == target_uin:
                                parent_c = prev
                                break
                        if not parent_c and root_uid == target_uin:
                            parent_c = root_c
                    if not parent_c and sub_idx > 0:
                        parent_c = sub_siblings[sub_idx - 1]
                    elif not parent_c:
                        parent_c = root_c

                # 精确判定是否属于回复 Bot 的情况
                is_reply_to_bot = False
                if not is_sub:
                    # 根评论：只要不是 Bot 自身发布的，均属于好友在 Bot 动态下的互动，应当回复
                    is_reply_to_bot = True
                else:
                    # 子评论/楼中楼多级回复判定：
                    # 1) 显式 target_uin 指向 Bot
                    if target_uin is not None and target_uin == target_qq:
                        is_reply_to_bot = True
                    # 2) 文本中艾特或提及了 Bot
                    elif is_mentioning_bot:
                        is_reply_to_bot = True
                    # 3) 显式 target_uin 指向了其他人（非 Bot）-> 明确是好友之间的讨论，不插嘴
                    elif target_uin is not None and target_uin != target_qq:
                        is_reply_to_bot = False
                    # 4) 文本以 "回复 @其他人" 起头且该人不是 Bot
                    elif re.search(r"^回复\s*@?([^:：\s]+)", raw_comment_content):
                        target_name = re.search(r"^回复\s*@?([^:：\s]+)", raw_comment_content).group(1).strip()
                        if target_name not in bot_names:
                            is_reply_to_bot = False
                        else:
                            is_reply_to_bot = True
                    # 5) 无显式指向对象：
                    else:
                        # 若直接上下文 parent_c 是 Bot 发言，或者没有前序兄弟评论且根评论是 Bot 发言
                        if parent_c and int(parent_c.get("uin", 0)) == target_qq:
                            is_reply_to_bot = True
                        elif not parent_c and root_uid == target_qq:
                            is_reply_to_bot = True
                        else:
                            is_reply_to_bot = False

                if not is_reply_to_bot:
                    # 既不是艾特bot也不是回复bot（例如路人A回复路人B），不予插嘴打扰，标记已读
                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                    continue

                # 核心防重：在启动 LLM 生成前立即前置占位，锁定该 unique_key，防止任何并发巡检或重入重复处理
                in_prog.add(unique_key)
                try:
                    parent_desc = ""
                    if is_sub:
                        root_name = root_c.get("name") or root_c.get("nick") or "楼主"
                        root_content = (root_c.get("content", "") or "").strip()
                        root_content_clean = clean_comment_content(root_content)

                        if parent_c:
                            parent_uid = int(parent_c.get("uin", 0))
                            parent_name = parent_c.get("name") or parent_c.get("nick") or "空间好友"
                            parent_content_clean = clean_comment_content(parent_c.get("content", ""))
                            if parent_uid == target_qq:
                                parent_desc = f"该好友正在回复你在该说说下的留言：【{parent_content_clean}】\n"
                                if root_c is not parent_c and root_uid != target_qq:
                                    parent_desc += f"（所属根评论为 {root_name} 发布的：【{root_content_clean}】）\n"
                            else:
                                parent_desc = f"该好友正在楼中楼针对【{parent_name}：{parent_content_clean}】进行互动回复\n"
                        else:
                            if root_uid == target_qq:
                                parent_desc = f"该好友正在回复你在该说说下的留言：【{root_content_clean}】\n"
                            else:
                                parent_desc = f"该好友正在楼中楼针对评论【{root_name}：{root_content_clean}】进行互动回复\n"

                    logger.info(f"[Qzone 评论互动] 发现新{'子评论' if is_sub else '根评论'} 来自: {comment_name}({comment_uid}) -> {comment_content}")

                    # 获取用户在 core_reply 的对话历史与用户印象
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
                            logger.warning(f"[Qzone] 读取 core_reply 对话上下文失败: {e}")

                    # 同动态防车轱辘复读判定
                    all_prior_replies = existing_bot_replies + recent_replies_for_this_post
                    anti_repetition_prompt = ""
                    if all_prior_replies:
                        prior_samples = all_prior_replies[-5:]
                        anti_repetition_prompt = (
                            "【防车轱辘复读警告（极度重要）】：你在本条说说下已经对其他好友做出过如下回复：\n"
                            + "\n".join([f"- {r}" for r in prior_samples])
                            + "\n⚠️ 本次回复【绝对严禁】再复读或变相复读上述任何相同的借口、解释理由、词汇或句式！针对当前好友必须换一个完全不同的角度、切入点或态度回应！\n"
                        )

                    # LLM 生成贴合人设与说说主题的回复（基于高阶对话原则与反套路动态检测，杜绝刻板模式化）
                    sys_reply_prompt_base = (
                        f"你是{bot_name}。\n"
                        f"人设信息：\n{chara_text}\n\n"
                        f"你在 QQ 空间发布了一条动态说说，好友正在你的说说评论区发表了互动评论。请以你的角色性格回复对方。\n"
                        f"动态说说内容：【{shuoshuo_text}】\n"
                        f"当前现实时间背景：{time_context}（{holiday_desc}）\n"
                    )
                    if parent_desc:
                        sys_reply_prompt_base += f"上下文背景：\n{parent_desc}\n"
                    if user_impression:
                        sys_reply_prompt_base += f"你对该好友({comment_name})的印象与记忆：\n{user_impression}\n"
                    if recent_chat_snippet:
                        sys_reply_prompt_base += f"你们近期的对话上下文片段：\n{recent_chat_snippet}\n"

                    if anti_repetition_prompt:
                        sys_reply_prompt_base += f"\n{anti_repetition_prompt}\n"

                    # 基于高阶原则的自然互动指引（彻底告别固定模板与机械套路）
                    conversational_guidance = (
                        "【真实社交互动原则（核心）】：\n"
                        f"1. 你是鲜活、机敏的{bot_name}，这是你在自己发表的动态说说评论区与好友们自然的实时互动。\n"
                        f"2. 【就事论事，顺应语境】：直接针对好友评论的具体内容（对方指出的细节、挑的刺、吐槽、调侃、玩梗、关切或疑问）给出具有针对性的真实反应！\n"
                        "   - 如果对方挑细节/挑刺（如质疑手指数量、表情奇怪、被微辣辣翻车等）：你可以自信狡辩（画画手抖、特效重影、滤镜抽风、辣到神志不清）、可以被气笑、也可以反挑对方的刺，态度灵活生动；\n"
                        "   - 如果对方调侃你（如叫你笨笨、笨宝宝）：可以傲娇抗议、反向给对方起搞怪外号、或者佯装生气；\n"
                        "   - 如果对方分享共鸣或聊吃的：顺着对方的具体话题聊，交流真实感受；\n"
                        "   - 如果对方只是发个表情、拟声词或玩抽象梗：简短打趣、接梗或轻快吐槽即可。\n"
                        "3. 情绪与反应完全自由多变，像真实生活中的女孩子与朋友互损打趣，严禁千篇一律的句式。"
                    )

                    negative_cliche_rules = (
                        "【严禁任何模板化套路与敷衍转移话题（高压红线）】：\n"
                        "1. 【绝对严禁】生硬扯天上的云朵、天气（如'啊哈哈天上的云好白/云像棉花糖/今天天气真好'），然后强行问对方'晚饭吃什么'！这是最劣质的机器人答非所问套路！\n"
                        "2. 【绝对严禁】动辄以'救命'起手喊救命，或千篇一律求对方'给我留条活路/无事发生/钻地缝/埋进沙发'！\n"
                        "3. 【绝对严禁】动不动就索要'奶茶/薯条作为封口费'，不要把自己当成只会要奶茶的NPC！\n"
                        "4. 【绝对严禁】动辄'快过来帮我把地拖了/把打翻的收拾干净'抓壮丁！\n"
                        f"5. 【绝对严禁】在假期/周末盲目指责对方'上班在工位偷摸摸鱼'！当前实况是：【{holiday_desc}】，大家都在放假休闲，指责在工位摸鱼完全违背常理！\n"
                        "6. 严禁车轱辘复读相同的借口或固定句式，针对不同好友给出不同角度的回应！"
                    )

                    reply_rules = (
                        f"【个性化优化引导词】：\n{custom_reply_guidance}\n\n"
                        "要求与人际分寸感规范：\n"
                        "1. 结合你的说说主题、上下文语境和对方的评论，自然、亲切地像在空间好友动态下互动一样进行回复。\n"
                        "2. 【重要分寸感约束】：当前处于所有人可见的公开动态评论区！绝对不要表现得过度亲密、过度撒娇、暧昧或调情（不要叫'老公'、'宝贝'、'主人'或做亲昵身体接触描写等），以免其他用户吃醋或显得你到处和人调情！\n"
                        "3. 保持健康、自然、元气可爱的朋友/Vtuber博主互动边界感，风趣机智地回应或友善吐槽即可。\n"
                        "4. 【绝对严禁输出任何括号动作描写】！严禁包含类似 (气呼呼)、(小声嘀咕)、(把手指伸过去)、（委屈地对手指）、(目移) 等任何圆括号或中文括号包裹的动作、心理或神态描写！必须只输出纯粹的人声自然口语台词！\n"
                        "5. 若有对他的印象或聊天经历，自然流露熟络感，不要刻意背诵。\n"
                        "6. 长度严格控制在 10~45 字以内，轻松口语化，绝对不要包含任何系统标记或多余引号，不要自己在回复开头写@谁（系统会自动添加标准艾特标签）。"
                    )

                    reply_text = ""
                    max_retries = 2
                    retry_hint = ""

                    for attempt in range(max_retries + 1):
                        full_sys_prompt = f"{sys_reply_prompt_base}\n{conversational_guidance}\n{negative_cliche_rules}\n{reply_rules}"
                        if retry_hint:
                            full_sys_prompt += f"\n{retry_hint}\n"

                        candidate = ""
                        try:
                            if mai_llm:
                                res = await mai_llm.chat(
                                    messages=[{"role": "user", "content": f"{comment_name} 评论道：\"{comment_content}\"，请回复他："}],
                                    system_prompt=full_sys_prompt,
                                )
                                candidate = res.strip() if res else ""
                        except Exception as e:
                            logger.error(f"[Qzone] 生成评论回复失败(attempt {attempt}): {e}")

                        if candidate:
                            # 彻底剥离任何中英文圆括号动作/心理描写（如 "(气呼呼)"、"（把手指伸到屏幕前）"）
                            while True:
                                cleaned = re.sub(r"[\(（][^()（）]*[\)）]", "", candidate).strip()
                                if cleaned == candidate:
                                    break
                                candidate = cleaned
                            candidate = re.sub(r'^[\u201c\u201d"\'\s\[\]]+|[\u201c\u201d"\'\s\[\]]+$', "", candidate).strip()

                        if candidate:
                            is_cliche, reason = check_reply_cliche_or_repetition(candidate, all_prior_replies)
                            if is_cliche and attempt < max_retries:
                                logger.warning(
                                    f"[Qzone 评论防套路] 候选回复命中模板套路: [{reason}] -> \"{candidate}\"，"
                                    f"正在触发针对性重试..."
                                )
                                retry_hint = (
                                    f"【系统严重警告】：你上一轮生成的回复「{candidate}」被系统拦截，因为命中了禁止的套路：【{reason}】！"
                                    f"请立刻打破该思维定势，完全就事论事直接针对好友的具体评论「{comment_content}」给出完全不同的自然回应，严禁再使用上述任何套路！"
                                )
                                continue
                            else:
                                reply_text = candidate
                                break

                    if not reply_text:
                        fallbacks = [
                            f"哼，{comment_name}你少幸灾乐祸啦！",
                            f"{comment_name}抓包速度这么快，是不是偷偷住我空间了！",
                            f"被{comment_name}看到了……快装作没看见！",
                            f"呜，{comment_name}别拆台，给我留点面子嘛~",
                            f"哎呀{comment_name}你别乱讲，才没有这回事呢！",
                            f"好你个{comment_name}，专门挑这个时候冒出来是吧！"
                        ]
                        clean_fallbacks = [fb for fb in fallbacks if not any(fb[:6] in p for p in all_prior_replies)]
                        reply_text = random.choice(clean_fallbacks or fallbacks)

                    recent_replies_for_this_post.append(reply_text)

                    # 发送空间评论回复 (传递 comment_id 确保楼中楼准确回复)
                    # 注：QQ空间在楼中楼回复时，comment_id 始终传根评论ID（root_c 的 cid）
                    send_cid = str(root_c.get("tid") or root_c.get("id") or cid).strip()
                    logger.info(f"[Qzone 评论回复] 正在回复 {comment_name}: {reply_text}")
                    res = await qzone._send_comments(
                        target_qq=target_qq,
                        uin=int(comment_uid),
                        content=reply_text,
                        cookies=cookies_str,
                        g_tk=g_tk,
                        fid=tid,
                        comment_id=str(send_cid) if send_cid else None,
                        comment_name=comment_name
                    )
                    logger.info(f"[Qzone 评论回复结果]: {res}")
                    if check_resp_for_expired(res):
                        await handle_cookie_expired(f"回复评论失败，Cookie已失效({str(res)[:60]})")
                        return

                    replied_comment_ids.add(unique_key)
                    save_replied_comments(replied_comment_ids)
                except Exception as e:
                    logger.error(f"[Qzone] 处理评论回复异常: {e}\n{traceback.format_exc()}")
                finally:
                    in_prog.discard(unique_key)

                await asyncio.sleep(2)

    # [已重构接入 DynamicScheduler] 原 start_comment_monitor 由调度器统一按间隔驱动，此处保留空定义兼容历史调用
    async def start_comment_monitor():
        pass

    # ---------------------------------------------------------
    # 动态定时任务调度器与工具注册 (DynamicScheduler)
    # ---------------------------------------------------------
    scheduledTasks = config.qq_zone.config.get("定时发空间", {})

    async def _execute_morning_task(**kwargs):
        task_info = kwargs.get("task_info") or scheduledTasks.get("早安", {})
        return await task_executor("早安", task_info)

    async def _execute_night_task(**kwargs):
        task_info = kwargs.get("task_info") or scheduledTasks.get("晚安", {})
        return await task_executor("晚安", task_info)

    async def _execute_custom_post_task(**kwargs):
        task_name = kwargs.get("task_name", "早安")
        task_info = kwargs.get("task_info") or scheduledTasks.get(task_name, {})
        return await task_executor(task_name, task_info)

    async def _execute_vtuber_daily(**kwargs):
        return await vtuber_daily_task()

    async def _execute_comment_reply(**kwargs):
        return await check_and_reply_comments()

    async def _execute_keepalive(**kwargs):
        alive = await check_cookie_alive()
        if alive:
            logger.info("[Qzone 保活] Cookie 状态有效，空间在线")
        else:
            logger.warning("[Qzone 保活] 检测到 QQ 空间 Cookie 可能已失效！")
            await handle_cookie_expired("空间保活探测失效")
            cookie_cfg = config.qq_zone.config.get("cookie设置", {})
            if cookie_cfg.get("失效时自动重新登陆", False):
                logger.warning("[Qzone 保活] 配置开启了自动重新登陆，尝试拉起登录二维码...")
                await login_task_wrapper()

    DynamicScheduler.register_tool("qzone_morning", _execute_morning_task)
    DynamicScheduler.register_tool("qzone_早安", _execute_morning_task)
    DynamicScheduler.register_tool("qzone_night", _execute_night_task)
    DynamicScheduler.register_tool("qzone_晚安", _execute_night_task)
    DynamicScheduler.register_tool("qzone_post_task", _execute_custom_post_task)
    DynamicScheduler.register_tool("qzone_vtuber_daily", _execute_vtuber_daily)
    DynamicScheduler.register_tool("qzone_comment_reply", _execute_comment_reply)
    DynamicScheduler.register_tool("qzone_keepalive", _execute_keepalive)

    async def init_background_services():
        nonlocal login_result
        if current_instance.stopped:
            return
        lock = _get_lock("bg_start_lock")
        async with lock:
            if current_instance.stopped:
                return
            state = _get_runtime_state()
            if state.get("active_instance") is not current_instance:
                return
            if state.get("bg_started"):
                logger.info("[Qzone] 后台服务与任务已在运行中，无需重复启动")
                try:
                    await fetch_cookie_from_onebot()
                except Exception as e:
                    logger.debug(f"[Qzone] 静默刷新凭证提示: {e}")
                return

            state["bg_started"] = True

            # 启动时先拉取一次 OneBot 凭据
            try:
                await fetch_cookie_from_onebot()
            except Exception as e:
                logger.warning(f"[Qzone] 启动同步 OneBot 凭证提示: {e}")

            # 接入统一的框架级动态定时任务引擎 DynamicScheduler
            try:
                dynamic_sched = get_scheduler(bot=bot, config=config)
                dynamic_sched.start()
                await dynamic_sched.sync_qzone_tasks_from_config()
                logger.info("[Qzone] 已成功向 DynamicScheduler 动态同步 QQ 空间定时任务！")
            except Exception as e:
                logger.error(f"[Qzone] 同步定时任务到 DynamicScheduler 异常: {e}", exc_info=True)

    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(event: LifecycleMetaEvent):
        if current_instance.stopped:
            return
        state = _get_runtime_state()
        if state.get("active_instance") is not current_instance:
            return
        sub_type = getattr(event, "sub_type", None)
        logger.info(f"[Qzone 生命周期] 收到 LifecycleMetaEvent (sub_type={sub_type})")
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
        if current_instance.stopped:
            return
        state = _get_runtime_state()
        if state.get("active_instance") is not current_instance:
            return
        nonlocal qzone_status
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
            task_info = dict(scheduledTasks.get("早安", {"绘制图片": True}))

            task_info["_force_test"] = True
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = dict(scheduledTasks.get("晚安", {"绘制图片": True}))

            task_info["_force_test"] = True
            await task_executor("晚安", task_info)
        elif event.pure_text in ["测试日常", "发送日常"] and is_master:
            await bot.send(event, [Text("正在测试生成并发送Vtuber风格日常互动说说...")])
            await vtuber_daily_task()
        elif event.pure_text == "测试空间互动" and is_master:
            await bot.send(event, [Text("正在立即检查空间评论并回复...")])
            await check_and_reply_comments()

    # 若事件循环已在运行（例如动态加载或热重载时未下发 LifecycleMetaEvent），立即排队启动后台服务
    # 稳健排队启动后台服务与任务同步（兼顾直接运行与生命周期事件）
    def _safe_schedule_init():
        target_loop = bot_loop
        if target_loop is None:
            try:
                target_loop = asyncio.get_running_loop()
            except RuntimeError:
                target_loop = None
        if target_loop and target_loop.is_running():
            try:
                curr_loop = asyncio.get_running_loop()
            except RuntimeError:
                curr_loop = None
            if curr_loop is target_loop:
                asyncio.create_task(init_background_services())
            else:
                target_loop.call_soon_threadsafe(lambda: asyncio.create_task(init_background_services()))

    _safe_schedule_init()

    @bot.on(PrivateMessageEvent)
    async def handle_private_message(event: PrivateMessageEvent):
        if current_instance.stopped:
            return
        state = _get_runtime_state()
        if state.get("active_instance") is not current_instance:
            return
        nonlocal qzone_status
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
            task_info = dict(scheduledTasks.get("早安", {"绘制图片": True}))

            task_info["_force_test"] = True
            await task_executor("早安", task_info)
        elif event.pure_text in ["测试晚安", "发送晚安"] and is_master:
            await bot.send(event, [Text("正在测试发送晚安说说...")])
            task_info = dict(scheduledTasks.get("晚安", {"绘制图片": True}))

            task_info["_force_test"] = True
            await task_executor("晚安", task_info)
        elif event.pure_text in ["测试日常", "发送日常"] and is_master:
            await bot.send(event, [Text("正在测试生成并发送Vtuber风格日常互动说说...")])
            await vtuber_daily_task()
        elif event.pure_text == "测试空间互动" and is_master:
            await bot.send(event, [Text("正在立即检查空间评论并回复...")])
            await check_and_reply_comments()
