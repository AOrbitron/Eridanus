# -*- coding: utf-8 -*-
"""
Wardrobe Module (衣橱系统)
"""

plugin_description = "衣橱系统"

try:
    from run.wardrobe.wardrobe_manager import WardrobeManager, get_wardrobe_manager, call_change_outfit
except Exception:
    try:
        from .wardrobe_manager import WardrobeManager, get_wardrobe_manager, call_change_outfit
    except Exception:
        WardrobeManager = None
        get_wardrobe_manager = None
        call_change_outfit = None

dynamic_imports = {
    "run.wardrobe.wardrobe_manager": [
        "call_change_outfit",
    ]
}

function_declarations = [
    {
        "name": "call_change_outfit",
        "description": "切换或更换当前穿着的服装/衣橱搭配。当用户在聊天中明确要求你换装、换衣服、穿上特定服饰，或希望你生成特定着装自拍/照片时，必须调用此工具以同步更新衣橱中的当前穿着状态。若同时需要生成自拍，需协同调用 call_text2img。",
        "parameters": {
            "type": "object",
            "properties": {
                "outfit_name": {
                    "type": "string",
                    "description": (
                        "要更换的目标服装名称，支持全季节、多场合款式或模糊描述。例如：\n"
                        "- 招牌日常：常服1、默认常服、分层蛋糕裙、甜美洛丽塔、清凉小吊带、优雅晚礼服、哥特洛丽塔、运动活力、日系水手服、清雅汉元素\n"
                        "- 四季特色：春日碎花连衣裙、早春双排扣风衣、夏日海滩泳装、夏祭金鱼浴衣、清凉无袖网球裙、露肩雪纺一字领、秋日落叶针织衫、英伦复古格纹大衣、万圣节小恶魔装、冬日加厚白羽绒服、圣诞红斗篷礼裙、牛角扣毛呢大衣\n"
                        "- 主题与场合：机能风骑行皮衣、可爱猫耳女仆装、宅家慵懒连帽卫衣、烘焙围裙料理服、户外露营冲锋衣、游乐园兔耳背带裤、优雅黑天鹅芭蕾裙、正统和风振袖礼服\n"
                        "- 睡衣居家系列：可爱粉彩睡衣、性感丝绸吊带睡裙、黑色蕾丝透气睡衣、法兰绒暖冬睡衣、天蓝色条纹睡衣、纯白吊带荷叶边睡裙、藏青真丝排扣睡衣、和风纯棉甚平睡衣、毛绒猫咪连帽睡袍，或用户指定的任意自定义服饰"
                    )
                },
                "custom_description": {
                    "type": "string",
                    "description": "若用户要求穿着自定义细节、特定颜色、饰品搭配或衣橱中未收录的服饰，可在此提供具体的服装描述或英文 SD Prompt 关键词"
                }
            },
            "required": ["outfit_name"]
        }
    }
]

__all__ = [
    "WardrobeManager",
    "get_wardrobe_manager",
    "call_change_outfit",
    "plugin_description",
    "dynamic_imports",
    "function_declarations"
]
