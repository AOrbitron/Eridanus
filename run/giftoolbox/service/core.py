# -*- coding: utf-8 -*-
"""表情包图像处理核心。

全部是同步纯函数（CPU 密集），调用方用 asyncio.to_thread 包起来。
失败统一抛 ToolError，异常信息就是给用户看的失败原因。
"""
import io
import random

from PIL import Image as PILImage, ImageSequence, ImageFilter, ImageOps, ImageEnhance

MIN_FRAME_MS = 20          # GIF 最小帧间隔，等效 50fps 上限
MAX_FPS = 50
MAX_FRAME_MS = 1000        # 单帧最长 1s，等效 1fps 下限


class ToolError(Exception):
    """处理失败，异常信息即失败原因。"""


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def _open(data: bytes) -> PILImage.Image:
    if not data:
        raise ToolError("图片内容为空")
    try:
        return PILImage.open(io.BytesIO(data))
    except Exception:
        raise ToolError("无法识别图片格式")


def _frames(img):
    """返回 (逐帧图像, 逐帧时长)；不是动图时返回 (None, None)。"""
    if not getattr(img, "is_animated", False):
        return None, None
    frames, durations = [], []
    for frame in ImageSequence.Iterator(img):
        try:
            dur = int(frame.info.get("duration") or 0)
        except Exception:
            dur = 0
        durations.append(dur if dur > 0 else 100)
        frames.append(frame.copy())
    if not frames:
        raise ToolError("动图里没有读到任何帧")
    return frames, durations


def _to_gif_frames(frames):
    """统一到共享调色板，顺带处理透明像素，避免不同帧颜色乱跳。"""
    has_alpha = any("A" in f.getbands() for f in frames)
    w, h = frames[0].size
    n = min(len(frames), 16)
    montage = PILImage.new("RGB", (w * n, h), (255, 255, 255))
    for i, f in enumerate(frames[:n]):
        montage.paste(f.convert("RGB").resize((w, h)), (i * w, 0))
    palette = montage.quantize(colors=255 if has_alpha else 256, method=1)

    out = []
    for f in frames:
        rgba = f.convert("RGBA").resize((w, h))
        p = rgba.convert("RGB").quantize(palette=palette)
        if has_alpha:
            mask = rgba.getchannel("A").point(lambda a: 255 if a < 128 else 0)
            p.paste(255, mask=mask)
        out.append(p)
    return out, has_alpha


def _save_anim(frames, durations, fmt="GIF", loop=0) -> bytes:
    fmt = (fmt or "GIF").upper()
    if not frames:
        raise ToolError("没有可保存的帧")
    if len(durations) != len(frames):
        durations = [100] * len(frames)
    out = io.BytesIO()
    try:
        if fmt == "GIF":
            gif_frames, has_alpha = _to_gif_frames(frames)
            kwargs = {"transparency": 255, "background": 255} if has_alpha else {}
            gif_frames[0].save(
                out, format="GIF", save_all=True, append_images=gif_frames[1:],
                duration=durations, loop=loop, disposal=2,
                optimize=not has_alpha, **kwargs,
            )
        elif fmt == "WEBP":
            frames[0].convert("RGBA").save(
                out, format="WEBP", save_all=True, append_images=frames[1:],
                duration=durations, loop=loop, quality=80, method=3,
            )
        elif fmt == "APNG":
            frames[0].convert("RGBA").save(
                out, format="PNG", save_all=True, append_images=frames[1:],
                duration=durations, loop=loop, default_image=True,
            )
        else:
            raise ToolError(f"不支持的输出格式：{fmt}")
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"保存动图失败（{type(e).__name__}: {e}）")
    return out.getvalue()


# --------------------------------------------------------------------------
# 变速
# --------------------------------------------------------------------------

