import asyncio
import html
import os
import re
import logging
from framework_common.manshuo_draw import manshuo_draw

logger = logging.getLogger("zlibrary")

FALLBACK_COVER = "framework_common/manshuo_draw/data/cache/manshuo.jpg"


def _clean_text(s: str) -> str:
    if not s:
        return ""
    text = html.unescape(str(s))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _sanitize_filename(name: str, max_len: int = 150) -> str:
    # 过滤 Windows 非法文件名字符
    clean = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', name).strip('. ')
    if not clean:
        clean = "downloaded_book"
    if len(clean) > max_len:
        base, ext = os.path.splitext(clean)
        clean = base[:max_len] + ext
    return clean


async def search_book(Z, book: str, num: int = 4):
    if not Z or not Z.isLoggedIn():
        raise RuntimeError("Z-Library 未登录或会话已失效")

    loop = asyncio.get_running_loop()
    # 在线程池中执行同步网络请求，避免阻塞事件循环
    results = await loop.run_in_executor(
        None,
        lambda: Z.search(message=book, order="bestmatch", limit=max(num * 2, 10))
    )

    if not results or not isinstance(results, dict) or not results.get("books"):
        return []

    domain = getattr(Z, "domain", "z-library.ec")
    return await parse_result(results, num, domain=domain)


async def parse_result(data: dict, num: int, domain: str = "z-library.ec"):
    result = []
    books = data.get("books", [])[:num]

    for book in books:
        try:
            title = _clean_text(book.get("title", "未知标题"))
            author = _clean_text(book.get("author", "未知作者"))
            year = book.get("year", "未知")
            publisher = _clean_text(book.get("publisher", "未知出版社"))
            filesize = book.get("filesizeString", "未知大小")
            extension = book.get("extension", "")
            description = _clean_text(book.get("description", "暂无简介"))
            if len(description) > 300:
                description = description[:300] + "..."

            text = (
                f"[title]{title}[/title]"
                f"\n 作者：{author}"
                f"\n 年份：{year}"
                f"\n 出版商：{publisher}"
                f"\n 文件大小：{filesize}  格式：{extension}"
                f"\n 简介：\n {description}"
            )

            cover = book.get("cover") or ""
            if cover.startswith("/"):
                cover = f"https://{domain}{cover}"
            elif not cover.startswith(("http://", "https://")):
                cover = FALLBACK_COVER

            # 尝试绘制卡片
            r = None
            try:
                r = await manshuo_draw([
                    {
                        "type": "basic_set",
                        "img_width": 2000,
                        "img_height": 2500,
                        "max_num_of_columns": 3,
                        "font_common_size": 34,
                        "font_des_size": 25,
                        "font_title_size": 46,
                        "spacing": 3,
                        "padding_up": 30,
                    },
                    {
                        "type": "img",
                        "subtype": "common_with_des_right",
                        "img": [cover],
                        "content": [text.replace("<br>", "\n ")],
                    },
                ])
            except Exception as draw_err:
                logger.warning(f"manshuo_draw failed with remote cover, trying fallback cover: {draw_err}")
                try:
                    r = await manshuo_draw([
                        {
                            "type": "basic_set",
                            "img_width": 2000,
                            "img_height": 2500,
                            "max_num_of_columns": 3,
                            "font_common_size": 34,
                            "font_des_size": 25,
                            "font_title_size": 46,
                            "spacing": 3,
                            "padding_up": 30,
                        },
                        {
                            "type": "img",
                            "subtype": "common_with_des_right",
                            "img": [FALLBACK_COVER],
                            "content": [text.replace("<br>", "\n ")],
                        },
                    ])
                except Exception as fb_err:
                    logger.error(f"manshuo_draw failed completely: {fb_err}")
                    r = None

            book_id = book.get("id", "")
            book_hash = book.get("hash", "")
            id_hash_text = f"book_id: {book_id}\nhash: {book_hash}"
            if r:
                result.append([id_hash_text, r])
            else:
                # 即使画图失败，也返回文字版信息
                result.append([f"{id_hash_text}\n{title} ({author}) [{extension}]", None])
        except Exception as e:
            logger.error(f"Error parsing book: {e}")
            continue

    return result


def download_book(Z, book_id: str, hash: str) -> str:
    if not Z or not Z.isLoggedIn():
        raise RuntimeError("Z-Library 未登录或会话已失效")

    save_dir = "data/text/books"
    os.makedirs(save_dir, exist_ok=True)

    book = {"id": str(book_id).strip(), "hash": str(hash).strip()}
    res = Z.downloadBook(book)
    if not res or not isinstance(res, (tuple, list)) or len(res) != 2:
        raise RuntimeError(f"下载失败：未能从 Z-Library 获取文件内容（ID: {book_id}）")

    filename, file_content = res
    if not file_content:
        raise RuntimeError("下载失败：获取到的文件内容为空")

    safe_name = _sanitize_filename(filename)
    path = os.path.join(save_dir, safe_name)

    with open(path, "wb") as f:
        f.write(file_content)

    return path
