# -*- coding: utf-8 -*-
"""
miHoYo SMS Login Tool v2.1
===========================
通过手机短信验证码登录米游社，一次性获取所有凭证并写入 MihoyoBBSTools config.yaml。

获取的凭证:
  - stoken_v2 + mid + stuid（SMS 登录直接获取）
  - ltoken + cookie_token（用 stoken 换取）
  - 完整 cookie 字符串（包含上述所有字段的 v1+v2 命名）

参考实现:
  - seriaati/genshin.py (auth.py, ds.py, web.py) — 核心 headers + DS 签名
  - BTMuli/TeyvatGuide (passportReq.ts) — RSA 加密 + 请求结构 + cookie 格式

关键参数:
  - 域名: passport-api.miyoushe.com
  - 登录路径: /app/loginByMobileCaptcha (优先) + /web/loginByMobileCaptcha (回退)
  - DS 签名: 发送验证码用简单版，登录用 passport 版，换取 token 用 LK2 版

流程:
  1. python sms_login.py send <手机号>          # 发送验证码
  2. python sms_login.py login <手机号> <验证码>  # 登录 + 换取全部凭证 + 写入 config

环境变量:
  CONFIG_PATH  = test_config.yaml (默认，可修改为实际路径)
"""

import hashlib
import json
import os
import random
import string
import sys
import time
import uuid
from typing import Any, Optional

import httpx
import yaml

# ============================================================
# RSA 加密（与 TeyvatGuide 一致）
# ============================================================

