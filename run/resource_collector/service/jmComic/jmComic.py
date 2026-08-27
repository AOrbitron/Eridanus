# -*- coding: utf-8 -*-
"""
jmComic 业务逻辑封装
重构要点：
  - 统一使用新版 jmcomic API（Feature、JmDownloader.use()）
  - 彻底废弃全局可变类变量控制 Downloader 的旧写法
  - 预览下载器通过工厂函数按需构造，互不影响
  - downloadALLAndToPdf 的 filename_rule 改为合法的 'Aid'（本子ID）
  - 消除 YAML 文件被反复读写修改 base_dir 的副作用
  - 排行榜函数每次实时请求，无缓存
"""
import pprint
import asyncio
import os
import httpx
import re
import urllib.parse
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import jmcomic
from jmcomic import (
    JmOption, JmAlbumDetail, JmPhotoDetail,
    JmSearchPage, JmCategoryPage,
    JmModuleConfig, JmMagicConstants,
    download_album, Feature,
)
from PIL import Image

from framework_common.utils.random_str import random_str
from run.ai_generated_art.service.antiSFW import process_folder, compress_gifs
from run.resource_collector.service.img_obfuscation import download_cover_bw, obfuscate_cover

_OPTION_FILE = 'run/resource_collector/jmcomic.yml'

# 月榜仍保留缓存，因为它只用于「随机本子」，不需要实时性，且数据量大
from datetime import date,datetime,timezone

_jm_month_cache: dict = {}


# ──────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────

def _load_option(base_dir: str | None = None) -> JmOption:
    """
    从配置文件加载 Option。
    若传入 base_dir，通过代码动态覆盖，不再改写磁盘上的 YAML 文件。
    """
    option = jmcomic.create_option_by_file(_OPTION_FILE)
    if base_dir is not None:
        option.dir_rule.base_dir = base_dir
    return option


def _make_preview_downloader(start: int, end: int, album_index: int):
    """
    工厂函数：每次调用都返回一个全新的预览用 Downloader 类。
    使用局部 class 避免全局状态污染，彻底解决并发/复用时参数串用问题。
    """
    _start = start
    _end = end
    _album_index = album_index

    class _PreviewDownloader(jmcomic.JmDownloader):
        def do_filter(self, detail):
            if detail.is_album():
                album: JmAlbumDetail = detail
                idx = max(0, min(_album_index - 1, len(album) - 1))
                return [album[idx]]

            if detail.is_photo():
                photo: JmPhotoDetail = detail
                s = max(0, _start)
                e = _end if _end > 0 else len(photo)
                e = min(e, len(photo))
                if s >= e:
                    s, e = 0, len(photo)
                return photo[s:e]

            return detail

    return _PreviewDownloader


# ──────────────────────────────────────────────
# 搜索 API
# ──────────────────────────────────────────────

def JM_search(name: str) -> str:
    """关键字站内搜索，返回格式化文本（最多 30 条）。"""
    client = JmOption.default().new_jm_client()
    page: JmSearchPage = client.search_site(search_query=name, page=1)
    lines = []
    for album_id, title in page:
        lines.append(f'[{album_id}]: {title}')
        if len(lines) >= 30:
            break
    return '\n'.join(lines)


def JM_search_with_covers(
        name: str,
        limit: int = 10,
        anti_nsfw: str = "obfuscate",
        cover_workers: int = 5,
) -> list[tuple[str, str, str | None]]:
    """
    带封面图的搜索，返回 [(album_id, title, cover_path_or_None), ...]。
    """
    client = JmOption.default().new_jm_client()
    page: JmSearchPage = client.search_site(search_query=name, page=1)

    id_title_list = []
    for aid, title in page:
        id_title_list.append((str(aid), title))
        if len(id_title_list) >= limit:
            break

    # 复用已有的并发封面下载
    return download_covers_concurrent(id_title_list, anti_nsfw=anti_nsfw, max_workers=cover_workers)
async def JM_search_id(comic_id) -> str:
    """通过车牌号查询本子标题（返回第一条结果）。"""
    client = JmOption.default().new_jm_client()
    page: JmSearchPage = client.search_site(search_query=str(comic_id), page=1)
    for _, title in page:
        return title
    return str(comic_id)


