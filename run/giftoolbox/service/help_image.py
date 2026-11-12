import asyncio
import glob
import importlib
import hashlib
import json
import os
from .settings import command_items, enabled


HELP_DIR = os.path.join("data", "pictures", "cache")
HELP_PREFIX = "giftoolbox_help_"


def escape(text):
    return str(text).replace("[", "［").replace("]", "］")


def help_items(cfg):
    return [item for item in command_items(cfg) if enabled(item)]


def help_fingerprint(cfg):
    payload = {"help": cfg.get("help"), "items": help_items(cfg), "prefixes": cfg.get("prefixes")}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def help_line(index, item):
    head = str(index) + ". " + str(item.get("name") or "")
    desc = item.get("desc")
    if desc:
        head += "：" + str(desc)
    lines = [escape(head)]
    triggers = [str(t) for t in (item.get("triggers") or [])]
    if triggers:
        lines.append(escape("    触发：" + " / ".join(triggers)))
    usage = item.get("usage")
    if usage:
        lines.append(escape("    用法：" + str(usage)))
    return lines


def help_body(cfg):
    h = cfg.get("help") or {}
    lines = ["[title]" + escape(h.get("title") or "表情包工具箱") + "[/title]"]
    intro = h.get("intro")
    if intro:
        lines.append("[des]" + escape(intro) + "[/des]")
    for index, item in enumerate(help_items(cfg), 1):
        lines.extend(help_line(index, item))
    lines.append("[des]提示[/des]")
    lines.append("· 回复图片 / 动图后再发指令，或把图和指令发在同一条消息里")
    footer = h.get("footer")
    if footer:
        lines.append(escape("· " + str(footer)))
    return "\n".join(lines)


def remove_old_help(keep_name):
    for path in glob.glob(os.path.join(HELP_DIR, HELP_PREFIX + "*.png")):
        if os.path.basename(path) != keep_name:
            try:
                os.remove(path)
            except OSError:
                pass


_help_lock = asyncio.Lock()


async def ensure_help_image(cfg):
    async with _help_lock:
        return await _ensure_help_image(cfg)


async def _ensure_help_image(cfg):
    name = HELP_PREFIX + help_fingerprint(cfg) + ".png"
    path = os.path.join(HELP_DIR, name)
    if await asyncio.to_thread(os.path.isfile, path):
        await asyncio.to_thread(remove_old_help, name)
        return path
    renderer = await asyncio.to_thread(importlib.import_module, "framework_common.manshuo_draw.manshuo_draw")
    manshuo_draw = renderer.manshuo_draw
    result = await manshuo_draw([
        {"type": "basic_set", "img_name_save": name, "debug": False},
        {"type": "backdrop", "subtype": "one_color"},
        {"type": "text", "content": [help_body(cfg)]},
    ])
    if not result or not await asyncio.to_thread(os.path.isfile, result):
        raise RuntimeError("绘图框架没有生成文件")
    await asyncio.to_thread(remove_old_help, os.path.basename(result))
    return result
