# -*- coding: utf-8 -*-
plugin_description = "定时任务与智能调度"

dynamic_imports = {
    "run.scheduled_tasks.schedule_tool": [
        "call_create_schedule_task",
        "call_cancel_schedule_task",
        "call_list_schedule_tasks",
    ]
}

function_declarations = [
    {
        "name": "call_create_schedule_task",
        "description": "创建或安排一个定时任务。支持一次性(once)、每天循环(daily)、每周特定天(weekly)、工作日(workday)、周末(weekend)、每年特定日期(yearly，如每年生日、纪念日等)。支持预输入其他function到点执行（例如‘每天睡前给我发个asmr’），或者生成拟人化早安/叫起床/生日祝福/提醒消息。系统会自动根据用户的城市和时区进行时间换算。",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "任务描述，例如‘每天早上叫起床’、‘睡前发asmr’、‘30分钟后提醒喝水’、‘每年生日祝福’"
                },
                "time_str": {
                    "type": "string",
                    "description": "触发时间，例如‘08:30’、‘22:00’、‘30分钟后’、‘2小时后’、‘2026-10-12 09:00:00’、‘10-24 08:30’（年度循环月日）"
                },
                "recur_type": {
                    "type": "string",
                    "enum": ["once", "daily", "weekly", "workday", "weekend", "yearly"],
                    "description": "循环模式：once(一次性任务), daily(每天循环), weekly(每周特定一天或几天), workday(工作日周一至周五), weekend(周末周六和周日), yearly(每年循环，如每年生日、周年纪念日)"
                },
                "weekdays": {
                    "type": "string",
                    "description": "当recur_type为weekly时的星期几，如‘周一,周三’或‘1,3,5’或‘3’"
                },
                "action_type": {
                    "type": "string",
                    "enum": ["message", "tool"],
                    "description": "动作类型：message表示到点由AI生成贴心问候/叫起/祝福/提醒消息；tool表示预输入其他function到点执行（如call_asmr）"
                },
                "prompt_or_message": {
                    "type": "string",
                    "description": "当action_type为message时的提示词，例如‘早上好，元气满满地叫用户起床并提醒添衣’、‘今天是用户的生日，以温柔真诚的语气为TA送上独一无二的生日祝福与陪伴感言’"
                },
                "tool_name": {
                    "type": "string",
                    "description": "当action_type为tool时要执行的function名称，例如‘call_asmr’"
                },
                "tool_params": {
                    "type": "object",
                    "description": "当action_type为tool时预输入的function参数字典，例如{'mode': 'hotest'}"
                },
                "city": {
                    "type": "string",
                    "description": "用户所在城市（可选，若不填会自动读取用户画像中的城市时区）"
                }
            },
            "required": [
                "description",
                "time_str"
            ]
        }
    },
    {
        "name": "call_cancel_schedule_task",
        "description": "取消已设置的定时任务。当用户表示‘还是算了吧’、‘不用叫我起床了’、‘取消asmr’、‘取消提醒’、‘取消生日提醒’时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id_or_keyword": {
                    "type": "string",
                    "description": "要取消的任务ID或任务关键词，例如‘叫起床’、‘asmr’、‘喝水’、‘生日’、‘task_xxx’"
                }
            },
            "required": [
                "task_id_or_keyword"
            ]
        }
    },
    {
        "name": "call_list_schedule_tasks",
        "description": "查询当前用户或群聊所有生效中的定时任务列表。",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]
