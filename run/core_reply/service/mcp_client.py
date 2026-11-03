"""
mcp_client.py
MCP stdio 客户端，用于把 MCP server 的 tools 暴露给 core_reply 的函数调用系统。

当前实现覆盖最常见的 MCP stdio 形态：
- command + args + env 启动 server
- initialize / notifications/initialized
- tools/list
- tools/call
"""

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from framework_common.utils.system_logger import get_logger

logger = get_logger(__name__)


@dataclass
class MCPTool:
    server_name: str
    name: str
    description: str
    input_schema: dict


class MCPStdioClient:
    def __init__(self, server_name: str, server_config: dict, timeout: float = 30.0):
        self.server_name = server_name
        self.server_config = server_config
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._id = 0
        self._lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return

        command = self._resolve_command(str(self.server_config.get("command", "")))
        if not command:
            raise RuntimeError(f"MCP server {self.server_name} 缺少 command")

        args = [str(arg) for arg in self.server_config.get("args", [])]
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self.server_config.get("env") or {}).items()})

        logger.info(f"[MaiReply][MCP] 启动 MCP server: {self.server_name} -> {command} {args}")
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            env=env,
            text=False,
        )
        self._start_stderr_drain()
        self._initialize()

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def list_tools(self) -> List[MCPTool]:
        self.start()
        result = self._request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        parsed = []
        for tool in tools:
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            parsed.append(
                MCPTool(
                    server_name=self.server_name,
                    name=name,
                    description=str(tool.get("description", "") or f"MCP tool {name}"),
                    input_schema=tool.get("inputSchema") or {"type": "object", "properties": {}},
                )
            )
        logger.info(f"[MaiReply][MCP] {self.server_name} 已加载 MCP tools: {[t.name for t in parsed]}")
        return parsed

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.start()
        return self._request("tools/call", {"name": tool_name, "arguments": arguments or {}})

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "eridanus-mai-reply", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._ensure_running()
            self._id += 1
            request_id = self._id
            self._write_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                message = self._read_message(deadline)
                if message is None:
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise RuntimeError(f"MCP {self.server_name}.{method} error: {message['error']}")
                return message.get("result", {})

            raise TimeoutError(f"MCP {self.server_name}.{method} 请求超时")

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._ensure_running()
            self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    def _write_message(self, payload: dict) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError(f"MCP server {self.server_name} stdin 不可用")
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.process.stdin.write(body)
        self.process.stdin.flush()

    def _read_message(self, deadline: float) -> Optional[dict]:
        if not self.process or not self.process.stdout:
            raise RuntimeError(f"MCP server {self.server_name} stdout 不可用")

        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if line == b"":
                self._ensure_running()
                continue
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            return json.loads(line)
        return None

    def _ensure_running(self) -> None:
        if not self.process:
            raise RuntimeError(f"MCP server {self.server_name} 未启动")
        code = self.process.poll()
        if code is not None:
            raise RuntimeError(f"MCP server {self.server_name} 已退出，退出码 {code}")

    def _start_stderr_drain(self) -> None:
        if not self.process or not self.process.stderr:
            return

        def drain() -> None:
            assert self.process and self.process.stderr
            for raw in iter(self.process.stderr.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info(f"[MaiReply][MCP][{self.server_name}] {text}")

        self._stderr_thread = threading.Thread(target=drain, daemon=True)
        self._stderr_thread.start()

    @staticmethod
    def _resolve_command(command: str) -> str:
        if not command:
            return ""
        found = shutil.which(command)
        if found:
            return found
        if os.name == "nt" and not command.lower().endswith((".exe", ".cmd", ".bat")):
            for suffix in (".cmd", ".exe", ".bat"):
                found = shutil.which(command + suffix)
                if found:
                    return found
        return command


class MCPManager:
    def __init__(self, config):
        cfg = config.core_reply.config.get("mcp", {})
        self.enabled = bool(cfg.get("enable", False))
        self.startup_timeout = float(cfg.get("startup_timeout_seconds", 30))
        self.tool_call_timeout = float(cfg.get("tool_call_timeout_seconds", 60))
        raw_servers = cfg.get("mcpServers") or cfg.get("servers") or {}
        self.clients: Dict[str, MCPStdioClient] = {
            name: MCPStdioClient(name, server_cfg, timeout=self.tool_call_timeout)
            for name, server_cfg in raw_servers.items()
        }
        self._tools: Dict[str, MCPTool] = {}

    def get_tool_map(self) -> Dict[str, Dict]:
        if not self.enabled:
            return {}

        result = {}
        for server_name, client in self.clients.items():
            try:
                client.timeout = self.startup_timeout
                tools = client.list_tools()
                client.timeout = self.tool_call_timeout
            except Exception as exc:
                logger.error(f"[MaiReply][MCP] 加载 MCP server 失败: {server_name} | {exc!r}", exc_info=True)
                continue

            for tool in tools:
                public_name = self._public_tool_name(server_name, tool.name)
                self._tools[public_name] = tool
                result[public_name] = {
                    "func": self._build_callable(public_name),
                    "declaration": {
                        "name": public_name,
                        "description": f"[MCP:{server_name}] {tool.description}",
                        "parameters": self._normalize_schema(tool.input_schema),
                    },
                }
        return result

    def _build_callable(self, public_name: str):
        async def call_mcp_tool(**kwargs):
            return await self.call_tool(public_name, kwargs)

        call_mcp_tool.__name__ = public_name
        return call_mcp_tool

    async def call_tool(self, public_name: str, arguments: dict) -> str:
        tool = self._tools.get(public_name)
        if not tool:
            return json.dumps({"error": f"未找到 MCP tool: {public_name}"}, ensure_ascii=False)

        client = self.clients.get(tool.server_name)
        if not client:
            return json.dumps({"error": f"未找到 MCP server: {tool.server_name}"}, ensure_ascii=False)

        try:
            logger.info(
                f"[MaiReply][MCP] 调用 MCP tool: server={tool.server_name}, tool={tool.name}, args={arguments}"
            )
            result = await asyncio.to_thread(client.call_tool, tool.name, arguments)
            logger.info(f"[MaiReply][MCP] MCP tool 调用完成: server={tool.server_name}, tool={tool.name}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            logger.error(
                f"[MaiReply][MCP] MCP tool 调用异常: server={tool.server_name}, tool={tool.name}, error={exc!r}",
                exc_info=True,
            )
            return json.dumps({"error": repr(exc)}, ensure_ascii=False)

    @staticmethod
    def _public_tool_name(server_name: str, tool_name: str) -> str:
        raw = f"mcp__{server_name}__{tool_name}"
        return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in raw)

    @staticmethod
    def _normalize_schema(schema: dict) -> dict:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}
        normalized = dict(schema)
        normalized.setdefault("type", "object")
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
        return normalized
