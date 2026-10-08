import os
import re
import httpx
from datetime import datetime
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from loguru import logger
from framework_common.utils.utils import download_img

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://science.nasa.gov/"
}

async def _fetch_from_nasa_api(apikey: str, proxy: str | None = None):
    proxies = {"http://": proxy, "https://": proxy} if proxy else None
    params = {"api_key": apikey or "DEMO_KEY", "thumbs": "True"}
    url = "https://api.nasa.gov/planetary/apod"
    
    async with httpx.AsyncClient(proxies=proxies, headers=DEFAULT_HEADERS, timeout=8.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    title = data.get("title", "")
    explanation = data.get("explanation", "")
    img_url = data.get("hdurl") or data.get("url")
    if data.get("media_type") == "video" and data.get("thumbnail_url"):
        img_url = data.get("thumbnail_url")
        
    if not img_url or "nasa-logo" in img_url.lower():
        raise ValueError(f"NASA API ???????? Logo ??: {img_url}")
        
    return date_str, title, explanation, img_url

async def _fetch_from_nasa_feed(proxy: str | None = None):
    url = "https://science.nasa.gov/feed/apod-basic/"
    response = None
    
    # ?????????????????????????
    attempt_proxies = [proxy, None] if proxy else [None]
    last_err = None
    for p in attempt_proxies:
        try:
            proxies = {"http://": p, "https://": p} if p else None
            async with httpx.AsyncClient(proxies=proxies, headers=DEFAULT_HEADERS, timeout=12.0) as client:
                res = await client.get(url)
                res.raise_for_status()
                response = res
                break
        except Exception as e:
            last_err = e
            continue
            
    if response is None:
        raise last_err or RuntimeError("????? NASA ?? Feed")

    xml_content = response.content
    root = ET.fromstring(xml_content)
    item = root.find(".//item")
    if item is None:
        raise ValueError("NASA APOD RSS feed ????????")

    title = item.find("title").text if item.find("title") is not None else ""
    pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""

    date_str = datetime.now().strftime("%Y-%m-%d")
    if pub_date:
        try:
            dt = datetime.strptime(pub_date[:16].strip(), "%a, %d %b %Y")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    img_url = ""
    for elem in item:
        tag = elem.tag.split("}")[-1]
        if tag == "hdurl" and elem.text:
            img_url = elem.text.strip()
            break
    if not img_url:
        for elem in item:
            tag = elem.tag.split("}")[-1]
            if tag == "url" and elem.text and not elem.text.endswith("/"):
                img_url = elem.text.strip()
                break

    desc_elem = item.find("description")
    desc_text = desc_elem.text if desc_elem is not None else ""
    soup = BeautifulSoup(desc_text, "html.parser")
    explanation = soup.get_text().strip()
    if explanation.lower().startswith("explanation:"):
        explanation = explanation[len("explanation:"):].strip()

    if not img_url or "nasa-logo" in img_url.lower():
        raise ValueError(f"NASA Feed ???????? Logo ??: {img_url}")

    return date_str, title, explanation, img_url

async def get_nasa_apod(apikey: str, proxy: str | None = None):
    """
    ?? NASA ??????????
    ???? APOD API????????? NASA Logo ?????? NASA ?? Feed?
    ???????? User-Agent headers ???? proxy??????????
    """
    date_str = ""
    title = ""
    explanation = ""
    img_url = ""

    # 1. ?????? APOD API
    try:
        date_str, title, explanation, img_url = await _fetch_from_nasa_api(apikey, proxy)
    except Exception as e:
        logger.warning(f"NASA APOD API ???? ({e})???????? NASA ?? Feed ?...")

    # 2. ????? Feed ????????/?????
    if not img_url:
        try:
            date_str, title, explanation, img_url = await _fetch_from_nasa_feed(proxy)
        except Exception as e:
            logger.error(f"NASA ?? Feed ??????: {e}")
            raise e

    # 3. ??????? proxy ???????????????
    save_path = f"data/pictures/cache/{date_str}.png"
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    filename = None
    try:
        filename = await download_img(img_url, save_path, proxy=proxy, headers=DEFAULT_HEADERS)
    except Exception as e:
        logger.warning(f"???????????? ({e})???????????...")
        filename = await download_img(img_url, save_path, proxy=None, headers=DEFAULT_HEADERS)

    txt = f"{date_str}\n{title}\n{explanation}"
    return filename, txt
