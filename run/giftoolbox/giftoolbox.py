# -*- coding: utf-8 -*-
"""表情包工具箱（Eridanus 版）。

动图裁剪 / 分解 / 变速 / 倒放 / 做旧 / 线稿 / 表情合成 / 视频转 gif。

所有指令、指令说明以及触发后的回复文案都来自 run/giftoolbox/config.yaml，
用户可自行增删改；处理结果（倍数、帧率、张数等）由插件自动追加在后面。
"""
import asyncio
import base64
import json
import os
import re
import tempfile
import time
import threading
from functools import wraps
from pathlib import Path

import httpx

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import (
    At, Forward, Image, Mface, Node, Reply, Text, Video,
)
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from framework_common.utils.random_str import random_str

from .service import core
from .service.help_image import ensure_help_image
from .service.settings import command_items, enabled as _enabled

CACHE_DIR = "data/pictures/giftoolbox"
CACHE_MAX_AGE = 30 * 60        # 缓存文件保留 30 分钟
CLEANUP_INTERVAL = 10 * 60     # 至少间隔 10 分钟才做一次清理
INDEX_FILE = os.path.join(CACHE_DIR, ".sent_index.json")

_last_cleanup = 0.0
MAX_MEDIA_BYTES = 32 * 1024 * 1024
MAX_MEDIA_ITEMS = 100
_cache_lock = threading.RLock()


def _cache_operation(func):
    @wraps(func)
    def locked(*args, **kwargs):
        with _cache_lock:
            return func(*args, **kwargs)
    return locked


def _check_size(data):
    if len(data) > MAX_MEDIA_BYTES:
        raise core.ToolError("媒体文件过大，单个文件最多 32 MiB")
    return data


def _read_local(path):
    with open(path, "rb") as file:
        return _check_size(file.read(MAX_MEDIA_BYTES + 1))


def _temporary_video(data):
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return path


def _convert_video(source, data, *args):
    """Create, consume and remove the temporary file within one worker lifetime."""
    temporary = _temporary_video(data) if data is not None else None
    try:
        path = temporary or _local_path(source)
        if not os.path.isfile(path):
            raise core.ToolError("视频文件不可读")
        return core.video_to_gif(path, *args)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


async def _run_in_worker(func, *args, **kwargs):
    """Cancellation must not free a job slot or remove files while its thread is using them."""
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def _save_many(datas, ext):
    return [_save_bytes(data, ext) for data in datas]



# --------------------------------------------------------------------------
# 配置读取
# --------------------------------------------------------------------------

def _cfg(config: YAMLManager) -> dict:
    """每次取最新配置，config.yaml 的改动由 YAMLManager 热重载进来。"""
    try:
        data = config.giftoolbox.config
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _commands(cfg: dict) -> dict:
    return dict(enumerate(command_items(cfg)))


def _reply_text(item: dict) -> str:
    """指令自定义的那半句文案；为空表示不发送。"""
    v = item.get("reply", "")
    return str(v).strip() if v is not None else ""


def _num(x: float) -> str:
    s = f"{float(x):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _prefixes(cfg: dict) -> list:
    ps = cfg.get("prefixes") or []
    return sorted([str(p) for p in ps if str(p)], key=len, reverse=True)


def _strip_prefix(text: str, cfg: dict) -> str:
    t = (text or "").strip()
    for p in _prefixes(cfg):
        if t.startswith(p):
            return t[len(p):].strip()
    return t


# --------------------------------------------------------------------------
# 缓存与文件
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# 发送记录：插件发出的图，message_id → 本地文件
# 引用自己发的消息时优先走这里，绕开 QQ 的 get_msg（很多实现取不到含图的历史消息）
# --------------------------------------------------------------------------

_SENT_INDEX = {}          # message_id(str) -> {"ts": float, "paths": [str]}
_SENT_INDEX_MAX = 500