def speed_change(data: bytes, mode: str, value: float, fmt="GIF"):
    """mode: 'factor'（倍速）| 'fps'（目标帧率）。返回 (bytes, info)。"""
    img = _open(data)
    frames, durations = _frames(img)
    if frames is None:
        raise ToolError("目标图片不是动图")

    total = sum(durations)
    src_fps = 1000.0 * len(durations) / total if total else 10.0
    dropped = False
    orig_frames = len(frames)
    kept = orig_frames

    if mode == "fps":
        target = float(value)
        if target <= 0:
            raise ToolError("目标帧率必须大于 0")
        if target > MAX_FPS:
            # GIF 帧间隔最小 20ms，更高帧率靠抽帧实现
            keep = max(2, int(len(frames) * MAX_FPS / target))
            keep = min(keep, len(frames))
            idx = [int(i * len(frames) / keep) for i in range(keep)]
            frames = [frames[i] for i in idx]
            durations = [MIN_FRAME_MS] * len(frames)
            dropped = True
        else:
            durations = [max(MIN_FRAME_MS, int(1000.0 / target))] * len(frames)
    else:
        factor = float(value)
        if factor <= 0:
            raise ToolError("倍数必须大于 0")
        scaled = [min(MAX_FRAME_MS, max(1, int(round(d / factor)))) for d in durations]
        if sum(scaled) / len(scaled) < MIN_FRAME_MS:
            # 时长压到 20ms 以下就装不下了，按总时长抽帧
            want_total = total / factor
            keep = max(2, int(want_total // MIN_FRAME_MS))
            keep = min(keep, len(frames))
            idx = [int(i * len(frames) / keep) for i in range(keep)]
            frames = [frames[i] for i in idx]
            durations = [MIN_FRAME_MS] * len(frames)
            dropped = True
        else:
            durations = scaled

    dst_fps = 1000.0 / (sum(durations) / len(durations))
    out = _save_anim(frames, durations, fmt)
    dropped = len(frames) < orig_frames
    info = {
        "factor": float(value) if mode == "factor" else dst_fps / src_fps if src_fps else 1.0,
        "src_fps": src_fps,
        "dst_fps": dst_fps,
        "kept": len(frames),
        "total_frames": orig_frames,
        "dropped": dropped,
    }
    return out, info


# --------------------------------------------------------------------------
# 倒放
# --------------------------------------------------------------------------

def reverse(data: bytes, fmt="GIF"):
    img = _open(data)
    frames, durations = _frames(img)
    if frames is None:
        raise ToolError("目标图片不是动图")
    if len(frames) < 2:
        raise ToolError("只有一帧，倒过来也还是它")
    frames.reverse()
    durations.reverse()
    out = _save_anim(frames, durations, fmt)
    return out, {"n": len(frames), "t": sum(durations) / 1000.0}


# --------------------------------------------------------------------------
# 分解
# --------------------------------------------------------------------------

def decompose(data: bytes, max_frames: int = 100):
    img = _open(data)
    frames, _ = _frames(img)
    if frames is None:
        raise ToolError("目标图片不是动图")
    out = []
    for frame in frames[:max_frames]:
        buf = io.BytesIO()
        frame.convert("RGBA").save(buf, format="PNG")
        out.append(buf.getvalue())
    if not out:
        raise ToolError("没有拆出任何帧")
    return out


# --------------------------------------------------------------------------
# 裁剪
# --------------------------------------------------------------------------

def crop_grid(data: bytes, rows: int, cols: int, margins: dict = None):
    img = _open(data).convert("RGBA")
    margins = margins or {}
    left = int(margins.get("left", 0))
    top = int(margins.get("top", 0))
    right = int(margins.get("right", 0))
    bottom = int(margins.get("bottom", 0))
    w, h = img.size
    if left + right >= w or top + bottom >= h:
        raise ToolError(f"切边超出图片尺寸（{w}x{h}）")
    img = img.crop((left, top, w - right, h - bottom))
    w, h = img.size
    cw, ch = w // cols, h // rows
    if cw < 1 or ch < 1:
        raise ToolError(f"图片太小，无法切成 {rows}x{cols}")

    out = []
    for r in range(rows):
        for c in range(cols):
            buf = io.BytesIO()
            img.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)).save(buf, format="PNG")
            out.append(buf.getvalue())
    return out


# --------------------------------------------------------------------------
# 做旧
# --------------------------------------------------------------------------

