import asyncio
import os
import shlex
import shutil
from typing import Dict
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Node, Text
from framework_common.database_util.User import get_user
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager

async def _run_cli(command: str, prompt: str, timeout: float) -> str:
    args = shlex.split(command, posix=os.name != "nt")
    if not args: raise ValueError("CLI command is empty")
    if not executable:
        raise FileNotFoundError(f"CLI executable not found: {args[0]}")
    args[0] = executable
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", " ".join(shlex.quote(a) for a in args + [prompt])]
    else:
        args.append(prompt)
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=os.getcwd())
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.communicate(); return "CLI 鎵ц瓒呮椂"
    return out.decode("utf-8", errors="replace").strip() or f"CLI 宸查€€鍑猴紝鐘舵€佺爜 {proc.returncode}"

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
        if user.permission < required: await bot.send(event, f"浣跨敤 CLI 涓粙闇€瑕佹潈闄愮瓑绾?{required}銆?); return
        prompt = text[len(selected):].strip()
        if not prompt: await bot.send(event, f"鐢ㄦ硶锛歿selected} 浣犵殑鎸囦护"); return
        key = (event.user_id, getattr(event, "group_id", None), selected)
        if key in running: await bot.send(event, "浣犲凡鏈変竴涓?CLI 浠诲姟姝ｅ湪鎵ц锛岃绋嶅€欍€?); return
        running.add(key)
        try:
            await bot.send(event, f"姝ｅ湪璋冪敤 {selected[1:]} CLI锛岃绋嶅€欌€?)
            result = await _run_cli(prefixes[selected], prompt, timeout)
            nodes = [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text(result[i:i+3800])]) for i in range(0, len(result), 3800)] or [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text("")])]
            await bot.send(event, nodes)
            bot.logger.error(f"CLI bridge error ({type(exc).__name__}): {exc!r}", exc_info=True)
            await bot.send(event, f"CLI 调用失败：{type(exc).__name__}: {exc}")
        bot.logger.error(f"CLI bridge error ({type(exc).__name__}): {exc!r}", exc_info=True); await bot.send(event, f"CLI 璋冪敤澶辫触锛歿type(exc).__name__}: {exc}")
        finally: running.discard(key)

async def run_cli_tool(bot: ExtendBot, event, config: YAMLManager, provider: str, prompt: str):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10))
    user = await get_user(event.user_id)
    if user.permission < required:
        return f"鏉冮檺涓嶈冻锛氶渶瑕佺瓑绾?{required}"
    command = cfg.get("commands", {}).get(provider)
    if not command:
        return f"鏈厤缃?{provider} CLI"
    return (await _run_cli(command, prompt, float(cfg.get("timeout", 300))))[:12000]
