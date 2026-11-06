# -*- coding: utf-8 -*-
plugin_description = "codex cli"

# 框架动态导入工具函数
dynamic_imports = {
    "run.cli_bridge.main": [
        "run_cli_tool"
    ]
}

# Gemini / OpenAI Function Calling 声明规范
function_declarations = [
    {
        "name": "run_cli_tool",
        "description": "调用宿主机本地已配置的 AI 代码智能体命令行工具（Codex 或 Claude CLI）来执行复杂编程、代码生成、系统运维等任务，并返回执行输出。",
        "parameters": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["codex", "claude"],
                    "description": "要调用的 CLI 工具引擎类型：codex 或 claude"
                },
                "prompt": {
                    "type": "string",
                    "description": "需要交给代码智能体执行的完整任务描述、代码需求或指令"
                },
                "reset_session": {
                    "type": "boolean",
                    "description": "是否丢弃历史会话并开启全新独立会话。默认为 false（延续上一次执行的上下文）"
                },
                "image_path": {
                    "type": "string",
                    "description": "图片本地文件路径或 URL。"
                }
            },
            "required": ["provider", "prompt"]
        }
    }
]
