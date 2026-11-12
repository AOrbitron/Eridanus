plugin_description="系统功能"
import os

dynamic_imports = {
    "run.system_plugin.Mface_Record": ["call_send_mface"],
    "run.system_plugin.func_collection": [
         "call_user_data_query", "call_user_data_sign",
        "call_change_city", "call_permit",
        "call_delete_user_history", "call_clear_all_history","operate_group_push_tasks"
    ],
}
mface_list = os.listdir("data/pictures/Mface")
function_declarations=[
    {
        "name": "operate_group_push_tasks",
        "description": "添加或取消推送任务",
        "parameters": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string", "enum": ["asmr", "bilibili"], "description": "任务类型: asmr/b站动态 "
                },
                "operation": {
                    "type": "boolean",
                    "description": "true为添加，false为取消"
                },
                "target_uid": {
                    "type": "integer",
                    "description": "b站动态订阅，目标uid"
                }
            },
            "required": [
                "task_type",
                "operation"
            ]
        }
    },
{
        "name": "call_delete_user_history",
        "description": "清理当前对话记录"
    },
    {
        "name": "call_clear_all_history",
        "description": "清理所有用户的对话记录"
    },


    {
        "name": "call_user_data_query",
        "description": "查询用户数据。eg.权限等级等内容。"
    },
    {
        "name": "call_user_data_sign",
        "description": "签到。实现签到行为。"
    },
    {
        "name": "call_change_city",
        "description": "调整所在城市信息。eg：修改城市为新乡。当用户告知所在地区后，主动调用此函数以保存。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "用户所在的城市。eg：新乡"
                }
            },
            "required": [
                "city"
            ]
        }
    },
    {
        "name": "call_permit",
        "description": "调整特定用户的permission。指令一般为 为{int}授权到{level}。函数内部已添加额外检查。不要以‘我没有权限’为由不执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "integer",
                    "description": "所要授权的对象的qq号码/群的群号"
                },
                "level": {
                    "type": "integer",
                    "description": "授权等级。1为最低"
                },
                "type": {
                    "type": "string", "enum": ["user", "group"], "description": "授权对象类型。user为qq号码，group为群号"
                }
            },
            "required": [
                "target_id",
                "level",
                "type"
            ]
        }
    },
    {
        "name": "call_send_mface",
        "description": "根据当前聊天内容选择一张表情包，只可从给定列表选取，只可选择一张。不要通过send函数发送表情包，不要总是用一张表情包。用户未要求时，也要时不时调用此函数，能增强角色扮演效果和趣味性。可以将此函数视为概率触发的'被动技能'",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": f"表情包。可选{mface_list}，将选择的结果输入此函数以记录并发送。"
                }
            },
            "required": [
                "summary"
            ]
        }
    }
]
