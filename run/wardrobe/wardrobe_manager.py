# -*- coding: utf-8 -*-
"""
Wardrobe Manager (衣橱管理系统)
管理 Bot 服饰配置、当前着装及各条动态独立的 SD 提示词组装。
支持 WebUI (run/wardrobe/config.yaml) 与 Function Calling 协同换装。
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List

try:
    from ruamel.yaml import YAML
    _has_ruamel = True
except ImportError:
    _has_ruamel = False

try:
    import yaml
except ImportError:
    yaml = None

try:
    from framework_common.framework_util.yamlLoader import YAMLManager
    _has_yaml_manager = True
except ImportError:
    _has_yaml_manager = False
    YAMLManager = None

logger = logging.getLogger("Wardrobe")

YAML_CONFIG_PATH = os.path.join("run", "wardrobe", "config.yaml")
OUTFITS_KEY = "outfits_v6"
LEGACY_OUTFIT_KEYS = ("outfits_v5", "outfits_v4", "outfits_v3", "outfits_v2", "outfits")
RETIRED_DAILY_FIELDS = ("today_default_outfit", "today_default_tags", "today_default_no_hat", "last_daily_date")

DEFAULT_CHARACTER_ANCHOR = (
    "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, "
    "light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2)"
)

DEFAULT_ART_ANCHOR = (
    "(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), "
    "masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), "
    "Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>"
)

DEFAULT_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, "
    "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, nsfw"
)

DEFAULT_OUTFITS = {   '万圣节小恶魔装': {   'category': 'festival',
                   'clothing_tags': 'halloween costume, mischievous little devil outfit, black and crimson ruffled '
                                    'dress, tiny bat wings on back, little devil horns headband, pumpkin lantern, '
                                    'striped thigh-high stockings, playful smirk, gothic fantasy party',
                   'description': '万圣节俏皮可爱小恶魔洋装（蝙蝠小翅膀、黑红蕾丝裙、南瓜糖果与俏皮眨眼）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), halloween costume, mischievous little devil outfit, '
                                  'black and crimson ruffled dress, tiny bat wings on back, little devil horns '
                                  'headband, pumpkin lantern, striped thigh-high stockings, playful smirk, gothic '
                                  'fantasy party, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                  '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                  "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '万圣节小恶魔装',
                   'occasion': 'halloween, party, costume',
                   'season': 'autumn'},
    '中秋织金马面裙云肩': {   'category': 'special',
                     'clothing_tags': 'traditional exquisite Chinese hanfu, crimson red and gold brocade mamianqun '
                                      'pleated skirt with embroidered dragon and floral patterns, ivory standing '
                                      'collar short jacket, ornate embroidered yunjian cloud collar, silk ribbon sash, '
                                      'glowing round full moon over ornate traditional carved pavilion railing',
                     'description': '中秋国风古典朱红织金马面裙配如意如意云肩与立领短衫，凭栏赏圆月',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), traditional exquisite Chinese hanfu, crimson red and '
                                    'gold brocade mamianqun pleated skirt with embroidered dragon and floral patterns, '
                                    'ivory standing collar short jacket, ornate embroidered yunjian cloud collar, silk '
                                    'ribbon sash, glowing round full moon over ornate traditional carved pavilion '
                                    'railing, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                    'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                    "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                     'name': '中秋织金马面裙云肩',
                     'no_hat': False,
                     'occasion': 'traditional, festival, moon festival',
                     'season': 'autumn'},
    '优雅晚礼服': {   'category': 'special',
                 'clothing_tags': 'elegant evening gown, off-shoulder black silk dress, satin finish, delicate silver '
                                  'necklace, graceful banquet attire, floor-length dress, soft ballroom lighting',
                 'description': '露肩宴会丝缎长裙晚礼服（端庄高贵、精致优雅）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), elegant evening gown, off-shoulder black silk dress, satin finish, '
                                'delicate silver necklace, graceful banquet attire, floor-length dress, soft ballroom '
                                'lighting, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                 'name': '优雅晚礼服',
                 'occasion': 'banquet, party, formal',
                 'season': 'all'},
    '优雅黑天鹅芭蕾裙': {   'category': 'special',
                    'clothing_tags': 'black swan ballet dress, intricate lace embroidered corset bodice, stiff layered '
                                     'tulle ballet tutu, delicate black feather hair accessory, silk ballet pointe '
                                     'shoes, theater stage spotlight, dramatic graceful pose',
                    'description': '华丽黑天鹅蕾丝刺绣芭蕾舞蓬蓬短裙（暗夜羽毛、优雅足尖鞋、舞台追光）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), black swan ballet dress, intricate lace embroidered '
                                   'corset bodice, stiff layered tulle ballet tutu, delicate black feather hair '
                                   'accessory, silk ballet pointe shoes, theater stage spotlight, dramatic graceful '
                                   'pose, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                   'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                   "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                    'name': '优雅黑天鹅芭蕾裙',
                    'occasion': 'stage, dance, formal',
                    'season': 'all'},
    '元宵绒毛斗篷短唐装': {   'category': 'special',
                     'clothing_tags': 'festive vibrant red velvet Tang suit jacket with gold frog buttons, cozy white '
                                      'faux fur trim collar, matching hooded red winter capelet with white pom-poms, '
                                      'embroidered black pleated skirt, holding glowing paper rabbit lantern, night '
                                      'lantern festival street',
                     'description': '元宵佳节喜庆红丝绒短款立领唐装配白绒毛边斗篷披肩，提着兔子花灯',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), festive vibrant red velvet Tang suit jacket with '
                                    'gold frog buttons, cozy white faux fur trim collar, matching hooded red winter '
                                    'capelet with white pom-poms, embroidered black pleated skirt, holding glowing '
                                    'paper rabbit lantern, night lantern festival street, (Rella:1.2), (chen bin:1.3), '
                                    'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                    "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                    'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '元宵绒毛斗篷短唐装',
                     'no_hat': False,
                     'occasion': 'traditional, festival, lantern',
                     'season': 'winter'},
    '冬日加厚白羽绒服': {   'category': 'seasonal',
                    'clothing_tags': 'winter clothing, oversized puffy white down jacket, chunky thick knit muffler scarf wrapped around neck, fluffy earmuffs, woolen mittens, snowy city street background, gentle snowflakes falling, breath vapor, charcoal wool straight-leg trousers, brown winter ankle boots',
                    'description': '冬日加厚米白立领羽绒服搭配厚毛线围巾与毛绒耳罩（初雪街头、呵气成霜）',
                    'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), winter clothing, oversized puffy white down jacket, chunky thick knit muffler scarf wrapped around neck, fluffy earmuffs, woolen mittens, snowy city street background, gentle snowflakes falling, breath vapor, charcoal wool straight-leg trousers, brown winter ankle boots, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                    'name': '冬日加厚白羽绒服',
                    'occasion': 'outdoor, snow, winter',
                    'season': 'winter'},
    '分层蛋糕裙': {'name': '分层蛋糕裙', 'description': '轻甜层叠花边蛋糕裙（多层褶皱下摆、甜美少女风）', 'category': 'daily', 'season': 'spring/summer', 'occasion': 'date, casual', 'clothing_tags': 'pastel tiered ruffle dress, layered cake skirt silhouette, delicate ribbon bow, cute Mary Jane shoes', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), pastel tiered ruffle dress, layered cake skirt silhouette, delicate ribbon bow, cute Mary Jane shoes, full body, standing, plain warm white background, simple background, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_background': 'full body, standing, plain warm white background, simple background', 'preview_negative': 'car, automobile, vehicle, truck, bus, traffic, road, garage'},
    '可爱猫耳女仆装': {   'category': 'special',
                   'clothing_tags': 'cute maid uniform, classic black french maid dress, frilled white apron with lace '
                                    'trim, cat ears headband, maid headdress, white ruffled wrist cuffs, holding '
                                    'silver tea tray, cafe interior, sweet playful smile',
                   'description': '经典黑白蕾丝花边短裙女仆装配猫耳发箍与猫爪装饰（俏皮女仆、托盘点心）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), cute maid uniform, classic black french maid dress, '
                                  'frilled white apron with lace trim, cat ears headband, maid headdress, white '
                                  'ruffled wrist cuffs, holding silver tea tray, cafe interior, sweet playful smile, '
                                  '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                  'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                  "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                   'name': '可爱猫耳女仆装',
                   'occasion': 'cafe, cosplay, party',
                   'season': 'all'},
    '可爱粉彩睡衣': {   'category': 'sleepwear',
                  'clothing_tags': 'cute oversized pastel pajamas, cozy cotton sleepwear, pastel pink and light mint '
                                   'accents, long sleeves, loose sleep pants, bedtime indoors, messy hair, cozy '
                                   'bedroom lighting, soft pillows',
                  'description': '软萌马卡龙粉彩纯棉睡衣（宽松长袖+长裤，居家晚安，免帽）',
                  'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                 'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                 '(round face:1.2), cute oversized pastel pajamas, cozy cotton sleepwear, pastel pink '
                                 'and light mint accents, long sleeves, loose sleep pants, bedtime indoors, messy '
                                 'hair, cozy bedroom lighting, soft pillows, (Rella:1.2), (chen bin:1.3), virtual '
                                 'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                 "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                 '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                  'name': '可爱粉彩睡衣',
                  'no_hat': True,
                  'occasion': 'sleep, bedtime, home',
                  'season': 'all'},

    '哥特洛丽塔': {   'category': 'daily',
                 'clothing_tags': 'gothic lolita, dark victorian aesthetic, black and purple frilled dress, lace '
                                  'bonnet, cross pendant choker, rose embroidery, mysterious elegant atmosphere',
                 'description': '暗黑维多利亚哥特式洋装（黑紫配色、十字与暗纹蕾丝）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), gothic lolita, dark victorian aesthetic, black and purple frilled '
                                'dress, lace bonnet, cross pendant choker, rose embroidery, mysterious elegant '
                                'atmosphere, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                 'name': '哥特洛丽塔',
                 'occasion': 'convention, gothic party',
                 'season': 'all'},
    '图书馆文艺知性长裙': {   'category': 'daily',
                     'clothing_tags': 'soft heather grey loose-fit wool cardigan, milk-tea colored accordion pleated '
                                      'maxi skirt, white silk blouse, thin gold-framed round reading glasses, holding '
                                      'vintage hardcover book, tall wooden library bookshelves filled with books',
                     'description': '图书馆知性文艺浅灰落肩羊毛开衫配奶茶色百褶半身长裙，细金丝眼镜与精装书',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), soft heather grey loose-fit wool cardigan, milk-tea '
                                    'colored accordion pleated maxi skirt, white silk blouse, thin gold-framed round '
                                    'reading glasses, holding vintage hardcover book, tall wooden library bookshelves '
                                    'filled with books, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                    '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                    "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                    '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '图书馆文艺知性长裙',
                     'no_hat': False,
                     'occasion': 'library, reading, calm',
                     'season': 'spring/autumn'},
    '圣诞红斗篷礼裙': {   'category': 'festival',
                   'clothing_tags': 'christmas holiday outfit, red velvet hooded capelet with fluffy white fur trim, '
                                    'matching festive mini dress, golden jingle bell ribbon choker, decorated '
                                    'christmas tree background, warm bokeh lights, festive holiday sparkles',
                   'description': '圣诞节日红丝绒白毛边连帽斗篷与抹胸小礼裙（金色铃铛、圣诞树暖光）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), christmas holiday outfit, red velvet hooded capelet '
                                  'with fluffy white fur trim, matching festive mini dress, golden jingle bell ribbon '
                                  'choker, decorated christmas tree background, warm bokeh lights, festive holiday '
                                  'sparkles, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                  'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                  "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                   'name': '圣诞红斗篷礼裙',
                   'occasion': 'christmas, holiday, party',
                   'season': 'winter'},
    '夏日海滩泳装': {'name': '夏日海滩泳装', 'description': '白色可爱蕾丝边分体比基尼，细致花边与蝴蝶结，无外搭，免帽', 'category': 'seasonal', 'season': 'summer', 'occasion': 'beach, seaside, pool, vacation', 'no_hat': True, 'clothing_tags': '(white two-piece bikini:1.5), (white triangle bikini top:1.3), matching white tie-side bikini bottoms, small scalloped lace edging on bikini cups, small white ribbon bows, bare midriff, navel, bare legs', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), (white two-piece bikini:1.5), (white triangle bikini top:1.3), matching white tie-side bikini bottoms, small scalloped lace edging on bikini cups, small white ribbon bows, bare midriff, navel, bare legs, full body, standing, arms relaxed at sides, simple light grey background, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_negative': 'cover-up, wrap, robe, jacket, blue bikini, pink bikini, nightdress, babydoll, dress, skirt, one-piece swimsuit, camisole, lace bodysuit, covered midriff, cropped, upper body, portrait', 'preview_background': 'full body, standing, arms relaxed at sides, simple light grey background'},
    '夏祭捞金鱼印花甚平': {'name': '夏祭捞金鱼印花甚平', 'description': '藏青金鱼印花短袖甚平上衣配同款短裤，单层两件套，无长袍或外搭', 'category': 'seasonal', 'season': 'summer', 'occasion': 'festival, summer night', 'no_hat': False, 'clothing_tags': 'indigo blue cotton jinbei short-sleeved shirt with side ties, matching indigo blue above-knee shorts, small goldfish print on shirt fabric, single-layer two-piece summer outfit, wooden geta sandals, bare forearms', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), indigo blue cotton jinbei short-sleeved shirt with side ties, matching indigo blue above-knee shorts, small goldfish print on shirt fabric, single-layer two-piece summer outfit, wooden geta sandals, bare forearms, full body, standing, simple light grey studio background, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_background': 'full body, standing, simple light grey studio background', 'preview_negative': 'long robe, kimono, yukata, haori, cape, cloak, coat, cardigan, outerwear, long sleeves, long skirt'},
    '夏祭金鱼浴衣': {'name': '夏祭金鱼浴衣', 'description': '深蓝金鱼与水波纹样浴衣，红色花纹腰带，木屐；不绑定场景或道具', 'category': 'festival', 'season': 'summer', 'occasion': 'festival, evening, fireworks', 'no_hat': True, 'clothing_tags': 'navy blue cotton yukata, orange goldfish and water ripple print on yukata fabric, red floral obi sash, wooden geta sandals', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), navy blue cotton yukata, orange goldfish and water ripple print on yukata fabric, red floral obi sash, wooden geta sandals, full body, standing, simple light grey studio background, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_background': 'full body, standing, simple light grey studio background', 'preview_negative': 'fireworks, lanterns, festival stalls, pond, river, standing in water, floating fish'},
    '天蓝色条纹睡衣': {   'category': 'sleepwear',
                   'clothing_tags': 'light blue striped pajamas, classic button-up pajama shirt, soft breathable '
                                    'cotton, neat collar, relaxed morning aesthetic, holding a glass of warm milk, '
                                    'sunlit bedroom',
                   'description': '经典清爽天蓝色条纹开襟睡衣（衬衫领、干净少年感，免帽）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), light blue striped pajamas, classic button-up pajama '
                                  'shirt, soft breathable cotton, neat collar, relaxed morning aesthetic, holding a '
                                  'glass of warm milk, sunlit bedroom, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                  '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                  "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '天蓝色条纹睡衣',
                   'no_hat': True,
                   'occasion': 'bedtime, morning',
                   'season': 'spring/autumn'},
    '宅家慵懒连帽卫衣': {   'category': 'daily',
                    'clothing_tags': 'ultra oversized slouchy pastel hoodie covering thighs, striped over-knee socks, '
                                     'RGB gaming headphones around neck, sitting on cozy couch with gaming controller, '
                                     'living room with anime posters, relaxed comfortable mood',
                    'description': '宅家超大号落肩oversize连帽衫与黑白条纹过膝袜（电竞耳机、沙发游戏躺平，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), ultra oversized slouchy pastel hoodie covering '
                                   'thighs, striped over-knee socks, RGB gaming headphones around neck, sitting on '
                                   'cozy couch with gaming controller, living room with anime posters, relaxed '
                                   'comfortable mood, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                   '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '宅家慵懒连帽卫衣',
                    'no_hat': True,
                    'occasion': 'home, gaming, relaxation',
                    'season': 'all'},
    '常服1': {   'category': 'daily',
               'clothing_tags': 'smirk, mischievous smile, wink, street style, oversized jacket, casual clothes',
               'description': '街头潮酷常服：Oversized 夹克外套配休闲私服（去除了扳手与修车元素，纯粹的街头潮服搭配）',
               'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                              'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                              '(round face:1.2), smirk, mischievous smile, wink, street style, oversized jacket, '
                              'casual clothes, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                              '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), '
                              "(sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                              '<lora:DeniaV1-Nuclear1811-IL:0.5>',
               'name': '常服1',
               'occasion': 'casual, street, daily',
               'season': 'all'},
    '性感丝绸吊带睡裙': {   'category': 'sleepwear',
                    'clothing_tags': 'sexy silk nightdress, slip dress, thin spaghetti straps, soft glossy champagne '
                                     'satin, collarbone, bare shoulders, feminine allure, dim romantic bedroom '
                                     'lighting, silk bedsheets',
                    'description': '柔滑光泽丝缎细吊带睡裙（微露锁骨、轻盈性感，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), sexy silk nightdress, slip dress, thin spaghetti '
                                   'straps, soft glossy champagne satin, collarbone, bare shoulders, feminine allure, '
                                   'dim romantic bedroom lighting, silk bedsheets, (Rella:1.2), (chen bin:1.3), '
                                   'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                   "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                   'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '性感丝绸吊带睡裙',
                    'no_hat': True,
                    'occasion': 'bedtime, sensual',
                    'season': 'summer/autumn'},
    '户外露营冲锋衣': {   'category': 'sport',
                   'clothing_tags': 'outdoor mountain techwear, color-blocked windbreaker camping jacket, khaki cargo '
                                    'pants, mountain boots, camping backpack, wilderness campfire background, starry '
                                    'night sky, cozy tent',
                   'description': '户外山野拼色防风防水三合一冲锋衣搭工装裤（山系露营、篝火帐篷星空）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), outdoor mountain techwear, color-blocked windbreaker '
                                  'camping jacket, khaki cargo pants, mountain boots, camping backpack, wilderness '
                                  'campfire background, starry night sky, cozy tent, (Rella:1.2), (chen bin:1.3), '
                                  'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                  "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '户外露营冲锋衣',
                   'occasion': 'camping, outdoor, hiking',
                   'season': 'spring/autumn'},
    '日系水手服': {'name': '日系水手服', 'description': '经典藏青百褶裙日系水手服（青春校园、微风拂动）', 'category': 'daily', 'season': 'spring/summer', 'occasion': 'school, campus', 'clothing_tags': 'sailor uniform, pleated navy skirt, white sailor collar blouse, small red ribbon bow at chest, white knee-high socks, brown loafers', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), sailor uniform, pleated navy skirt, white sailor collar blouse, small red ribbon bow at chest, white knee-high socks, brown loafers, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_negative': 'scarf, muffler, neck wrap, cape, cloak'},
    '早春双排扣风衣': {   'category': 'seasonal',
                   'clothing_tags': 'khaki double-breasted trench coat, open coat, pastel striped turtleneck sweater, '
                                    'plaid scarf, pleated skirt, brown ankle boots, spring breeze, city street '
                                    'background',
                   'description': '早春卡其色经典双排扣长款风衣搭格子围巾（英伦街头、微风漫步）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), khaki double-breasted trench coat, open coat, pastel '
                                  'striped turtleneck sweater, plaid scarf, pleated skirt, brown ankle boots, spring '
                                  'breeze, city street background, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                  '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                  "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '早春双排扣风衣',
                   'occasion': 'street, casual, city',
                   'season': 'spring'},
    '春日田园野餐格纹裙': {   'category': 'seasonal',
                     'clothing_tags': 'pastel yellow gingham cottagecore dress, cute puff sleeves, ruffled sweetheart '
                                      'neckline, wide-brim straw sunhat with chiffon ribbon, holding woven picnic '
                                      'basket, blooming wildflower meadow in spring breeze',
                     'description': '早春田园鹅黄细格纹泡泡袖连衣裙，系带宽檐草帽与野餐竹篮',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), pastel yellow gingham cottagecore dress, cute puff '
                                    'sleeves, ruffled sweetheart neckline, wide-brim straw sunhat with chiffon ribbon, '
                                    'holding woven picnic basket, blooming wildflower meadow in spring breeze, '
                                    '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                    'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                    "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                     'name': '春日田园野餐格纹裙',
                     'no_hat': False,
                     'occasion': 'picnic, park, outdoor',
                     'season': 'spring'},
    '春日碎花连衣裙': {'name': '春日碎花连衣裙', 'description': '春日清新碎花雪纺吊带长裙，单穿无外搭', 'category': 'seasonal', 'season': 'spring', 'occasion': 'picnic, park, date', 'clothing_tags': 'floral print sundress, pastel chiffon maxi dress, thin shoulder straps, fitted bodice, flowing floral skirt, bare arms', 'full_prompt': "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), floral print sundress, pastel chiffon maxi dress, thin shoulder straps, fitted bodice, flowing floral skirt, bare arms, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>", 'preview_negative': 'cardigan, jacket, coat, shawl, cape, outerwear'},
    '春雨透明轻便雨衣': {   'category': 'seasonal',
                    'clothing_tags': 'clear transparent vinyl hooded raincoat, pastel pink oversized hoodie '
                                     'underneath, denim skinny jeans, bright yellow rain boots, holding clear vinyl '
                                     'umbrella, rain drops on coat, wet city pavement with neon reflections',
                    'description': '春日细雨透明PVC连帽雨衣，内搭粉彩卫衣，手撑透明雨伞与雨中水坑倒影',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), clear transparent vinyl hooded raincoat, pastel pink '
                                   'oversized hoodie underneath, denim skinny jeans, bright yellow rain boots, holding '
                                   'clear vinyl umbrella, rain drops on coat, wet city pavement with neon reflections, '
                                   '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                   'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                   "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                    'name': '春雨透明轻便雨衣',
                    'no_hat': False,
                    'occasion': 'rainy, outdoor, city walk',
                    'season': 'spring'},
    '极地专业加厚滑雪服': {   'category': 'seasonal',
                     'clothing_tags': 'professional waterproof ski jacket with neon turquoise and purple '
                                      'color-blocking, matching insulated snow pants, colorful reflective ski goggles '
                                      'pushed up on winter helmet, waterproof ski gloves, majestic snow-covered '
                                      'mountain peaks background',
                     'description': '极地荧光拼色加厚防水专业滑雪服配护目镜与雪板，雪山峰巅',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), professional waterproof ski jacket with neon '
                                    'turquoise and purple color-blocking, matching insulated snow pants, colorful '
                                    'reflective ski goggles pushed up on winter helmet, waterproof ski gloves, '
                                    'majestic snow-covered mountain peaks background, (Rella:1.2), (chen bin:1.3), '
                                    'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                    "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                    'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '极地专业加厚滑雪服',
                     'no_hat': False,
                     'occasion': 'skiing, snow sport, mountain',
                     'season': 'winter'},
    '正统和风振袖礼服': {   'category': 'special',
                    'clothing_tags': 'traditional Japanese formal furisode kimono, long flowing sleeves, vibrant red '
                                     'and gold floral embroidery, luxurious brocade obi sash, elegant kanzashi cherry '
                                     'blossom hair ornament, traditional shrine garden background, dignified graceful '
                                     'aura',
                    'description': '华丽庄重红白金纹正统振袖和服配华贵锦缎腰封（成人礼/新年参拜、樱花发饰，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), traditional Japanese formal furisode kimono, long '
                                   'flowing sleeves, vibrant red and gold floral embroidery, luxurious brocade obi '
                                   'sash, elegant kanzashi cherry blossom hair ornament, traditional shrine garden '
                                   'background, dignified graceful aura, (Rella:1.2), (chen bin:1.3), virtual '
                                   'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '正统和风振袖礼服',
                    'no_hat': True,
                    'occasion': 'ceremony, new year, shrine',
                    'season': 'all'},
    '毛绒猫咪连帽睡袍': {   'category': 'sleepwear',
                    'clothing_tags': 'fluffy oversized coral fleece bathrobe, cute cat ears on hood, belted waist wrap '
                                     'robe, cream white with pastel pink trim, embroidered cat paw pockets, soft warm '
                                     'indoor bedroom, fluffy slippers, yawning cute sleepy expression',
                    'description': '软糯加厚珊瑚绒猫耳连帽系带浴袍睡衣（奶白撞粉、小猫爪刺绣口袋，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), fluffy oversized coral fleece bathrobe, cute cat ears '
                                   'on hood, belted waist wrap robe, cream white with pastel pink trim, embroidered '
                                   'cat paw pockets, soft warm indoor bedroom, fluffy slippers, yawning cute sleepy '
                                   'expression, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                   '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '毛绒猫咪连帽睡袍',
                    'no_hat': True,
                    'occasion': 'bath, morning, cozy night',
                    'season': 'autumn/winter'},
    '法兰绒暖冬睡衣': {   'category': 'sleepwear',
                   'clothing_tags': 'flannel hooded pajamas, fluffy warm bear ears sleepwear, ultra cozy thick coral '
                                    'fleece, cream white and milk tea tones, hugging a plush toy, warm indoor '
                                    'lighting, sleepy cute expression',
                   'description': '加厚保暖珊瑚绒小熊连帽睡衣（软糯温暖、冬夜治愈，免帽）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), flannel hooded pajamas, fluffy warm bear ears '
                                  'sleepwear, ultra cozy thick coral fleece, cream white and milk tea tones, hugging a '
                                  'plush toy, warm indoor lighting, sleepy cute expression, (Rella:1.2), (chen '
                                  'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                  "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                  'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '法兰绒暖冬睡衣',
                   'no_hat': True,
                   'occasion': 'winter sleep, cozy home',
                   'season': 'winter'},
    '涂鸦机修工装背带裤': {   'category': 'daily',
                     'clothing_tags': 'distressed denim mechanic overalls, worn over fitted black crop top, colorful '
                                      'graffiti spray paint splatters, slight engine grease smudge on cheek, holding '
                                      'ratcheting socket wrench, canvas utility pouch, work boots, messy urban '
                                      'workshop',
                     'description': '街头机修个性背带工装裤，微量机油痕与亮色涂鸦，手持棘轮扳手',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), distressed denim mechanic overalls, worn over fitted '
                                    'black crop top, colorful graffiti spray paint splatters, slight engine grease '
                                    'smudge on cheek, holding ratcheting socket wrench, canvas utility pouch, work '
                                    'boots, messy urban workshop, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                    '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                    "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                    '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '涂鸦机修工装背带裤',
                     'no_hat': False,
                     'occasion': 'workshop, street, casual',
                     'season': 'all'},
    '深秋复古灯芯绒背带裤': {   'category': 'seasonal',
                      'clothing_tags': 'warm caramel brown corduroy dungarees, cozy cream white ribbed turtleneck '
                                       'sweater underneath, brass button details, brown leather ankle boots, golden '
                                       'ginkgo leaves floating in wind, cozy autumn park bench',
                      'description': '深秋温暖焦糖色灯芯绒背带阔腿裤配米白高领毛衣，银杏落叶长椅',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), warm caramel brown corduroy dungarees, cozy cream '
                                     'white ribbed turtleneck sweater underneath, brass button details, brown leather '
                                     'ankle boots, golden ginkgo leaves floating in wind, cozy autumn park bench, '
                                     '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                     'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), '
                                     "Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                      'name': '深秋复古灯芯绒背带裤',
                      'no_hat': False,
                      'occasion': 'casual, autumn, city',
                      'season': 'autumn'},
    '清凉小吊带': {   'category': 'daily',
                 'clothing_tags': 'spaghetti strap top, casual white camisole, denim shorts, collarbone, bare '
                                  'shoulders, summer casual wear, refreshing cute outfit, soft indoor natural light',
                 'description': '夏日清凉细吊带搭配牛仔短裤（慵懒休闲、锁骨微露）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), spaghetti strap top, casual white camisole, denim shorts, '
                                'collarbone, bare shoulders, summer casual wear, refreshing cute outfit, soft indoor '
                                'natural light, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), '
                                "(sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                 'name': '清凉小吊带',
                 'occasion': 'casual, indoor, summer',
                 'season': 'summer'},
    '清凉无袖网球裙': {   'category': 'sport',
                   'clothing_tags': 'sporty tennis uniform, sleeveless white polo shirt with green collar trim, '
                                    'pleated tennis miniskirt, white wristbands, athletic socks, white sneakers, sunny '
                                    'outdoor tennis court, sweat drop, dynamic athletic pose',
                   'description': '夏日清爽白绿配色无袖立领网球服与百褶超短裙（阳光球场、元气运动）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), sporty tennis uniform, sleeveless white polo shirt '
                                  'with green collar trim, pleated tennis miniskirt, white wristbands, athletic socks, '
                                  'white sneakers, sunny outdoor tennis court, sweat drop, dynamic athletic pose, '
                                  '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                  'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                  "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                   'name': '清凉无袖网球裙',
                   'occasion': 'sports, tennis, summer',
                   'season': 'summer'},
    '清爽无袖水手百褶裙': {   'category': 'seasonal',
                     'clothing_tags': 'sleeveless crisp white sailor shirt with navy blue striped collar, blue silk '
                                      'neckerchief, matching pleated navy mini skirt, white ankle socks, brown '
                                      'loafers, coastal seaside promenade with clear blue sky',
                     'description': '盛夏清爽无袖水手领制服衬衫配海军蓝百褶超短裙与领巾，海风步道',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), sleeveless crisp white sailor shirt with navy blue '
                                    'striped collar, blue silk neckerchief, matching pleated navy mini skirt, white '
                                    'ankle socks, brown loafers, coastal seaside promenade with clear blue sky, '
                                    '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                    'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                    "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                     'name': '清爽无袖水手百褶裙',
                     'no_hat': False,
                     'occasion': 'school, coastal, summer',
                     'season': 'summer'},
    '清雅汉元素': {   'category': 'special',
                 'clothing_tags': 'hanfu-inspired dress, modern modified hanfu, flowing chiffon sleeves, pastel teal '
                                  'and white gradients, delicate floral embroidery, traditional ribbon tassels, '
                                  'classical pavilion',
                 'description': '改良国风汉元素轻纱仙女裙（飘逸雪纺、灵动温婉）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), hanfu-inspired dress, modern modified hanfu, flowing chiffon '
                                'sleeves, pastel teal and white gradients, delicate floral embroidery, traditional '
                                'ribbon tassels, classical pavilion, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, (hand-drawn:1.3), '
                                "(sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                 'name': '清雅汉元素',
                 'occasion': 'festival, scenic travel',
                 'season': 'spring/summer'},
    '游乐园兔耳背带裤': {   'category': 'daily',
                    'clothing_tags': 'playful amusement park outfit, light blue denim dungarees overalls, bright '
                                     'pastel yellow t-shirt, fluffy white bunny ears headband, holding cute novelty '
                                     'popcorn bucket, colorful amusement park Ferris wheel background',
                    'description': '游乐园萌系浅色牛仔背带长裤内搭印花黄T恤与毛绒兔耳发箍（摩天轮、爆米花桶）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), playful amusement park outfit, light blue denim '
                                   'dungarees overalls, bright pastel yellow t-shirt, fluffy white bunny ears '
                                   'headband, holding cute novelty popcorn bucket, colorful amusement park Ferris '
                                   'wheel background, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                   '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '游乐园兔耳背带裤',
                    'occasion': 'amusement park, date, travel',
                    'season': 'spring/summer'},
    '烘焙围裙料理服': {   'category': 'daily',
                   'clothing_tags': 'cute ruffled cooking apron, pastel gingham plaid apron over casual white t-shirt, '
                                    'rolled up sleeves, flour smudge on cheek, holding tray of fresh baked chocolate '
                                    'cookies, cozy kitchen background, proud happy smile',
                   'description': '居家浅粉格子荷叶边烘焙围裙内搭纯白T恤（鼻尖面粉、烤盘刚出炉曲奇，免帽）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), cute ruffled cooking apron, pastel gingham plaid apron '
                                  'over casual white t-shirt, rolled up sleeves, flour smudge on cheek, holding tray '
                                  'of fresh baked chocolate cookies, cozy kitchen background, proud happy smile, '
                                  '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                  'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                  "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                   'name': '烘焙围裙料理服',
                   'no_hat': True,
                   'occasion': 'kitchen, cooking, baking',
                   'season': 'all'},
    '牛角扣毛呢大衣': {   'category': 'seasonal',
                   'clothing_tags': 'navy blue duffle coat, wooden toggle buttons, hooded wool coat, warm dark grey '
                                    'woolen tights, plaid wool scarf, holding hot canned coffee, winter afternoon '
                                    'sunlight, cozy street corner',
                   'description': '经典藏青色牛角扣连帽毛呢大衣搭羊毛保暖袜（日系冬日JK、冬日暖阳）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), navy blue duffle coat, wooden toggle buttons, hooded '
                                  'wool coat, warm dark grey woolen tights, plaid wool scarf, holding hot canned '
                                  'coffee, winter afternoon sunlight, cozy street corner, (Rella:1.2), (chen bin:1.3), '
                                  'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                  "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '牛角扣毛呢大衣',
                   'occasion': 'school, casual, winter',
                   'season': 'winter'},
    '甜美洛丽塔': {   'category': 'daily',
                 'clothing_tags': 'sweet lolita dress, frills, lace trim, petticoat, layered ribbons, cute tea party '
                                  'dress, white lace socks, Mary Jane shoes, elegant doll aesthetic',
                 'description': '软萌甜系茶会洛丽塔洋装（蓬蓬裙、蕾丝缎带）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), sweet lolita dress, frills, lace trim, petticoat, layered ribbons, '
                                'cute tea party dress, white lace socks, Mary Jane shoes, elegant doll aesthetic, '
                                '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, '
                                'extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van '
                                "Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                 'name': '甜美洛丽塔',
                 'occasion': 'tea party, convention',
                 'season': 'all'},
    '电子极客焊接工装': {   'category': 'special',
                    'clothing_tags': 'protective retro welding goggles resting on forehead, heavy khaki canvas '
                                     'workshop apron, grey henley shirt with sleeves pushed up, anti-static gloves, '
                                     'soldering iron on bench, wooden electronics workbench with circuit boards and '
                                     'wires',
                    'description': '电子极客工坊装束，额头推戴复古防风护目镜，耐磨帆布围裙与工作台',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), protective retro welding goggles resting on forehead, '
                                   'heavy khaki canvas workshop apron, grey henley shirt with sleeves pushed up, '
                                   'anti-static gloves, soldering iron on bench, wooden electronics workbench with '
                                   'circuit boards and wires, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                   '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '电子极客焊接工装',
                    'no_hat': False,
                    'occasion': 'maker, electronics, indoor',
                    'season': 'all'},
    '男友风宽松白色长衬衫': {   'category': 'sleepwear',
                      'clothing_tags': 'oversized boyfriend white cotton button-down shirt, loosely unbuttoned at '
                                       'collar, slipping slightly off one bare shoulder, bare legs, mussed bed hair, '
                                       'sitting on soft white wrinkled bed sheets, warm morning sunbeams streaming '
                                       'through bedroom window, cozy cute yawn',
                      'description': '清晨男友风大码长款纯白棉质衬衫，半滑落肩线与凌乱睡发，晨光微醺床单',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), oversized boyfriend white cotton button-down shirt, '
                                     'loosely unbuttoned at collar, slipping slightly off one bare shoulder, bare '
                                     'legs, mussed bed hair, sitting on soft white wrinkled bed sheets, warm morning '
                                     'sunbeams streaming through bedroom window, cozy cute yawn, (Rella:1.2), (chen '
                                     'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                     "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's "
                                     'almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                      'name': '男友风宽松白色长衬衫',
                      'no_hat': True,
                      'occasion': 'morning, bedroom, lazy, sleep',
                      'season': 'all'},
    '盛夏阳光露背吊带短裤': {   'category': 'seasonal',
                      'clothing_tags': 'bright lemon yellow backless halter camisole top, frayed light-wash denim '
                                       'shorts, stylish sunglasses pushed up on hair, shell necklace, bare shoulders, '
                                       'sun-drenched wooden seaside boardwalk, ocean waves in background',
                      'description': '海边盛夏柠檬黄露背挂脖吊带背心配毛边牛仔超短裤，头顶太阳镜与码头木栈道',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), bright lemon yellow backless halter camisole top, '
                                     'frayed light-wash denim shorts, stylish sunglasses pushed up on hair, shell '
                                     'necklace, bare shoulders, sun-drenched wooden seaside boardwalk, ocean waves in '
                                     'background, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                     '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                     "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                     '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                      'name': '盛夏阳光露背吊带短裤',
                      'no_hat': False,
                      'occasion': 'vacation, beach, sunny',
                      'season': 'summer'},
    '秋日落叶针织衫': {   'category': 'seasonal',
                   'clothing_tags': 'autumn fashion, warm oversized caramel chunky knit sweater, brown wool pleated '
                                    'skirt, coffee mug in hands, golden fallen ginkgo leaves, cozy autumn afternoon, '
                                    'soft warm golden lighting',
                   'description': '秋日慵懒焦糖色大号粗针毛衣搭配毛呢百褶裙（落叶大道、暖秋治愈）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), autumn fashion, warm oversized caramel chunky knit '
                                  'sweater, brown wool pleated skirt, coffee mug in hands, golden fallen ginkgo '
                                  'leaves, cozy autumn afternoon, soft warm golden lighting, (Rella:1.2), (chen '
                                  'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                  "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                  'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '秋日落叶针织衫',
                   'occasion': 'casual, walk, autumn',
                   'season': 'autumn'},
    '纯白吊带荷叶边睡裙': {   'category': 'sleepwear',
                     'clothing_tags': 'pure white ruffled nightgown, delicate frilled hem, breathable linen cotton, '
                                      'thin shoulder straps, innocent angelic style, morning sunlight filtering '
                                      'through sheer curtains, pure serene look',
                     'description': '纯白天使荷叶边透气棉麻睡裙（初恋少女感、纯洁无瑕，免帽）',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), pure white ruffled nightgown, delicate frilled hem, '
                                    'breathable linen cotton, thin shoulder straps, innocent angelic style, morning '
                                    'sunlight filtering through sheer curtains, pure serene look, (Rella:1.2), (chen '
                                    'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                    "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's "
                                    'almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '纯白吊带荷叶边睡裙',
                     'no_hat': True,
                     'occasion': 'bedtime, dreamy',
                     'season': 'spring/summer'},
    '美术生沾彩工装罩衫': {   'category': 'special',
                     'clothing_tags': 'beige linen painter smock apron with vibrant colorful oil paint stains and '
                                      'splatters, striped long sleeve tee underneath, holding wooden painter palette '
                                      'and fine paintbrushes, canvas easel with colorful artwork, cozy sunlit art '
                                      'studio',
                     'description': '美术生亚麻画画围裙罩衫，点缀油彩颜料渍，手持调色板与画笔，阳光画室',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), beige linen painter smock apron with vibrant '
                                    'colorful oil paint stains and splatters, striped long sleeve tee underneath, '
                                    'holding wooden painter palette and fine paintbrushes, canvas easel with colorful '
                                    'artwork, cozy sunlit art studio, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                    '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                    "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                    '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '美术生沾彩工装罩衫',
                     'no_hat': False,
                     'occasion': 'painting, art studio, creative',
                     'season': 'all'},
    '花房园艺围裙装': {   'category': 'special',
                   'clothing_tags': 'olive green durable canvas gardening apron with front pruner pockets, delicate '
                                    'floral print blouse, canvas work gloves, holding metal watering can, surrounded '
                                    'by lush potted plants and hanging flowers, warm sunlit botanical glasshouse',
                   'description': '温室花房园艺军绿帆布围裙配碎花衬衫与工作手套，手持金属水壶',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), olive green durable canvas gardening apron with front '
                                  'pruner pockets, delicate floral print blouse, canvas work gloves, holding metal '
                                  'watering can, surrounded by lush potted plants and hanging flowers, warm sunlit '
                                  'botanical glasshouse, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                  '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                  "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '花房园艺围裙装',
                   'no_hat': False,
                   'occasion': 'gardening, greenhouse, morning',
                   'season': 'all'},
    '英伦复古格纹大衣': {   'category': 'seasonal',
                    'clothing_tags': 'vintage british houndstooth wool coat, brown plaid woolen skirt, chocolate '
                                     'beret, leather messenger bag, dark brown Oxford brogues, historic university '
                                     'campus, autumn leaves',
                    'description': '深秋复古千鸟格毛呢双排扣大衣配复古贝雷帽与邮差包（英伦学院、知性浪漫）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), vintage british houndstooth wool coat, brown plaid '
                                   'woolen skirt, chocolate beret, leather messenger bag, dark brown Oxford brogues, '
                                   'historic university campus, autumn leaves, (Rella:1.2), (chen bin:1.3), virtual '
                                   'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '英伦复古格纹大衣',
                    'occasion': 'college, library, street',
                    'season': 'autumn'},
    '英伦学院菱格针织马甲': {   'category': 'seasonal',
                      'clothing_tags': 'crisp white oxford button-up shirt, navy and burgundy argyle knit sweater '
                                       'vest, pleated grey wool skirt, dark brown leather messenger bag, knee socks, '
                                       'oxford brogues, golden autumn tree-lined campus pathway',
                      'description': '英伦学院纯白牛津衬衫叠穿复古菱格针织马甲与百褶裙，皮革邮差包与金秋林荫道',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), crisp white oxford button-up shirt, navy and '
                                     'burgundy argyle knit sweater vest, pleated grey wool skirt, dark brown leather '
                                     'messenger bag, knee socks, oxford brogues, golden autumn tree-lined campus '
                                     'pathway, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                     '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                     "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                     '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                      'name': '英伦学院菱格针织马甲',
                      'no_hat': False,
                      'occasion': 'campus, study, autumn',
                      'season': 'autumn'},
    '藏青真丝排扣睡衣': {   'category': 'sleepwear',
                    'clothing_tags': 'luxurious navy blue silk pajama set, classic button-down long sleeve pajama '
                                     'shirt with white piping trim, matching silk pajama pants, collar open, cozy dim '
                                     'bedroom lighting, bed background',
                    'description': '轻奢高雅深藏青色真丝开襟长袖睡衣套装（白色包边、居家微醺夜，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), luxurious navy blue silk pajama set, classic '
                                   'button-down long sleeve pajama shirt with white piping trim, matching silk pajama '
                                   'pants, collar open, cozy dim bedroom lighting, bed background, (Rella:1.2), (chen '
                                   'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                   "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's "
                                   'almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '藏青真丝排扣睡衣',
                    'no_hat': True,
                    'occasion': 'bedtime, night, relaxing',
                    'season': 'all'},
    '街头滑板少年风卫衣': {   'category': 'sport',
                     'clothing_tags': 'oversized charcoal black graphic skate hoodie, baggy cargo track pants, durable '
                                      'skate knee pads, chunky skate sneakers, one foot resting on grip-taped '
                                      'skateboard, concrete skatepark with ramps and graffiti walls',
                     'description': '街头滑板宽版印花连帽卫衣配束脚工装裤与护膝，脚踩滑板，滑板公园',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), oversized charcoal black graphic skate hoodie, baggy '
                                    'cargo track pants, durable skate knee pads, chunky skate sneakers, one foot '
                                    'resting on grip-taped skateboard, concrete skatepark with ramps and graffiti '
                                    'walls, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                    'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                    "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                     'name': '街头滑板少年风卫衣',
                     'no_hat': False,
                     'occasion': 'skatepark, extreme sport, street',
                     'season': 'spring/autumn'},
    '赛车维修站连体服': {   'category': 'special',
                    'clothing_tags': 'professional pit crew racing jumpsuit, rolled-up sleeves, neon yellow reflective '
                                     'safety stripes, leather tool belt with spanner, dark grey mechanic overalls, '
                                     'fingerless driving gloves, high-top racing boots, bright garage workshop with '
                                     'tools on wall',
                    'description': '赛车维修站专业Pit房技工连体服，带有荧光反光条、多功能工具腰包与扳手',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), professional pit crew racing jumpsuit, rolled-up '
                                   'sleeves, neon yellow reflective safety stripes, leather tool belt with spanner, '
                                   'dark grey mechanic overalls, fingerless driving gloves, high-top racing boots, '
                                   'bright garage workshop with tools on wall, (Rella:1.2), (chen bin:1.3), virtual '
                                   'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                   "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                   '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '赛车维修站连体服',
                    'no_hat': False,
                    'occasion': 'racing, workshop, garage',
                    'season': 'all'},
    '软萌垂耳兔珊瑚绒连体睡衣': {   'category': 'sleepwear',
                        'clothing_tags': 'fluffy pastel lavender and cream coral fleece bunny onesie kigurumi pajamas, '
                                         'long floppy rabbit ears on hood, cute pom-pom tail, zippered front with '
                                         'heart pull, hugging giant soft plushie bolster, warm fairy lights bedroom, '
                                         'adorable sleepy expression',
                        'description': '粉紫拼色软萌珊瑚绒连体睡衣，长长垂耳兔耳朵连帽与圆圆尾巴，抱抱玩偶',
                        'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                       'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, '
                                       'middle long hair, (round face:1.2), fluffy pastel lavender and cream coral '
                                       'fleece bunny onesie kigurumi pajamas, long floppy rabbit ears on hood, cute '
                                       'pom-pom tail, zippered front with heart pull, hugging giant soft plushie '
                                       'bolster, warm fairy lights bedroom, adorable sleepy expression, (Rella:1.2), '
                                       '(chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, '
                                       'extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, '
                                       "Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                        'name': '软萌垂耳兔珊瑚绒连体睡衣',
                        'no_hat': True,
                        'occasion': 'cozy, bedroom, cute, sleep',
                        'season': 'winter'},
    '轻音贝斯手朋克百褶裙': {   'category': 'special',
                      'clothing_tags': 'cropped black faux-leather biker vest, sleeveless band graphic tee, red and '
                                       'black tartan plaid pleated mini skirt, studded leather choker and wristbands, '
                                       'fishnet stockings, holding sleek electric bass guitar, dramatic stage '
                                       'spotlight beams',
                      'description': '轻音酷感电贝斯乐手短款皮背心叠穿红黑格纹百褶短裙与网袜，舞台聚光灯',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), cropped black faux-leather biker vest, sleeveless '
                                     'band graphic tee, red and black tartan plaid pleated mini skirt, studded leather '
                                     'choker and wristbands, fishnet stockings, holding sleek electric bass guitar, '
                                     'dramatic stage spotlight beams, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                     '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                     "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                     '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                      'name': '轻音贝斯手朋克百褶裙',
                      'no_hat': False,
                      'occasion': 'rock, stage, live concert',
                      'season': 'all'},
    '运动活力': {   'category': 'sport',
                'clothing_tags': 'sportswear, sporty zip hoodie, white athletic tank top, running dolphin shorts, '
                                 'sneakers, ponytail, active lifestyle, city park running trail',
                'description': '运动休闲连帽卫衣与短裤（户外/慢跑/活力充沛）',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                               'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                               '(round face:1.2), sportswear, sporty zip hoodie, white athletic tank top, running '
                               'dolphin shorts, sneakers, ponytail, active lifestyle, city park running trail, '
                               '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, '
                               "extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's "
                               'almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                'name': '运动活力',
                'occasion': 'jogging, fitness, outdoor',
                'season': 'spring/autumn'},
    '雪人粗针麻花高领毛衣': {   'category': 'seasonal',
                      'clothing_tags': 'chunky oversized cream cable knit sweater, thick turtleneck cowl, warm knit '
                                       'beanie with fluffy pom-pom, matching knitted mittens, dark fleece-lined '
                                       'leggings, snow boots, gentle soft falling snowflakes, winter wonderland',
                      'description': '冬日温暖软糯米白粗针麻花大高领毛衣，毛球针织帽与手套，初雪飘落',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), chunky oversized cream cable knit sweater, thick '
                                     'turtleneck cowl, warm knit beanie with fluffy pom-pom, matching knitted mittens, '
                                     'dark fleece-lined leggings, snow boots, gentle soft falling snowflakes, winter '
                                     'wonderland, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                     '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                     "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                     '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                      'name': '雪人粗针麻花高领毛衣',
                      'no_hat': False,
                      'occasion': 'snow, winter, cozy',
                      'season': 'winter'},
    '露肩雪纺一字领': {   'category': 'daily',
                   'clothing_tags': 'off-shoulder ruffled chiffon blouse, bare shoulders, collarbone, light blue denim '
                                    'miniskirt, thin pendant necklace, summer iced drink, trendy cafe street, golden '
                                    'hour summer lighting',
                   'description': '夏日微风一字领露肩荷叶雪纺上衣搭配浅色牛仔短裙（清爽甜美、小资街头）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), off-shoulder ruffled chiffon blouse, bare shoulders, '
                                  'collarbone, light blue denim miniskirt, thin pendant necklace, summer iced drink, '
                                  'trendy cafe street, golden hour summer lighting, (Rella:1.2), (chen bin:1.3), '
                                  'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                  "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '露肩雪纺一字领',
                   'occasion': 'casual, cafe, shopping',
                   'season': 'summer'},
    '黑色蕾丝透气睡衣': {   'category': 'sleepwear',
                    'clothing_tags': 'black lace sleepwear, translucent silk camisole, delicate dark floral lace hem, '
                                     'thin straps, collarbone, alluring midnight mood, shadowy bedroom atmosphere, '
                                     'moonlight from window',
                    'description': '轻熟神秘黑蕾丝轻薄睡裙（透气微透、暗色魅惑，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), black lace sleepwear, translucent silk camisole, '
                                   'delicate dark floral lace hem, thin straps, collarbone, alluring midnight mood, '
                                   'shadowy bedroom atmosphere, moonlight from window, (Rella:1.2), (chen bin:1.3), '
                                   'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                   "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                   'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                    'name': '黑色蕾丝透气睡衣',
                    'no_hat': True,
                    'occasion': 'bedtime, sensual, night',
                    'season': 'summer/autumn'},
'默认常服': {   'category': 'daily',
                'clothing_tags': '(cream oversized cable knit cardigan:1.1), off-white camisole, ribbed '
                                 'top, brown pleated wool skirt, (chocolate brown beret:1.1), beige knee-high socks, '
                                 'retro loafer shoes, casual daily wear',
                'description': '经典奶油白粗针大毛衣内搭米白小吊带与罗纹上衣，配棕色百褶呢裙、贝雷帽与复古乐福鞋',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                               'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                               '(round face:1.2), (cream oversized cable knit cardigan:1.1), off-white '
                               'camisole, ribbed top, brown pleated wool skirt, (chocolate brown beret:1.1), beige '
                               'knee-high socks, retro loafer shoes, casual daily wear, (Rella:1.2), (chen bin:1.3), '
                               'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                               "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                               '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                'name': '默认常服',
                'occasion': 'casual, campus',
                'season': 'autumn/winter'},
'洛丽塔梦幻荷叶边睡裙': {'name': '洛丽塔梦幻荷叶边睡裙',
                'description': '软萌洛丽塔风格睡裙，多层轻纱蓬蓬下摆、精致蕾丝缎带与蝴蝶结，梦幻甜美公主感（免帽）',
                'category': 'sleepwear',
                'season': 'all',
                'occasion': 'bedtime, sweet, lolita',
                'no_hat': True,
                'clothing_tags': 'sweet lolita nightdress, tiered ruffled hemline, soft pink ribbon bows, '
                                 'delicate lace trim, puffy short sleeves, baby doll style, frilled hem, '
                                 'dreamlike sweet bedtime, bedroom pillow',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                               'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                               'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), sweet '
                               'lolita nightdress, tiered ruffled hemline, soft pink ribbon bows, delicate '
                               'lace trim, puffy short sleeves, baby doll style, frilled hem, dreamlike '
                               'sweet bedtime, bedroom pillow, (Rella:1.2), (chen bin:1.3), virtual '
                               'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                               "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                               'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '半透明月光轻纱吊带睡裙': {'name': '半透明月光轻纱吊带睡裙',
                 'description': '朦胧微透的月光白轻纱细吊带睡裙，双层薄纱下摆与镂空蕾丝罩纱，微露锁骨与轻熟朦胧美感（免帽）',
                 'category': 'sleepwear',
                 'season': 'summer/autumn',
                 'occasion': 'bedtime, sheer, alluring',
                 'no_hat': True,
                 'clothing_tags': 'semi-sheer nightdress, translucent white chiffon overlay, thin spaghetti '
                                  'straps, layered sheer tulle fabric, delicate floral lace bustier, soft '
                                  'ethereal glow, moonlight night, collarbone, bare shoulders, dreamy sheer '
                                  'sleepwear',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                                'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                                'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), '
                                'semi-sheer nightdress, translucent white chiffon overlay, thin spaghetti '
                                'straps, layered sheer tulle fabric, delicate floral lace bustier, soft '
                                'ethereal glow, moonlight night, collarbone, bare shoulders, dreamy sheer '
                                'sleepwear, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                '<lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '黑天鹅半透明蕾丝吊带睡裙': {'name': '黑天鹅半透明蕾丝吊带睡裙',
                  'description': '暗夜魅惑的黑天鹅微透蕾丝吊带睡裙，半透明薄纱侧开衩与精致黑玫瑰暗纹蕾丝，慵懒小性感（免帽）',
                  'category': 'sleepwear',
                  'season': 'all',
                  'occasion': 'bedtime, sexy, dark',
                  'no_hat': True,
                  'clothing_tags': 'semi-sheer black lace nightdress, translucent dark chiffon, delicate '
                                   'floral lace embroidery, thin slip straps, side slit sheer hem, sheer '
                                   'fabric, subtle silhouette, sultry bedroom, soft romantic night',
                  'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                                 'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                                 'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), '
                                 'semi-sheer black lace nightdress, translucent dark chiffon, delicate '
                                 'floral lace embroidery, thin slip straps, side slit sheer hem, sheer '
                                 'fabric, subtle silhouette, sultry bedroom, soft romantic night, '
                                 '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                 'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), '
                                 "Picasso style, Van Gogh's almond blossoms, "
                                 '<lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '哥特轻纱洛丽塔睡裙': {'name': '哥特轻纱洛丽塔睡裙',
               'description': '暗黑轻甜哥特风轻纱睡裙，黑紫拼色双层轻薄欧根纱、微透蕾丝泡泡袖与十字缎带蝴蝶结（免帽）',
               'category': 'sleepwear',
               'season': 'all',
               'occasion': 'bedtime, gothic, lolita',
               'no_hat': True,
               'clothing_tags': 'gothic lolita nightgown, sheer black organza, translucent purple accents, '
                                'puffy sheer sleeves, delicate ruffles, criss-cross ribbon, dark romance, '
                                'vintage gothic sleepwear',
               'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                              'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side swept '
                              'hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), gothic lolita '
                              'nightgown, sheer black organza, translucent purple accents, puffy sheer '
                              'sleeves, delicate ruffles, criss-cross ribbon, dark romance, vintage gothic '
                              'sleepwear, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                              '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                              "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                              '<lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '薄荷轻纱清凉吊带睡裙': {'name': '薄荷轻纱清凉吊带睡裙',
                'description': '清新薄荷绿双层透气轻纱吊带睡裙，淡雅碎褶飘逸轻纱与细锁骨吊带，初夏清凉可爱（免帽）',
                'category': 'sleepwear',
                'season': 'summer',
                'occasion': 'bedtime, summer, fresh',
                'no_hat': True,
                'clothing_tags': 'mint green sheer chiffon nightdress, floating translucent fabric, delicate '
                                 'spaghetti straps, pleated sheer ruffle hem, lightweight airy nightwear, '
                                 'pastel tone, fresh morning breeze',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                               'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                               'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), mint '
                               'green sheer chiffon nightdress, floating translucent fabric, delicate '
                               'spaghetti straps, pleated sheer ruffle hem, lightweight airy nightwear, '
                               'pastel tone, fresh morning breeze, (Rella:1.2), (chen bin:1.3), virtual '
                               'youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                               "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                               'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '甜心猫耳奶绒开衫': {'name': '甜心猫耳奶绒开衫',
              'description': '软糯米白羊羔绒针织开衫搭配嫩粉百褶短裙，可爱小猫刺绣与软萌毛球配饰，甜美治愈日常私服',
              'category': 'daily',
              'season': 'autumn/winter',
              'occasion': 'casual, sweet, daily',
              'clothing_tags': 'soft fluffy cream oversized knit cardigan, cute cat embroidery, pastel pink '
                               'pleated mini skirt, white collared inner shirt, knee-high socks, playful '
                               'youthful style, cozy sweet daily wear',
              'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored '
                             'hair, blue hair, light purple-light blue mixed eyes, (Side swept hair:1.6), '
                             'ahoge, bangs, middle long hair, (round face:1.2), soft fluffy cream oversized '
                             'knit cardigan, cute cat embroidery, pastel pink pleated mini skirt, white '
                             'collared inner shirt, knee-high socks, playful youthful style, cozy sweet '
                             'daily wear, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                             '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                             "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                             '<lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '法式小碎花吊带连衣裙': {'name': '法式小碎花吊带连衣裙',
                'description': '清新鹅黄法式复古碎花细吊带收腰连衣裙，内搭泡泡短袖薄纱衬衫，可爱甜美日常约会穿搭',
                'category': 'daily',
                'season': 'spring/summer',
                'occasion': 'casual, date, daily',
                'clothing_tags': 'yellow floral spaghetti strap sundress, sweetheart neckline, white puff '
                                 'sleeve inner blouse, ruffled hem, high waist A-line silhouette, cute '
                                 'dainty necklace, sunny street stroll, adorable summer fashion',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                               'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                               'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), yellow '
                               'floral spaghetti strap sundress, sweetheart neckline, white puff sleeve '
                               'inner blouse, ruffled hem, high waist A-line silhouette, cute dainty '
                               'necklace, sunny street stroll, adorable summer fashion, (Rella:1.2), (chen '
                               'bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                               "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's "
                               'almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '软萌娃娃领格纹背带裙': {'name': '软萌娃娃领格纹背带裙',
                'description': '日系减龄米咖色格子背带百褶裙内搭白色大翻娃娃领衬衫，胸口蝴蝶结领结，乖巧元气少女感',
                'category': 'daily',
                'season': 'all',
                'occasion': 'casual, school, campus',
                'clothing_tags': 'beige plaid overall pinafore dress, Peter Pan collar white blouse, tied '
                                 'ribbon bow tie, pleated skirt, cute layered styling, preppy casual daily, '
                                 'adorable girlish charm',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                               'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                               'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), beige '
                               'plaid overall pinafore dress, Peter Pan collar white blouse, tied ribbon bow '
                               'tie, pleated skirt, cute layered styling, preppy casual daily, adorable '
                               'girlish charm, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                               '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                               "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                               '<lora:DeniaV1-Nuclear1811-IL:0.5>'},
 '慵懒小熊露肩连帽卫衣': {'name': '慵懒小熊露肩连帽卫衣',
                'description': '奶咖色落肩露单肩宽松连帽卫衣搭配毛边牛仔短裤与小熊印花长筒袜，元气与慵懒兼备的可爱私服',
                'category': 'daily',
                'season': 'spring/autumn',
                'occasion': 'casual, home, street',
                'clothing_tags': 'oversized brown hoodie, one-shoulder off, cute bear graphic print, denim '
                                 'cutoff shorts, mismatched patterned knee socks, slouchy casual streetwear, '
                                 'youthful playful vibe',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, '
                               'multicolored hair, blue hair, light purple-light blue mixed eyes, (Side '
                               'swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2), oversized '
                               'brown hoodie, one-shoulder off, cute bear graphic print, denim cutoff '
                               'shorts, mismatched patterned knee socks, slouchy casual streetwear, youthful '
                               'playful vibe, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                               '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                               "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                               '<lora:DeniaV1-Nuclear1811-IL:0.5>'}}

def _read_catalog(doc):
    import copy
    removed = {"和风纯棉甚平睡衣"}
    current = OUTFITS_KEY in doc
    outfits = copy.deepcopy(dict(doc[OUTFITS_KEY]) if current else DEFAULT_OUTFITS)
    # Read earlier versions for custom entries only. Old presets cannot override
    # new templates, and removed presets cannot reappear as "custom" entries.
    for legacy_key in LEGACY_OUTFIT_KEYS:
        for name, value in doc.get(legacy_key, {}).items():
            if name not in outfits and name not in DEFAULT_OUTFITS and name not in removed:
                outfits[name] = copy.deepcopy(value)
            elif not current and name == "默认常服":
                outfits[name] = copy.deepcopy(value)
    outfits.pop("和风纯棉甚平睡衣", None)
    for outfit in outfits.values():
        if outfit.get("full_prompt"):
            outfit["full_prompt"] = outfit["full_prompt"].replace("teenager", "teenager")
    return outfits


class WardrobeManager:
    _instance: Optional['WardrobeManager'] = None
    _lock = threading.Lock()

    def __init__(self, yaml_path: str = YAML_CONFIG_PATH):
        self.yaml_path = yaml_path
        self._rw_lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._yaml_rt = None
        self._commented_map = None
        self._yaml_manager = None
        self._registered_reload_cb = False
        if _has_ruamel:
            self._yaml_rt = YAML()
            self._yaml_rt.preserve_quotes = True
            self._yaml_rt.indent(mapping=2, sequence=4, offset=2)
        self.load_config()
        self._setup_yaml_manager_listener()

    def _setup_yaml_manager_listener(self) -> None:
        """若存在 YAMLManager，注册重载回调以支持 WebUI 或外部文件修改后的热重载"""
        if not _has_yaml_manager or YAMLManager is None:
            return
        try:
            ym = YAMLManager.get_instance()
            if ym and not self._registered_reload_cb:
                def on_yaml_reload(plugin_name: Optional[str]):
                    if plugin_name == "wardrobe":
                        logger.info("[Wardrobe] 检测到 wardrobe/config.yaml 被外部修改，正在同步热重载...")
                        self.load_config()
                        from run.wardrobe import refresh_function_declarations
                        refresh_function_declarations("wardrobe")
                ym.register_reload_callback(on_yaml_reload)
                self._registered_reload_cb = True
                self._yaml_manager = ym
        except Exception as e:
            logger.debug(f"[Wardrobe] 注册 YAMLManager 监听失败 (可能尚未完全初始化): {e}")

    @classmethod
    def get_instance(cls, yaml_path: str = YAML_CONFIG_PATH) -> 'WardrobeManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = WardrobeManager(yaml_path)
            return cls._instance

    def load_config(self) -> None:
        with self._rw_lock:
            loaded = False
            # 1. 优先使用统一 YAMLManager 实例管理 (支持热重载与 ruamel.yaml 无损注释)
            if self.yaml_path == YAML_CONFIG_PATH and _has_yaml_manager and YAMLManager is not None:
                try:
                    ym = YAMLManager.get_instance()
                    if ym is not None and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                        doc = ym.wardrobe.config
                        if doc is not None and (OUTFITS_KEY in doc or any(k in doc for k in LEGACY_OUTFIT_KEYS)):
                            self._yaml_manager = ym
                            self._commented_map = doc
                            self._data = dict(doc)
                            if OUTFITS_KEY in self._data:
                                self._data[OUTFITS_KEY] = dict(self._data[OUTFITS_KEY])
                            loaded = True
                            #logger.info("[Wardrobe] 成功接入统一 YAMLManager 管理 wardrobe/config")
                except Exception as e:
                    logger.debug(f"[Wardrobe] 从 YAMLManager 载入失败或未初始化，尝试直接读取: {e}")

            # 2. 独立/回退：使用 ruamel.yaml 直接读取 YAML 配置，严格保留所有注释与排版格式
            if not loaded and self._yaml_rt and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        doc = self._yaml_rt.load(f)
                    if doc is not None and (OUTFITS_KEY in doc or any(k in doc for k in LEGACY_OUTFIT_KEYS)):
                        self._commented_map = doc
                        self._data = dict(doc)
                        if OUTFITS_KEY in self._data:
                            self._data[OUTFITS_KEY] = dict(self._data[OUTFITS_KEY])
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] ruamel.yaml 加载 YAML 失败: {e}")

            # 2. 回退使用 PyYAML 读取
            if not loaded and yaml and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict) and (OUTFITS_KEY in data or any(k in data for k in LEGACY_OUTFIT_KEYS)):
                        self._data = data
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] PyYAML 加载 YAML 失败: {e}")

            if loaded:
                self._data[OUTFITS_KEY] = _read_catalog(self._data)
                for field in RETIRED_DAILY_FIELDS:
                    self._data.pop(field, None)
            if loaded:
                for field in ("default_outfit", "current_outfit"):
                    if self._data.get(field) == "和风纯棉甚平睡衣":
                        self._data[field] = "可爱粉彩睡衣"
                        tag_field = {"current_outfit": "current_outfit_tags"}.get(field)
                        if tag_field:
                            self._data[tag_field] = self._data[OUTFITS_KEY]["可爱粉彩睡衣"]["clothing_tags"]
                self._data["character_anchor"] = self._data.get("character_anchor", DEFAULT_CHARACTER_ANCHOR)
                for legacy_key in LEGACY_OUTFIT_KEYS:
                    if self._commented_map is not None and legacy_key in self._commented_map:
                        self._commented_map.pop(legacy_key, None)
                    self._data.pop(legacy_key, None)

            # 3. 若均不存在或损坏，初始化默认结构并持久化至 YAML
            if not loaded:
                self._data = self._build_default_data()
                self._save_to_disk()

    def _sync_to_commented_map(self) -> None:
        """将 self._data 的更新同步至 self._commented_map，完整保留原有 YAML 注释"""
        if self._commented_map is None:
            return
        for legacy_key in (*LEGACY_OUTFIT_KEYS, *RETIRED_DAILY_FIELDS):
            if legacy_key in self._commented_map:
                self._commented_map.pop(legacy_key, None)
        for k, v in self._data.items():
            if k == OUTFITS_KEY and isinstance(v, dict):
                if OUTFITS_KEY not in self._commented_map:
                    self._commented_map[OUTFITS_KEY] = {}
                for ok, ov in v.items():
                    if ok not in self._commented_map[OUTFITS_KEY]:
                        self._commented_map[OUTFITS_KEY][ok] = dict(ov)
                    else:
                        if isinstance(ov, dict):
                            for fk, fv in ov.items():
                                self._commented_map[OUTFITS_KEY][ok][fk] = fv
            else:
                self._commented_map[k] = v

    def _build_default_data(self) -> Dict[str, Any]:
        default_outfit = "常服1"
        default_tags = DEFAULT_OUTFITS[default_outfit]["clothing_tags"]
        return {
            "enabled": True,
            "default_outfit": default_outfit,
            "current_outfit": default_outfit,
            "current_outfit_tags": default_tags,
            "character_anchor": DEFAULT_CHARACTER_ANCHOR,
            "art_anchor": DEFAULT_ART_ANCHOR,
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
            OUTFITS_KEY: dict(DEFAULT_OUTFITS)
        }

    def _save_to_disk(self) -> None:
        """将配置持久化至磁盘，优先通过统一 YAMLManager 保存，保留全部注释与排版"""
        self._sync_to_commented_map()

        # 1. 若当前受 YAMLManager 管理，优先使用 YAMLManager.save_yaml
        if self.yaml_path == YAML_CONFIG_PATH and self._yaml_manager is not None:
            try:
                if hasattr(self._yaml_manager, "data") and "wardrobe" in self._yaml_manager.data:
                    if self._commented_map is not None:
                        self._yaml_manager.data["wardrobe"]["config"] = self._commented_map
                    self._yaml_manager.save_yaml("config", "wardrobe")
                    return
            except Exception as e:
                logger.warning(f"[Wardrobe] 通过 YAMLManager 保存配置失败，回退至独立写盘: {e}")

        # 2. 回退写入 YAML 权威配置文件（使用 ruamel.yaml 保留全部注释与键序，.tmp 原子替换防崩溃）
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.yaml_path)), exist_ok=True)
            tmp_yaml = f"{self.yaml_path}.tmp"
            if self._yaml_rt:
                target_obj = self._commented_map if self._commented_map is not None else self._data
                with open(tmp_yaml, "w", encoding="utf-8") as f:
                    self._yaml_rt.dump(target_obj, f)
                os.replace(tmp_yaml, self.yaml_path)
            elif yaml:
                with open(tmp_yaml, "w", encoding="utf-8") as f:
                    yaml.dump(self._data, f, allow_unicode=True, sort_keys=False)
                os.replace(tmp_yaml, self.yaml_path)
        except Exception as e:
            logger.error(f"[Wardrobe] 保存 YAML 配置失败: {e}")

    def save_config(self) -> None:
        with self._rw_lock:
            self._save_to_disk()

    def is_enabled(self) -> bool:
        with self._rw_lock:
            return bool(self._data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        with self._rw_lock:
            self._data["enabled"] = bool(enabled)
            self._save_to_disk()

    def get_character_anchor(self) -> str:
        with self._rw_lock:
            return self._data.get("character_anchor", DEFAULT_CHARACTER_ANCHOR)

    def get_art_anchor(self) -> str:
        with self._rw_lock:
            return self._data.get("art_anchor", DEFAULT_ART_ANCHOR)

    def get_negative_prompt(self) -> str:
        with self._rw_lock:
            return self._data.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)

    def get_outfits(self) -> Dict[str, Any]:
        with self._rw_lock:
            return dict(self._data.get(OUTFITS_KEY, {}))

    def get_outfit(self, name: str) -> Optional[Dict[str, Any]]:
        with self._rw_lock:
            return self._data.get(OUTFITS_KEY, {}).get(name)

    def get_current_outfit(self) -> Dict[str, Any]:
        with self._rw_lock:
            if not self._data.get("enabled", True):
                name = self._data.get("default_outfit", "常服1")
                outfit = self._data.get(OUTFITS_KEY, {}).get(name, {})
                tags = outfit.get("clothing_tags", "")
                return {
                    "name": name,
                    "clothing_tags": tags,
                    "category": outfit.get("category", "daily"),
                    "no_hat": outfit.get("no_hat", False),
                    "description": outfit.get("description", "")
                }
            name = self._data.get("current_outfit", "常服1")
            outfit = self._data.get(OUTFITS_KEY, {}).get(name, {})
            tags = self._data.get("current_outfit_tags") or outfit.get("clothing_tags", "")
            no_hat = self._data.get("current_outfit_no_hat")
            if no_hat is None:
                no_hat = outfit.get("no_hat", False)
            return {
                "name": name,
                "clothing_tags": tags,
                "category": outfit.get("category", "daily"),
                "no_hat": no_hat,
                "description": outfit.get("description", "")
            }


    def set_current_outfit(self, outfit_name: str, custom_tags: Optional[str] = None, no_hat: Optional[bool] = None) -> bool:
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return False
            outfit = self._data.get(OUTFITS_KEY, {}).get(outfit_name)
            if not outfit and not custom_tags:
                return False
            self._data["current_outfit"] = outfit_name
            if custom_tags is not None:
                self._data["current_outfit_tags"] = custom_tags
            elif outfit:
                self._data["current_outfit_tags"] = outfit.get("clothing_tags", "")
            if no_hat is not None:
                self._data["current_outfit_no_hat"] = no_hat
            elif outfit:
                self._data["current_outfit_no_hat"] = outfit.get("no_hat", False)
            else:
                self._data.pop("current_outfit_no_hat", None)
            self._save_to_disk()
            logger.info(f"[Wardrobe] 当前穿着已切换至: {outfit_name}")
            return True


    def match_outfit(self, query: str):
        """Resolve the exact catalog key already selected by the LLM/tool caller."""
        if not query:
            return None
        return next((key for key in self.get_outfits() if key.casefold() == query.strip().casefold()), None)


    def get_qzone_candidates(self, post_text="", theme_desc="", season_name=""):
        """Expose every usable outfit; semantic selection belongs to the LLM."""
        return {key: obj for key, obj in self.get_outfits().items() if obj.get("clothing_tags")}

    def resolve_qzone_outfit(self, key, post_text="", theme_desc=""):
        """Keep the model's exact key; never replace it by category or usage count."""
        obj = self.get_outfits()[key]
        return {"name": key, "clothing_tags": obj.get("clothing_tags", ""),
                "no_hat": obj.get("no_hat", False), "matched_by": "llm_key"}

    def record_qzone_outfit_usage(self, key):
        """Called only after a post containing its image has been published."""
        with self._rw_lock:
            if key not in self._data.get(OUTFITS_KEY, {}):
                return
            counts = self._data.setdefault("qzone_outfit_usage", {})
            counts[key] = counts.get(key, 0) + 1
            self._save_to_disk()

    def pick_base_outfit_for_theme(self, theme_desc="", post_text="", is_first_today=False, season_name=""):
        """Compatibility accessor; never infer clothing from theme or post text."""
        return self.get_current_outfit()

    def update_from_qzone_tags(self, outfit_name: str, clothing_tags: str, no_hat: Optional[bool] = None) -> None:
        """记录该条动态的最终穿搭；后续动态独立交给 LLM 选择。"""
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return
            if not isinstance(clothing_tags, str) or not clothing_tags.strip():
                return
            self._data["current_outfit"] = outfit_name
            self._data["current_outfit_tags"] = clothing_tags
            if no_hat is not None:
                self._data["current_outfit_no_hat"] = no_hat
            logger.info(f"[Wardrobe] Qzone 动态更新当前着装: [{outfit_name}] -> {clothing_tags[:60]}... (no_hat={no_hat})")
            self._save_to_disk()


    def on_post_change_check(self, task_name, post_content="", theme_desc="", selection=None):
        """Apply an explicit LLM selection only; post text cannot trigger a change."""
        if not self.is_enabled() or not selection:
            return None
        self.update_from_qzone_tags(selection["name"], selection["clothing_tags"],
                                    no_hat=selection.get("no_hat", False))
        return selection["name"]

    def get_visual_prompt_section(self) -> str:
        """
        动态生成注入 System Prompt 的视觉与绘图触发规则段落。
        结构严格对应 yucca.txt 原版格式：
        [基础形象设定] + [画风与模型设定] + [当前服装设定] + [绘图原则] + [换装协同规则]
        """
        char_anchor = self.get_character_anchor()
        art_anchor = self.get_art_anchor()

        if not self.is_enabled():
            default_name = self._data.get("default_outfit", "常服1")
            outfit = self._data.get(OUTFITS_KEY, {}).get(default_name, {})
            clothing_tags = outfit.get("clothing_tags", "")
            clothing_header = f"3. 默认服装设定（衣橱未启用，默认穿着: {default_name}）："
        else:
            cur = self.get_current_outfit()
            cur_name = cur.get("name", "常服1")
            clothing_tags = cur.get("clothing_tags", "")
            clothing_header = f"3. 当前服装设定（衣橱当前穿着: {cur_name}）："

        section = f"""# ️ 视觉与绘图触发规则
当你觉得在聊天中合适时，你会时不时发送一张自拍或当前状态的照片给对方。
照片的 Prompt 组合方式：【基础特征】+【画风模型】+【当前的情绪表情】+【当前的服装/场景】+【自拍视角/日常视角】。

Prompt 公式：
[基础形象设定] + [当前情绪/表情] + [当前动作/场景] + [视角与画风]

1. 基础形象设定：
{char_anchor}

2. 画风与模型设定：
{art_anchor}

{clothing_header}
{clothing_tags}

在所有情况下，场景、动作、服饰和表情都不是固定的。在保持角色基本形象锚点的前提下，尽可能通过多样化的形象展示让用户保持新鲜感。

⚠️ 绘图原则与换装规则：
- 构图要有变化（不要全是正面大头照，可以尝试不同视角）。
- 穿搭以当前完整套装为准；睡衣不混入外出毛衣、围巾或靴子；裙装不叠加无关长裤。
- 保留手绘风格 lineart, (hand-drawn:1.3), (sketch:1.2)。
- 调用绘图必须严格遵守函数调用规则，不要直接把提示词丢到正文。
- 【重点·换装联动】：当用户明确要求换装、换衣服、穿上特定服饰，或者在请求自拍/合照时指定了新服装，你在调用绘图工具（call_text2img）生成图片的同时，必须同时调用 call_change_outfit 工具更新衣橱穿着！这样你之后的日常状态和后续照片就会一直保持这套新穿搭。"""
        return section


