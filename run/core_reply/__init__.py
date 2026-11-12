plugin_description = "core_reply 新版ai对话"

dynamic_imports = {
    "run.core_reply.func_collection": [
        "clear_chat_history",
        "update_system",
    ]
}

function_declarations = [
    {
        "name": "clear_chat_history",
        "description": "清除当前用户与bot的对话历史记录，重置记忆",
        "parameters": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "update_system",
        "description": "系统管理员专用的系统更新工具。当管理员明确要求更新系统、更新代码或升级bot时调用。执行前会自动鉴权，在后台完成Git拉取并向管理员发送私信汇报更新结果，随后安全重启Bot生效。",
        "parameters": {
            "type": "object",
            "properties": {},
        }
    },
]
