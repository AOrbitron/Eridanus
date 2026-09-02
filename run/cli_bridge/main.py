import asyncio
import os
import shlex
from typing import Dict
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Node, Text
from framework_common.database_util.User import get_user
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager

async def _run_cli(command: str, prompt: str, timeout: float) -> str:
    args = shlex.split(command, posix=os.name != "nt")
    if not args: raise ValueError("CLI command is empty")
    proc = await asyncio.create_subprocess_exec(*args, prompt, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=os.getcwd())
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.communicate(); return "CLI 执行超时"
    return out.decode("utf-8", errors="replace").strip() or f"CLI 已退出，状态码 {proc.returncode}"

def main(bot: ExtendBot, config: YAMLManager):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10)); timeout = float(cfg.get("timeout", 300))
    commands: Dict[str, str] = cfg.get("commands", {})
    prefixes = {"/codex": commands.get("codex", "codex"), "/claude": commands.get("claude", "claude")}; running = set()
    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def cli_handler(event):
        text = (event.pure_text or "").strip(); selected = next((p for p in prefixes if text == p or text.startswith(p + " ")), None)
        if not selected: return
        user = await get_user(event.user_id)
        if user.permission < required: await bot.send(event, f"使用 CLI 中介需要权限等级 {required}。"); return
        prompt = text[len(selected):].strip()
        if not prompt: await bot.send(event, f"用法：{selected} 你的指令"); return
        key = (event.user_id, getattr(event, "group_id", None), selected)
        if key in running: await bot.send(event, "你已有一个 CLI 任务正在执行，请稍候。"); return
        running.add(key)
        try:
            await bot.send(event, f"正在调用 {selected[1:]} CLI，请稍候…")
            result = await _run_cli(prefixes[selected], prompt, timeout)
            nodes = [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text(result[i:i+3800])]) for i in range(0, len(result), 3800)] or [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text("")])]
            await bot.send(event, nodes)
        except Exception as exc:
            bot.logger.error(f"CLI bridge error: {exc}", exc_info=True); await bot.send(event, f"CLI 调用失败：{exc}")
        finally: running.discard(key)

async def run_cli_tool(bot: ExtendBot, event, config: YAMLManager, provider: str, prompt: str):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10))
    user = await get_user(event.user_id)
    if user.permission < required:
        return f"权限不足：需要等级 {required}"
    command = cfg.get("commands", {}).get(provider)
    if not command:
        return f"未配置 {provider} CLI"
    return (await _run_cli(command, prompt, float(cfg.get("timeout", 300))))[:12000]