def get_wardrobe_manager() -> WardrobeManager:
    return WardrobeManager.get_instance()


async def call_change_outfit(bot=None, event=None, config=None, outfit_name: str = "", custom_description: str = "") -> dict:
    """
    Function Calling 工具：切换或更换当前穿着的服装/衣橱搭配。
    当用户要求换装、换衣服、穿上特定服饰，或希望你生成特定着装自拍时调用。
    """
    wm = get_wardrobe_manager()
    if not wm.is_enabled():
        return {
            "status": "disabled",
            "message": "衣橱功能当前处于关闭状态，保持使用默认设置的穿着。",
            "current_outfit": wm.get_current_outfit()
        }

    if not outfit_name and not custom_description:
        cur = wm.get_current_outfit()
        return {
            "status": "info",
            "message": f"当前穿着是：【{cur.get('name')}】。描述：{cur.get('clothing_tags')}",
            "current_outfit": cur
        }

    # 智能模糊匹配已有服饰
    matched_name = wm.match_outfit(outfit_name) if outfit_name else None

    if matched_name:
        outfit_info = wm.get_outfit(matched_name) or {}
        tags = outfit_info.get("clothing_tags", "")
        if custom_description:
            tags = f"{tags}, {custom_description.strip()}"
        wm.set_current_outfit(matched_name, tags)
        logger.info(f"[Wardrobe Tool] 已切换着装至已知款式: {matched_name}")
        return {
            "status": "success",
            "message": f"已成功换上【{matched_name}】！",
            "outfit_name": matched_name,
            "clothing_tags": tags
        }
    else:
        # 用户指定了自定义全新服饰
        target_name = outfit_name.strip() if outfit_name else "定制新装"
        custom_tags = custom_description.strip() if custom_description else target_name
        wm.set_current_outfit(target_name, custom_tags)
        logger.info(f"[Wardrobe Tool] 已切换着装至自定义新装: {target_name} -> {custom_tags}")
        return {
            "status": "success",
            "message": f"已换上特别搭配的【{target_name}】！",
            "outfit_name": target_name,
            "clothing_tags": custom_tags
        }


