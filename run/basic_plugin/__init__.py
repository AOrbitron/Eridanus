plugin_description = "基础功能集合"


dynamic_imports = {
    "run.basic_plugin.basic_plugin": [
        "call_weather_query", "call_setu","call_tarot", "call_pick_music",
        "call_fortune","call_menu"
    ],
    "run.basic_plugin.image_search":
        ["call_image_search"],
}
function_declarations=[
    {
        "name": "call_weather_query",
        "description": "Get the current weather in a given location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. 上海"
                }
            },
            "required": [
                "location"
            ]
        }
    },
    {
        "name": "call_setu",
        "description": "根据关键字发送一张图片（涩图图片）",
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "description": "想要的关键字。eg.黑丝 白丝",
                    "items": {
                        "type": "string"
                    }
                },
                "num": {
                    "type": "integer",
                    "description": "返回的图片数量，默认为1"
                }
            },
            "required": [
                "tags"
            ]
        }
    },
    {
        "name": "call_image_search",
        "description": "按照用户要求搜索给定图片的来源、作者、出处或番号。支持动漫插画、二次元、本子以及视频截图番号识别(AVScan)。如果用户没有要求，不要主动搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "待搜索图片的url或本地文件路径"
                }
            },
            "required": [
                "image_url"
            ]
        }
    },
    {
        "name": "call_pick_music",
        "description": "点歌或选取音乐。根据歌曲名或歌手查找音乐。",
        "parameters": {
            "type": "object",
            "properties": {
                "aim": {
                    "type": "string",
                    "description": "歌曲名或歌手名。eg.周杰伦 eg.晴天"
                }
            },
            "required": [
                "aim"
            ]
        }
    },
    {
        "name": "call_tarot",
        "description": "抽取一张塔罗牌。"
    },
    {
        "name": "call_fortune",
        "description": "今日占卜（运势卡片）。"
    },

    {
        "name": "call_menu",
        "description": "发送功能列表/菜单/帮助指令。"
    },

]