# miHoYo passport RSA 公钥
PUB_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDDvekdPMHN3AYhm/vktJT+YJr7
cI5DcsNKqdsx5DZX0gDuWFuIjzdwButrIYPNmRJ1G8ybDIF7oDW2eEpm5sMbL9zs
9ExXCdvqrn51qELbqj0XxtMTIpaCHFSI50PfPpTFV9Xt/hmyVwokoOXFlAEgCn+Q
CgGs52bFoYMtyi+xEQIDAQAB
-----END PUBLIC KEY-----"""

try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    import base64

    _rsa_key = RSA.import_key(PUB_KEY_PEM)
    _rsa_cipher = PKCS1_v1_5.new(_rsa_key)

    def rsa_encrypt(plaintext: str) -> str:
        """RSA 加密（PKCS1_v1_5 填充），返回 base64 字符串。"""
        encrypted = _rsa_cipher.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")

except ImportError:
    # 备选: 使用 rsa 库
    try:
        import importlib
        import base64

        rsa_lib = importlib.import_module("rsa")

        _pub_key = rsa_lib.PublicKey.load_pkcs1_openssl_pem(PUB_KEY_PEM.encode())

        def rsa_encrypt(plaintext: str) -> str:
            """RSA 加密（PKCS1_v1_5 填充），返回 base64 字符串。"""
            encrypted = rsa_lib.encrypt(plaintext.encode("utf-8"), _pub_key)
            return base64.b64encode(encrypted).decode("utf-8")

    except ImportError:
        print("[FATAL] 需要安装 pycryptodome 或 rsa 库:")
        print("  pip install pycryptodome")
        print("  或 pip install rsa")
        sys.exit(1)


# ============================================================
# 常量（参考 TeyvatGuide TGBbs.ts + passportReq.ts）
# ============================================================

CONFIG_PATH = os.environ.get("CONFIG_PATH", "test_config.yaml")

# BBS 版本号（来自 TGBbs.ts）
BBS_VERSION = "2.102.1"
BBS_UA = f"Mozilla/5.0 (Linux; Android 12) Mobile miHoYoBBS/{BBS_VERSION}"

# API 基础 URL（必须用 miyoushe.com，不是 mihoyo.com！）
PASSPORT_BASE = "https://passport-api.miyoushe.com/"

# SMS 验证码 API
# 发送验证码用 miyoushe.com 域名
CREATE_CAPTCHA_URL = (
    f"{PASSPORT_BASE}account/ma-cn-verifier/verifier/createLoginCaptcha"
)
# 登录用 /app/ 端点（返回 stoken 在 body 中）和 /web/ 端点（返回 token 在 cookies 中）
LOGIN_BY_CAPTCHA_APP_URL = (
    f"{PASSPORT_BASE}account/ma-cn-passport/app/loginByMobileCaptcha"
)
LOGIN_BY_CAPTCHA_WEB_URL = (
    f"{PASSPORT_BASE}account/ma-cn-passport/web/loginByMobileCaptcha"
)

# Token 交换 API（这些可能仍用 mihoyo.com 域名）
TAKUMI_BASE = "https://passport-api.mihoyo.com/"
GET_LTOKEN_URL = f"{TAKUMI_BASE}account/auth/api/getLTokenBySToken"
GET_COOKIE_TOKEN_URL = f"{TAKUMI_BASE}account/auth/api/getCookieAccountInfoBySToken"

# DS 签名 salt（来自 TeyvatGuide TGBbs.ts v2.102.1）
# cn_signin: 用于 SMS 发送验证码（简单版 DS，无 body/query）
DS_SALT_CN_SIGNIN = "LyD1rXqMv2GJhnwdvCBjFOKGiKuLY3aO"
# cn_passport: 用于 SMS 登录（带 body 的 DS）
DS_SALT_CN_PASSPORT = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"
# LK2: 备用（已验证不适用于 stoken 换 token）
DS_SALT_LK2 = "yBh10ikxtLPoIhgwgPZSv5dmfaOTSJ6a"
# X4: 用于 stoken 换 ltoken/cookie_token（getRequestHeader 默认用 X4）
DS_SALT_X4 = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"

# app_id（来自 TeyvatGuide passportReq.ts，验证码登录专用）
APP_ID = "bll8iq97cem8"


# ============================================================
# 工具函数
# ============================================================


def generate_device_id() -> str:
    """生成 UUID v4 设备 ID。"""
    return str(uuid.uuid4())


def generate_device_fp() -> str:
    """生成 13 位十六进制设备指纹。"""
    return "".join(random.choices("0123456789abcdef", k=13))


def generate_ds_simple(salt: str = DS_SALT_CN_SIGNIN) -> str:
    """生成简单版 DS 签名（用于 SMS 发送验证码）。
    来源: genshin.py ds.py generate_dynamic_secret()
    只有 salt+t+r 参与签名，无 body/query。
    """
    t = str(int(time.time()))
    r = "".join(random.choices(string.ascii_letters, k=6))
    h = hashlib.md5(f"salt={salt}&t={t}&r={r}".encode()).hexdigest()
    return f"{t},{r},{h}"


def generate_ds_passport(body_dict: dict[str, Any]) -> str:
    """生成 passport DS 签名（用于 SMS 登录）。
    来源: genshin.py ds.py generate_passport_ds()
    body 参与签名（json.dumps 后的字符串）。
    """
    t = str(int(time.time()))
    r = "".join(random.choices(string.ascii_letters, k=6))
    b = json.dumps(body_dict)
    h = hashlib.md5(
        f"salt={DS_SALT_CN_PASSPORT}&t={t}&r={r}&b={b}&q=".encode()
    ).hexdigest()
    return f"{t},{r},{h}"


def generate_ds_lk2(body: str = "", query: str = "") -> str:
    """生成 LK2 DS 签名（备用）。"""
    t = str(int(time.time()))
    r = str(random.randint(100001, 200000))
    h = hashlib.md5(
        f"salt={DS_SALT_LK2}&t={t}&r={r}&b={body}&q={query}".encode()
    ).hexdigest()
    return f"{t},{r},{h}"


def generate_ds_x4(query: str = "", body: str = "") -> str:
    """生成 X4 DS 签名（用于 stoken 换 ltoken/cookie_token）。

    来源: TeyvatGuide getRequestHeader.ts getDS()
      - method=GET 时: body="", query=transParams(data)
      - random 为 100000~200000 整数（非字母）
      - salt = X4 = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
    """
    t = str(int(time.time()))
    r = str(random.randint(100000, 200000))
    h = hashlib.md5(
        f"salt={DS_SALT_X4}&t={t}&r={r}&b={body}&q={query}".encode()
    ).hexdigest()
    return f"{t},{r},{h}"


# ============================================================
# SMS 登录类
# ============================================================


class SMSLogin:
    """通过手机短信验证码登录米游社，获取 stoken_v2。"""

    def __init__(self) -> None:
        self.device_id: str = generate_device_id()
        self.device_fp: str = generate_device_fp()
        self.client: httpx.Client = httpx.Client(timeout=30.0)

    def _get_sms_headers(self, ds_value: str, aigis: str = "") -> dict[str, str]:
        """构造发送验证码/登录请求的通用 headers。
        参考: genshin.py auth.py CN_LOGIN_HEADERS
        关键差异（vs 旧版）:
          - client_type: "4" (web) 而非 "2" (app)
          - x-rpc-source: "v2.webLogin"（缺少会 -3001）
          - x-rpc-sdk_version: "2.31.0"（缺少会 -3001）
          - x-rpc-game_biz: "bbs_cn" 而非 "hk4e_cn"
          - device_model/name: Firefox 而非 Windows
          - ds: 每次请求动态生成
        """
        return {
            "x-rpc-app_id": APP_ID,
            "x-rpc-client_type": "4",
            "x-rpc-source": "v2.webLogin",
            "x-rpc-sdk_version": "2.31.0",
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-device_fp": self.device_fp,
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_model": "Firefox%20131.0",
            "x-rpc-device_name": "Firefox",
            "x-rpc-aigis": aigis,
            "ds": ds_value,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
            "content-type": "application/json",
            "referer": "https://user.miyoushe.com/",
        }

    def send_captcha(self, phone: str, aigis: str = "") -> dict[str, Any]:
        """发送短信验证码。

        API: POST https://passport-api.miyoushe.com/account/ma-cn-verifier/verifier/createLoginCaptcha
        Body: { area_code: RSA("+86"), mobile: RSA(phone) }
        DS: 简单版（cn_signin salt，无 body 参与）

        返回:
          - 成功: { "action_type": "login", ... }
          - 需要 Geetest: retcode != 0，响应头 x-rpc-aigis 包含验证信息

        Returns:
            dict with keys:
              - success: bool
              - action_type: str (成功时)
              - aigis: str (需要 Geetest 时，从响应头获取)
              - retcode: int
              - message: str
        """
        body = {
            "area_code": rsa_encrypt("+86"),
            "mobile": rsa_encrypt(phone),
        }

        headers = self._get_sms_headers(ds_value=generate_ds_simple(), aigis=aigis)
        resp = self.client.post(CREATE_CAPTCHA_URL, headers=headers, json=body)
        data = resp.json()

        print(
            f"[SMS] 发送验证码响应: retcode={data.get('retcode')}, message={data.get('message')}"
        )

        if data.get("retcode") == 0:
            return {
                "success": True,
                "action_type": data.get("data", {}).get("action_type", "login"),
                "retcode": 0,
                "message": data.get("message", "OK"),
            }
        else:
            # 可能需要 Geetest 人机验证
            aigis_header = resp.headers.get("x-rpc-aigis", "")
            return {
                "success": False,
                "retcode": data.get("retcode"),
                "message": data.get("message", ""),
                "aigis": aigis_header,
            }

    def _try_login_endpoint(
        self, url: str, label: str, body: dict[str, Any], aigis: str = ""
    ) -> tuple[dict[str, Any] | None, httpx.Response]:
        """尝试单个登录端点，返回 (解析结果 or None, response)。"""
        # 每次请求需要新的 DS（时间戳不同）
        headers = self._get_sms_headers(
            ds_value=generate_ds_passport(body), aigis=aigis
        )
        resp = self.client.post(url, headers=headers, json=body)
        data = resp.json()

        retcode = data.get("retcode")
        print(f"[SMS][{label}] 响应: retcode={retcode}, message={data.get('message')}")

        if retcode == 0:
            print(
                f"[SMS][{label}] 完整响应: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            cookies = dict(resp.cookies)
            if cookies:
                print(f"[SMS][{label}] Response cookies: {list(cookies.keys())}")
            return data, resp
        else:
            print(f"[SMS][{label}] 失败，retcode={retcode}")
            return None, resp

    def login_by_captcha(
        self, phone: str, captcha: str, action_type: str, aigis: str = ""
    ) -> dict[str, Any]:
        """使用短信验证码登录。

        策略：先尝试 app 端点（stoken 在 response body），失败则回退 web 端点（token 在 cookies）。
        两个端点使用相同的 headers（已验证发送验证码可用的那套），只换 URL。

        app 端点返回（成功时）:
            { "token": { "token_type": 1, "token": "stoken_v2..." },
              "user_info": { "aid": "...", "mid": "..." } }

        web 端点返回（成功时）:
            body 只有 user_info，stoken 不在 body 也不在 cookies（已验证）。
            但会返回 cookie_token_v2, ltoken_v2 等 cookies。
        """
        body = {
            "area_code": rsa_encrypt("+86"),
            "mobile": rsa_encrypt(phone),
            "captcha": captcha,
        }

        # ---- 第一优先：app 端点（body 返回 stoken） ----
        print("[SMS] 尝试 app 端点获取 stoken_v2...")
        app_data, app_resp = self._try_login_endpoint(
            LOGIN_BY_CAPTCHA_APP_URL, "APP", body, aigis=aigis
        )

        if app_data:
            login_data = app_data.get("data", {})
            token_info = login_data.get("token", {})
            user_info = login_data.get("user_info", {})

            stoken = token_info.get("token", "")
            aid = user_info.get("aid", "")
            mid = user_info.get("mid", "")

            if stoken:
                print(f"[SMS][APP] stoken_v2 获取成功! (长度={len(stoken)})")
                return {
                    "success": True,
                    "stoken": stoken,
                    "stuid": aid,
                    "mid": mid,
                    "cookies": dict(app_resp.cookies),
                }
            else:
                print("[SMS][APP] 登录成功但 body 中无 stoken，尝试 cookies...")
                cookies = dict(app_resp.cookies)
                stoken = cookies.get("stoken", "") or cookies.get("stoken_v2", "")
                if stoken:
                    aid = (
                        aid or cookies.get("stuid", "") or cookies.get("account_id", "")
                    )
                    mid = mid or cookies.get("mid", "")
                    print(f"[SMS][APP] 从 cookies 获取 stoken! (长度={len(stoken)})")
                    return {
                        "success": True,
                        "stoken": stoken,
                        "stuid": aid,
                        "mid": mid,
                        "cookies": cookies,
                    }
                print("[SMS][APP] app 端点成功但无 stoken，回退 web 端点...")

        # ---- 第二优先：web 端点（已验证能成功，但不返回 stoken） ----
        # 注意：一个验证码只能用一次，如果 app 端点已消耗验证码，web 端点会失败
        # 所以只在 app 端点返回 retcode != 0 时尝试
        if app_data is None:
            print("[SMS] app 端点失败，尝试 web 端点...")
            web_data, web_resp = self._try_login_endpoint(
                LOGIN_BY_CAPTCHA_WEB_URL, "WEB", body, aigis=aigis
            )

            if web_data:
                login_data = web_data.get("data", {})
                user_info = login_data.get("user_info", {})
                cookies = dict(web_resp.cookies)

                # web 端点已知不返回 stoken，但返回其他有用的 cookies
                stoken = cookies.get("stoken", "") or cookies.get("stoken_v2", "")
                aid = (
                    user_info.get("aid", "")
                    or cookies.get("stuid", "")
                    or cookies.get("account_id", "")
                )
                mid = user_info.get("mid", "") or cookies.get("mid", "")

                if stoken:
                    print(f"[SMS][WEB] 从 cookies 获取 stoken! (长度={len(stoken)})")
                else:
                    print("[SMS][WEB] web 端点登录成功但无 stoken（符合预期）")
                    print(f"[SMS][WEB] 获得的 cookies: {list(cookies.keys())}")
                    print("[SMS][WEB] 建议重新发送验证码并使用 app 端点")

                return {
                    "success": True,
                    "stoken": stoken,
                    "stuid": aid,
                    "mid": mid,
                    "cookies": cookies,
                }

        # ---- 两个端点都失败 ----
        # 返回最后一个响应的错误信息
        last_resp = app_resp
        last_data = app_resp.json() if app_data is None else {}
        aigis_header = last_resp.headers.get("x-rpc-aigis", "")
        return {
            "success": False,
            "retcode": last_data.get("retcode"),
            "message": last_data.get("message", ""),
            "aigis": aigis_header,
        }

    def _get_token_exchange_headers(
        self, stoken: str, mid: str, query_str: str
    ) -> dict[str, str]:
        """构造 token 交换请求的 headers。

        来源: TeyvatGuide getRequestHeader.ts getRequestHeader()
          - saltType: X4（默认）
          - method: GET -> body="", query=transParams(data)
          - x-rpc-client_type: "5"（PC 端）
          - cookie: 按 key 排序：mid=...;stoken=...（字典序 m < s）
        """
        # cookie 按字典序排序：mid < stoken
        cookie_str = f"mid={mid};stoken={stoken}"
        ds = generate_ds_x4(query=query_str)
        return {
            "user-agent": BBS_UA,
            "x-rpc-app_version": BBS_VERSION,
            "x-rpc-client_type": "5",
            "x-requested-with": "com.mihoyo.hyperion",
            "referer": "https://webstatic.mihoyo.com",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_fp": self.device_fp,
            "ds": ds,
            "cookie": cookie_str,
        }

    def get_ltoken(self, stoken: str, mid: str) -> Optional[str]:
        """用 stoken 换取 ltoken。

        API: GET https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken
        Params: { stoken }
        Cookie: mid=...;stoken=...（字典序排序）
        DS: X4 salt，GET 方式，query=transParams({stoken})
        """
        params = {"stoken": stoken}
        # transParams: 按字典序排序后 key=val& 连接，去掉末尾 &
        # 只有一个参数 stoken，排序后直接是 "stoken={stoken}"
        query_str = f"stoken={stoken}"
        headers = self._get_token_exchange_headers(stoken, mid, query_str)

        resp = self.client.get(GET_LTOKEN_URL, headers=headers, params=params)
        data = resp.json()
        print(
            f"[TOKEN] getLToken 响应: retcode={data.get('retcode')}, message={data.get('message')}"
        )

        if data.get("retcode") == 0:
            ltoken = data.get("data", {}).get("ltoken", "")
            print(f"[TOKEN] ltoken 获取成功: {ltoken[:20]}...")
            return ltoken
        else:
            print(f"[TOKEN] ltoken 获取失败: {data}")
            return None

    def get_cookie_token(self, stoken: str, mid: str) -> Optional[str]:
        """用 stoken 换取 cookie_token。

        API: GET https://passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken
        Params: { stoken }
        Cookie: mid=...;stoken=...（字典序排序）
        DS: X4 salt，GET 方式，query=transParams({stoken})
        """
        params = {"stoken": stoken}
        query_str = f"stoken={stoken}"
        headers = self._get_token_exchange_headers(stoken, mid, query_str)

        resp = self.client.get(GET_COOKIE_TOKEN_URL, headers=headers, params=params)
        data = resp.json()
        print(
            f"[TOKEN] getCookieToken 响应: retcode={data.get('retcode')}, message={data.get('message')}"
        )

        if data.get("retcode") == 0:
            cookie_token = data.get("data", {}).get("cookie_token", "")
            print(f"[TOKEN] cookie_token 获取成功: {cookie_token[:20]}...")
            return cookie_token
        else:
            print(f"[TOKEN] cookie_token 获取失败: {data}")
            return None

    def close(self) -> None:
        self.client.close()


# ============================================================
# Geetest 处理
# ============================================================


def handle_geetest(aigis_data: str) -> str:
    """处理 Geetest 人机验证。

    当 API 返回需要验证时，x-rpc-aigis 响应头包含验证信息。
    格式: session_id;base64_encoded_data

    验证数据 JSON 包含:
      - gt: Geetest GT 值
      - challenge: Geetest challenge 值
      - new_captcha: 是否新版验证码

    用户需要在浏览器中完成验证，获取 validate 值。

    返回格式: session_id;base64({"geetest_validate":"...","geetest_seccode":"...|jordan"})
    """
    import base64

    if not aigis_data:
        print("[GEETEST] 无验证数据")
        return ""

    parts = aigis_data.split(";", 1)
    if len(parts) != 2:
        print(f"[GEETEST] 验证数据格式异常: {aigis_data}")
        return ""

    session_id = parts[0]
    try:
        captcha_data = json.loads(base64.b64decode(parts[1]).decode("utf-8"))
    except Exception as e:
        print(f"[GEETEST] 解码验证数据失败: {e}")
        return ""

    gt = captcha_data.get("gt", "")
    challenge = captcha_data.get("challenge", "")

    print()
    print("=" * 60)
    print("  需要完成人机验证 (Geetest)")
    print("=" * 60)
    print()
    print(f"  GT:        {gt}")
    print(f"  Challenge: {challenge}")
    print()
    print("  请在浏览器中打开以下 URL 完成验证:")
    print("  https://gt.geetest.com/demo/gt4.html")
    print()
    print("  或者使用第三方 Geetest 验证工具:")
    print(f"  gt={gt}")
    print(f"  challenge={challenge}")
    print()

    # 尝试自动打开浏览器验证页面
    geetest_url = (
        f"https://api.geetest.com/ajax.php?"
        f"gt={gt}&challenge={challenge}&lang=zh-hans&pt=3&client_type=web"
    )
    print(f"  Geetest API URL: {geetest_url}")
    print()

    validate = input("  请输入 validate 值 (完成验证后获取): ").strip()

    if not validate:
        print("[GEETEST] 未输入 validate，取消验证")
        return ""

    # 构造 aigis 返回值
    seccode = f"{validate}|jordan"
    aigis_result = {
        "geetest_validate": validate,
        "geetest_seccode": seccode,
    }
    aigis_str = (
        f"{session_id};{base64.b64encode(json.dumps(aigis_result).encode()).decode()}"
    )
    print(f"[GEETEST] 验证数据已构造: session_id={session_id}")
    return aigis_str


# ============================================================
# Config 写入
# ============================================================


def update_config(
    stoken: str,
    mid: str,
    stuid: str,
    ltoken: Optional[str] = None,
    cookie_token: Optional[str] = None,
) -> None:
    """将登录凭证写入 MihoyoBBSTools config.yaml。

    写入字段：
      - stuid / stoken / mid（必填）
      - ltoken / cookie_token（可选，有则写入）
    """
    # 无论 config 是否存在，先打印出来供手动参考
    print()
    print("[凭证汇总]")
    print(f"  stuid:        {stuid}")
    print(f"  stoken:       {stoken}")
    print(f"  mid:          {mid}")
    if ltoken:
        print(f"  ltoken:       {ltoken}")
    if cookie_token:
        print(f"  cookie_token: {cookie_token}")
    print()

    # 完整 cookie 字符串（参考 TeyvatGuide TGClient.ts）
    cookie_str = ""
    if ltoken and cookie_token:
        cookie_str = (
            f"account_id={stuid}; "
            f"account_id_v2={stuid}; "
            f"account_mid_v2={mid}; "
            f"cookie_token={cookie_token}; "
            f"ltmid_v2={mid}; "
            f"ltoken={ltoken}; "
            f"ltuid={stuid}; "
            f"ltuid_v2={stuid}"
        )
        print("[Cookie 字符串 (可直接粘贴到浏览器)]")
        print(f"  {cookie_str}")
        print()

    if not os.path.exists(CONFIG_PATH):
        print(f"[WARN] Config 文件不存在: {CONFIG_PATH}")
        print("[INFO] 请手动将以上凭证写入 config.yaml")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    def _set_fields(target: dict[str, Any]) -> None:
        target["stuid"] = stuid
        target["stoken"] = stoken
        target["mid"] = mid
        if ltoken and cookie_token:
            target["cookie"] = cookie_str

    if (
        "account" in config
        and isinstance(config["account"], list)
        and len(config["account"]) > 0
    ):
        _set_fields(config["account"][0])
    else:
        _set_fields(config)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    print(f"[INFO] 凭证已写入: {CONFIG_PATH}")
    if ltoken and cookie_token:
        print(
            f"[INFO] cookie 字段包含: account_id, ltoken, cookie_token, mid (v1+v2 命名)"
        )


# ============================================================
# 主流程
# ============================================================


STATE_FILE = "sms_state.json"


def save_state(data: dict[str, Any]) -> None:
    """保存中间状态（设备信息等）以便分步执行。"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> dict[str, Any]:
    """加载中间状态。"""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_send(phone: str, aigis: str = "") -> None:
    """步骤 1: 发送短信验证码。

    用法: python sms_login.py send <手机号>
    """
    print(f"[步骤 1] 发送短信验证码到 {phone}...")

    login = SMSLogin()
    try:
        result = login.send_captcha(phone, aigis=aigis)

        if not result["success"]:
            print(
                f"[ERROR] 发送失败: retcode={result.get('retcode')}, message={result.get('message')}"
            )
            if result.get("aigis"):
                print()
                print("[INFO] 触发了 Geetest 人机验证!")
                print(f"[INFO] aigis 数据: {result['aigis']}")
                # 解析并打印 Geetest 信息
                import base64 as b64

                parts = result["aigis"].split(";", 1)
                if len(parts) == 2:
                    try:
                        captcha_data = json.loads(
                            b64.b64decode(parts[1]).decode("utf-8")
                        )
                        print(f"  session_id: {parts[0]}")
                        print(f"  gt:         {captcha_data.get('gt', '')}")
                        print(f"  challenge:  {captcha_data.get('challenge', '')}")
                        print()
                        print("[下一步] 完成 Geetest 后，运行:")
                        print(
                            f'  python sms_login.py send {phone} --aigis "<session_id>;<base64_validate>"'
                        )
                    except Exception:
                        pass
            return

        action_type = result.get("action_type", "login")
        print(f"[OK] 验证码已发送! action_type={action_type}")

        # 保存状态（设备 ID 等需要在登录时复用）
        state = {
            "phone": phone,
            "action_type": action_type,
            "device_id": login.device_id,
            "device_fp": login.device_fp,
        }
        save_state(state)
        print(f"[INFO] 状态已保存到 {STATE_FILE}")
        print()
        print("[下一步] 收到验证码后运行:")
        print(f"  python sms_login.py login {phone} <验证码>")
    finally:
        login.close()


