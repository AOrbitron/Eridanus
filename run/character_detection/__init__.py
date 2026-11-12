plugin_description = "图片表情包审核"

dynamic_imports = {
    "run.character_detection.func_collection": ["operate_group_censor"],
}

function_declarations = [
    {
        "name": "operate_group_censor",
        "description": "开启或关闭群聊图片审核",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "开启奶龙审核", "关闭奶龙审核",
                        "开启doro审核", "关闭doro审核",
                        "开启男娘审核", "关闭男娘审核",
                        "开启deepseek审核", "关闭deepseek审核"
                    ],
                    "description": "要执行的审核开关操作"
                },
                "target_id": {
                    "type": "integer",
                    "description": "要操作的目标群号"
                }
            },
            "required": ["operation", "target_id"]
        }
    },
]
