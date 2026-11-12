# -*- coding: utf-8 -*-
import asyncio
import collections
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional, Tuple, Dict, Any, List

from framework_common.utils.utils import get_img, download_img, get_local_file_path, is_local_file_path
from .session_manager import get_session_id, save_session, clear_session

# ANSI 转义序列正则，用于剥离终端彩色字符
ANSI_REGEX = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')

# 正在运行的任务映射：key -> dict(process, provider, start_time, recent_lines, last_activity_time, etc.)
RUNNING_TASKS: Dict[str, Dict[str, Any]] = {}


def strip_ansi(text: str) -> str:
    """去除终端 ANSI 颜色与控制序列"""
    if not text:
        return ""
    return ANSI_REGEX.sub('', text)


def is_noise_line(line: str) -> bool:
    """过滤终端输出中的无用噪声行与配置打印"""
    s = line.strip()
    if not s:
        return True
    lower = s.lower()
    if lower.startswith("reading additional input from stdin"):
        return True
    if lower.startswith("openai codex v"):
        return True
    if lower.startswith("tokens used") or lower.isdigit():
        return True
    if lower.startswith("sandbox:") or lower.startswith("reasoning effort:") or lower.startswith("reasoning summaries:"):
        return True
    if lower.startswith("workdir:") or lower.startswith("provider:") or lower.startswith("approval:"):
        return True
    if lower.startswith("session id:"):
        return True
    if lower in ("--------", "========", "--------------------------------"):
        return True
    if lower.startswith("warning: codex is ignoring"):
        return True
    if "is ignored." in lower and "config.toml" in lower:
        return True
    return False


def decode_bytes(b: bytes) -> str:
    """解码字节数据，优先 utf-8，其次系统编码"""
    if not b:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("mbcs" if os.name == "nt" else "gbk", errors="replace")


async def resolve_image(bot, event, raw_image: Optional[str] = None) -> Optional[str]:
    """
    解析并下载/转换图片为本地绝对路径。
    优先检查显式传入的 raw_image（如函数调用传入的图片路径/URL），
    若无显式图片则通过 get_img(event, bot) 从当前消息或引用消息中提取。
    """
    target = (raw_image or "").strip()
    if not target and event and bot:
        try:
            found = await get_img(event, bot)
            if found and isinstance(found, str):
                target = found.strip()
        except Exception as e:
            if getattr(bot, "logger", None):
                bot.logger.warning(f"CLI bridge: get_img 获取图片失败: {e}")

    if not target:
        return None

    # 如果已经是本地文件
    try:
        if is_local_file_path(target):
            norm_path = get_local_file_path(target)
            if os.path.isfile(norm_path):
                return os.path.abspath(norm_path)
    except Exception:
        pass

    # 尝试下载图片（支持 http/https/base64 等）
    try:
        saved_path = await download_img(target)
        if saved_path and os.path.isfile(saved_path):
            return os.path.abspath(saved_path)
    except Exception as e:
        if hasattr(bot, "logger"):
            bot.logger.warning(f"CLI bridge: 下载/保存图片失败 ({target}): {e}")

    return None


