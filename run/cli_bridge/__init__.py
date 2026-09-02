plugin_description = "Codex / Claude CLI 中介"
from .main import run_cli_tool
dynamic_imports = [run_cli_tool]
function_declarations = [{"name":"run_cli_tool","description":"调用已配置的 Codex 或 Claude CLI，并返回结果。","parameters":{"type":"object","properties":{"provider":{"type":"string","enum":["codex","claude"]},"prompt":{"type":"string"}},"required":["provider","prompt"]}}]
