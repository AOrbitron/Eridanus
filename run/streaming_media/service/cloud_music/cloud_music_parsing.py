import os
import aiofiles
import httpx
import pprint
import asyncio
import re

from developTools.utils.logger import get_logger

logger = get_logger("cloud_music_parser")


class CloudMusicParser:
    def __init__(self, base_url=None, proxies=None):
        self.proxies = proxies
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
            "Referer": "https://music.163.com/",
        }
        self.base_url = base_url

    async def _resolve_song_id(self, song_url: str) -> str:
        """从用户输入的链接或ID中提取网易云歌曲ID"""
        song_url = str(song_url).strip()
        if song_url.isdigit():
            return song_url

        # 如果是短链接，重定向获取完整链接
        if "163cn.tv" in song_url or "163.lu" in song_url:
            async with httpx.AsyncClient(headers=self.headers, proxies=self.proxies, follow_redirects=True, timeout=10.0) as client:
                resp = await client.get(song_url)
                song_url = str(resp.url)

        match = re.search(r"(?:id=|\/song\/|\/song\?id=)(?P<id>\d+)", song_url)
        if match:
            return match.group("id")
        match = re.search(r"\d+", song_url)
        if match:
            return match.group(0)
        raise ValueError(f"无法从输入中解析出有效的网易云歌曲ID: {song_url}")

    async def getSongDetail(self, song_url):
        # 1. 如果配置了可用的第三方 base_url，优先尝试第三方接口（设置较短超时避免死等）
        if self.base_url:
            try:
                api_url = f"{self.base_url}/song"
                params = {
                    'url': song_url,
                    'type': 'json',
                }
                async with httpx.AsyncClient(proxies=self.proxies, headers=self.headers, timeout=5.0) as client:
                    response = await client.get(api_url, params=params)
                    if response.status_code == 200:
                        data = response.json()
                        if data and "data" in data and data["data"].get("url"):
                            logger.info(f"第三方解析接口响应成功: {api_url}")
                            return data
            except Exception as e:
                logger.warning(f"第三方网易云解析接口不可用或超时 ({e})，切换为官方接口与外链解析")

        # 2. 官方 API + 外链播放器直链回退机制
        song_id = await self._resolve_song_id(song_url)
        api_url = f"https://music.163.com/api/song/detail?ids=[{song_id}]"

        async with httpx.AsyncClient(proxies=self.proxies, headers=self.headers, timeout=10.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            result = response.json()

            if not result.get("songs"):
                raise ValueError(f"未找到歌曲信息，ID: {song_id}")

            song_data = result["songs"][0]
            name = song_data.get("name", "未知歌曲")
            artists = " / ".join([artist.get("name", "") for artist in song_data.get("artists", []) if artist.get("name")])
            album_data = song_data.get("album", {})
            pic_url = album_data.get("picUrl", "")
            outer_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"

            return {
                "code": 200,
                "data": {
                    "id": int(song_id),
                    "al_name": name,
                    "ar_name": artists or "未知歌手",
                    "pic": pic_url,
                    "url": outer_url,
                }
            }

    async def download_music(self, url: str, save_path: str):
        """异步下载音频文件到指定路径"""
        try:
            # 确保保存路径的目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # 以流式方式下载文件
            async with httpx.AsyncClient(proxies=self.proxies, headers=self.headers, follow_redirects=True, timeout=30.0) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()

                    # 检查是否跳转到404页面或返回非音频内容
                    content_type = response.headers.get("content-type", "")
                    if "404" in str(response.url) or "text/html" in content_type:
                        raise ValueError("该歌曲因版权或VIP限制，网易云外链播放器未提供可用音频直链")

                    # 异步写入文件
                    async with aiofiles.open(save_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            await f.write(chunk)

            if not os.path.exists(save_path) or os.path.getsize(save_path) == 0:
                raise ValueError("音频下载失败，生成文件为空")

            logger.info(f"音频文件已下载到: {save_path} (大小: {os.path.getsize(save_path)} 字节)")
            return {"status": "success", "message": f"音频文件已下载到 {save_path}"}
        except Exception as e:
            logger.error(f"下载失败: {e}")
            raise e

    async def download_music_stream(self, song_id, save_path=None, level=None):
        if save_path is None:
            save_path = f"data/voice/cache/{song_id}.mp3"

        # 1. 如果配置了可用的第三方接口，优先尝试高品质流
        if self.base_url:
            try:
                api_url = f"{self.base_url}/download"
                params = {
                    'id': int(song_id),
                    'quality': level or 'standard',
                }
                async with httpx.AsyncClient(proxies=self.proxies, headers=self.headers, timeout=5.0) as client:
                    response = await client.get(api_url, params=params)
                    if response.status_code == 200 and "text/html" not in response.headers.get("content-type", ""):
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        with open(save_path, 'wb') as f:
                            f.write(response.content)
                        if os.path.getsize(save_path) > 0:
                            logger.info(f"第三方高品质音频已下载到: {save_path}")
                            return {"status": "success", "message": f"音频文件已下载到 {save_path}"}
            except Exception as e:
                logger.warning(f"第三方网易云下载流接口不可用 ({e})，切换为外链播放器直链下载")

        # 2. 外链播放器直链下载
        outer_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
        return await self.download_music(outer_url, save_path)


async def test(url):
    music = CloudMusicParser()
    detail_result = await music.getSongDetail(url)
    pprint.pprint(detail_result)
    song_id = detail_result['data']["id"]
    stream = await music.download_music_stream(song_id, save_path="data/voice/cache/test_download.mp3")
    pprint.pprint(stream)

if __name__ == "__main__":
    url = 'https://music.163.com/song?id=1436709403'
    asyncio.run(test(url))