def extract_session_id(text: str) -> Optional[str]:
    """从文本中提取 Codex / Claude 的 session id (UUID)"""
    if not text:
        return None
    # 优先匹配明确标注的 session id
    explicit_match = re.search(r'session\s*id[:\s]+([0-9a-fA-F-]{32,36})', text, re.IGNORECASE)
    if explicit_match:
        return explicit_match.group(1).strip()
    # 通用 UUID 匹配
    uuid_match = re.findall(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', text)
    if uuid_match:
        return uuid_match[-1]
    return None


def clean_cli_output(text: str, max_length: int = 6000) -> str:
    """清理 CLI 终端输出中的无用日志与冗余头部"""
    text = strip_ansi(text).strip()
    if not text:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if is_noise_line(stripped):
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()
    if len(result) > max_length:
        result = result[:max_length] + f"\n\n... [输出较长，已截断前 {max_length} 字符]"
    return result


def is_session_expired_error(output: str) -> bool:
    """判断是否为会话失效/不存在的错误"""
    lower = output.lower()
    keywords = [
        "session not found",
        "invalid session",
        "could not find session",
        "cannot find session",
        "no session found",
        "unknown session",
        "session expired",
        "no rollout found",
        "thread/resume failed",
        "no conversation found",
        "does not match any session"
    ]
    return any(k in lower for k in keywords)


def find_executable(cmd_name: str) -> Optional[str]:
    """在系统 PATH 中定位可执行文件，支持 Windows 下优先查找 .cmd / .exe"""
    which_res = shutil.which(cmd_name)
    if which_res:
        return which_res
    if os.name == "nt":
        for ext in [".cmd", ".CMD", ".exe", ".EXE", ".bat", ".BAT"]:
            candidate = shutil.which(cmd_name + ext)
            if candidate:
                return candidate
    return None


def terminate_running_task(session_key: str) -> bool:
    """终止指定 key 正在运行的底层 CLI 进程及其所有子进程"""
    task = RUNNING_TASKS.get(session_key)
    if not task:
        return False
    proc = task.get("process")
    task["terminated_by_user"] = True
    if not proc or proc.poll() is not None:
        RUNNING_TASKS.pop(session_key, None)
        return False

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        else:
            proc.kill()
    except Exception:
        pass
    finally:
        RUNNING_TASKS.pop(session_key, None)
    return True


def is_task_running(session_key: str) -> bool:
    """检查指定 key 是否有任务在运行"""
    task = RUNNING_TASKS.get(session_key)
    if not task:
        return False
    proc = task.get("process")
    if proc and proc.poll() is None:
        return True
    RUNNING_TASKS.pop(session_key, None)
    return False


def _run_process_with_streaming(
    cmd_args: List[str],
    timeout: float,
    session_key: str,
    provider: str
) -> Tuple[int, bytes, bytes]:
    """
    在后台线程中启动子进程，并通过管道流式捕获 stdout / stderr，实时更新执行进展。
    """
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        cwd=os.getcwd()
    )

    stdout_chunks: List[bytes] = []
    stderr_chunks: List[bytes] = []
    recent_lines = collections.deque(maxlen=30)
    task_info: Dict[str, Any] = {
        "process": proc,
        "provider": provider,
        "start_time": time.time(),
        "last_activity_time": time.time(),
        "recent_lines": recent_lines,
        "terminated_by_user": False,
    }
    if session_key:
        RUNNING_TASKS[session_key] = task_info

    def stream_reader(pipe, chunks_list, is_stderr):
        try:
            for raw_line in iter(pipe.readline, b""):
                chunks_list.append(raw_line)
                decoded = decode_bytes(raw_line).strip()
                if decoded:
                    clean = strip_ansi(decoded).strip()
                    if clean and not is_noise_line(clean):
                        recent_lines.append(clean)
                        task_info["last_activity_time"] = time.time()
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t_stdout = threading.Thread(target=stream_reader, args=(proc.stdout, stdout_chunks, False), daemon=True)
    t_stderr = threading.Thread(target=stream_reader, args=(proc.stderr, stderr_chunks, True), daemon=True)
    t_stdout.start()
    t_stderr.start()

    try:
        proc.wait(timeout=timeout)
        t_stdout.join(timeout=3)
        t_stderr.join(timeout=3)
        return proc.returncode, b"".join(stdout_chunks), b"".join(stderr_chunks)
    except subprocess.TimeoutExpired:
        # 超时中止子进程树
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            else:
                proc.kill()
        except Exception:
            pass
        t_stdout.join(timeout=2)
        t_stderr.join(timeout=2)
        raise
    finally:
        if session_key:
            RUNNING_TASKS.pop(session_key, None)


