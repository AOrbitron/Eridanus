import asyncio
import os
import shlex
import shutil
import subprocess
import json
import re

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Node, Text
from framework_common.database_util.User import get_user


SESSION_FILE = os.path.join("data", "cli_bridge_sessions.json")

def _load_sessions():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _save_session(key, session_id):
    sessions = _load_sessions(); sessions[key] = session_id
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

def _clean_cli_output(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    noise = ("tokens used", "sandbox:", "planning", "codex", "claude")
    kept = [line for line in lines if not any(line.lower().startswith(n) for n in noise)]
    # 保留末尾的最终答复，丢弃前置执行过程和 token 统计。
    return "\n".join(kept[-40:])[:4000]

async def _run_cli(command: str, prompt: str, timeout: float, provider: str = "", session_key: str = "") -> str:
    args = shlex.split(command, posix=os.name != "nt")
    if not args:
        raise ValueError("CLI command is empty")
    executable = shutil.which(args[0])
    if not executable:
        raise FileNotFoundError(f"CLI executable not found: {args[0]}")
    args[0] = executable
    session_id = _load_sessions().get(session_key) if session_key else None
    if session_id and provider == "codex":
        args.insert(2, session_id)
        args.insert(2, "resume")
    elif session_id and provider == "claude":
        args.extend(["--resume", session_id])
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        # cmd.exe 不支持 Unix 单引号；使用 Windows 原生 argv 转义规则。
        command_line = subprocess.list2cmdline(args + [prompt])
        args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    else:
        args.append(prompt)
    def invoke():
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, timeout=timeout, cwd=os.getcwd())
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
    decoded = _clean_cli_output(decoded)
    # Codex/Claude 通常会在输出中给出 session id；保存后供下次 resume。
    found = re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", decoded)
    if found and session_key:
        _save_session(session_key, found[-1])
    return decoded or f"CLI exited ({completed.returncode})"


async def run_cli_tool(bot, event, config, provider: str, prompt: str):
    cfg = config.cli_bridge.config
    required = int(cfg.get("permission_level", 10))
    user = await get_user(event.user_id)
    if user.permission < required:
        return f"Permission denied (required level: {required})"
    command = cfg.get("commands", {}).get(provider)
    if not command:
        return f"CLI not configured: {provider}"
    key = f"{event.user_id}:{getattr(event, 'group_id', None)}:{provider}"
    if provider == "codex":
        prompt = (prompt + "\n\n[Eridanus plugin instructions]"
                  "\nWhen creating or modifying an Eridanus plugin, follow the existing plugin conventions."
                  "\nThe plugin must have a valid run/<plugin_name>/__init__.py with plugin_description."
                  "\nIn __init__.py define dynamic_imports as a dict: {'run.<plugin_name>.func_collection': ['tool_func']}."
                  "\nDefine function_declarations as a list of Gemini-style declarations with name, description, parameters."
                  "\nImplement each declared async tool function in func_collection.py or main.py with signature (bot, event, config, ...)."
                  "\nExample:"
                  "\n# run/example_plugin/__init__.py"
                  "\nplugin_description = '示例工具'"
                  "\ndynamic_imports = {'run.example_plugin.func_collection': ['example_tool']}"
                  "\nfunction_declarations = [{'name': 'example_tool', 'description': '执行示例操作', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]"
                  "\n# run/example_plugin/func_collection.py"
                  "\nfrom framework_common.database_util.User import get_user"
                  "\nasync def example_tool(bot, event, config, text: str):"
                  "\n    user = await get_user(event.user_id)"
                  "\n    if user.permission < 1: return '权限不足'"
                  "\n    return text"
                  "\nDo not put function_declarations into func_map directly; build_tool_map resolves dynamic_imports to callables, and llm_client converts declarations for the provider."
                  "\nUse async handlers, enforce permission checks for user-facing operations, and avoid shell=True."
                  "\nAfter writing files, verify Python syntax and ensure the new plugin is discoverable by the run/ scanner.")
    result = (await _run_cli(command, prompt, float(cfg.get("timeout", 300)), provider, key))[:8000]
    # Codex/Claude 可能刚刚生成了带 function calling 的插件；执行后立即重扫。
    try:
        from run.mai_reply.service.reply_engine import refresh_tools
        refresh_tools()
    except Exception:
        pass
    return result


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
            bot.logger.info(f"CLI bridge: starting provider={selected[1:]} user={event.user_id}")
            provider = selected[1:]
            key = f"{event.user_id}:{getattr(event, 'group_id', None)}:{provider}"
            result = await asyncio.wait_for(
                _run_cli(prefixes[selected], prompt, timeout, provider, key),
                timeout=timeout + 5,
            )
            bot.logger.info(f"CLI bridge: process finished provider={provider} chars={len(result)}")
            try:
                from run.mai_reply.service.reply_engine import refresh_tools
                refresh_tools()
            except Exception:
                pass
            nodes = [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text(result[i:i + 1200])]) for i in range(0, len(result), 1200)]
            await bot.send(event, nodes or [Node(user_id=str(bot.id), nickname=selected[1:], content=[Text("")])])
            # 原始结果单独折叠展示后，再交给 MaiReply 以 yucca 口吻转述。
            from run.mai_reply.service.reply_engine import ReplyEngine
            summary_event = type("CliSummaryEvent", (), {"user_id": event.user_id, "group_id": getattr(event, "group_id", None)})()
            try:
                await asyncio.wait_for(ReplyEngine(config).handle(
                    bot, summary_event,
                    "请用你自己的角色和语气，简洁转述刚才 CLI 执行的最终结果。不要提及 CLI、系统提示、工具调用或执行日志。最终结果如下：\n" + result[:1800],
                ), timeout=45)
            except asyncio.TimeoutError:
                bot.logger.warning("CLI bridge: MaiReply summary timed out")
        except Exception as exc:
            bot.logger.error("CLI bridge error", exc_info=True)
            await bot.send(event, f"CLI failed: {type(exc).__name__}: {exc}")
        finally:
            running.discard(key)
