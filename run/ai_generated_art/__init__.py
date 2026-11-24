from framework_common.framework_util.yamlLoader import YAMLManager

plugin_description = "ai绘画"
config = YAMLManager.get_instance()

try:
    bot_name = config.common_config.basic_config.get("bot", "Bot")
except Exception:
    bot_name = "Bot"

declarations = [
    {
        "name": "call_aiArtModerate",
        "description": "检测图片是否为ai生成，只有当用户要求检测时才可触发。",
        "parameters": {
            "type": "object",
            "properties": {
                "img_url": {
                    "type": "string",
                    "description": "目标图片的url"
                }
            },
            "required": [
                "img_url"
            ]
        }
    },
    {
        "name": "image_edit",
        "description": "根据用户的要求，对图片进行编辑",
        "parameters": {
            "type": "object",
            "properties": {
                "img_url": {
                    "type": "string",
                    "description": "需要的图片url"
                },
                "prompt": {
                    "type": "string",
                    "description": "对图片的要求"
                }
            },
            "required": [
                "img_url", "prompt"
            ]
        }
    },
    {
        "name": "text2img",
        "description": f"AI文生图工具。根据用户需求生成图片或自拍。如涉及{bot_name}本人自拍或肖像，将 is_about_bot 设为 true。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "画面内容描述（角色动作、服装、场景与氛围，中英文均可）。"
                },
                "is_about_bot": {
                    "type": "boolean",
                    "description": f"是否绘制{bot_name}本人或自拍。涉及{bot_name}、'你'或'她'时为 true。"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "画幅宽高比，例如 '1:1', '3:4', '4:3', '9:16', '16:9'。默认竖屏。"
                }
            },
            "required": ["prompt"]
        }
    }
]

dynamic_imports = {
    "run.ai_generated_art.aiDraw": ["call_aiArtModerate", "call_text2img"],
    "run.ai_generated_art.function_collection": ["text2img", "image_edit"]
}

function_declarations = declarations
