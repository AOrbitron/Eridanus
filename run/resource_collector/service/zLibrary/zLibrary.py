"""
Copyright (c) 2023-2024 Bipinkrish
This file is part of the Zlibrary-API by Bipinkrish, updated for Eridanus
"""

import os
import json
import logging
import requests

logger = logging.getLogger("zlibrary")

DEFAULT_DOMAINS = [
    "z-library.ec",
    "singlelogin.re",
    "z-library.sk",
    "1lib.sk",
]

TOKEN_CACHE_FILE = os.path.join(os.path.dirname(__file__), "token_cache.json")


class Zlibrary:
    def __init__(
        self,
        email: str = None,
        password: str = None,
        remix_userid: [int, str] = None,
        remix_userkey: str = None,
        proxies: dict = None,
        domain: str = None,
    ):
        self.__email: str = email or ""
        self.__name: str = ""
        self.__kindle_email: str = ""
        self.__remix_userid: [int, str] = remix_userid
        self.__remix_userkey: str = remix_userkey
        self.__domain = domain or DEFAULT_DOMAINS[0]
        self.__domains = [self.__domain] + [d for d in DEFAULT_DOMAINS if d != self.__domain]
        self.__proxies = proxies

        self.__loggedin = False
        self.__headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        self.__cookies = {
            "siteLanguageV2": "en",
        }

        # 优先使用显式 token
        if remix_userid is not None and remix_userkey is not None:
            self.loginWithToken(remix_userid, remix_userkey)
        elif email and password:
            # 检查本地是否有持久化 token
            cached = self._load_token_cache(email)
            if cached and cached.get("remix_userid") and cached.get("remix_userkey"):
                res = self.loginWithToken(cached["remix_userid"], cached["remix_userkey"])
                if self.__loggedin:
                    return
            self.login(email, password)

    @property
    def domain(self) -> str:
        return self.__domain

    def _load_token_cache(self, email: str) -> dict:
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get(email, {})
        except Exception:
            pass
        return {}

    def _save_token_cache(self, email: str, remix_userid: str, remix_userkey: str):
        try:
            data = {}
            if os.path.exists(TOKEN_CACHE_FILE):
                try:
                    with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data[email] = {
                "remix_userid": str(remix_userid),
                "remix_userkey": str(remix_userkey),
            }
            with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Failed to save token cache: {e}")

    def __setValues(self, response) -> dict:
        if not response or not isinstance(response, dict) or not response.get("success"):
            return response or {}
        user = response.get("user", {})
        self.__email = user.get("email", self.__email)
        self.__name = user.get("name", "")
        self.__kindle_email = user.get("kindle_email", "")
        self.__remix_userid = str(user.get("id", ""))
        self.__remix_userkey = user.get("remix_userkey", "")
        self.__cookies["remix_userid"] = self.__remix_userid
        self.__cookies["remix_userkey"] = self.__remix_userkey
        self.__loggedin = True

        if self.__email and self.__remix_userid and self.__remix_userkey:
            self._save_token_cache(self.__email, self.__remix_userid, self.__remix_userkey)

        return response

    def __login(self, email, password) -> dict:
        self.__email = email
        res = self.__makePostRequest(
            "/eapi/user/login",
            data={
                "email": email,
                "password": password,
            },
            override=True,
        )
        return self.__setValues(res)

    def __checkIDandKey(self, remix_userid, remix_userkey) -> dict:
        res = self.__makeGetRequest(
            "/eapi/user/profile",
            cookies={
                "siteLanguageV2": "en",
                "remix_userid": str(remix_userid),
                "remix_userkey": str(remix_userkey),
            },
        )
        return self.__setValues(res)

    def login(self, email: str, password: str) -> dict:
        return self.__login(email, password)

    def loginWithToken(self, remix_userid: [int, str], remix_userkey: str) -> dict:
        return self.__checkIDandKey(remix_userid, remix_userkey)

    def __makePostRequest(self, url: str, data: dict = None, override=False) -> dict:
        if not self.isLoggedIn() and override is False:
            logger.warning("Not logged in")
            return {}
        data = data or {}

        domains_to_try = [self.__domain] + [d for d in self.__domains if d != self.__domain]
        last_error = None

        for d in domains_to_try:
            target_url = f"https://{d}{url}"
            try:
                res = requests.post(
                    target_url,
                    data=data,
                    cookies=self.__cookies,
                    headers=self.__headers,
                    proxies=self.__proxies,
                    timeout=15,
                )
                res.encoding = "utf-8"

                if res.status_code == 513 or "<title>Verifying your browser" in res.text:
                    logger.warning(f"DiamWall detected on {d}, rotating domain...")
                    continue

                if res.status_code in (200, 400):
                    self.__domain = d
                    try:
                        return res.json()
                    except Exception:
                        pass
            except Exception as e:
                last_error = e
                continue

        logger.error(f"zlibrary POST {url} failed on all domains: {last_error}")
        return {}

    def __makeGetRequest(self, url: str, params: dict = None, cookies=None) -> dict:
        if not self.isLoggedIn() and cookies is None:
            logger.warning("Not logged in")
            return {}
        params = params or {}

        domains_to_try = [self.__domain] + [d for d in self.__domains if d != self.__domain]
        req_cookies = self.__cookies if cookies is None else cookies
        last_error = None

        for d in domains_to_try:
            target_url = f"https://{d}{url}"
            try:
                res = requests.get(
                    target_url,
                    params=params,
                    cookies=req_cookies,
                    headers=self.__headers,
                    proxies=self.__proxies,
                    timeout=15,
                )
                res.encoding = "utf-8"

                if res.status_code == 513 or "<title>Verifying your browser" in res.text:
                    logger.warning(f"DiamWall detected on {d}, rotating domain...")
                    continue

                if res.status_code in (200, 400):
                    self.__domain = d
                    try:
                        return res.json()
                    except Exception:
                        pass
            except Exception as e:
                last_error = e
                continue

        logger.error(f"zlibrary GET {url} failed on all domains: {last_error}")
        return {}

    def getProfile(self) -> dict:
        return self.__makeGetRequest("/eapi/user/profile")

    def getMostPopular(self, switch_language: str = None) -> dict:
        params = {"switch-language": switch_language} if switch_language else {}
        return self.__makeGetRequest("/eapi/book/most-popular", params=params)

    def getRecently(self) -> dict:
        return self.__makeGetRequest("/eapi/book/recently")

    def getUserRecommended(self) -> dict:
        return self.__makeGetRequest("/eapi/user/book/recommended")

    def deleteUserBook(self, bookid: [int, str]) -> dict:
        return self.__makeGetRequest(f"/eapi/user/book/{bookid}/delete")

    def unsaveUserBook(self, bookid: [int, str]) -> dict:
        return self.__makeGetRequest(f"/eapi/user/book/{bookid}/unsave")

    def getBookFormats(self, bookid: [int, str], hashid: str) -> dict:
        return self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}/formats")

    def getDonations(self) -> dict:
        return self.__makeGetRequest("/eapi/user/donations")

    def getDownloaded(self, order: str = None, page: int = None, limit: int = None) -> dict:
        params = {k: v for k, v in {"order": order, "page": page, "limit": limit}.items() if v is not None}
        return self.__makeGetRequest("/eapi/user/book/downloaded", params=params)

    def getExtensions(self) -> dict:
        return self.__makeGetRequest("/eapi/info/extensions")

    def getLanguages(self) -> dict:
        return self.__makeGetRequest("/eapi/info/languages")

    def getPlans(self, switch_language: str = None) -> dict:
        params = {"switchLanguage": switch_language} if switch_language else {}
        return self.__makeGetRequest("/eapi/info/plans", params=params)

    def getSaved(self, order: str = None, page: int = None, limit: int = None) -> dict:
        params = {k: v for k, v in {"order": order, "page": page, "limit": limit}.items() if v is not None}
        return self.__makeGetRequest("/eapi/user/book/saved", params=params)

    def getInfo(self, switch_language: str = None) -> dict:
        params = {"switchLanguage": switch_language} if switch_language else {}
        return self.__makeGetRequest("/eapi/info", params=params)

    def hideBanner(self) -> dict:
        return self.__makeGetRequest("/eapi/user/hide-banner")

    def passwordRecovery(self, email: str) -> dict:
        return self.__makePostRequest("/eapi/user/password-recovery", {"email": email}, override=True)

    def resendConfirmation(self) -> dict:
        return self.__makePostRequest("/eapi/user/email/confirmation/resend")

    def saveBook(self, bookid: [int, str]) -> dict:
        return self.__makeGetRequest(f"/eapi/user/book/{bookid}/save")

    def sendTo(self, bookid: [int, str], hashid: str, totype: str) -> dict:
        return self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}/send-to-{totype}")

    def getBookInfo(self, bookid: [int, str], hashid: str, switch_language: str = None) -> dict:
        params = {"switch-language": switch_language} if switch_language else {}
        return self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}", params=params)

    def getSimilar(self, bookid: [int, str], hashid: str) -> dict:
        return self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}/similar")

    def search(
        self,
        message: str = None,
        yearFrom: int = None,
        yearTo: int = None,
        languages: str = None,
        extensions: [str] = None,
        order: str = None,
        page: int = None,
        limit: int = None,
    ) -> dict:
        data = {
            k: v
            for k, v in {
                "message": message,
                "yearFrom": yearFrom,
                "yearTo": yearTo,
                "languages": languages,
                "extensions[]": extensions,
                "order": order,
                "page": page,
                "limit": limit,
            }.items()
            if v is not None
        }
        return self.__makePostRequest("/eapi/book/search", data)

    def __getImageData(self, url: str) -> bytes:
        if not url:
            return b""
        if url.startswith("/"):
            url = f"https://{self.__domain}{url}"
        res = requests.get(url, headers=self.__headers, proxies=self.__proxies, timeout=15)
        if res.status_code == 200:
            return res.content
        return b""

    def getImage(self, book: dict) -> bytes:
        return self.__getImageData(book.get("cover", ""))

    def __getBookFile(self, bookid: [int, str], hashid: str) -> [(str, bytes), None]:
        response = self.__makeGetRequest(f"/eapi/book/{bookid}/{hashid}/file")
        if not response or not response.get("success") or "file" not in response:
            logger.error(f"Failed to get book file info: {response}")
            return None

        file_obj = response["file"]
        filename = file_obj.get("description", f"book_{bookid}")

        author = file_obj.get("author")
        if author:
            filename += f" ({author})"
        ext = file_obj.get("extension", "bin")
        filename += f".{ext}"

        ddl = file_obj.get("downloadLink")
        if not ddl:
            logger.error(f"No downloadLink in response: {response}")
            return None

        headers = self.__headers.copy()
        try:
            res = requests.get(ddl, headers=headers, proxies=self.__proxies, timeout=60)
            if res.status_code == 200:
                return filename, res.content
            logger.error(f"Download failed with status code {res.status_code}")
        except Exception as e:
            logger.error(f"Download request exception: {e}")
        return None

    def downloadBook(self, book: dict) -> [(str, bytes), None]:
        return self.__getBookFile(book["id"], book["hash"])

    def isLoggedIn(self) -> bool:
        return self.__loggedin

    def getDownloadsLeft(self) -> int:
        profile = self.getProfile()
        if not profile or not profile.get("success"):
            return 0
        user_profile = profile.get("user", {})
        return user_profile.get("downloads_limit", 10) - user_profile.get("downloads_today", 0)
