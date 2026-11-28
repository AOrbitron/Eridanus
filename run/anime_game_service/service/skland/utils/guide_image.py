"""查询图片共用字体、原始头像及全新成品输出。"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont

from .guide_resource import FONT, OUTPUT_DIR
from .draw_gacha import _icon_urls, _valid_icon, _write_icon, icon_path


@lru_cache(maxsize=32)
def core_font(size: int):
    return ImageFont.truetype(str(FONT), size)


def _row(kind: str, item: str) -> dict:
    return {"weaponId" if kind == "weapon" else "charId": item}


def load_icon(game: str, kind: str, item: str) -> Image.Image | None:
    path = icon_path(game, kind, _row(kind, item))
    if path:
        try:
            with Image.open(path) as image:
                return image.convert("RGBA")
        except (OSError, ValueError):
            pass
    return None


async def ensure_icons(game: str, items: list[tuple[str, str]], proxy: str | None = None) -> None:
    semaphore = asyncio.Semaphore(6)
    async with httpx.AsyncClient(proxy=proxy, timeout=4, follow_redirects=True) as client:
        async def download(kind, item):
            row = _row(kind, item)
            path = icon_path(game, kind, row)
            if path is None or await asyncio.to_thread(_valid_icon, path):
                return
            async with semaphore:
                for url in _icon_urls(game, kind, row):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        await asyncio.to_thread(_write_icon, path, response.content)
                        return
                    except (httpx.HTTPError, OSError, ValueError):
                        continue
        try:
            async with asyncio.timeout(25):
                await asyncio.gather(*(download(kind, item) for kind, item in set(items)))
        except TimeoutError:
            pass  # 素材缺失使用占位图，不影响查询或下次重新补充。


def get_ICON() -> Image.Image:
    image = Image.new("RGBA", (100, 100), (43, 51, 66, 255))
    ImageDraw.Draw(image).text((50, 50), "?", font=core_font(42), anchor="mm", fill=(244, 198, 116))
    return image


def get_footer() -> Image.Image:
    image = Image.new("RGBA", (440, 44))
    ImageDraw.Draw(image).text((220, 22), "function by manshuo", font=core_font(23), anchor="mm", fill=(150, 162, 180))
    return image


def save_image(image: Image.Image, prefix: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{prefix}_{uuid4().hex}.png"
    image.convert("RGB").save(path)
    return str(path)