@_cache_operation
def _load_sent_index() -> None:
    """启动时读回上次记录的 message_id → 本地文件，重启后也能引用旧结果。"""
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    for mid, rec in data.items():
        if isinstance(rec, dict) and isinstance(rec.get("paths"), list):
            try:
                ts = float(rec.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if now - ts <= CACHE_MAX_AGE:
                _SENT_INDEX[str(mid)] = {"ts": ts, "paths": [str(p) for p in rec["paths"]]}


@_cache_operation
def _flush_sent_index() -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = INDEX_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_SENT_INDEX, f, ensure_ascii=False)
        os.replace(tmp, INDEX_FILE)
    except OSError:
        pass


@_cache_operation
def _remember_sent(result, paths) -> None:
    """把刚发送消息返回的 message_id 和对应的本地文件记下来（并落盘）。"""
    if not paths:
        return
    ids = _message_ids(result)
    if not ids:
        return
    for mid in ids:
        _SENT_INDEX[str(mid)] = {"ts": time.time(), "paths": list(paths)}
    if len(_SENT_INDEX) > _SENT_INDEX_MAX:
        for mid in sorted(_SENT_INDEX, key=lambda k: _SENT_INDEX[k]["ts"])[:len(_SENT_INDEX) - _SENT_INDEX_MAX]:
            _SENT_INDEX.pop(mid, None)
    _flush_sent_index()


def _message_ids(result) -> list:
    """从 send 返回值里挖出 message_id（不同适配器层级不一）。"""
    ids = []
    if isinstance(result, int):
        return [result]
    if not isinstance(result, dict):
        return ids
    data = result.get("data")
    if isinstance(data, dict):
        for k in ("message_id", "messageId", "msg_id", "message_seq", "id",
                  "forward_id", "res_id", "fid"):
            v = data.get(k)
            if v not in (None, ""):
                ids.append(v)
    elif isinstance(data, (int, str)):
        ids.append(data)
    for k in ("message_id", "msg_id", "message_seq", "forward_id", "res_id"):
        if result.get(k) not in (None, ""):
            ids.append(result[k])
    return list(dict.fromkeys(str(i) for i in ids))


@_cache_operation
def _paths_for_sent(mid) -> list:
    rec = _SENT_INDEX.get(str(mid))
    if not rec:
        return []
    return [p for p in rec["paths"] if p and os.path.isfile(_local_path(p))]


