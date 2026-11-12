plugin_description = "tts_v2"

dynamic_imports = {
    "run.tts_v2.service.tts": [
        "call_tts",
        "get_all_speakers",
        "get_breeze_tags",
        "clone_voice",
        "list_cloned_voices",
    ]
}

function_declarations = [
    {
        "name": "call_tts",
        "description": "语音合成并发送语音消息。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "待合成文本。"
                },
                "speaker": {
                    "type": "string",
                    "description": "发音人名称（如'达妮娅'、'natuki'、'JP_Mari'或克隆角色），留空为默认声线。"
                }
            },
            "required": [
                "text"
            ]
        }
    },
    {
        "name": "get_all_speakers",
        "description": "获取所有可用的TTS角色列表。"
    },
    {
        "name": "get_breeze_tags",
        "description": "获取Breeze-TTS官方音频表现力标签及使用指南。"
    },
    {
        "name": "clone_voice",
        "description": "临时克隆音频为自定义角色（1小时有效）。",
        "parameters": {
            "type": "object",
            "properties": {
                "speaker_name": {
                    "type": "string",
                    "description": "克隆角色名。"
                },
                "audio_url_or_path": {
                    "type": "string",
                    "description": "参考音频文件路径或URL。"
                },
                "ref_text": {
                    "type": "string",
                    "description": "参考音频原台词文本。"
                }
            },
            "required": [
                "speaker_name",
                "audio_url_or_path",
                "ref_text"
            ]
        }
    },
    {
        "name": "list_cloned_voices",
        "description": "查询当前1小时有效期内已生效的克隆角色列表。"
    }
]