def cmd_login(phone: str, captcha: str, aigis: str = "") -> None:
    """步骤 2: 用验证码登录，获取 stoken_v2 并写入 config。

    用法: python sms_login.py login <手机号> <验证码>
    """
    # 加载之前保存的状态
    state = load_state()
    action_type = state.get("action_type", "login")

    login = SMSLogin()
    # 复用之前的设备信息
    if state.get("device_id"):
        login.device_id = state["device_id"]
    if state.get("device_fp"):
        login.device_fp = state["device_fp"]

    try:
        print(f"[步骤 2] 使用验证码登录...")
        print(f"  phone={phone}, captcha={captcha}, action_type={action_type}")
        print()

        login_result = login.login_by_captcha(phone, captcha, action_type, aigis=aigis)

        if not login_result["success"]:
            print(
                f"[ERROR] 登录失败: retcode={login_result.get('retcode')}, message={login_result.get('message')}"
            )
            if login_result.get("aigis"):
                print(f"[INFO] 触发了 Geetest: {login_result['aigis']}")
            return

        stoken = login_result["stoken"]
        stuid = login_result["stuid"]
        mid = login_result["mid"]

        print()
        print("=" * 60)
        print("  SMS 登录成功!")
        print("=" * 60)
        print(f"  stuid:  {stuid}")
        print(f"  stoken: {stoken[:50]}...")
        print(f"  mid:    {mid}")
        print("=" * 60)
        print()

        # 换取 ltoken + cookie_token
        print("[步骤 3] 换取 ltoken 和 cookie_token...")
        ltoken = login.get_ltoken(stoken, mid)
        cookie_token = login.get_cookie_token(stoken, mid)

        if ltoken:
            print(f"  ltoken: {ltoken[:30]}...")
        if cookie_token:
            print(f"  cookie_token: {cookie_token[:30]}...")
        print()

        # 写入 config
        print("[步骤 4] 写入 config.yaml...")
        update_config(stoken, mid, stuid, ltoken=ltoken, cookie_token=cookie_token)

        print("=" * 60)
        print("  全部完成!")
        print("=" * 60)

        # 清理状态文件
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)

    finally:
        login.close()


