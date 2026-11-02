from framework_common.framework_util.yamlLoader import YAMLManager

plugin_description = "ai绘画"
config=YAMLManager.get_instance()
ban_sd=config.ai_generated_art.config["gptimage2"]["接管sd"]
bot_name = config.common_config.basic_config["bot"]
aiDraw_funcs=["call_aiArtModerate"]
gptimage2_funcs=[
        "image_edit"
    ]
decrearations=[
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

]
if not ban_sd:
    aiDraw_funcs.append("call_text2img")
    decrearations.append(    {
    "name": "call_text2img",
    "description": "stable diffusion 文本转图像，仅支持英文tag，一般绘图使用。特别注意：当用户在对话中明确要求换装、换衣服、穿上特定服饰或希望你穿着特定服装自拍时，在调用本生图工具的同时，必须同时调用 call_change_outfit 工具更新衣橱中的当前穿着！",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "生成图片的提示词。如果原始提示词中有中文，则需要你把它们替换为对应英文,尽量使用词组，单词来进行描述，并用','来分割。可通过将词语x变为(x:n)的形式改变权重，n为0-1之间的浮点数，默认为1，为1时则无需用(x:1)的形式而是直接用x。例如，如果想要增加“猫”(也就是cat)的权重，则可以把它变成(cat:1.2)或更大的权重，反之则可以把权重变小。你需要关注不同词的重要性并给于权重，正常重要程度的词的权重为1，为1时则无需用(x:1)的形式而是直接用x。例如，想要画一个可爱的女孩则可输出1girl,(cute:1.2),bright eyes,smile,casual dress,detailed face,natural pose,soft lighting;想要更梦幻的感觉则可输出1girl,ethereal,floating hair,magical,sparkles,(dreamy:1.5),soft glow,pastel colors;想要未来风格则可输出1girl,(futuristic:1.3),neon lights,(cyber:1.2),hologram effects,(tech:1.5),clean lines,metallic;同时当输入中含有英文或用户要求保留时，要保留这些词"
            }
        },
        "required": [
            "prompt"
        ]
    }
})
else:
    gptimage2_funcs.append("text2img")
    decrearations.append({
        "name": "text2img",
        "description": (
            f"使用 gptimage2 文生图，支持中文，理解自然语言描述。"
            f"注意：本接口与 stable diffusion 完全不同，"
            f"禁止使用 tag 堆砌或英文权重语法（如 (cat:1.2) 这类写法），"
            f"必须用完整的中文句子描述画面内容。"
            f"如果是关于{bot_name}的图，将 is_about_bot 设为 true，"
            f"prompt 中不要加任何外貌描述，只描述场景、动作、表情等要求即可。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        f"用自然语言（完整句子）描述绘图要求，支持中文。"
                        f"禁止使用逗号分隔的 tag 列表，禁止使用 (词:权重) 语法。"
                        f"正确示例：'在樱花树下弹钢琴，傍晚暖光，温柔微笑'。"
                        f"错误示例：'1girl, sakura, (smile:1.2), piano, warm light'。"
                        f"如果 is_about_bot 为 true，不要在 prompt 里描述{bot_name}的外貌，"
                        f"只描述她在做什么、在哪里、什么氛围即可。"
                    )
                },
                "is_about_bot": {
                    "type": "boolean",
                    "description": (
                        f"是否是关于{bot_name}的图。"
                        f"用户明确提到{bot_name}或用'她''你'指代{bot_name}时为 true，"
                        f"其他情况默认 false。"
                    )
                }
            },
            "required": ["prompt"]
        }
    })
dynamic_imports = {
"run.ai_generated_art.aiDraw": aiDraw_funcs,
    "run.ai_generated_art.function_collection": gptimage2_funcs
}

function_declarations=decrearations