@_cache_operation
def _cleanup_cache() -> None:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    before = len(_SENT_INDEX)
    for mid in [m for m, r in _SENT_INDEX.items() if now - r["ts"] > CACHE_MAX_AGE]:
        _SENT_INDEX.pop(mid, None)
    if len(_SENT_INDEX) != before:
        _flush_sent_index()
    try:
        for name in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, name)
            try:
                if os.path.isfile(p) and not name.startswith(".") \
                        and now - os.path.getmtime(p) > CACHE_MAX_AGE:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _save_bytes(data: bytes, ext: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{random_str(12)}.{ext.lstrip('.')}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _ext_of(data: bytes, default: str = "gif") -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return default


def _processing_text(cfg: dict, item: dict):
    """识别到指令后先发的提示语；返回 None 表示不发。"""
    p = cfg.get("processing")
    if isinstance(p, dict) and p.get("enable", True) is False:
        return None
    if isinstance(p, dict):
        default = p.get("text", "")
    else:
        default = p if isinstance(p, str) else ""
    raw = item.get("processing", default)
    if raw is None:
        raw = default
    raw = str(raw).strip()
    return raw or None


def _forward_max_nodes(cfg: dict) -> int:
    try:
        n = int(cfg.get("forward_max_nodes", 100))
    except (TypeError, ValueError):
        n = 100
    return max(1, min(n, 100))


def _chunks(seq, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _chain_text(chain) -> str:
    return "".join(c.text for c in chain if isinstance(c, Text))


# --------------------------------------------------------------------------
# 图片 / 视频来源
# --------------------------------------------------------------------------

MAX_RESOLVE_DEPTH = 4          # 引用 / 转发最多向下展开几层
_ART_TYPES = ("image", "mface", "video")


def _media_of_item(item):
    """从一个消息段里取媒体地址（组件与原始 dict 都支持）。"""
    if isinstance(item, (Image, Mface, Video)):
        u = getattr(item, "url", "") or getattr(item, "file", "")
        return u if isinstance(u, str) and u else None
    if isinstance(item, dict):
        t = item.get("type")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if t in _ART_TYPES:
            u = data.get("url") or data.get("file") or item.get("url") or item.get("file")
            return u if isinstance(u, str) and u else None
    return None


def _seg_kind(item):
    """归一化成一个元组 (类型, 关键字段)，用于展开引用与转发。"""
    if isinstance(item, Reply):
        rid = getattr(item, "id", None)
        chain = getattr(item, "chain", None)
        return "reply", rid, chain
    if isinstance(item, Forward):
        return "forward", getattr(item, "id", None), None
    if isinstance(item, dict):
        t = item.get("type")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if t == "reply":
            return "reply", data.get("id") or data.get("message_id"), data.get("chain") or data.get("content")
        if t in ("forward", "node"):
            return "forward", data.get("id"), data.get("content") or data.get("message")
    return None, None, None


def _chains_in_container(raw):
    """从 get_forward_msg / node 的返回值里挖出所有节点消息链。

    节点常见两种形状：{"type":"node","data":{"content":[...]}} 和 {"content":[...]}。
    """
    chains = []
    if isinstance(raw, dict):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        nodes = data.get("messages") or data.get("nodes") or data.get("message") or []
        if isinstance(nodes, dict):
            nodes = [nodes]
        for node in nodes:
            if isinstance(node, dict):
                ndata = node.get("data") if isinstance(node.get("data"), dict) else {}
                content = (node.get("content") or node.get("message")
                           or ndata.get("content") or ndata.get("message"))
                if isinstance(content, list):
                    chains.append(content)
                elif isinstance(content, str):
                    chains.append([{"type": "text", "data": {"text": content}}])
            elif isinstance(node, list):
                chains.append(node)
    elif isinstance(raw, list):
        chains.append(raw)
    return chains


async def _fetch_forward(bot, fid):
    if not fid:
        return None
    try:
        if hasattr(bot, "get_forward_msg"):
            return await bot.get_forward_msg(str(fid))
    except Exception:
        pass
    for action, params in (
        ("get_forward_msg", {"id": str(fid)}),
        ("get_forward_msg", {"message_id": str(fid)}),
    ):
        try:
            if hasattr(bot, "_call_api"):
                return await bot._call_api(action, params)
        except Exception:
            continue
    return None


def _chain_from_message(msg):
    """把 get_msg 的各种返回形状统一成消息段列表。"""
    if msg is None:
        return []
    if isinstance(msg, list):
        return list(msg)
    if isinstance(msg, dict):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        chain = data.get("message") or data.get("messages")
        if isinstance(chain, list):
            return list(chain)
        return []
    for attr in ("message_chain", "message"):
        chain = getattr(msg, attr, None)
        if isinstance(chain, list) and chain:
            return list(chain)
    return []


async def _fetch_message(bot, mid):
    """拉取一条历史消息，返回消息段列表；取不到返回空列表。"""
    if mid is None:
        return []
    try:
        mid_int = int(mid)
    except (TypeError, ValueError):
        return []

    # 走适配器封装
    try:
        chain = _chain_from_message(await bot.get_msg(mid_int))
        if chain:
            return chain
    except Exception:
        pass

    # 退回原始 API（部分适配器的 get_msg 在 data 为空时会直接抛异常）
    if hasattr(bot, "_call_api"):
        try:
            raw = await bot._call_api("get_msg", {"message_id": mid_int})
            chain = _chain_from_message(raw)
            if chain:
                return chain
        except Exception:
            pass
    return []


async def _resolve_media(bot, chain, allow_avatar: bool, depth: int = 0,
                         visited: set = None, urls: list = None) -> list:
    """递归展开 消息段 → 引用消息 → 合并转发 → 嵌套转发，按顺序收集媒体地址。

    关键点：引用一条「合并转发」时，引用链里只有一个 forward 引用（只有 id，
    没有内容），必须再调 get_forward_msg 才能真正拿到图片，所以这里逐层下钻。
    """
    if urls is None:
        urls = []
    if visited is None:
        visited = set()
    if depth > MAX_RESOLVE_DEPTH or not isinstance(chain, list):
        return urls

    for item in chain:
        u = _media_of_item(item)
        if len(urls) >= MAX_MEDIA_ITEMS:
            break
        if u and u not in urls:
            urls.append(u)
            continue

        kind, key, inline = _seg_kind(item)
        if kind is None:
            continue
        if inline:
            await _resolve_media(bot, list(inline), allow_avatar, depth + 1, visited, urls)
            continue
        if key is None:
            continue

        tag = (kind, str(key))
        if tag in visited:
            continue
        visited.add(tag)

        if kind == "reply":
            # 1) 优先：引用的是插件自己发出的消息，直接拿本地文件
            cached = await _run_in_worker(_paths_for_sent, key)
            if cached:
                for p in cached:
                    if p not in urls:
                        urls.append(p)
                continue
            # 2) 退回：向 QQ 拉取被引用消息
            inner = await _fetch_message(bot, key)
            if inner:
                await _resolve_media(bot, inner, allow_avatar, depth + 1, visited, urls)
        elif kind == "forward":
            cached = await _run_in_worker(_paths_for_sent, key)
            if cached:
                for p in cached:
                    if p not in urls:
                        urls.append(p)
                continue
            raw = await _fetch_forward(bot, key)
            for inner in _chains_in_container(raw):
                await _resolve_media(bot, inner, allow_avatar, depth + 1, visited, urls)

    if not urls and allow_avatar and depth == 0:
        for item in chain:
            if isinstance(item, At) and getattr(item, "qq", None):
                urls.append(f"https://q1.qlogo.cn/g?b=qq&nk={item.qq}&s=640")
    return urls


async def _collect_media(bot, event, allow_avatar: bool = True) -> list:
    """当前消息 → 被引用消息 → 合并转发（可嵌套）→ @对象头像。"""
    chain = list(event.message_chain)
    urls = await _resolve_media(bot, chain, allow_avatar)

    # 部分适配器把引用单独放在 event.reply 里（消息链中没有 reply 段）
    if not urls:
        reply = getattr(event, "reply", None)
        if reply is not None:
            if isinstance(reply, (dict, list)):
                extra = [reply]
            else:
                extra = []
                for attr in ("message", "message_chain"):
                    inner = getattr(reply, attr, None)
                    if isinstance(inner, list) and inner:
                        extra = list(inner)
                        break
                if not extra:
                    rid = getattr(reply, "id", None) or getattr(reply, "message_id", None)
                    if rid is not None:
                        extra = [{"type": "reply", "data": {"id": rid}}]
            if extra:
                urls = await _resolve_media(bot, extra, allow_avatar)
    return urls


def _has_reply(chain) -> bool:
    for item in chain:
        kind, _, _ = _seg_kind(item)
        if kind in ("reply", "forward"):
            return True
    return False


def _no_media_reason(event) -> str:
    """取不到图时给一句能定位问题的原因。"""
    if _has_reply(list(event.message_chain)):
        return "引用的消息里没有解析到图片，可能是不支持解析的转发卡片，请直接发图片或回复单张图"
    return "请回复一张动图再试"


def _local_path(src: str) -> str:
    s = str(src)
    if s.startswith("file://"):
        s = s[7:]
        if re.match(r"^/[A-Za-z]:", s):
            s = s[1:]
    return os.path.normpath(s)


async def _download(src: str) -> bytes:
    """下载 URL / 读取本地文件 / 解 base64://。"""
    if not src:
        raise core.ToolError("没有拿到可用的媒体地址")
    s = str(src).strip()

    if s.startswith("base64://"):
        try:
            if len(s) > (MAX_MEDIA_BYTES + 2) // 3 * 4 + 9:
                raise core.ToolError("媒体文件过大")
            return await _run_in_worker(lambda: _check_size(base64.b64decode(s[9:], validate=True)))
        except core.ToolError:
            raise
        except Exception:
            raise core.ToolError("base64 图片解析失败")

    if not s.lower().startswith(("http://", "https://")):
        path = _local_path(s)
        try:
            return await _run_in_worker(_read_local, path)
        except FileNotFoundError:
            raise core.ToolError("本地文件不存在")
        except OSError as e:
            raise core.ToolError(f"本地文件读取失败（{e.strerror or e}）")

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"},
                                     timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", s) as resp:
                if resp.status_code != 200:
                    raise core.ToolError(f"下载失败（HTTP {resp.status_code}）")
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    if len(data) + len(chunk) > MAX_MEDIA_BYTES:
                        raise core.ToolError("媒体文件过大，单个文件最多 32 MiB")
                    data.extend(chunk)
                if not data:
                    raise core.ToolError("下载到的是空内容")
                return bytes(data)
    except core.ToolError:
        raise
    except Exception as e:
        raise core.ToolError(f"下载失败（{type(e).__name__}）")


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

def _parse_speed(arg: str, item: dict):
    """返回 (mode, value)；mode='factor' 是倍数，'fps' 是目标帧率。"""
    t = (arg or "").strip().lower()
    direction = str(item.get("direction", "auto")).lower()

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:fps|帧)", t)
    if m:
        val = float(m.group(1))
        if val <= 0:
            raise core.ToolError("目标帧率必须大于 0")
        return "fps", val

    try:
        default = float(item.get("default_value", 2))
    except (TypeError, ValueError):
        default = 2.0

    m = re.search(r"(\d+(?:\.\d+)?)", t)
    val = float(m.group(1)) if m else default
    if val <= 0:
        raise core.ToolError("倍数必须大于 0")
    if direction == "dec":
        return "factor", 1.0 / val
    return "factor", val


def _parse_crop(arg: str):
    margins = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    text = arg or ""
    pat = r"边距\s*([上下左右])?边?\s*(\d+)"
    side = {"上": "top", "下": "bottom", "左": "left", "右": "right"}
    for direction, num in re.findall(pat, text):
        try:
            n = int(num)
        except ValueError:
            continue
        if not direction:
            for k in margins:
                margins[k] += n
        else:
            margins[side[direction]] += n
    text = re.sub(pat, " ", text)
    m = re.search(r"(\d+)\s*[*x×]\s*(\d+)", text)
    rows, cols = (int(m.group(1)), int(m.group(2))) if m else (1, 1)
    return rows, cols, margins


def _parse_age(arg: str, item: dict) -> int:
    m = re.search(r"(\d+)", arg or "")
    if m:
        times = int(m.group(1))
    else:
        try:
            times = int(item.get("default_times", 5))
        except (TypeError, ValueError):
            times = 5
    return max(1, min(times, 50))


def _parse_concat(arg: str, item: dict) -> float:
    t = arg or ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:fps|帧)", t, re.I)
    if m:
        fps = float(m.group(1))
        if fps > 0:
            return 1.0 / fps
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if m:
        val = float(m.group(1))
        if 0.01 <= val <= 60:
            return val
    try:
        return float(item.get("default_frame_sec", 0.5))
    except (TypeError, ValueError):
        return 0.5


