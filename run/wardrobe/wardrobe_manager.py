# -*- coding: utf-8 -*-
"""
Wardrobe Manager (衣橱管理系统)
管理 Bot 服饰配置、当前着装、每日着装演变及 SD 提示词解耦组装。
支持 WebUI (run/wardrobe/config.yaml) 与 Function Calling 协同换装。
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional

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
                    'clothing_tags': 'winter clothing, oversized puffy white down jacket, chunky thick knit muffler '
                                     'scarf wrapped around neck, fluffy earmuffs, woolen mittens, snowy city street '
                                     'background, gentle snowflakes falling, breath vapor',
                    'description': '冬日加厚米白立领羽绒服搭配厚毛线围巾与毛绒耳罩（初雪街头、呵气成霜）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), winter clothing, oversized puffy white down jacket, '
                                   'chunky thick knit muffler scarf wrapped around neck, fluffy earmuffs, woolen '
                                   'mittens, snowy city street background, gentle snowflakes falling, breath vapor, '
                                   '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                   'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                   "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                    'name': '冬日加厚白羽绒服',
                    'occasion': 'outdoor, snow, winter',
                    'season': 'winter'},
    '分层蛋糕裙': {   'category': 'daily',
                 'clothing_tags': 'layered dress, tiered ruffled skirt, pastel frill sundress, delicate ribbon bow, '
                                  'sweet feminine style, cute Mary Jane shoes, gentle afternoon sunlight',
                 'description': '轻甜层叠花边蛋糕裙（多层褶皱下摆、甜美少女风）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), layered dress, tiered ruffled skirt, pastel frill sundress, '
                                'delicate ribbon bow, sweet feminine style, cute Mary Jane shoes, gentle afternoon '
                                'sunlight, (Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                 'name': '分层蛋糕裙',
                 'occasion': 'date, casual',
                 'season': 'spring/summer'},
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
    '和风纯棉甚平睡衣': {   'category': 'sleepwear',
                    'clothing_tags': 'traditional Japanese jinbei lounge pajamas, light grey-blue pinstripe cotton '
                                     'fabric, criss-cross tie kimono collar, loose comfortable shorts, bare feet, '
                                     'tatami room background, gentle night breeze',
                    'description': '日系和风浅灰蓝细条纹纯棉甚平家居服（系带交领开襟、透气凉爽夏夜，免帽）',
                    'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                   'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                   'long hair, (round face:1.2), traditional Japanese jinbei lounge pajamas, light '
                                   'grey-blue pinstripe cotton fabric, criss-cross tie kimono collar, loose '
                                   'comfortable shorts, bare feet, tatami room background, gentle night breeze, '
                                   '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                   'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso '
                                   "style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                    'name': '和风纯棉甚平睡衣',
                    'no_hat': True,
                    'occasion': 'summer night, relaxing, home',
                    'season': 'summer'},
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
    '夏日海滩泳装': {   'category': 'seasonal',
                  'clothing_tags': 'summer swimwear, cute pastel blue and pink ruffled bikini, translucent chiffon '
                                   'beach cover-up wrap, bare legs, wet skin, collarbone, sunny ocean beach, tropical '
                                   'resort, turquoise sea waves',
                  'description': '夏日海边粉蓝荷叶边分体比基尼与薄纱防晒罩衫（海滩度假、浪花轻抚，严格免帽）',
                  'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                 'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                 '(round face:1.2), summer swimwear, cute pastel blue and pink ruffled bikini, '
                                 'translucent chiffon beach cover-up wrap, bare legs, wet skin, collarbone, sunny '
                                 'ocean beach, tropical resort, turquoise sea waves, (Rella:1.2), (chen bin:1.3), '
                                 'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                 "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                 '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                  'name': '夏日海滩泳装',
                  'no_hat': True,
                  'occasion': 'beach, seaside, pool, vacation',
                  'season': 'summer'},
    '夏祭捞金鱼印花甚平': {   'category': 'seasonal',
                     'clothing_tags': 'indigo blue breathable cotton jinbei two-piece set, cute goldfish and wave '
                                      'crest patterns, tied front robe top and matching shorts, wooden geta clogs, '
                                      'holding transparent plastic goldfish bag with water, lively festival lantern '
                                      'food stalls',
                     'description': '夏日祭典藏青纯棉印花甚平短装，提着金鱼水袋与木屐，夜市灯笼',
                     'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                    'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                    'long hair, (round face:1.2), indigo blue breathable cotton jinbei two-piece set, '
                                    'cute goldfish and wave crest patterns, tied front robe top and matching shorts, '
                                    'wooden geta clogs, holding transparent plastic goldfish bag with water, lively '
                                    'festival lantern food stalls, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                    '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                    "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                    '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                     'name': '夏祭捞金鱼印花甚平',
                     'no_hat': False,
                     'occasion': 'festival, summer night',
                     'season': 'summer'},
    '夏祭金鱼浴衣': {   'category': 'festival',
                  'clothing_tags': 'summer festival yukata, navy blue yukata with orange goldfish and water ripples '
                                   'pattern, red floral obi sash, wooden geta sandals, holding round uchiwa fan, '
                                   'evening festival lanterns, night sky, fireworks reflection',
                  'description': '日式夏日祭典金鱼纹样深蓝浴衣（手持团扇、庙会夜市烟火，免帽）',
                  'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                 'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                 '(round face:1.2), summer festival yukata, navy blue yukata with orange goldfish and '
                                 'water ripples pattern, red floral obi sash, wooden geta sandals, holding round '
                                 'uchiwa fan, evening festival lanterns, night sky, fireworks reflection, (Rella:1.2), '
                                 '(chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely '
                                 "detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond "
                                 'blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>',
                  'name': '夏祭金鱼浴衣',
                  'no_hat': True,
                  'occasion': 'festival, evening, fireworks',
                  'season': 'summer'},
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
    '日系水手服': {   'category': 'daily',
                 'clothing_tags': 'sailor uniform, pleated navy skirt, white sailor collar blouse, red scarf necktie, '
                                  'high knee socks, loafers, cherry blossoms, classroom window',
                 'description': '经典藏青百褶裙日系水手服（青春校园、微风拂动）',
                 'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                                'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                                '(round face:1.2), sailor uniform, pleated navy skirt, white sailor collar blouse, red '
                                'scarf necktie, high knee socks, loafers, cherry blossoms, classroom window, '
                                '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), masterpiece, '
                                'extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van '
                                "Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                 'name': '日系水手服',
                 'occasion': 'school, campus',
                 'season': 'spring/summer'},
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
    '春日碎花连衣裙': {   'category': 'seasonal',
                   'clothing_tags': 'spring fashion, floral print sundress, pastel chiffon maxi dress, light beige '
                                    'knitted cardigan, holding cherry blossom branch, outdoors, soft natural spring '
                                    'sunlight, scenic park background',
                   'description': '春日清新碎花雪纺吊带长裙搭薄针织开衫（浪漫樱花、春游野餐风）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), spring fashion, floral print sundress, pastel chiffon '
                                  'maxi dress, light beige knitted cardigan, holding cherry blossom branch, outdoors, '
                                  'soft natural spring sunlight, scenic park background, (Rella:1.2), (chen bin:1.3), '
                                  'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, '
                                  "lineart, (hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '春日碎花连衣裙',
                   'occasion': 'picnic, park, date',
                   'season': 'spring'},
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
    '机能风骑行皮衣': {   'category': 'daily',
                   'clothing_tags': 'cool biker girl, cropped black motorcycle leather jacket, neon blue accents, '
                                    'black tactical cargo pants with utility straps, fingerless leather gloves, combat '
                                    'boots, futuristic cyberpunk garage background, neon signs, confident smirk',
                   'description': '机能街头风立领机车皮夹克与战术多袋工装裤（修车骑行进阶版、酷飒帅气）',
                   'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                  'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                  'long hair, (round face:1.2), cool biker girl, cropped black motorcycle leather '
                                  'jacket, neon blue accents, black tactical cargo pants with utility straps, '
                                  'fingerless leather gloves, combat boots, futuristic cyberpunk garage background, '
                                  'neon signs, confident smirk, (Rella:1.2), (chen bin:1.3), virtual youtuber, '
                                  '(starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                                  "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                                  '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                   'name': '机能风骑行皮衣',
                   'occasion': 'riding, biker, street, workshop',
                   'season': 'all'},
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
    '街头复古机车皮衣长裤': {   'category': 'seasonal',
                      'clothing_tags': 'vintage distressed brown leather motorcycle jacket with asymmetric zipper, '
                                       'black fitted tee, tactical multi-pocket cargo pants, lace-up combat boots, '
                                       'metal chain accessory, golden hour urban street corner',
                      'description': '复古做旧棕色机车夹克搭配黑色工装束脚长裤与马丁靴，黄昏街头角',
                      'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, '
                                     'light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle '
                                     'long hair, (round face:1.2), vintage distressed brown leather motorcycle jacket '
                                     'with asymmetric zipper, black fitted tee, tactical multi-pocket cargo pants, '
                                     'lace-up combat boots, metal chain accessory, golden hour urban street corner, '
                                     '(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), '
                                     'masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), '
                                     "Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>",
                      'name': '街头复古机车皮衣长裤',
                      'no_hat': False,
                      'occasion': 'street, motor, sunset',
                      'season': 'autumn'},
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
                'clothing_tags': '(cream oversized cable knit cardigan:1.1)或者oversize coat, off-white camisole, ribbed '
                                 'top, brown pleated wool skirt, (chocolate brown beret:1.1), beige knee-high socks, '
                                 'retro loafer shoes, casual daily wear',
                'description': '原版毛衣外套与百褶裙日常服（从yucca.txt迁移保存）',
                'full_prompt': '1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, light '
                               'purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, '
                               '(round face:1.2), (cream oversized cable knit cardigan:1.1)或者oversize coat, off-white '
                               'camisole, ribbed top, brown pleated wool skirt, (chocolate brown beret:1.1), beige '
                               'knee-high socks, retro loafer shoes, casual daily wear, (Rella:1.2), (chen bin:1.3), '
                               'virtual youtuber, (starshadowmagician:1.2), masterpiece, extremely detailed, lineart, '
                               "(hand-drawn:1.3), (sketch:1.2), Picasso style, Van Gogh's almond blossoms, "
                               '<lora:DeniaV1-Nuclear1811-IL:0.5>',
                'name': '默认常服',
                'occasion': 'casual, campus',
                'season': 'autumn/winter'}}

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
            if _has_yaml_manager and YAMLManager is not None:
                try:
                    ym = YAMLManager.get_instance()
                    if ym is not None and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                        doc = ym.wardrobe.config
                        if doc is not None and "outfits" in doc:
                            self._yaml_manager = ym
                            self._commented_map = doc
                            self._data = dict(doc)
                            if "outfits" in self._data:
                                self._data["outfits"] = dict(self._data["outfits"])
                            loaded = True
                            #logger.info("[Wardrobe] 成功接入统一 YAMLManager 管理 wardrobe/config")
                except Exception as e:
                    logger.debug(f"[Wardrobe] 从 YAMLManager 载入失败或未初始化，尝试直接读取: {e}")

            # 2. 独立/回退：使用 ruamel.yaml 直接读取 YAML 配置，严格保留所有注释与排版格式
            if not loaded and self._yaml_rt and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        doc = self._yaml_rt.load(f)
                    if doc is not None and "outfits" in doc:
                        self._commented_map = doc
                        self._data = dict(doc)
                        if "outfits" in self._data:
                            self._data["outfits"] = dict(self._data["outfits"])
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] ruamel.yaml 加载 YAML 失败: {e}")

            # 2. 回退使用 PyYAML 读取
            if not loaded and yaml and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict) and "outfits" in data:
                        self._data = data
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] PyYAML 加载 YAML 失败: {e}")

            # 3. 若均不存在或损坏，初始化默认结构并持久化至 YAML
            if not loaded:
                self._data = self._build_default_data()
                self._save_to_disk()

    def _sync_to_commented_map(self) -> None:
        """将 self._data 的更新同步至 self._commented_map，完整保留原有 YAML 注释"""
        if self._commented_map is None:
            return
        for k, v in self._data.items():
            if k == "outfits" and isinstance(v, dict):
                if "outfits" not in self._commented_map:
                    self._commented_map["outfits"] = {}
                for ok, ov in v.items():
                    if ok not in self._commented_map["outfits"]:
                        self._commented_map["outfits"][ok] = dict(ov)
                    else:
                        if isinstance(ov, dict):
                            for fk, fv in ov.items():
                                self._commented_map["outfits"][ok][fk] = fv
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
            "today_default_outfit": default_outfit,
            "today_default_tags": default_tags,
            "last_daily_date": "",
            "character_anchor": DEFAULT_CHARACTER_ANCHOR,
            "art_anchor": DEFAULT_ART_ANCHOR,
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
            "outfits": dict(DEFAULT_OUTFITS)
        }

    def _save_to_disk(self) -> None:
        """将配置持久化至磁盘，优先通过统一 YAMLManager 保存，保留全部注释与排版"""
        self._sync_to_commented_map()

        # 1. 若当前受 YAMLManager 管理，优先使用 YAMLManager.save_yaml
        if self._yaml_manager is not None:
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
            return dict(self._data.get("outfits", {}))

    def get_outfit(self, name: str) -> Optional[Dict[str, Any]]:
        with self._rw_lock:
            return self._data.get("outfits", {}).get(name)

    def get_current_outfit(self) -> Dict[str, Any]:
        with self._rw_lock:
            if not self._data.get("enabled", True):
                name = self._data.get("default_outfit", "常服1")
                outfit = self._data.get("outfits", {}).get(name, {})
                tags = outfit.get("clothing_tags", "")
                return {
                    "name": name,
                    "clothing_tags": tags,
                    "category": outfit.get("category", "daily"),
                    "no_hat": outfit.get("no_hat", False),
                    "description": outfit.get("description", "")
                }
            name = self._data.get("current_outfit", "常服1")
            outfit = self._data.get("outfits", {}).get(name, {})
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

    def get_today_default_outfit(self) -> Dict[str, Any]:
        with self._rw_lock:
            name = self._data.get("today_default_outfit") or self._data.get("default_outfit", "常服1")
            outfit = self._data.get("outfits", {}).get(name, {})
            tags = self._data.get("today_default_tags") or outfit.get("clothing_tags", "")
            no_hat = self._data.get("today_default_no_hat")
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
            outfit = self._data.get("outfits", {}).get(outfit_name)
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

    def set_today_default_outfit(self, outfit_name: str, custom_tags: Optional[str] = None) -> bool:
        with self._rw_lock:
            outfit = self._data.get("outfits", {}).get(outfit_name)
            if not outfit and not custom_tags:
                return False
            self._data["today_default_outfit"] = outfit_name
            if custom_tags is not None:
                self._data["today_default_tags"] = custom_tags
            elif outfit:
                self._data["today_default_tags"] = outfit.get("clothing_tags", "")
            self._save_to_disk()
            logger.info(f"[Wardrobe] 今日默认着装已设定为: {outfit_name}")
            return True

    def match_outfit(self, query: str):
        """智能模糊匹配服装名称与风格"""
        if not query:
            return None
        q = query.strip().lower()
        outfits = self._data.get("outfits", {})

        # 1. 精确匹配
        if query in outfits:
            return query
        for k in outfits:
            if k.lower() == q:
                return k

        # 2. 睡衣系列智能选择 (全部带免帽属性)
        if any(w in q for w in ["睡衣", "睡裙", "睡袍", "浴袍", "甚平", "寝衣", "晚安", "睡觉", "睡了", "好梦", "被窝", "困了", "sleep", "bed", "pajama", "night", "nightgown", "bathrobe"]):
            if any(w in q for w in ["甚平", "和风", "日式", "交领"]):
                return "和风纯棉甚平睡衣"
            if any(w in q for w in ["浴袍", "猫咪", "猫耳", "珊瑚绒", "连帽睡袍"]):
                return "毛绒猫咪连帽睡袍"
            if any(w in q for w in ["藏青", "深蓝", "排扣", "开襟", "长袖"]):
                return "藏青真丝排扣睡衣"
            if any(w in q for w in ["粉", "可爱", "纯棉", "软萌"]):
                return "可爱粉彩睡衣"
            if any(w in q for w in ["丝绸", "缎面", "吊带睡裙", "性感", "香槟"]):
                return "性感丝绸吊带睡裙"
            if any(w in q for w in ["黑", "蕾丝", "透气", "暗色", "轻熟"]):
                return "黑色蕾丝透气睡衣"
            if any(w in q for w in ["暖", "冬", "法兰绒", "珊瑚绒", "小熊", "加厚"]):
                return "法兰绒暖冬睡衣"
            if any(w in q for w in ["条纹", "蓝", "天蓝", "衬衫领"]):
                return "天蓝色条纹睡衣"
            if any(w in q for w in ["白", "荷叶边", "天使", "清纯", "棉麻"]):
                return "纯白吊带荷叶边睡裙"
            if any(w in q for w in ["男友", "男友风", "白衬衫", "长衬衫", "boyfriend"]):
                return "男友风宽松白色长衬衫"
            if any(w in q for w in ["垂耳兔", "兔子", "连体睡衣", "珊瑚绒连体", "kigurumi", "onesie"]):
                return "软萌垂耳兔珊瑚绒连体睡衣"
            return "可爱粉彩睡衣"

        # 3. 四季、特定生活场合与主题风格匹配
        keyword_map = [
            # 春季
            (["碎花", "花裙", "春游", "野餐", "樱花", "spring"], "春日碎花连衣裙"),
            (["早春", "双排扣", "风衣", "卡其色风衣", "trench"], "早春双排扣风衣"),
            # 夏季
            (["泳装", "泳衣", "比基尼", "海滩", "海边", "游泳", "bikini", "swim"], "夏日海滩泳装"),
            (["浴衣", "夏祭", "祭典", "花火", "烟火", "金鱼", "yukata"], "夏祭金鱼浴衣"),
            (["网球", "网球服", "网球裙", "tennis"], "清凉无袖网球裙"),
            (["一字领", "露肩", "雪纺", "露肩装", "短裙"], "露肩雪纺一字领"),
            (["小吊带", "细吊带", "吊带", "吊带短裤", "吊带衫", "camisole"], "清凉小吊带"),
            # 秋季
            (["落叶", "粗针毛衣", "焦糖", "暖秋", "针织衫", "autumn"], "秋日落叶针织衫"),
            (["千鸟格", "格纹大衣", "英伦大衣", "复古大衣", "格子大衣"], "英伦复古格纹大衣"),
            (["万圣节", "小恶魔", "恶魔", "南瓜", "蝙蝠", "halloween"], "万圣节小恶魔装"),
            # 冬季
            (["羽绒服", "白羽绒", "厚羽绒", "初雪", "雪地", "down jacket"], "冬日加厚白羽绒服"),
            (["圣诞", "圣诞装", "红斗篷", "麋鹿", "铃铛", "christmas"], "圣诞红斗篷礼裙"),
            (["牛角扣", "大衣", "连帽大衣", "duffle"], "牛角扣毛呢大衣"),
            # 角色与场合
            (["皮衣", "机能", "机车", "赛车", "骑行皮衣", "帅气", "biker"], "机能风骑行皮衣"),
            (["女仆", "女仆装", "maid"], "可爱猫耳女仆装"),
            (["宅家", "连帽卫衣", "打游戏", "电竞", "oversize卫衣", "躺平"], "宅家慵懒连帽卫衣"),
            (["围裙", "烘焙", "料理", "做饭", "做曲奇", "apron"], "烘焙围裙料理服"),
            (["冲锋衣", "露营", "户外", "登山", "爬山", "camping"], "户外露营冲锋衣"),
            (["游乐园", "兔耳", "背带裤", "摩天轮", "爆米花"], "游乐园兔耳背带裤"),
            (["芭蕾", "黑天鹅", "芭蕾裙", "ballet"], "优雅黑天鹅芭蕾裙"),
            (["振袖", "和服", "成人礼", "参拜", "kimono", "furisode"], "正统和风振袖礼服"),
            (["晚礼服", "宴会", "长裙", "礼服", "gown"], "优雅晚礼服"),
            (["哥特", "gothic"], "哥特洛丽塔"),
            (["洛丽塔", "lolita", "茶会", "洋装"], "甜美洛丽塔"),
            (["蛋糕裙", "分层裙", "layered"], "分层蛋糕裙"),
            (["运动", "晨跑", "慢跑", "跑步", "健身", "卫衣短裤", "运动服", "sport"], "运动活力"),
            (["水手服", "校服", "学生装", "jk", "sailor"], "日系水手服"),
            (["汉服", "汉元素", "古风", "仙女裙"], "清雅汉元素"),
            (["修车", "工装", "电瓶车", "扳手", "常服", "常服1"], "常服1"),
            (["原版", "毛衣外套", "贝雷帽", "百褶裙", "默认常服", "默认"], "默认常服"),
            (["浴袍", "猫咪睡袍", "毛绒猫咪", "连帽睡袍"], "毛绒猫咪连帽睡袍"),
            (["甚平", "甚平睡衣"], "和风纯棉甚平睡衣"),
            # 机械与工坊特色
            (["赛车", "pit", "维修站", "修车工", "技工", "连体服"], "赛车维修站连体服"),
            (["涂鸦", "喷漆", "机修背带裤", "背带工装"], "涂鸦机修工装背带裤"),
            (["极客", "焊接", "创客", "护目镜", "焊枪", "电烙铁"], "电子极客焊接工装"),
            # 四季与户外特色
            (["雨衣", "透明雨衣", "雨天", "雨伞", "下雨", "raincoat"], "春雨透明轻便雨衣"),
            (["田园", "细格纹", "草帽", "野花", "cottagecore"], "春日田园野餐格纹裙"),
            (["无袖水手", "短裙领巾", "盛夏水手"], "清爽无袖水手百褶裙"),
            (["露背", "柠檬黄", "挂脖", "海边吊带"], "盛夏阳光露背吊带短裤"),
            (["捞金鱼", "金鱼甚平", "短甚平", "夏夜甚平"], "夏祭捞金鱼印花甚平"),
            (["菱格", "针织马甲", "学院风马甲", "牛津衬衫", "邮差包"], "英伦学院菱格针织马甲"),
            (["灯芯绒", "焦糖色", "灯芯绒背带裤", "银杏"], "深秋复古灯芯绒背带裤"),
            (["做旧皮衣", "复古机车", "机车夹克", "工装束脚裤"], "街头复古机车皮衣长裤"),
            (["雪人", "粗针麻花", "高领毛衣", "毛球帽", "初雪毛衣"], "雪人粗针麻花高领毛衣"),
            (["滑雪", "滑雪服", "雪板", "雪山", "ski", "snowboard"], "极地专业加厚滑雪服"),
            # 兴趣爱好与传统节庆
            (["美术", "画画", "画室", "颜料", "油彩", "调色板", "画笔", "罩衫"], "美术生沾彩工装罩衫"),
            (["轻音", "贝斯", "朋克", "电贝斯", "摇滚", "bass", "rock"], "轻音贝斯手朋克百褶裙"),
            (["花房", "园艺", "花店", "温室", "花架", "浇水", "gardening"], "花房园艺围裙装"),
            (["图书馆", "知性", "金丝眼镜", "文艺长裙", "看书", "温书", "阅览室"], "图书馆文艺知性长裙"),
            (["滑板", "滑板少年", "滑板公园", "skateboard", "skater"], "街头滑板少年风卫衣"),
            (["马面裙", "云肩", "中秋", "织金", "织金马面裙"], "中秋织金马面裙云肩"),
            (["元宵", "唐装", "短唐装", "花灯", "兔子灯", "绒毛斗篷"], "元宵绒毛斗篷短唐装"),
        ]
        for kw_list, target in keyword_map:
            if any(w in q for w in kw_list) and target in outfits:
                return target

        # 4. 子字符串匹配
        for k in outfits:
            if k in query or query in k:
                return k

        return None


    def pick_base_outfit_for_theme(self, theme_desc: str = "", post_text: str = "", is_first_today: bool = False, season_name: str = "") -> dict:
        """
        Qzone 动态主题抽选后，从衣橱挑选最合适的基准服饰：
        1. 优先度1（场景/关键词精准匹配）：海滩、晚安、雨天、图书馆、运动、女仆、洛丽塔等；
        2. 优先度2（若非特异场景，且为今日首发）：根据当前时令/季节在日常私服池中轮换挑选；
        3. 优先度3（若是白天后续动态）：沿用今日已锁定的当前穿着；
        4. 兜底：返回 default_outfit ("常服1")。
        """
        combined = f"{theme_desc} {post_text}".strip()
        outfits = self._data.get("outfits", {})

        # 1. 优先度 1：语义/关键词特异性匹配
        matched_name = self.match_outfit(combined)
        if matched_name and matched_name in outfits:
            matched_obj = outfits[matched_name]
            logger.info(f"[Wardrobe] Qzone 主题/文案精确命中衣橱款式: [{matched_name}]")
            return {
                "name": matched_name,
                "clothing_tags": matched_obj.get("clothing_tags", ""),
                "no_hat": matched_obj.get("no_hat", False),
                "matched_by": "keyword"
            }

        # 2. 优先度 2：无特定关键词，若是今日首发动态 -> 按季节轮换日常穿搭
        if is_first_today:
            season_pools = {
                "spring": ["常服1", "春日碎花连衣裙", "早春双排扣风衣", "春日田园野餐格纹裙", "学院风百褶短裙", "运动活力", "日系水手服", "美术生文艺罩衫", "街头滑板连帽卫衣"],
                "summer": ["清凉小吊带", "盛夏阳光露背吊带短裤", "清凉无袖网球裙", "露肩雪纺一字领", "清爽无袖水手百褶裙", "运动活力", "夏祭捞金鱼印花甚平"],
                "autumn": ["常服1", "秋日落叶针织衫", "英伦复古格纹大衣", "英伦学院菱格针织马甲", "深秋复古灯芯绒背带裤", "街头机能风工装", "温暖粗棒针毛衣"],
                "winter": ["冬日加厚白羽绒服", "牛角扣毛呢大衣", "温暖粗棒针毛衣", "极地防寒专业滑雪服", "高领羊绒毛衣", "常服1"]
            }

            current_season = "spring"
            s_lower = season_name.lower()
            if any(k in s_lower for k in ["夏", "summer"]):
                current_season = "summer"
            elif any(k in s_lower for k in ["秋", "autumn", "fall"]):
                current_season = "autumn"
            elif any(k in s_lower for k in ["冬", "winter"]):
                current_season = "winter"
            else:
                import datetime
                m = datetime.datetime.now().month
                if m in [3, 4, 5]: current_season = "spring"
                elif m in [6, 7, 8]: current_season = "summer"
                elif m in [9, 10, 11]: current_season = "autumn"
                else: current_season = "winter"

            candidates = season_pools.get(current_season, ["常服1"])
            valid_candidates = [c for c in candidates if c in outfits]
            if not valid_candidates:
                valid_candidates = ["常服1"]

            import datetime
            date_seed = datetime.datetime.now().strftime("%Y%m%d")
            picked_name = valid_candidates[abs(hash(date_seed)) % len(valid_candidates)]
            picked_obj = outfits.get(picked_name, {})
            logger.info(f"[Wardrobe] Qzone 今日首条动态根据时令 [{current_season}] 轮换挑选衣橱款式: [{picked_name}]")
            return {
                "name": picked_name,
                "clothing_tags": picked_obj.get("clothing_tags", ""),
                "no_hat": picked_obj.get("no_hat", False),
                "matched_by": "season_rotation"
            }

        # 3. 优先度 3：若是白天日常动态（非首发，无强特异场景），平滑继承今日当前穿着
        current = self.get_current_outfit()
        return {
            "name": current.get("name", "常服1"),
            "clothing_tags": current.get("clothing_tags", ""),
            "no_hat": current.get("no_hat", False),
            "matched_by": "current_carryover"
        }


    def update_from_qzone_tags(self, outfit_name: str, clothing_tags: str, is_daily_default: bool = False, no_hat: Optional[bool] = None) -> None:
        """
        当 Qzone 根据每日动态主题抽选或微调提示词后，回写衣橱：
        - 更新当前穿着 tags 与免帽状态
        - 若是今日首条动态 (is_daily_default=True)，同步更新当天默认着装 tags 与免帽状态
        """
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return
            if not clothing_tags or not clothing_tags.strip():
                return
            clean_tags = clothing_tags.strip()
            self._data["current_outfit"] = outfit_name
            self._data["current_outfit_tags"] = clean_tags
            if no_hat is not None:
                self._data["current_outfit_no_hat"] = no_hat
            if is_daily_default:
                self._data["today_default_outfit"] = outfit_name
                self._data["today_default_tags"] = clean_tags
                if no_hat is not None:
                    self._data["today_default_no_hat"] = no_hat
                logger.info(f"[Wardrobe] 今日首发动态已锁定今日默认着装: [{outfit_name}] -> {clean_tags[:60]}... (no_hat={no_hat})")
            else:
                logger.info(f"[Wardrobe] Qzone 动态更新当前着装: [{outfit_name}] -> {clean_tags[:60]}... (no_hat={no_hat})")
            self._save_to_disk()

    def on_daily_first_post(self, date_str: str, post_content: str = "", theme_desc: str = "") -> bool:
        """
        Qzone 每日首条动态触发检查。
        若属于新的一天，重置今日默认着装与当前穿着，并返回 True。
        """
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return False
            if self._data.get("last_daily_date") == date_str:
                return False
            self._data["last_daily_date"] = date_str
            default_outfit = self._data.get("default_outfit", "常服1")
            outfit_info = self._data.get("outfits", {}).get(default_outfit, {})
            base_tags = outfit_info.get("clothing_tags", "")
            self._data["today_default_outfit"] = default_outfit
            self._data["today_default_tags"] = base_tags
            self._data["current_outfit"] = default_outfit
            self._data["current_outfit_tags"] = base_tags
            self._save_to_disk()
            logger.info(f"[Wardrobe] 新的一天 ({date_str})，重置今日着装与当前穿着为: {default_outfit}")
            return True

    def on_post_change_check(self, task_name: str, post_content: str = "", theme_desc: str = "") -> Optional[str]:
        """
        根据动态任务名称与内容判断是否需要自动更换着装：
        - 晚安/睡觉动态 -> 更换为睡衣系列中的一款
        - 早安/起床动态 -> 恢复为今日默认着装
        - 运动/跑步/健身 -> 切换为运动活力
        - 修车/街头/工装 -> 切换为常服1
        """
        if not self.is_enabled():
            return None

        combined = f"{task_name} {post_content} {theme_desc}".lower()

        # 1. 晚安/睡眠场景
        sleep_kw = ["晚安", "睡觉", "睡了", "好梦", "失眠", "洗漱", "躺下", "困了", "床头", "被窝", "sleep", "bed", "pajama", "night"]
        if task_name == "晚安" or any(k in combined for k in sleep_kw):
            target_sleepwear = self.match_outfit(combined) or "可爱粉彩睡衣"
            current = self.get_current_outfit()
            if current.get("name") != target_sleepwear:
                self.set_current_outfit(target_sleepwear)
                return target_sleepwear
            return None

        # 2. 早安/晨起场景 -> 恢复今日默认着装
        morning_kw = ["早安", "起床", "醒了", "晨间", "醒来", "清晨", "morning"]
        if task_name == "早安" or any(k in combined for k in morning_kw):
            today_def = self.get_today_default_outfit()
            self.set_current_outfit(today_def["name"], today_def["clothing_tags"])
            return today_def["name"]

        # 3. 运动/跑步/健身场景
        sport_kw = ["跑步", "慢跑", "运动", "健身", "夜跑", "晨跑", "gym", "workout", "sport"]
        if any(k in combined for k in sport_kw):
            if "运动活力" in self._data.get("outfits", {}):
                current = self.get_current_outfit()
                if current.get("name") != "运动活力":
                    self.set_current_outfit("运动活力")
                    return "运动活力"

        # 4. 修车/街头/骑行场景
        street_kw = ["修车", "扳手", "电瓶车", "机车", "街头", "工装", "scooter", "wrench", "street"]
        if any(k in combined for k in street_kw):
            if "常服1" in self._data.get("outfits", {}):
                current = self.get_current_outfit()
                if current.get("name") != "常服1":
                    self.set_current_outfit("常服1")
                    return "常服1"

        return None

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
            outfit = self._data.get("outfits", {}).get(default_name, {})
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
    优先通过 YAMLManager 实时获取服饰列表，精简紧凑描述，避免硬编码巨幅长文本。
    """
    outfits = custom_outfits
    if outfits is None and _has_yaml_manager and YAMLManager is not None:
        try:
            ym = YAMLManager.get_instance()
            if ym and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                doc = ym.wardrobe.config
                if doc and "outfits" in doc:
                    outfits = dict(doc["outfits"])
        except Exception as e:
            logger.debug(f"[Wardrobe] 从 YAMLManager 读取服饰列表失败: {e}")

    if outfits is None:
        try:
            if _has_ruamel and os.path.exists(yaml_path):
                ryaml = YAML()
                ryaml.preserve_quotes = True
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = ryaml.load(f)
                    if doc and "outfits" in doc:
                        outfits = dict(doc["outfits"])
            elif yaml and os.path.exists(yaml_path):
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
                    if doc and "outfits" in doc:
                        outfits = doc["outfits"]
        except Exception as e:
            logger.warning(f"[Wardrobe] 从 {yaml_path} 读取服饰列表失败: {e}")

    if not outfits:
        outfits = DEFAULT_OUTFITS

    count = len(outfits)
    sample_candidates = ["常服1", "默认常服", "分层蛋糕裙", "甜美洛丽塔", "清凉小吊带", "优雅晚礼服", "哥特洛丽塔", "可爱粉彩睡衣"]
    picked_samples = [name for name in sample_candidates if name in outfits]
    if len(picked_samples) < 5:
        for name in outfits.keys():
            if name not in picked_samples:
                picked_samples.append(name)
            if len(picked_samples) >= 6:
                break

    samples_str = "、".join(picked_samples[:6])

    optimized_outfit_desc = (
        f"要更换的目标服装名称或风格描述。系统启动时已从衣橱配置(config.yaml)动态载入{count}套服饰"
        f"（涵盖日常私服、四季特色、华丽礼服、汉元素及居家睡衣等，例如：{samples_str}等）。"
        f"支持输入衣橱款式名，或输入任意自定义/模糊服装描述。"
    )

    return {
        "name": "call_change_outfit",
        "description": "切换或更换当前穿着的服装/衣橱搭配。当用户在聊天中要求换装、换衣服、穿上特定服饰，或希望你生成特定着装自拍/照片时必须协同调用此工具更新穿着状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "outfit_name": {
                    "type": "string",
                    "description": optimized_outfit_desc
                },
                "custom_description": {
                    "type": "string",
                    "description": "特定服饰细节、颜色搭配或自定义 SD Prompt 关键词（可选，留空则使用对应服装的标准衣橱配置）"
                }
            },
            "required": ["outfit_name"]
        }
    }


def get_function_declarations(yaml_path: str = YAML_CONFIG_PATH) -> list:
    """获取动态生成的 Function Declarations 声明列表"""
    return [build_change_outfit_declaration(yaml_path=yaml_path)]