def JM_search_week() -> str:
    """本周排行，返回纯文本（兼容旧接口）。"""
    return '\n'.join(f'[{aid}]: {title}' for aid, title in JM_ranking_week())


def JM_search_month() -> list:
    """本月热门榜，返回 album_id 列表，有日级缓存（供随机本子使用）。"""
    today = date.today()
    cache_key = f'{today}_month'
    if cache_key in _jm_month_cache:
        return _jm_month_cache[cache_key]

    cl = JmOption.default().new_jm_client()
    result = []
    for page in cl.categories_filter_gen(
        page=1,
        time=JmMagicConstants.TIME_MONTH,
        category=JmMagicConstants.CATEGORY_ALL,
        order_by=JmMagicConstants.ORDER_BY_VIEW,
    ):
        for aid, _ in page:
            result.append(aid)
        if len(result) >= 50:
            break

    _jm_month_cache[cache_key] = result
    #每月第一天会返回一个空列表，若返回位空列表则设定默认值
    if not result:
        result_list = [298119,1243884,452206,317728,597511,1238381,139073,143090]
        return result_list
    return result


# ── 实时排行榜（无缓存）─────────────────────────────────────────

def JM_ranking_week(limit: int = 10) -> list[tuple[str, str]]:
    """本周热门榜，每次实时请求，返回 [(album_id, title), ...]。"""
    cl = JmOption.default().new_jm_client()
    result = []
    for page in cl.categories_filter_gen(
        page=1,
        time=JmMagicConstants.TIME_WEEK,
        category=JmMagicConstants.CATEGORY_ALL,
        order_by=JmMagicConstants.ORDER_BY_VIEW,
    ):
        for aid, atitle in page:
            result.append((str(aid), atitle))
            if len(result) >= limit:
                break
        break  # 只取第一页
    return result


def JM_ranking_today(limit: int = 10) -> list[tuple[str, str]]:
    """今日热门榜，每次实时请求，返回 [(album_id, title), ...]。"""
    cl = JmOption.default().new_jm_client()
    result = []
    for page in cl.categories_filter_gen(
        page=1,
        time=JmMagicConstants.TIME_TODAY,
        category=JmMagicConstants.CATEGORY_ALL,
        order_by=JmMagicConstants.ORDER_BY_VIEW,
    ):
        for aid, atitle in page:
            result.append((str(aid), atitle))
            if len(result) >= limit:
                break
        break
    return result


# ──────────────────────────────────────────────
# 封面下载（排行榜图文专用）
# ──────────────────────────────────────────────




def download_covers_concurrent(
    id_title_list: list[tuple[str, str]],
    anti_nsfw: str = "black_and_white",
    max_workers: int = 5,
) -> list[tuple[str, str, str | None]]:
    """
    并发下载一批封面，返回 [(album_id, title, cover_path_or_None), ...]。
    顺序与输入 id_title_list 保持一致。
    """
    results: dict[str, tuple[str, str | None]] = {}

    def _fetch(aid: str, title: str):
        return aid, title, download_cover_bw(aid, anti_nsfw=anti_nsfw)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch, aid, title): aid for aid, title in id_title_list}
        for future in as_completed(futures):
            aid, title, cover = future.result()
            results[aid] = (title, cover)

    return [(aid, results[aid][0], results[aid][1]) for aid, _ in id_title_list]


# ──────────────────────────────────────────────
# 下载 API
# ──────────────────────────────────────────────

