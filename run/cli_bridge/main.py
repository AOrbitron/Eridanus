import asyncio
import os
import shlex
import shutil
import subprocess

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Node, Text
from framework_common.database_util.User import get_user


async def _run_cli(command: str, prompt: str, timeout: float) -> str:
    args = shlex.split(command, posix=os.name != "nt")
    if not args:
        raise ValueError("CLI command is empty")
    executable = shutil.which(args[0])
    if not executable:
        raise FileNotFoundError(f"CLI executable not found: {args[0]}")
    args[0] = executable
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        command_line = " ".join(shlex.quote(x) for x in args + [prompt])
        args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    else:
        args.append(prompt)
    def invoke():
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, cwd=os.getcwd())
    try:
        completed = await asyncio.to_thread(invoke)
    except subprocess.TimeoutExpired:
        return "CLI execution timed out"
    output = completed.stdout or b""
    # Windows CLI 可能使用 UTF-8、系统代码页或混合输出；避免直接以 UTF-8 替换造成乱码。
    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError:
        decoded = output.decode("mbcs" if os.name == "nt" else "gbk", errors="replace")
    return decoded.strip() or f"CLI exited ({completed.returncode})"


async def run_cli_tool(bot, event, config, provider: str, prompt: str):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10))
    user = await get_user(event.user_id)
    if user.permission < required:
        return f"Permission denied (required level: {required})"
    command = cfg.get("commands", {}).get(provider)
    if not command:
        return f"CLI not configured: {provider}"
    return (await _run_cli(command, prompt, float(cfg.get("timeout", 300))))[:12000]


def main(bot, config):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10))
    timeout = float(cfg.get("timeout", 300))
    commands = cfg.get("commands", {})
    prefixes = {"/codex": commands.get("codex", "codex exec"), "/claude": commands.get("claude", "claude -p")}
    running = set()

    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def cli_handler(event):
        text = (event.pure_text or "").strip()
        selected = next((p for p in prefixes if text == p or text.startswith(p + " ")), None)
        if not selected:
            return
        user = await get_user(event.user_id)
        if user.permission < required:
            await bot.send(event, f"Permission denied (required level: {required})")
            return
        prompt = text[len(selected):].strip()
        if not prompt:
            await bot.send(event, f"Usage: {selected} <prompt>")
            return
        key = (event.user_id, getattr(event, "group_id", None), selected)
        if key in running:
            await bot.send(event, "A CLI task is already running for you.")
            return
        running.add(key)
        try:
            await bot.send(event, f"Calling {selected[1:]} CLI, please wait...")
            result = await _run_cli(prefixes[selected], prompt, timeout)
            nodes = [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text(result[i:i + 3800])]) for i in range(0, len(result), 3800)]
            await bot.send(event, nodes or [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text("")])])
        except Exception as exc:
            bot.logger.error("CLI bridge error", exc_info=True)
            await bot.send(event, f"CLI failed: {type(exc).__name__}: {exc}")
        finally:
            running.discard(key)