def main() -> None:
    """CLI 入口。

    用法:
      python sms_login.py send <手机号>                  # 步骤1: 发送验证码
      python sms_login.py login <手机号> <验证码>         # 步骤2: 登录
      python sms_login.py send <手机号> --aigis <aigis>  # 带 Geetest 重试
    """
    if len(sys.argv) < 3:
        print("miHoYo SMS Login Tool v2.1")
        print("=" * 50)
        print()
        print("用法:")
        print("  python sms_login.py send <手机号>             # 发送验证码")
        print(
            "  python sms_login.py login <手机号> <验证码>    # 登录 + 获取全部凭证 + 写入 config"
        )
        print()
        print("登录后自动获取: stoken_v2, ltoken, cookie_token, 完整 cookie 字符串")
        print(f"Config 路径: {CONFIG_PATH}")
        return

    cmd = sys.argv[1]

    if cmd == "send":
        phone = sys.argv[2]
        aigis = ""
        if "--aigis" in sys.argv:
            idx = sys.argv.index("--aigis")
            if idx + 1 < len(sys.argv):
                aigis = sys.argv[idx + 1]
        cmd_send(phone, aigis=aigis)

    elif cmd == "login":
        if len(sys.argv) < 4:
            print("用法: python sms_login.py login <手机号> <验证码>")
            return
        phone = sys.argv[2]
        captcha = sys.argv[3]
        aigis = ""
        if "--aigis" in sys.argv:
            idx = sys.argv.index("--aigis")
            if idx + 1 < len(sys.argv):
                aigis = sys.argv[idx + 1]
        cmd_login(phone, captcha, aigis=aigis)

    else:
        print(f"[ERROR] 未知命令: {cmd}")
        print("可用命令: send, login")


if __name__ == "__main__":
    main()