def downloadComic(
    comic_id,
    start: int = 1,
    end: int = 5,
    anti_nsfw: str = "black_and_white",
    gif_compress: bool = False,
) -> list[str]:
    """
    预览下载：下载本子第一章的第 start～end 张图，返回处理后的本地文件路径列表。

    参数:
        comic_id    : 禁漫车牌号
        start       : 图片起始下标（1-based，含）
        end         : 图片结束下标（1-based，不含）；0 表示全部
        anti_nsfw   : "black_and_white" / "gif" / "no_censor"
        gif_compress: 是否压缩 gif
    """
    temp_dir = f'data/pictures/benzi/temp{comic_id}'
    os.makedirs(temp_dir, exist_ok=True)

    slice_start = max(0, start - 1)  # 外部 1-based → 内部 0-based
    slice_end = end

    PreviewDownloader = _make_preview_downloader(
        start=slice_start,
        end=slice_end,
        album_index=1,
    )
    PreviewDownloader.use()

    option = _load_option(base_dir=temp_dir)
    jmcomic.download_album(comic_id, option)
    jmcomic.JmDownloader.use()  # 恢复默认 Downloader

    file_names = sorted(os.listdir(temp_dir))
    new_files: list[str] = []

    if anti_nsfw == "gif":
        asyncio.run(process_folder(input_folder=temp_dir, output_folder=temp_dir))
        for filename in sorted(os.listdir(temp_dir)):
            if filename.lower().endswith('.gif'):
                dst = f'data/pictures/cache/{random_str()}.gif'
                shutil.move(os.path.join(temp_dir, filename), dst)
                new_files.append(dst)
        if gif_compress:
            asyncio.run(compress_gifs(new_files))

    elif anti_nsfw == "black_and_white":
        for fname in file_names:
            img = Image.open(os.path.join(temp_dir, fname)).convert('1')
            dst = f'data/pictures/cache/{random_str()}.png'
            img.save(dst)
            new_files.append(dst)

    elif anti_nsfw == "no_censor":
        for fname in file_names:
            dst = os.path.join('data/pictures/cache', fname)
            shutil.move(os.path.join(temp_dir, fname), dst)
            new_files.append(dst)
    elif anti_nsfw == "obfuscate":
        for fname in file_names:
            dst = f'data/pictures/cache/{random_str()}.png'
            img = Image.open(os.path.join(temp_dir, fname))
            obfuscated_img = obfuscate_cover(img)
            obfuscated_img.save(dst, format="PNG")
            new_files.append(dst)
    return new_files


def downloadALLAndToPdf(comic_id, save_path: str) -> str:
    """
    全本下载并导出为 PDF。
    返回值：PDF 文件路径（不含 .pdf 后缀，兼容调用方的 f"{r}.pdf" 拼接写法）。
    """
    download_album(
        str(comic_id),
        extra=Feature.export_pdf(
            pdf_dir=save_path,
            filename_rule='Aid',
            delete_original_file=True,
        ),
    )
    return os.path.join(save_path, str(comic_id))


#上传下载文件至openlist指定文件夹中
class OpenListClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.client = httpx.Client()

    async def login(self):
        login_url = f"{self.base_url}/api/auth/login"
        data = {
            "username": self.username,
            "password": self.password
        }
        resp = self.client.post(login_url, json=data)
        resp.raise_for_status()
        #pprint.pprint(resp.json())
        return_json = {'status':True,'msg':'','token':None}
        if resp.status_code != 200:
            return_json['msg'] = resp.text
            return return_json
        if resp.json().get("code") != 200:
            return_json = {'status': False, 'msg': resp.json().get("message"), 'token': None}
            return return_json
            #raise Exception("登录失败，未获取到访问令牌，返回：{}".format(resp.json().get("message")))
        #print("登录成功，token:", self.token)
        self.token = resp.json()['data'].get("token")
        return_json = {'status': True, 'msg': '登录成功', 'token': self.token}
        return return_json

    async def is_login(self):
        if self.token is None:return False
        else:return True

    async def logout(self):
        return_json = {'status': False, 'msg': '', 'token': self.token}
        if not self.token:
            return_json['msg'] = '"未登录，无需登出"'
            return return_json
        logpout_url = f"{self.base_url}/api/auth/login"
        headers = {
           'Authorization': self.token,
        }
        resp = self.client.get(logpout_url,headers=headers)
        if resp.status_code != 200:
            return_json['msg'] = resp.text
            return return_json
        # print(resp.status_code)
        # if resp.json().get("code") != 200:
        #     return_json['msg'] = resp.json().get("message")
        #     return return_json
        return_json['status'], return_json['msg'] = True, '成功登出喵'
        return return_json

    async def check_dir(self, folder_path):
        dir_url = f"{self.base_url}/api/fs/dirs"  # 根据实际接口修改
        data = {
            "username": self.username,
            "password": self.password
        }
        headers = {
           'Authorization': self.token,
           'Content-Type': 'application/json'
        }
        resp = self.client.post(dir_url, json=data,headers=headers)
        resp.raise_for_status()
        pprint.pprint(resp.json())
        if resp.json().get("code") != 200:
            raise Exception("登录失败，未获取到访问令牌，返回：{}".format(resp.json().get("message")))
        self.token = resp.json()['data'].get("token")
        if not self.token:
            raise Exception("登录失败，未获取到访问令牌")
        print("登录成功，token:", self.token)

    async def upload_file(self, filepath, folder_path):
        return_json = {'status': False, 'msg': '', 'token': self.token}
        if not self.token:
            return_json['msg'] = '"未登录，请先调用 login()"'
            return return_json
        upload_url = f"{self.base_url}/api/fs/put"  # 根据实际接口修改
        # 计算文件哈希
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        md5_hash, sha1_hash, sha256_hash = md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()
        filename = os.path.basename(filepath)
        timestamp = os.path.getmtime(filepath)
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        last_modified_str = dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
        encoded_filename = urllib.parse.quote(filename, safe='')
        #构建headers
        headers = {
            'File-Path': f'{folder_path}/{encoded_filename}',
            'As-Task': 'false',
            'Overwrite': 'true',
            'Last-Modified': last_modified_str,
            'X-File-Md5': md5_hash,
            'X-File-Sha1': sha1_hash,
            'X-File-Sha256': sha256_hash,
            'Authorization': self.token,
            'Content-Type': 'application/octet-stream'
        }
        #files = { "file": open(filepath, "rb") }
        # 读取文件内容
        with open(filepath, 'rb') as f:
            payload = f.read()
        resp = self.client.request('PUT',upload_url, headers=headers, content=payload, timeout = 300)
        if resp.status_code != 200:
            return_json['msg'] = resp.text
            if resp.status_code == 413: return_json['msg'] = '文件过大，上传失败喵'
            return return_json
        if resp.json().get("code") != 200:
            return_json['msg'] = resp.json().get("message")
            if resp.json().get("code") == 403:return_json['msg'] = f'权限不足，{resp.json().get("message")}'
            return return_json
        resp.raise_for_status()
        return_json['status'], return_json['msg'] = True, '上传成功'
        return return_json