def build_change_outfit_declaration(yaml_path: str = YAML_CONFIG_PATH, custom_outfits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    根据 config.yaml 动态构建 call_change_outfit 的 Function Calling 声明。
    完整罗列全部服饰名称（按分类整理），使 bot 具备完全的自主挑选能力。
    """
    outfits = custom_outfits
    if outfits is None and yaml_path == YAML_CONFIG_PATH and _has_yaml_manager and YAMLManager is not None:
        try:
            ym = YAMLManager.get_instance()
            if ym and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                doc = ym.wardrobe.config
                if doc and (OUTFITS_KEY in doc or any(k in doc for k in LEGACY_OUTFIT_KEYS)):
                    outfits = _read_catalog(doc)
        except Exception as e:
            logger.debug(f"[Wardrobe] 从 YAMLManager 读取服饰列表失败: {e}")

    if outfits is None:
        try:
            if _has_ruamel and os.path.exists(yaml_path):
                ryaml = YAML()
                ryaml.preserve_quotes = True
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = ryaml.load(f)
                    if doc and (OUTFITS_KEY in doc or any(k in doc for k in LEGACY_OUTFIT_KEYS)):
                        outfits = _read_catalog(doc)
            elif yaml and os.path.exists(yaml_path):
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
                    if doc and (OUTFITS_KEY in doc or any(k in doc for k in LEGACY_OUTFIT_KEYS)):
                        outfits = _read_catalog(doc)
        except Exception as e:
            logger.warning(f"[Wardrobe] 从 {yaml_path} 读取服饰列表失败: {e}")

    if not outfits:
        outfits = DEFAULT_OUTFITS

    count = len(outfits)

    cat_order = [
        ("daily", "日常私服"),
        ("seasonal", "四季时令"),
        ("sleepwear", "居家睡衣"),
        ("special", "特色装扮"),
        ("sport", "运动活力"),
        ("festival", "节日庆典"),
    ]
    cat_map: Dict[str, List[str]] = {}
    for name, data in outfits.items():
        c = data.get("category", "other") if isinstance(data, dict) else "other"
        cat_map.setdefault(c, []).append(f"{name}" if isinstance(data, dict) else name)

    catalog_lines = []
    for c_key, c_label in cat_order:
        names = cat_map.pop(c_key, [])
        if names:
            catalog_lines.append("、".join(names))
    if cat_map:
        other_names = []
        for v in cat_map.values():
            other_names.extend(v)
        if other_names:
            catalog_lines.append(f"【其他款式 ({len(other_names)}套)】: " + "、".join(other_names))

    all_outfits_formatted = "\n".join(catalog_lines)

    tool_description = (
        f"切换或更换当前穿着的服装/衣橱搭配。当用户在聊天中要求换装、换衣服、穿上特定服饰，"
    )

    outfit_param_desc = (
        f"要更换的目标服装名称。请优先从以下完整收录的全部 {count} 套衣橱服饰中自主挑选最契合当前语境、活动或用户需求的款式名称：\n"
        f"{all_outfits_formatted}\n"
        f"（也支持输入任意自定义或模糊服装风格描述）。"
    )

    return {
        "name": "call_change_outfit",
        "description": tool_description,
        "parameters": {
            "type": "object",
            "properties": {
                "outfit_name": {
                    "type": "string",
                    "description": outfit_param_desc
                },
                "custom_description": {
                    "type": "string",
                    "description": "特定服饰细节、配色或额外的自定义 SD Prompt 关键词（可选，留空则使用对应服装的标准衣橱配置）"
                }
            },
            "required": ["outfit_name"]
        }
    }


def get_function_declarations(yaml_path: str = YAML_CONFIG_PATH) -> list:
    """获取动态生成的 Function Declarations 声明列表"""
    return [build_change_outfit_declaration(yaml_path=yaml_path)]
