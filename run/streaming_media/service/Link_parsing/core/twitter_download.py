"""推特媒体下载，适配 manshuo_api 的分段续传、代理回退和 GIF 转换实现。"""
from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import aiofiles
import httpx


GIF_REFERENCE_KEY = "__manshuo_twitter_gif"


def twitter_gif_reference(url: str) -> str:
    parsed = urlparse(url)
    fragment = [(key, value) for key, value in parse_qsl(parsed.fragment) if key != GIF_REFERENCE_KEY]
    return urlunparse(parsed._replace(fragment=urlencode([*fragment, (GIF_REFERENCE_KEY, "1")])))


def is_twitter_gif(url: str) -> bool:
    parsed = urlparse(url)
    if parse_qs(parsed.fragment).get(GIF_REFERENCE_KEY) == ["1"]:
        return True
    # Also recognize media URLs returned before GIF references were introduced.
    return parsed.hostname == "video.twimg.com" and parsed.path.startswith("/tweet_video/")


def twitter_gif_source(url: str) -> str:
    parsed = urlparse(url)
    fragment = [(key, value) for key, value in parse_qsl(parsed.fragment) if key != GIF_REFERENCE_KEY]
    return urlunparse(parsed._replace(fragment=urlencode(fragment)))


async def convert_twitter_gif(source: Path, target: Path) -> None:
    with source.open("rb") as input_file:
        signature = input_file.read(6)
    if signature in {b"GIF87a", b"GIF89a"}:
        source.replace(target)
        return

    async def ffmpeg(*arguments: str) -> None:
        try:
            process = subprocess.Popen(
                ("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1", *arguments),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg 未安装或不在 PATH 中") from exc
        # Windows SelectorEventLoop cannot create asyncio subprocesses.
        # Shield the worker so timeout/cancellation can kill and reap FFmpeg
        # before the temporary palette directory is removed.
        communication = asyncio.create_task(asyncio.to_thread(process.communicate))
        try:
            _, stderr = await asyncio.wait_for(asyncio.shield(communication), 300)
        except BaseException as exc:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await communication
            if isinstance(exc, TimeoutError):
                raise TimeoutError("GIF 转换超时，请稍后重试") from exc
            raise
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace")[-300:] if stderr else ""
            raise RuntimeError(f"GIF 转换失败：{detail}")

    # Generate a palette in a separate pass so a long animation does not need
    # to buffer all decoded frames. Preserve the source dimensions and timing.
    with tempfile.TemporaryDirectory(prefix="twitter-gif-") as directory:
        palette = Path(directory) / "palette.png"
        await ffmpeg("-i", str(source), "-vf", "palettegen=reserve_transparent=0",
                     "-frames:v", "1", "-update", "1", str(palette))
        await ffmpeg("-i", str(source), "-i", str(palette), "-lavfi", "paletteuse=dither=sierra2_4a",
                     "-an", "-loop", "0", "-f", "gif", str(target))


class TwitterMediaStream:
    """Stream X media with bounded retries that preserve already sent bytes."""

    IMAGE_CONNECT_TIMEOUT = 5
    IMAGE_HEADER_TIMEOUT = 8
    IMAGE_IDLE_TIMEOUT = 6
    IMAGE_SLOW_WINDOW = 8
    IMAGE_MIN_BYTES_PER_SECOND = 16 * 1024
    IMAGE_ATTEMPT_TIMEOUT = 45
    IMAGE_RANGE_BYTES = 256 * 1024
    VIDEO_CONNECT_TIMEOUT = 5
    VIDEO_HEADER_TIMEOUT = 8
    VIDEO_IDLE_TIMEOUT = 6
    VIDEO_SLOW_WINDOW = 8
    VIDEO_MIN_BYTES_PER_SECOND = 16 * 1024
    VIDEO_ATTEMPT_TIMEOUT = 45
    VIDEO_RANGE_BYTES = 256 * 1024

    def __init__(self, url: str, proxy_url: str | None, headers: dict[str, str], *, image: bool = False):
        self.url = url
        self.proxy_url = proxy_url
        self.image = image
        host = (urlparse(url).hostname or "").lower()
        self.ranged_image = image and (host == "pbs.twimg.com" or host.endswith(".pbs.twimg.com"))
        self.ranged_video = not image and (host == "video.twimg.com" or host.endswith(".video.twimg.com"))
        self.ranged_media = self.ranged_image or self.ranged_video
        self.connect_timeout = self.IMAGE_CONNECT_TIMEOUT if image else self.VIDEO_CONNECT_TIMEOUT
        self.header_timeout = self.IMAGE_HEADER_TIMEOUT if image else self.VIDEO_HEADER_TIMEOUT
        self.idle_timeout = self.IMAGE_IDLE_TIMEOUT if image else self.VIDEO_IDLE_TIMEOUT
        self.slow_window = self.IMAGE_SLOW_WINDOW if image else self.VIDEO_SLOW_WINDOW
        self.min_bytes_per_second = self.IMAGE_MIN_BYTES_PER_SECOND if image else self.VIDEO_MIN_BYTES_PER_SECOND
        self.attempt_timeout = self.IMAGE_ATTEMPT_TIMEOUT if image else self.VIDEO_ATTEMPT_TIMEOUT
        self.range_bytes = self.IMAGE_RANGE_BYTES if image else self.VIDEO_RANGE_BYTES
        self.request_headers = {**headers, "Accept-Encoding": "identity"}
        if self.ranged_media:
            self.request_headers["Connection"] = "close"
        self.headers = httpx.Headers()
        self.client: httpx.AsyncClient | None = None
        self.response: httpx.Response | None = None
        self.using_proxy = False
        self.validator = ""
        # Direct access can be blocked locally, so allow one final attempt
        # on the selected route after the fallback also fails. Never enable
        # a configured proxy when the caller selected direct access.
        self.routes = [proxy_url, None, proxy_url] if proxy_url else [None, None]
        self.next_route = 0
        self.prefetched: dict[int, asyncio.Task[httpx.Response]] = {}

    async def _request(self, proxy_url: str | None, offset: int = 0) -> None:
        await self.aclose()
        headers = dict(self.request_headers)
        if self.ranged_media:
            headers["Range"] = f"bytes={offset}-{offset + self.range_bytes - 1}"
        elif offset:
            headers["Range"] = f"bytes={offset}-"
        if offset and self.validator:
            headers["If-Range"] = self.validator
        self.using_proxy = bool(proxy_url)
        if self.client is None:
            self.client = httpx.AsyncClient(
                headers=self.request_headers, proxy=proxy_url, trust_env=False,
                timeout=httpx.Timeout(self.idle_timeout, connect=self.connect_timeout),
                follow_redirects=True,
            )
        request = self.client.build_request("GET", self.url, headers=headers)
        try:
            # Keep cancellation in this task. Nested wait_for calls on
            # Python 3.11 can swallow cancellation when headers arrive at
            # the same instant, leaving a cancelled transfer still reading.
            async with asyncio.timeout(self.header_timeout):
                self.response = await self.client.send(request, stream=True)
        except TimeoutError as exc:
            raise httpx.ReadTimeout("Twitter media response headers stalled", request=request) from exc
        self.response.raise_for_status()
        self.headers = self.response.headers

    async def _request_next(self, offset: int = 0) -> None:
        while self.next_route < len(self.routes):
            proxy_url = self.routes[self.next_route]
            self.next_route += 1
            try:
                await self._request(proxy_url, offset)
                return
            except (httpx.HTTPError, ValueError):
                if self.next_route >= len(self.routes):
                    raise

    async def open(self) -> TwitterMediaStream:
        await self._request_next()
        etag = self.headers.get("etag", "")
        self.validator = etag if etag and not etag.startswith("W/") else self.headers.get("last-modified", "")
        if self.ranged_media and self.response.status_code == 206:
            total, _skip = self._validate_resume(0, True, None)
            # Expose the whole file's size to callers instead of one range.
            self.headers = httpx.Headers(self.headers)
            self.headers.pop("content-range", None)
            self.headers["Content-Length"] = str(total)
        return self

    def _validate_resume(
        self, offset: int, identity: bool, total: int | None, response: httpx.Response | None = None,
    ) -> tuple[int | None, int]:
        response = response if response is not None else self.response
        assert response is not None
        headers = response.headers
        resumed_validator = (headers.get("etag", "") if self.validator.startswith('"')
                             else headers.get("last-modified", ""))
        if offset and self.validator and resumed_validator and resumed_validator != self.validator:
            raise httpx.ReadError("Twitter media changed while resuming")
        if offset and identity and headers.get("content-encoding", "identity").lower() != "identity":
            raise httpx.ReadError("Twitter media encoding changed while resuming")
        if response.status_code == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", headers.get("content-range", ""))
            if not identity or not match or int(match[1]) != offset or int(match[2]) < offset:
                raise httpx.ReadError("Twitter media returned an invalid resume offset")
            if total is not None and match[3] != str(total):
                raise httpx.ReadError("Twitter media size changed while resuming")
            if match[3] != "*":
                total = int(match[3])
                if int(match[2]) >= total:
                    raise httpx.ReadError("Twitter media returned an invalid range end")
            elif self.ranged_media:
                raise httpx.ReadError("Twitter media range did not include its full size")
            return total, 0
        if response.status_code == 200:
            length = headers.get("content-length", "")
            if identity and length.isdigit() and total is not None and int(length) != total:
                raise httpx.ReadError("Twitter media size changed while resuming")
            return total, offset
        raise httpx.ReadError("Twitter media could not be resumed")

    async def _fetch_range(self, offset: int, total: int, proxy_url: str | None) -> httpx.Response:
        end = min(offset + self.range_bytes, total) - 1
        headers = {**self.request_headers, "Range": f"bytes={offset}-{end}"}
        if self.validator:
            headers["If-Range"] = self.validator
        # Use a fresh connection for each small range. Reusing a connection
        # can reproduce the same mid-transfer stall across consecutive ranges.
        async with httpx.AsyncClient(
            headers=headers, proxy=proxy_url, trust_env=False, follow_redirects=True,
            timeout=httpx.Timeout(self.idle_timeout, connect=self.connect_timeout),
        ) as client:
            response = None
            try:
                async with asyncio.timeout(self.header_timeout):
                    response = await client.send(client.build_request("GET", self.url), stream=True)
                response.raise_for_status()
                self._validate_resume(offset, True, total, response)
                if response.status_code != 206 or response.headers.get("content-range") != f"bytes {offset}-{end}/{total}":
                    raise httpx.ReadError("Twitter media returned an unexpected prefetched range")
                async with asyncio.timeout(self.idle_timeout):
                    content = await response.aread()
                if len(content) != end - offset + 1:
                    raise httpx.ReadError("Twitter media range was incomplete")
                return response
            except TimeoutError as exc:
                raise httpx.ReadTimeout("Twitter media range stalled") from exc
            finally:
                if response is not None:
                    await response.aclose()

    def _prefetch_ranges(self, offset: int, total: int) -> None:
        # At most two future ranges are buffered (512 KiB). Preserve output
        # order while overlapping network latency across three connections.
        for start in range(offset, min(total, offset + 2 * self.range_bytes), self.range_bytes):
            if start not in self.prefetched:
                self.prefetched[start] = asyncio.create_task(
                    self._fetch_range(start, total, self.proxy_url if self.using_proxy else None),
                )

    def raise_for_status(self) -> None:
        assert self.response is not None
        self.response.raise_for_status()

    async def aiter_bytes(self, chunk_size: int):
        assert self.response is not None
        identity = self.headers.get("content-encoding", "identity").lower() == "identity"
        length = self.headers.get("content-length", "")
        total = int(length) if identity and length.isdigit() else None
        sent = 0
        skip = 0
        while True:
            try:
                if self.ranged_media and self.response.status_code == 206 and total is not None:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", self.response.headers.get("content-range", ""))
                    if match:
                        self._prefetch_ranges(int(match[2]) + 1, total)
                # Fixed-size HTTPX chunks can hide tiny upstream trickles for
                # minutes without a socket read timeout. Forward each block so
                # progress and slow-transfer detection see actual network data.
                iterator = self.response.aiter_bytes().__aiter__()
                waiting = window_waiting = 0.0
                window_bytes = 0
                while True:
                    started = asyncio.get_running_loop().time()
                    try:
                        # Bound a small range, not the total duration of a
                        # healthy long video when a server ignores Range.
                        remaining = (
                            self.attempt_timeout - waiting
                            if self.image or (self.ranged_media and self.response.status_code == 206)
                            else self.idle_timeout
                        )
                        if remaining <= 0:
                            raise httpx.ReadTimeout("Twitter media transfer exceeded its time limit")
                        try:
                            async with asyncio.timeout(min(self.idle_timeout, remaining)):
                                chunk = await anext(iterator)
                        except TimeoutError as exc:
                            raise httpx.ReadTimeout("Twitter media transfer stalled") from exc
                    except StopAsyncIteration:
                        break
                    elapsed = asyncio.get_running_loop().time() - started
                    waiting += elapsed
                    window_waiting += elapsed
                    window_bytes += len(chunk)
                    if skip:
                        discarded = min(skip, len(chunk))
                        chunk = chunk[discarded:]
                        skip -= discarded
                    if chunk:
                        sent += len(chunk)
                        yield chunk
                    if window_waiting >= self.slow_window:
                        # Measure only time spent awaiting upstream data, not
                        # browser backpressure or writing the cache file.
                        if window_bytes < window_waiting * self.min_bytes_per_second and (total is None or sent < total):
                            raise httpx.ReadTimeout("Twitter media transfer remained too slow")
                        window_waiting = 0.0
                        window_bytes = 0
                if self.ranged_media and self.response.status_code == 206:
                    # Keep each CDN response small: long responses through some
                    # upstream routes repeatedly stall partway through a file.
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", self.response.headers.get("content-range", ""))
                    if not match or sent != int(match[2]) + 1:
                        raise httpx.ReadError("Twitter media range was incomplete")
                    if total is not None and sent < total:
                        pending = self.prefetched.pop(sent, None)
                        if pending is not None:
                            self.response = await pending
                            self.headers = self.response.headers
                        else:
                            await self._request(self.proxy_url if self.using_proxy else None, sent)
                        total, skip = self._validate_resume(sent, identity, total)
                        continue
                if skip or (total is not None and sent != total):
                    raise httpx.ReadError("Twitter media response was incomplete")
                return
            except httpx.HTTPError:
                if self.next_route >= len(self.routes):
                    raise
                # Bytes already streamed to the browser cannot be retracted.
                # Resume at that offset; if Range is ignored, discard the prefix.
                await self._request_next(sent if identity else 0)
                total, skip = self._validate_resume(sent, identity, total)

    async def aclose(self) -> None:
        pending = list(self.prefetched.values())
        self.prefetched.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        response, client = self.response, self.client
        self.response = None
        self.client = None
        try:
            if response is not None:
                await response.aclose()
        finally:
            if client is not None:
                await client.aclose()


async def download_twitter_media(url, filepath, proxy=None, media_type="video"):
    """下载图片、视频或 GIF；失败与取消时清理中间文件。"""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("推特媒体下载地址不能为空")
    if media_type not in {"image", "video", "gif"}:
        raise ValueError(f"不支持的推特媒体类型: {media_type}")
    url = url.strip()
    gif = media_type == "gif" or (media_type == "video" and is_twitter_gif(url))
    directory = Path(filepath)
    directory.mkdir(parents=True, exist_ok=True)
    extension = ".gif" if gif else {"image": ".jpg", "video": ".mp4"}[media_type]
    target = directory / f"twitter_{uuid.uuid4().hex}{extension}"
    source = target.with_suffix(".download")
    stream = TwitterMediaStream(
        twitter_gif_source(url), proxy,
        {"User-Agent": "Mozilla/5.0", "Referer": "https://x.com/"},
        image=media_type == "image",
    )
    complete = False
    try:
        try:
            await stream.open()
            async with aiofiles.open(source, "wb") as output:
                async for chunk in stream.aiter_bytes(128 * 1024):
                    await output.write(chunk)
        finally:
            await stream.aclose()
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError("推特媒体下载返回了空文件")
        if gif:
            await convert_twitter_gif(source, target)
            with target.open("rb") as output:
                if output.read(6) not in {b"GIF87a", b"GIF89a"}:
                    raise RuntimeError("GIF 转换未生成有效的 GIF 文件")
        else:
            source.replace(target)
        complete = True
        return str(target)
    finally:
        source.unlink(missing_ok=True)
        if not complete:
            target.unlink(missing_ok=True)