async def get_jm_name(jm_id,client=None):
    if client is None:
        client = JmOption.default().new_jm_client()
    Detail = client.get_album_detail(jm_id)
    pprint.pprint(Detail)
    #print(Detail.name)
    Detail.name = Detail.name.replace('–', '-')
    Detail.name = re.sub(r'[\\/:*?"<>|]', '_', Detail.name)
    Detail.name = Detail.name.replace('[', '(').replace(']', ')')
    Detail.name = re.sub(r'\s+', '_', Detail.name)
    Detail.name = Detail.name.strip('_')
    return Detail.name

async def check_jm_multiple(jm_id,client=None):
    if client is None:
        client = JmOption.default().new_jm_client()
    Detail = client.get_album_detail(jm_id)
    if len(Detail.episode_list) > 1: return True
    else: return False

async def test(jm_id=592082):
    headers = { "Content-Type": "application/json" }
    data = {
        "provider": "kuro",
        "qq_id": "1270858640"
    }
    async with httpx.AsyncClient(timeout=60.0) as client:  # 这里timeout单位是秒，30秒等待时间
        response = await client.post('http://127.0.0.1:5000/api/game_checkin/checkin', json=data, headers=headers)
    if response.status_code == 200:
        pprint.pprint(response.json())
        #today_wife_url_path = response.json()['data']['relative_url']



    return
    client = JmOption.default().new_jm_client()
    Detail = client.get_album_detail(jm_id)
    pprint.pprint(Detail)
    pprint.pprint(Detail.episode_list)
    print(len(Detail.episode_list))
    print(Detail.name)
    Detail.name = Detail.name.replace('–', '-')
    Detail.name = re.sub(r'[\\/:*?"<>|]', '_', Detail.name)
    Detail.name = Detail.name.replace('[', '(').replace(']', ')')
    Detail.name = re.sub(r'\s+', '_', Detail.name)
    Detail.name = Detail.name.strip('_')
    return
    base_url = ""  # 替换成实际地址
    username = ""
    password = ""
    filepath = ""
    folder_path = ""

    client = OpenListClient(base_url, username, password)
    info = await client.login()
    await client.logout()
    # pprint.pprint(info)
    # #await client.check_dir(folder_path)
    # info = await client.upload_file(filepath, folder_path)
    # pprint.pprint(info)

if __name__ == '__main__':
    pass
    #JM_search_month()
    info = asyncio.run(test(1336828))
    pprint.pprint(info)