def _parse_video(arg: str, item: dict):
    text = arg or ""
    start, end = 0.0, None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[sS]?\s*[-~]\s*(\d+(?:\.\d+)?)\s*[sS]?", text)
    if m:
        start, end = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(r"(?:开始|start)\s*(\d+(?:\.\d+)?)", text)
        if m:
            start = float(m.group(1))
        m = re.search(r"(?:时长|len)\s*(\d+(?:\.\d+)?)", text)
        if m:
            end = start + float(m.group(1))

    try:
        fps = float(item.get("default_fps", 10))
        scale = float(item.get("default_scale", 0.3))
        max_dur = float(item.get("max_duration", 10))
    except (TypeError, ValueError):
        fps, scale, max_dur = 10.0, 0.3, 10.0

    m = re.search(r"(?:fps|帧率)\s*(\d+)", text, re.I)
    if m:
        fps = float(m.group(1))
    m = re.search(r"(?:缩放|scale)\s*(0?\.\d+)", text, re.I)
    if m:
        scale = float(m.group(1))
    scale = max(0.05, min(scale, 1.0))
    return start, end, fps, scale, max_dur


# --------------------------------------------------------------------------
# 结果文案
# --------------------------------------------------------------------------

def _speed_suffix(mode: str, info: dict) -> str:
    if mode == "fps":
        return f"目标 {info['dst_fps']:.0f}fps | 原 {info['src_fps']:.1f}fps"
    f = info["factor"]
    label = "加速" if f > 1 else ("减速" if f < 1 else "")
    return f"{_num(f)}x{label} | 原 {info['src_fps']:.1f}fps → 等效 {info['dst_fps']:.1f}fps"