async def _progress_reporter(
    bot,
    event,
    provider: str,
    session_key: str,
    interval: float,
    start_time: float
) -> None:
    """
    在后台周期性向用户汇报超长任务的当前执行状态与进展
    """
    if interval <= 0 or not bot or not event:
        return

    try:
        while True:
            await asyncio.sleep(interval)
            # 检查任务是否仍在运行
            task = RUNNING_TASKS.get(session_key)
            if not task or not is_task_running(session_key):
                break

            elapsed = int(time.time() - start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            time_desc = f"{minutes} 分钟" if seconds == 0 else f"{minutes} 分 {seconds} 秒"

            recent = list(task.get("recent_lines", []))
            sample_lines = [l for l in recent if len(l.strip()) > 3][-3:]

            report_parts = [
                f"⏳【{provider.capitalize()} CLI 任务执行中】",
                f"• 已执行耗时：{time_desc}",
            ]

            if sample_lines:
                snippet = "\n  > ".join(sample_lines)
                if len(snippet) > 300:
                    snippet = snippet[-300:]
                report_parts.append(f"• 最新动态：\n  > {snippet}")
            else:
                report_parts.append("• 最新动态：模型正在深入分析需求或执行后台操作...")

            report_parts.append(f"\n💡 任务仍在持续进行，请耐心等待；若需中止可发送 `/{provider} stop`。")
            msg = "\n".join(report_parts)

            try:
                await bot.send(event, msg)
            except Exception as e:
                if hasattr(bot, "logger"):
                    bot.logger.warning(f"CLI bridge: 进度汇报发送失败: {e}")

    except asyncio.CancelledError:
        pass


async def run_cli_command(
    command_str: str,
    prompt: str,
    timeout: float,
    provider: str,
    session_key: str = "",
    reset_session: bool = False,
    max_output_length: int = 6000,
    auto_fallback: bool = True,
    bot: Any = None,
    event: Any = None,
    report_interval: float = 180.0,
    image_path: Optional[str] = None
) -> str:
    """执行底层 CLI 命令并返回经过清洗的结果文本，支持图文传入与长任务进度汇报"""
    # 检查是否已有同名任务在跑
    if session_key and is_task_running(session_key):
        return f"当前已有一个 {provider.capitalize()} 任务正在为您运行中，请等待其完成或发送 `/{provider} stop` 终止当前任务。"

    # 如果显式指定了重置会话
    if reset_session and session_key:
        clear_session(session_key)

    raw_args = shlex.split(command_str, posix=os.name != "nt")
    if not raw_args:
        return "错误：CLI 命令配置为空。"

    base_exe = raw_args[0]
    executable = find_executable(base_exe)
    if not executable:
        return f"错误：未在系统环境变量 PATH 中找到可执行命令 `{base_exe}`，请检查是否已正确安装该 CLI 工具。"

    # 解析 session id
    saved_session_id = None if reset_session else (get_session_id(session_key) if session_key else None)
    is_resume = bool(saved_session_id)

    # 临时文件，用于 codex 捕获最终纯净回复
    temp_last_msg_file = None
    if provider == "codex":
        fd, temp_last_msg_file = tempfile.mkstemp(prefix="codex_last_msg_", suffix=".txt")
        os.close(fd)

    reporter_task = None
    start_time = time.time()

    try:
        # 构建执行参数列表
        cmd_args = [executable]
        extra_options = raw_args[1:]

        if provider == "codex":
            # 过滤掉可能遗留的不合法参数
            extra_options = [opt for opt in extra_options if opt != "--yolo"]
            filtered_opts = [opt for opt in extra_options if opt not in ("exec", "resume")]
            if is_resume:
                cmd_args.extend(["exec", "resume"])
                cmd_args.extend(filtered_opts)
                if temp_last_msg_file:
                    cmd_args.extend(["-o", temp_last_msg_file])
                if image_path and os.path.isfile(image_path):
                    cmd_args.extend(["-i", os.path.abspath(image_path)])
                cmd_args.append(saved_session_id)
                cmd_args.append(prompt)
            else:
                cmd_args.append("exec")
                cmd_args.extend(filtered_opts)
                if temp_last_msg_file:
                    cmd_args.extend(["-o", temp_last_msg_file])
                if image_path and os.path.isfile(image_path):
                    cmd_args.extend(["-i", os.path.abspath(image_path)])
                cmd_args.append(prompt)

        elif provider == "claude":
            cmd_args.extend(extra_options)
            if is_resume:
                cmd_args.extend(["--resume", saved_session_id])
            if image_path and os.path.isfile(image_path):
                prompt = prompt + f"\n[附带图片本地路径: {os.path.abspath(image_path)}]"
            cmd_args.append(prompt)

        else:
            cmd_args.extend(extra_options)
            cmd_args.append(prompt)

        # 启动后台进度汇报协程
        if report_interval > 0 and bot and event and session_key:
            reporter_task = asyncio.create_task(
                _progress_reporter(
                    bot=bot,
                    event=event,
                    provider=provider,
                    session_key=session_key,
                    interval=report_interval,
                    start_time=start_time
                )
            )

        try:
            returncode, stdout_bytes, stderr_bytes = await asyncio.to_thread(
                _run_process_with_streaming,
                cmd_args,
                timeout,
                session_key,
                provider
            )
        except subprocess.TimeoutExpired:
            if session_key:
                terminate_running_task(session_key)
            timeout_min = int(timeout // 60)
            timeout_msg = (
                f"⚠️【{provider.capitalize()} CLI 执行超时】\n"
                f"任务执行时间已超过预设的 {int(timeout)} 秒（约 {timeout_min} 分钟），已自动中止进程。\n"
                f"• 可能原因：任务处理量极大、正在执行长耗时构建/测试、或网络拉取资源较慢。\n"
                f"• 建议解决办法：\n"
                f"  1. 可在 `run/cli_bridge/config.yaml` 中调大 `timeout` 配置项（如设为 1800 秒）。\n"
                f"  2. 可将复杂需求拆解为更小的子任务分步执行。\n"
                f"  3. 发送 `/{provider} new` 可开启新会话重新尝试。"
            )
            return timeout_msg

        # 解码输出
        stdout_text = decode_bytes(stdout_bytes)
        stderr_text = decode_bytes(stderr_bytes)
        combined_text = (stdout_text + "\n" + stderr_text).strip()

        # 检查是否因为旧 session 失效导致 resume 失败
        if is_resume and auto_fallback and returncode != 0 and is_session_expired_error(combined_text):
            clear_session(session_key)
            retry_res = await run_cli_command(
                command_str=command_str,
                prompt=prompt,
                timeout=timeout,
                provider=provider,
                session_key=session_key,
                reset_session=True,
                max_output_length=max_output_length,
                auto_fallback=False,
                bot=bot,
                event=event,
                report_interval=report_interval,
                image_path=image_path
            )
            return f"[提示：检测到旧会话已失效，已自动为您重置并开启新会话]\n\n" + retry_res

        # 仅在命令执行成功时保存捕获的 session id
        if returncode == 0:
            captured_session_id = extract_session_id(stderr_text) or extract_session_id(stdout_text)
            if captured_session_id and session_key:
                save_session(session_key, captured_session_id, prompt)

        # 优先读取 codex 的 last message 纯净输出文件
        last_message_content = ""
        if temp_last_msg_file and os.path.exists(temp_last_msg_file):
            try:
                with open(temp_last_msg_file, "r", encoding="utf-8") as f:
                    last_message_content = f.read().strip()
            except Exception:
                pass

        if last_message_content:
            final_reply = last_message_content
        else:
            final_reply = clean_cli_output(combined_text or stdout_text, max_length=max_output_length)

        if not final_reply:
            if returncode == 0:
                return "CLI 执行完成，但未产生任何控制台输出。"
            else:
                return f"CLI 执行异常退出 (退出码 {returncode})。\n{stderr_text[:500]}"

        return final_reply

    finally:
        # 取消进度汇报协程
        if reporter_task:
            reporter_task.cancel()
            try:
                await reporter_task
            except asyncio.CancelledError:
                pass

        # 清理临时文件
        if temp_last_msg_file and os.path.exists(temp_last_msg_file):
            try:
                os.remove(temp_last_msg_file)
            except OSError:
                pass
