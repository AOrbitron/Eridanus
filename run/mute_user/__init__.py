plugin_description = "群聊用户管理插件"

dynamic_imports = {
    "run.mute_user.mute_user": ["mute_group_user"],
}

function_declarations = [
    {
        "name": "mute_group_user",
        "description": "在当前群聊中禁言指定用户。仅群主、群管理员或 bot 主人可调用；未指定时长时默认禁言 5 分钟。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_user_id": {
                    "type": "integer",
                    "description": "需要禁言的用户 QQ 号",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "禁言时长（分钟），默认为 5，最大为 43200（30 天）",
                    "minimum": 1,
                    "maximum": 43200,
                    "default": 5,
                },
            },
            "required": ["target_user_id"],
        },
    },
]