def _compose(reply: str, suffix: str) -> str:
    if reply and suffix:
        return f"{reply}{suffix}"
    return reply or suffix


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main(bot: ExtendBot, config: YAMLManager):
    active_jobs = 0
    initialized = False
    init_lock = asyncio.Lock()

    def _match(text: str, cfg: dict):
        """返回 (item, 参数字符串)；未命中返回 (None, "")。最长触发词优先。"""
        t = _strip_prefix(text, cfg)
        low = t.lower()
        best = (None, "", 0)
        for item in _commands(cfg).values():
            if not isinstance(item, dict) or not _enabled(item):
                continue
            for trig in (item.get("triggers") or []):
                trig = str(trig).strip()
                if not trig or not low.startswith(trig.lower()):
                    continue
                if len(trig) > best[2]:
                    best = (item, t[len(trig):].strip(), len(trig))
        return best[0], best[1]

    def _help_text(cfg: dict) -> str:
        h = cfg.get("help") or {}
        lines = [str(h.get("title", "📦 表情包工具箱"))]
        intro = str(h.get("intro", "") or "")
        footer = str(h.get("footer", "") or "")
        if intro:
            lines += ["", intro]

        cmds = [v for v in _commands(cfg).values()
                if isinstance(v, dict) and _enabled(v)]
        if cmds:
            lines += ["", "【指令】"]
            for idx, item in enumerate(cmds, 1):
                name = str(item.get("name") or "").strip()
                desc = str(item.get("desc") or "").strip()
                usage = str(item.get("usage") or "").strip()
                trig = [str(t).strip() for t in (item.get("triggers") or []) if str(t).strip()]
                head = f"{idx}. {name}" if name else f"{idx}."
                if desc:
                    head += f"：{desc}"
                lines.append(head)
                if trig:
                    lines.append(f"    触发：{' / '.join(trig)}")
                if usage:
                    lines.append(f"    用法：{usage}")

        lines += ["", "【提示】", "· 回复图片 / 动图后再发指令，或把图和指令发在同一条消息里"]
        ps = _prefixes(cfg)
        if ps:
            lines.append(f"· 指令前可以加前缀：{' '.join(ps)}")
        if footer:
            lines.append(f"· {footer}")
        return "\n".join(lines)

    async def _send_image(event, data: bytes, cfg: dict, text: str = "", split_mb: float = None):
        """带图结果：体积小就一条消息；较大时先文字后纯图片，避免动图被压成静图。

        发出的图片消息会记进发送索引，用户之后再引用它就能直接命中本地文件。
        """
        path = await _run_in_worker(_save_bytes, data, _ext_of(data))
        size_mb = len(data) / 1024.0 / 1024.0
        try:
            limit = float(split_mb if split_mb is not None else cfg.get("split_mb", 1.0))
        except (TypeError, ValueError):
            limit = 1.0

        sent = []
        if not text:
            sent.append(await bot.send(event, [Image(file=path)]))
        elif size_mb > limit:
            sent.append(await bot.send(event, [Text(text)]))
            sent.append(await bot.send(event, [Image(file=path)]))
        else:
            sent.append(await bot.send(event, [Text(text), Image(file=path)]))
        for r in sent:
            await _run_in_worker(_remember_sent, r, [path])

    async def _first_media(event, cfg: dict, kind: str):
        srcs = await _collect_media(bot, event, allow_avatar=(kind == "图片"))
        if not srcs:
            raise core.ToolError(f"没有找到{kind}，{_no_media_reason(event)}")
        return await _download(srcs[0])

    async def _send_nodes_in_batches(event, nodes: list, cfg: dict, label: str = ""):
        """按 forward_max_nodes 分批发合并转发，单批不超过聊天记录上限，超出不丢图。"""
        size = _forward_max_nodes(cfg)
        multi = len(nodes) > size
        # 多条时每批前面会插一条标题节点，给它留出位置
        per = max(1, size - 1) if (multi and label) else size
        batches = list(_chunks(nodes, per))
        for idx, batch in enumerate(batches, 1):
            if len(batches) > 1 and label and size > 1:
                batch = [Node(content=[Text(f"{label}（{idx}/{len(batches)}）")])] + batch
            res = await bot.send(event, batch)
            paths = []
            for n in batch:
                for c in getattr(n, "content", []) or []:
                    f = getattr(c, "file", None)
                    if isinstance(f, str) and f:
                        paths.append(f)
            await _run_in_worker(_remember_sent, res, paths)
        return len(batches)

    async def _handle(event, item: dict, args: str, cfg: dict):
        action = str(item.get("action", "")).strip().lower()
        reply = _reply_text(item)
        fmt = str(cfg.get("output_format", "GIF"))

        if action == "reverse":
            srcs = await _collect_media(bot, event)
            if not srcs:
                raise core.ToolError(f"没有找到动图，{_no_media_reason(event)}")
            data = await _download(srcs[0])
            if reply:
                await bot.send(event, [Text(reply)])
            out, _ = await _run_in_worker(core.reverse, data, fmt)
            await _send_image(event, out, cfg)
            return

        if action == "speed":
            mode, value = _parse_speed(args, item)
            data = await _first_media(event, cfg, "动图")
            out, info = await _run_in_worker(core.speed_change, data, mode, value, fmt)
            text = _compose(reply, _speed_suffix(mode, info))
            if info.get("dropped"):
                text += f"\n💡 帧太多装不下，抽出 {info['kept']}/{info['total_frames']} 帧"
            await _send_image(event, out, cfg, text)
            return

        if action == "decompose":
            data = await _first_media(event, cfg, "动图")
            try:
                max_frames = int(item.get("max_frames") or cfg.get("decompose_max_frames") or 500)
            except (TypeError, ValueError):
                max_frames = 500
            frames = await _run_in_worker(core.decompose, data, max(1, min(500, max_frames)))
            label = str(item.get("frame_label") or "第{n}帧")
            total = len(frames)
            if reply:
                await bot.send(event, [Text(f"{reply}（共 {total} 帧）")])
            paths = await _run_in_worker(_save_many, frames, "png")
            nodes = [
                Node(content=[Text(label.replace("{n}", str(i))), Image(file=path)])
                for i, path in enumerate(paths, 1)
            ]
            batches = await _send_nodes_in_batches(event, nodes, cfg, label="分解")
            if batches > 1:
                await bot.send(event, [Text(
                    f"共 {total} 帧，超出单条聊天记录上限，已分成 {batches} 条发送～")])
            return

        if action == "crop":
            rows, cols, margins = _parse_crop(args)
            if rows > 20 or cols > 20:
                raise core.ToolError("格子太密了，最多 20x20")
            data = await _first_media(event, cfg, "图片")
            crops = await _run_in_worker(core.crop_grid, data, rows, cols, margins)
            if reply:
                await bot.send(event, [Text(f"{reply}（{rows}x{cols}，共 {len(crops)} 张）")])
            paths = await _run_in_worker(_save_many, crops, "png")
            nodes = [Node(content=[Image(file=path)]) for path in paths]
            await _send_nodes_in_batches(event, nodes, cfg, label="裁剪")
            return

        if action == "age":
            times = _parse_age(args, item)
            data = await _first_media(event, cfg, "图片")
            out, info = await _run_in_worker(core.age, data, times, fmt)
            suffix = f"{times}次做旧"
            if info["frames"] > 1:
                suffix += f" · {info['frames']}帧"
            await _send_image(event, out, cfg, _compose(reply, suffix))
            return

        if action == "lineart":
            data = await _first_media(event, cfg, "图片")
            out = await _run_in_worker(core.lineart, data)
            await _send_image(event, out, cfg, reply)
            return

        if action == "concat":
            frame_sec = _parse_concat(args, item)
            srcs = await _collect_media(bot, event)
            if not srcs:
                raise core.ToolError(f"没有找到图片，{_no_media_reason(event)}")
            datas = []
            for s in srcs:
                try:
                    data = await _download(s)
                except core.ToolError:
                    continue
                if sum(map(len, datas)) + len(data) > MAX_MEDIA_BYTES:
                    raise core.ToolError("合成输入总计最多 32 MiB")
                datas.append(data)
            if not datas:
                raise core.ToolError("图片全都下载失败了")
            out, info = await _run_in_worker(core.concat, datas, frame_sec, fmt)
            text = _compose(reply, f"{info['n']}张 · {info['frames']}帧 · {info['t']:.1f}s")
            if info["frames"] < 2:
                text += "\n💡 只有一帧，动不起来哦～多给几张图试试"
            # 动图混排容易被当成静图，强制先文字后图片
            await _send_image(event, out, cfg, text, split_mb=0)
            return

        if action == "video":
            start, end, fps, scale, max_dur = _parse_video(args, item)
            srcs = await _collect_media(bot, event, allow_avatar=False)
            if not srcs:
                raise core.ToolError(f"没有找到视频，{_no_media_reason(event)}")
            source = str(srcs[0])
            data = await _download(source) if source.lower().startswith(("http://", "https://", "base64://")) else None
            if reply:
                await bot.send(event, [Text(reply)])
            out, info = await _run_in_worker(
                _convert_video, source, data, start, end, fps, scale, fmt, max_dur
            )
            suffix = f"{info['frames']}帧 · {info['fps']:.1f}fps"
            if info.get("truncated"):
                suffix += " · 已截断"
            await _send_image(event, out, cfg, suffix)
            return

        raise core.ToolError(f"未知的指令类型：{action}")

    async def _on_message(event):
        nonlocal active_jobs, initialized
        cfg = _cfg(config)
        if not cfg.get("enable", True):
            return
        if isinstance(event, PrivateMessageEvent) and not cfg.get("enable_private", True):
            return

        text = _chain_text(event.message_chain).strip()
        if not text:
            return

        commands = _commands(cfg)
        if not commands:
            return

        help_cfg = cfg.get("help") or {}
        help_triggers = [str(t).strip() for t in (help_cfg.get("triggers") or []) if str(t).strip()]
        if _strip_prefix(text, cfg) in help_triggers:
            try:
                img_path = await ensure_help_image(cfg)
                await bot.send(event, [Image(file=img_path)])
            except Exception as e:
                bot.logger.warning(f"[giftoolbox] 生成帮助图片失败: {type(e).__name__}: {e}")
                await bot.send(event, [Text("生成帮助图片失败")])
                await bot.send(event, [Text(_help_text(cfg))])
            return

        item, args = _match(text, cfg)
        if item is None:
            return

        fail_prefix = str(cfg.get("fail_reply", "表情包处理失败") or "表情包处理失败")
        name = item.get("name") or item.get("action") or "指令"
        if active_jobs >= 2:
            await bot.send(event, [Text("表情包工具正在处理其他任务，请稍后重试")])
            return
        active_jobs += 1
        try:
            async with init_lock:
                if not initialized:
                    await _run_in_worker(_load_sent_index)
                    initialized = True
            await _run_in_worker(_cleanup_cache)
            hint = _processing_text(cfg, item)
            if hint:
                await bot.send(event, [Text(hint)])
            await _handle(event, item, args, cfg)
        except core.ToolError as e:
            bot.logger.warning(f"[giftoolbox] {name} 处理失败: {e}")
            await bot.send(event, [Text(f"{fail_prefix}（{e}）")])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            bot.logger.error(f"[giftoolbox] {name} 异常: {type(e).__name__}: {e}")
            reason = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            await bot.send(event, [Text(f"{fail_prefix}（{reason}）")])
        finally:
            active_jobs -= 1

    @bot.on(GroupMessageEvent)
    async def _(event: GroupMessageEvent):
        await _on_message(event)

    @bot.on(PrivateMessageEvent)
    async def _(event: PrivateMessageEvent):
        await _on_message(event)

    bot.logger.info("[giftoolbox] 表情包工具箱已加载")