def _age_single_frame(img, times: int):
    if img.mode != "RGB":
        img = img.convert("RGB")
    for i in range(times):
        if i % 3 == 0:
            r, g, b = img.split()
            g = g.point(lambda x, v=random.randint(1, 2): min(255, x + v))
            rr = random.randint(0, 1)
            br = random.randint(0, 1)
            if rr:
                r = r.point(lambda x, v=rr: max(0, x - v))
            if br:
                b = b.point(lambda x, v=br: max(0, x - v))
            img = PILImage.merge("RGB", (r, g, b))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=max(25, 70 - i * 3))
        buf.seek(0)
        img = PILImage.open(buf).convert("RGB")

        if i % 3 == 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=0.2 + (i // 3) * 0.1))
        if i % 5 == 2:
            img = img.filter(ImageFilter.SHARPEN)
        if i % 2 == 0:
            img = ImageEnhance.Color(img).enhance(max(0.85, 1.0 - 0.015))
        if i % 2 == 1:
            img = ImageEnhance.Contrast(img).enhance(max(0.85, 1.0 - 0.01))
        if times >= 15 and i == times // 2:
            w, h = img.size
            if w > 50 and h > 50:
                small = img.resize((int(w * 0.8), int(h * 0.8)), PILImage.Resampling.BILINEAR)
                img = small.resize((w, h), PILImage.Resampling.BILINEAR)
    return img


def age(data: bytes, times: int, fmt="GIF"):
    times = max(1, min(int(times), 50))
    img = _open(data)
    if getattr(img, "is_animated", False):
        frames, durations = _frames(img)
        aged = [_age_single_frame(f.convert("RGB"), times) for f in frames]
        return _save_anim(aged, durations, fmt), {"times": times, "frames": len(aged)}
    out = _age_single_frame(img.convert("RGB"), times)
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=max(30, 70 - times * 3))
    return buf.getvalue(), {"times": times, "frames": 1}


# --------------------------------------------------------------------------
# 线稿
# --------------------------------------------------------------------------

def lineart(data: bytes) -> bytes:
    img = _open(data).convert("RGB")
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    result = ImageOps.invert(edges)
    result = ImageEnhance.Contrast(result).enhance(3.0)
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# --------------------------------------------------------------------------
# 表情合成（多图按顺序接成动图）
# --------------------------------------------------------------------------

def _frame_duration(img, default_ms: int) -> int:
    try:
        d = int(img.info.get("duration") or 0)
    except Exception:
        d = 0
    if d <= 0:
        d = default_ms
    return max(MIN_FRAME_MS, min(d, 10000))


