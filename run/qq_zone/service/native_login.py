# -*- coding: utf-8 -*-
"""
native_login.py
原生的 QQ 空间扫码登录与 Cookie 获取实现，零依赖 pyzbar/libzbar/libiconv。
完全基于 aiohttp/httpx/requests 异步网络请求，通过发送图片消息直接让管理员扫码登录。
"""
import asyncio
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any

import aiohttp
from developTools.utils.logger import get_logger

logger = get_logger("QzoneNativeLogin")


def bkn(pSkey: str) -> int:
    """计算 QQ 空间的 g_tk / bkn 校验码"""
    t, n, o = 5381, 0, len(pSkey)
    while n < o:
        t += (t << 5) + ord(pSkey[n])
        n += 1
    return t & 2147483647


def ptqrToken(qrsig: str) -> int:
    """计算二维码轮询所需的 ptqrtoken"""
    n, i, e = len(qrsig), 0, 0
    while n > i:
        e += (e << 5) + ord(qrsig[i])
        i += 1
    return 2147483647 & e


class NativeQzoneLogin:
    def __init__(self, temp_dir: str = "data/pictures/cache"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.qr_img_path = self.temp_dir / "qzone_login_qr.png"

    async def get_qrcode(self) -> Optional[tuple[str, Path]]:
        """获取登录二维码图片并保存，返回 (qrsig, qr_image_path)"""
        url = (
            "https://ssl.ptlogin2.qq.com/ptqrshow?"
            "appid=549000912&e=2&l=M&s=3&d=72&v=4&"
            f"t={time.time()}&daid=5&pt_3rd_aid=0"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        qrsig = resp.cookies.get("qrsig")
                        if not qrsig:
                            logger.error("[Qzone Login] 获取二维码响应中缺少 qrsig cookie")
                            return None
                        qrsig_val = qrsig.value if hasattr(qrsig, "value") else str(qrsig)
                        img_bytes = await resp.read()
                        self.qr_img_path.write_bytes(img_bytes)
                        logger.info(f"[Qzone Login] 二维码下载成功: {self.qr_img_path}")
                        return qrsig_val, self.qr_img_path
                    else:
                        logger.error(f"[Qzone Login] 请求二维码失败，HTTP status: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"[Qzone Login] 获取二维码异常: {e}")
            return None

    async def wait_for_login(self, qrsig: str, timeout_seconds: int = 120) -> Dict[str, Any]:
        """轮询二维码扫码状态并换取空间 Cookie"""
        ptqrtoken = ptqrToken(qrsig)
        start_time = time.time()

        timeout = aiohttp.ClientTimeout(total=10)
        while time.time() - start_time < timeout_seconds:
            poll_url = (
                f"https://ssl.ptlogin2.qq.com/ptqrlogin?"
                f"u1=https%3A%2F%2Fqzs.qq.com%2Fqzone%2Fv5%2Floginsucc.html%3Fpara%3Dizone&"
                f"ptqrtoken={ptqrtoken}&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052&"
                f"action=0-0-{int(time.time()*1000)}&js_ver=20032614&js_type=1&login_sig=&"
                f"pt_uistyle=40&aid=549000912&daid=5&"
            )
            cookies_dict = {"qrsig": qrsig}
            try:
                async with aiohttp.ClientSession(trust_env=False, timeout=timeout, cookies=cookies_dict) as session:
                    async with session.get(poll_url) as resp:
                        text = await resp.text()

                        if "二维码未失效" in text or "二维码认证中" in text:
                            await asyncio.sleep(2)
                            continue

                        if "二维码已失效" in text or "用户取消登录" in text:
                            logger.warning(f"[Qzone Login] 二维码已失效或用户取消")
                            return {"code": -2, "msg": "二维码已失效或已取消"}

                        if "登录成功" in text:
                            logger.info("[Qzone Login] 扫码成功，正在换取空间凭证...")
                            # 提取登录凭证 Cookies
                            res_cookies = {k: v.value for k, v in resp.cookies.items()}
                            uin = res_cookies.get("uin", "")

                            sigx_match = re.search(r"ptsigx=(.*?)&", text)
                            sigx = sigx_match.group(1) if sigx_match else ""

                            check_sig_url = (
                                f"https://ptlogin2.qzone.qq.com/check_sig?pttype=1&uin={uin}"
                                f"&service=ptqrlogin&nodirect=0&ptsigx={sigx}"
                                f"&s_url=https%3A%2F%2Fqzs.qq.com%2Fqzone%2Fv5%2Floginsucc.html"
                                f"%3Fpara%3Dizone&f_url=&ptlang=2052&ptredirect=100&aid=549000912"
                                f"&daid=5&j_later=0&low_login_hour=0&regmaster=0&pt_login_type=3"
                                f"&pt_aid=0&pt_aaid=16&pt_light=0&pt_3rd_aid=0"
                            )

                            async with aiohttp.ClientSession(trust_env=False, timeout=timeout, cookies=res_cookies) as sig_session:
                                # ???? check_sig ??????????? (qzone.qq.com) ??? p_skey ? p_uin
                                current_url = check_sig_url
                                final_cookies = res_cookies.copy()
                                for _ in range(5):
                                    async with sig_session.get(current_url, allow_redirects=False) as sig_resp:
                                        for k, v in sig_resp.cookies.items():
                                            final_cookies[k] = v.value
                                        if sig_resp.status in (301, 302, 303, 307):
                                            current_url = sig_resp.headers.get("Location", "")
                                            if not current_url:
                                                break
                                            if current_url.startswith("/"): 
                                                current_url = f"https://ptlogin2.qzone.qq.com{current_url}"
                                        else:
                                            break

                                p_skey = final_cookies.get("p_skey", "")
                                skey = final_cookies.get("skey", "")
                                calc_bkn = bkn(p_skey) if p_skey else (bkn(skey) if skey else None)
                                target_qq = uin.replace("o", "")

                                return {
                                    "code": 0,
                                    "msg": "????",
                                    "cookies": final_cookies,
                                    "skey": skey,
                                    "qq": target_qq,
                                    "bkn": calc_bkn,
                                }
            except Exception as e:
                logger.debug(f"[Qzone Login] 轮询异常: {e}")

            await asyncio.sleep(2)

        return {"code": -1, "msg": "扫码登录超时"}