def _fit_to_canvas(img, cw: int, ch: int):
    bg = PILImage.new("RGBA", (cw, ch), (255, 255, 255, 0))
    src_ratio = img.width / img.height
    tgt_ratio = cw / ch
    if src_ratio > tgt_ratio:
        new_w, new_h = cw, max(1, int(cw / src_ratio))
    else:
        new_h, new_w = ch, max(1, int(ch * src_ratio))
    resized = img.resize((new_w, new_h), PILImage.Resampling.BILINEAR)
    bg.paste(resized, ((cw - new_w) // 2, (ch - new_h) // 2),
             mask=resized if "A" in resized.getbands() else None)
    return bg


def _decimate(durations, max_frames: int):
    n = len(durations)
    if n <= max_frames:
        return list(range(n)), list(durations)
    step = n / float(max_frames)
    keep_idx, keep_dur = [], []
    pos = 0.0
    while int(pos) < n:
        j = int(pos)
        nxt = min(n, max(int(pos + step), j + 1))
        if len(keep_idx) >= max_frames:
            keep_dur[-1] += sum(durations[j:n])
            break
        keep_idx.append(j)
        keep_dur.append(sum(durations[j:nxt]))
        pos += step
    return keep_idx, keep_dur


def concat(datas, frame_sec: float = 0.5, fmt="GIF", max_frames: int = 500):
    default_ms = max(MIN_FRAME_MS, int(frame_sec * 1000))

    probes, cw, ch = [], 0, 0
    for data in datas:
        try:
            with PILImage.open(io.BytesIO(data)) as im:
                cw = max(cw, im.width)
                ch = max(ch, im.height)
                if getattr(im, "is_animated", False):
                    durs = []
                    for i in range(getattr(im, "n_frames", 1)):
                        im.seek(i)
                        durs.append(_frame_duration(im, default_ms))
                else:
                    durs = [default_ms]
                probes.append((data, durs))
        except Exception:
            continue
    if not probes:
        raise ToolError("没有可用的图片")
    if cw <= 0 or ch <= 0:
        raise ToolError("图片尺寸异常")

    total = sum(len(d) for _, d in probes)
    frames, durations = [], []
    for data, durs in probes:
        if total > max_frames:
            allow = max(1, int(len(durs) * max_frames / total))
            idx, dur = _decimate(durs, allow)
        else:
            idx, dur = list(range(len(durs))), list(durs)
        try:
            with PILImage.open(io.BytesIO(data)) as im:
                for fi, ms in zip(idx, dur):
                    im.seek(fi)
                    frames.append(_fit_to_canvas(im.convert("RGBA"), cw, ch))
                    durations.append(ms)
        except Exception:
            continue
    if not frames:
        raise ToolError("没有可合成的帧")

    out = _save_anim(frames, durations, fmt)
    return out, {"n": len(probes), "frames": len(frames), "t": sum(durations) / 1000.0}


# --------------------------------------------------------------------------
# 视频转 gif（需要 imageio[ffmpeg]，缺依赖时给出明确原因）
# --------------------------------------------------------------------------

def _py_env_hint() -> str:
    """缺依赖时附上运行环境信息，便于判断装到了哪个 Python 里。"""
    import sys
    try:
        import imageio_ffmpeg
        ff = f"imageio_ffmpeg 可导入（{imageio_ffmpeg.__file__}）"
    except Exception as e:
        ff = f"imageio_ffmpeg 导入失败（{type(e).__name__}: {e}）"
    return f"[运行解释器: {sys.executable}；{ff}]"


def video_to_gif(path: str, start: float = 0.0, end: float = None, fps: float = 10,
                 scale: float = 0.3, fmt="GIF", max_duration: float = 10.0,
                 max_frames: int = 400):
    try:
        import imageio.v2 as imageio
    except ImportError as e:
        raise ToolError(f"缺少 imageio，请在 bot 的 Python 环境执行 pip install imageio imageio-ffmpeg（{e}）")

    try:
        reader = imageio.get_reader(path, format="FFMPEG")
    except ImportError as e:
        raise ToolError(f"缺少 imageio-ffmpeg，请在 bot 的 Python 环境执行 pip install imageio-ffmpeg（{e}）\n{_py_env_hint()}")
    except Exception as e:
        raise ToolError(f"视频打不开（{type(e).__name__}: {e}）")

    try:
        meta = reader.get_meta_data()
        duration = float(meta.get("duration", 0) or 0)
        src_fps = float(meta.get("fps", 30) or 30)
        if duration <= 0:
            duration = None
        if end is None or (duration and end > duration):
            end = duration
        if start < 0:
            start = 0.0
        if end is not None and end <= start:
            raise ToolError("结束时间必须晚于开始时间")
        if end is not None and duration and start >= duration:
            raise ToolError("开始时间超出了视频长度")

        truncated = False
        if end is not None and end - start > max_duration:
            end = start + max_duration
            truncated = True

        if not fps or fps <= 0:
            fps = 10
        if fps > src_fps:
            fps = src_fps
        step = max(1, int(round(src_fps / fps)))
        target_fps = src_fps / step
        frame_ms = max(MIN_FRAME_MS, int(1000 / target_fps))

        frames = []
        for i, raw in enumerate(reader):
            t = i / src_fps
            if t < start:
                continue
            if end is not None and t > end:
                break
            if i % step:
                continue
            img = PILImage.fromarray(raw)
            w, h = img.size
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                             PILImage.Resampling.BILINEAR)
            frames.append(img)
            if len(frames) >= max_frames:
                truncated = True
                break
    finally:
        try:
            reader.close()
        except Exception:
            pass

    if not frames:
        raise ToolError("这段时间里没有抽到任何帧")

    out = _save_anim(frames, [frame_ms] * len(frames), fmt)
    return out, {"frames": len(frames), "fps": target_fps, "truncated": truncated}
