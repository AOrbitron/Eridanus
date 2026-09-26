# -*- coding: utf-8 -*-
"""
QQ空间动态主题库 - 海量百种场景与动态变体衍生库
包含丰富多样的早安、晚安、日常生活切面，并提供动态变体衍生引导词，充分发挥 LLM 创造力。
"""

MORNING_THEME_POOL = [
    {
        "id": "m_001",
        "category": "户外自然",
        "theme": "海边栈道看日出：微咸微凉的海风吹乱头发，海平面尽头第一缕橙红色的金光把浪花和沙滩全染成了温柔的蜜桃粉",
        "elements": [
            "海边",
            "日出",
            "栈道",
            "海浪晨光",
            "海风"
        ],
        "sd_hint": "early morning, coastal wooden boardwalk, watching sunrise over ocean horizon, golden orange sky, gentle sea breeze, casual jacket, serene happy smile"
    },
    {
        "id": "m_002",
        "category": "户外自然",
        "theme": "山顶看壮丽云海：裹紧厚厚的外套站在山顶观景台，脚下是翻滚如白浪般的无边云海，天边泛起淡金色的光芒",
        "elements": [
            "山顶",
            "云海",
            "晨曦",
            "厚外套",
            "观景台"
        ],
        "sd_hint": "morning, mountaintop viewpoint, sea of clouds below, glowing dawn light, wearing cozy thick windbreaker, looking into distance, awe expression"
    },
    {
        "id": "m_003",
        "category": "户外自然",
        "theme": "冷杉林晨雾漫步：漫步在清晨的冷杉针叶林间，空气里满是冷冽的松针与潮湿泥土香，丁达尔光束穿透薄雾洒在脚边",
        "elements": [
            "冷杉林",
            "晨雾",
            "松针香",
            "丁达尔光",
            "漫步"
        ],
        "sd_hint": "morning, pine forest, morning mist, crepuscular rays, pine needles on ground, casual walking outfit, fresh peaceful atmosphere"
    },
    {
        "id": "m_004",
        "category": "户外自然",
        "theme": "晨光中的金黄麦田：清晨的风吹过连绵的麦浪发出沙沙声，露水还挂在麦芒上，整片原野在晨光下泛着柔软的金黄",
        "elements": [
            "麦田",
            "麦浪",
            "晨露",
            "原野",
            "金光"
        ],
        "sd_hint": "morning, golden wheat field, vast countryside, morning dew sparkling, gentle breeze, straw hat, sundress, warm sunshine"
    },
    {
        "id": "m_005",
        "category": "户外自然",
        "theme": "古镇石桥与水波晨雾：江南水乡石板路上还泛着潮气，摇橹船划开晨雾泛起一圈圈涟漪，街巷里飘出刚蒸好的青团香",
        "elements": [
            "古镇",
            "石拱桥",
            "晨雾水乡",
            "摇橹船",
            "石板路"
        ],
        "sd_hint": "early morning, traditional water town, ancient stone bridge, mist over canal, quiet riverside street, delicate pastel lighting"
    },
    {
        "id": "m_006",
        "category": "户外自然",
        "theme": "清晨海岛轮渡甲板：吹着略带凉意的初晨海风，栏杆旁盘旋着两三只白色海鸥，看着对岸小岛的轮廓逐渐在晨曦中清晰",
        "elements": [
            "轮渡",
            "海鸥",
            "海岛",
            "甲板",
            "晨光"
        ],
        "sd_hint": "morning, ferry deck, sea seagulls flying around, ocean breeze blowing hair, morning sunlight, holding railing, bright eyes"
    },
    {
        "id": "m_007",
        "category": "户外自然",
        "theme": "乡间小径与带露野花：路边不知名的淡蓝色野花上缀着晶莹的露珠，脚底踩着松软的草叶，远处农舍升起第一缕淡白炊烟",
        "elements": [
            "乡间小路",
            "野花",
            "露珠",
            "炊烟",
            "青草香"
        ],
        "sd_hint": "morning, countryside path, blooming small wildflowers with dew drops, grassy field, distant farmhouse, peaceful country morning"
    },
    {
        "id": "m_008",
        "category": "户外自然",
        "theme": "江畔慢跑与晨光微风：沿着波光粼粼的江边慢跑，两岸的晨雾刚刚散去，江面映着浅金色的波纹，整个人神清气爽",
        "elements": [
            "江畔",
            "慢跑",
            "波光",
            "运动耳机",
            "江风"
        ],
        "sd_hint": "morning, riverside jogging trail, sparkling river reflection, wearing sportswear and earbuds, healthy light blush, energetic smile"
    },
    {
        "id": "m_009",
        "category": "户外自然",
        "theme": "满地金黄银杏道：一整夜的风吹落了一地金灿灿的扇形银杏叶，踩上去沙沙作响，忍不住捡起一片最好看的夹进书里",
        "elements": [
            "银杏",
            "落叶",
            "金黄",
            "晨光",
            "捡树叶"
        ],
        "sd_hint": "morning, street covered with golden ginkgo leaves, holding a yellow ginkgo leaf, warm autumn knit sweater, golden sunlight filter"
    },
    {
        "id": "m_010",
        "category": "户外自然",
        "theme": "春晨落樱小道：微风掠过枝头，粉白色的樱花瓣像细雪一样飘在发梢和肩头，清晨的整条小街静悄悄的只有鸟鸣",
        "elements": [
            "樱花",
            "花瓣雨",
            "春晨",
            "长椅",
            "安静小街"
        ],
        "sd_hint": "morning, cherry blossom street, falling sakura petals, pink and white flowers, soft spring light, lovely cute dress, poetic atmosphere"
    },
    {
        "id": "m_011",
        "category": "户外自然",
        "theme": "静谧湖畔如镜倒影：清晨的湖面没有一丝波纹，像一面澄澈的大镜子倒映着蓝天白云和远处的青山，空气清新得想装一罐带走",
        "elements": [
            "静水湖泊",
            "倒影",
            "倒映蓝天",
            "草甸",
            "清新空气"
        ],
        "sd_hint": "morning, crystal clear mountain lake, mirror-like lake reflection of sky and mountains, wooden pier, tranquil and breathtaking"
    },
    {
        "id": "m_012",
        "category": "户外自然",
        "theme": "露营帐篷拉链初开：拉开帐篷拉链的一瞬间，冷冽清新的山间空气涌了进来，金色的晨光正穿透树梢落在睡袋边缘",
        "elements": [
            "露营",
            "帐篷",
            "清晨山风",
            "睡袋",
            "山间晨曦"
        ],
        "sd_hint": "early morning, peeking out of camping tent, mountain sunrise through trees, sleepy cute face, warm sleeping bag, camping mug"
    },
    {
        "id": "m_013",
        "category": "城市漫步",
        "theme": "街角面包房第一炉可颂：踩着刚开门的时间溜进街角老面包店，刚出炉的黄油牛角包香气浓郁得让人走不动路，外壳金黄酥脆",
        "elements": [
            "面包房",
            "刚出炉",
            "牛角包",
            "黄油香",
            "纸袋"
        ],
        "sd_hint": "morning, quaint bakery shop, holding warm brown paper bag with freshly baked croissants, butter aroma, casual street outfit, blissful smile"
    },
    {
        "id": "m_014",
        "category": "城市漫步",
        "theme": "早市热气腾腾的小笼包：早市摊位巨大的竹蒸笼揭开盖子，滚滚白汽伴随着葱油和小笼包的香气扑面而来，最是人间烟火气",
        "elements": [
            "早市",
            "竹蒸笼",
            "白汽",
            "小笼包",
            "烟火气"
        ],
        "sd_hint": "morning, lively morning street market, steam billowing from bamboo dim sum steamers, food stall, warm bustling atmosphere, cute foodie face"
    },
    {
        "id": "m_015",
        "category": "城市漫步",
        "theme": "晨光花市挑郁金香：清晨批发花市水灵灵的，给房间挑了一束还带着水珠的奶油黄郁金香，抱着走在路上心情像踩着跳跳糖",
        "elements": [
            "花市",
            "郁金香",
            "水珠",
            "牛皮纸包装",
            "明快心情"
        ],
        "sd_hint": "morning, flower market, holding a bouquet of fresh yellow tulips wrapped in kraft paper, soft pastel tones, bright sunny day"
    },
    {
        "id": "m_016",
        "category": "城市漫步",
        "theme": "空荡荡的清晨有轨电车：坐上清晨第一班绿皮有轨电车，车厢里空荡荡的，阳光透过车窗在地板上拉出长长的金色斜影",
        "elements": [
            "有轨电车",
            "第一班车",
            "空荡车厢",
            "车窗斜光",
            "看风景"
        ],
        "sd_hint": "morning, inside vintage tram car, sitting by window, morning sunlight streaming through windows, empty seats, earphones, peaceful contemplation"
    },
    {
        "id": "m_017",
        "category": "城市漫步",
        "theme": "沿街咖啡馆靠窗高脚凳：点一杯热燕麦拿铁坐在临街的高脚凳上，看着街上匆匆走过的路人，享受难得的慢吞吞偷闲时光",
        "elements": [
            "街边咖啡馆",
            "高脚凳",
            "燕麦拿铁",
            "观察街景",
            "慢节奏"
        ],
        "sd_hint": "morning, modern cozy cafe, sitting on barstool by large glass window, ceramic coffee cup with latte art, watching street, warm aesthetic"
    },
    {
        "id": "m_018",
        "category": "城市漫步",
        "theme": "骑单车迎着晨风飞驰：蹬着小单车穿过林荫道，微凉的风灌进袖口，车筐里放着刚买的橙汁和两支法棍，轻快得想哼歌",
        "elements": [
            "骑单车",
            "车筐",
            "林荫道",
            "法棍",
            "晨风灌袖口"
        ],
        "sd_hint": "morning, riding bicycle along tree-lined avenue, front basket with bread and flowers, wind in hair, dynamic cheerful pose, vibrant light"
    },
    {
        "id": "m_019",
        "category": "城市漫步",
        "theme": "早开的书店角落：钻进刚刚开门还没什么人的旧书店，被陈旧纸张与墨水的好闻味道包围，站在窗边翻看一本有趣的画册",
        "elements": [
            "书店",
            "翻书",
            "纸墨香",
            "靠窗角落",
            "安静"
        ],
        "sd_hint": "morning, quiet classic bookstore, wooden bookshelves, reading an open book near window, dust motes dancing in sunlight, gentle cute smile"
    },
    {
        "id": "m_020",
        "category": "城市漫步",
        "theme": "天台眺望苏醒的城市：站在顶楼天台俯瞰，整座城市的大楼玻璃幕墙正一座接着一座被晨曦照亮，像沉睡的巨人慢慢醒来",
        "elements": [
            "天台",
            "俯瞰城市",
            "玻璃反光",
            "晨曦",
            "风吹刘海"
        ],
        "sd_hint": "morning, rooftop railing, panoramic city skyline waking up, golden light reflecting on skyscrapers, wind blowing bangs, oversized hoodie"
    },
    {
        "id": "m_021",
        "category": "美食手作",
        "theme": "香脆厚吐司与溏心蛋：平底锅上的黄油融化出诱人的坚果香，两颗溏心蛋煎得边缘微脆，趁热在烤得金黄的厚吐司上切开流心",
        "elements": [
            "平底锅",
            "煎蛋",
            "溏心蛋",
            "厚吐司",
            "黄油香"
        ],
        "sd_hint": "morning, home kitchen, wearing cute apron, cooking sunny-side up eggs on frying pan, golden toast, steam, appetizing breakfast"
    },
    {
        "id": "m_022",
        "category": "美食手作",
        "theme": "打泡器与浓郁抹茶拿铁：用电动打泡器把燕麦奶打出细腻绵密如云朵般的奶泡，缓缓倒进浓绿的抹茶里，拉出歪歪扭扭的小爱心",
        "elements": [
            "抹茶拿铁",
            "奶泡",
            "打泡器",
            "马克杯",
            "心形拉花"
        ],
        "sd_hint": "morning, kitchen counter, making matcha latte, pouring dense milk foam into mug, cute messy heart latte art, soft lighting, cozy sweater"
    },
    {
        "id": "m_023",
        "category": "美食手作",
        "theme": "五彩斑斓的燕麦酸奶碗：把浓稠的希腊酸奶倒进玻璃碗，铺上满满的蓝莓、红草莓切片和香脆的坚果碎，看着就让人食指大动",
        "elements": [
            "酸奶碗",
            "草莓",
            "蓝莓",
            "坚果麦片",
            "玻璃碗"
        ],
        "sd_hint": "morning, wooden dining table, colorful yogurt bowl topped with berries and granola, silver spoon, sunny windowsill background, appetizing"
    },
    {
        "id": "m_024",
        "category": "美食手作",
        "theme": "松软舒芙蕾松饼：慢火烘烤出两面金黄的小松饼，高高叠在一起，顶上放一块融化的黄油，淋上晶莹剔透、香气扑鼻的枫糖浆",
        "elements": [
            "松饼",
            "舒芙蕾",
            "枫糖浆",
            "黄油块",
            "甜点早餐"
        ],
        "sd_hint": "morning, plate of fluffy pancake stack with melting butter cube and maple syrup drizzle, fork in hand, happy sparkling eyes, kitchen"
    },
    {
        "id": "m_025",
        "category": "美食手作",
        "theme": "肉桂烤苹果热燕麦粥：小锅里咕嘟咕嘟煮着香浓的牛奶燕麦，撒上一小勺肉桂粉和清甜的焦糖苹果粒，整个厨房都是温暖的气息",
        "elements": [
            "热燕麦粥",
            "肉桂香",
            "烤苹果",
            "咕嘟咕嘟",
            "暖烘烘"
        ],
        "sd_hint": "morning, stove with simmering small pot, holding wooden spoon, bowl of warm oatmeal with cinnamon and apple slices, warm homey light"
    },
    {
        "id": "m_026",
        "category": "美食手作",
        "theme": "手冲咖啡的焖蒸香气：细口壶注入热水，新鲜研磨的深烘咖啡粉在滤杯里像小蘑菇一样高高膨胀焖蒸，整个屋子弥漫着浓郁坚果醇香",
        "elements": [
            "手冲咖啡",
            "手冲壶",
            "滤杯",
            "膨胀焖蒸",
            "咖啡香"
        ],
        "sd_hint": "morning, brewing pourover drip coffee, slender goose-neck kettle pouring water, coffee blooming in filter, aromatic steam, morning sun"
    },
    {
        "id": "m_027",
        "category": "美食手作",
        "theme": "现榨多汁橙汁：咔嚓切开两颗汁水饱满的甜橙，在榨汁器上用力旋转，清冽微酸的果香瞬间爆开，一杯倒满阳光的维C能量",
        "elements": [
            "鲜榨橙汁",
            "切橙子",
            "玻璃杯",
            "果汁飞溅",
            "维C满满"
        ],
        "sd_hint": "morning, bright kitchen, slicing fresh juicy oranges, glass of freshly squeezed orange juice with ice cube, energetic cheerful vibe"
    },
    {
        "id": "m_028",
        "category": "美食手作",
        "theme": "华夫饼机叮的一声：华夫饼机散发出浓郁的香草奶香，伴随着清脆的叮当提示音，打开盖子是一块烤得格外均匀的焦糖色格子华夫",
        "elements": [
            "华夫饼",
            "华夫饼机",
            "香草味",
            "焦糖色",
            "格子"
        ],
        "sd_hint": "morning, waffle maker with fresh golden checkered waffle, steam rising, sweet expression, wearing cozy domestic clothes, bright sunlight"
    },
    {
        "id": "m_029",
        "category": "少女日常",
        "theme": "镜子前跟顽固呆毛搏斗：今天头顶正中间不知为何倔强地翘起了一大撮呆毛，拿水抹、用夹子压，一松手它又弹起来，绝望了",
        "elements": [
            "镜子",
            "呆毛",
            "发夹",
            "梳子",
            "搏斗十分钟"
        ],
        "sd_hint": "morning, bathroom mirror, holding hair clip and spray bottle, prominent funny ahoge bouncing up, funny troubled cute face, pajamas"
    },
    {
        "id": "m_030",
        "category": "少女日常",
        "theme": "迷迷糊糊把睡衣穿反了：坐在床沿揉了半天眼睛，喝了半杯水才突然发现自己居然把睡裤的正反面穿反了，怪不得前面兜鼓鼓的",
        "elements": [
            "穿反衣服",
            "迷迷糊糊",
            "揉眼睛",
            "床沿",
            "犯傻"
        ],
        "sd_hint": "morning, sitting on bed edge, messy hair, rubbing eyes, wearing cute pajamas backward, sheepish silly cute smile, soft morning light"
    },
    {
        "id": "m_031",
        "category": "少女日常",
        "theme": "单只小猫袜子神秘失踪案：衣柜里明明洗好的小猫图案棉袜只剩下一只，翻遍床缝、沙发底和洗衣机筒都不见踪影，它是离家出走了吗",
        "elements": [
            "找袜子",
            "单只袜子",
            "翻找",
            "床底下",
            "小谜题"
        ],
        "sd_hint": "morning, kneeling on carpet looking under bed, holding a single striped sock with cat print, puzzled confused expression, cute casual"
    },
    {
        "id": "m_032",
        "category": "少女日常",
        "theme": "窗台绿植冒出小嫩芽：早起给窗台那盆半死不活的绿萝浇水，竟然在最底下的老茎上发现了一个米粒大小的新绿嫩芽，开心了一上午",
        "elements": [
            "盆栽",
            "嫩芽",
            "浇水壶",
            "窗台",
            "小惊喜"
        ],
        "sd_hint": "morning, holding small pastel watering can, leaning over windowsill looking closely at tiny green sprout in ceramic pot, radiant happy face"
    },
    {
        "id": "m_033",
        "category": "少女日常",
        "theme": "有线耳机打了八十八个结：准备出门戴耳机听歌，从口袋里掏出来的有线耳机竟然打成了世界上最复杂死结，耐着性子解了整整五分钟",
        "elements": [
            "有线耳机",
            "解死结",
            "口袋里",
            "耐心告罄",
            "出门前"
        ],
        "sd_hint": "morning, holding tangled white earphone wires, trying to untangle them, slight cute frown and puffed cheeks, entrance hallway"
    },
    {
        "id": "m_034",
        "category": "少女日常",
        "theme": "在地板光斑里抢地盘的小猫：地板上刚好有一块被窗框切出的长方形阳光，家里的猫已经先一步摊成了一张猫饼，忍不住凑过去一起蹭太阳",
        "elements": [
            "地板光斑",
            "猫咪",
            "晒太阳",
            "懒洋洋",
            "趴在地板上"
        ],
        "sd_hint": "morning, lying on wooden floor in sunlight patch next to a sleeping fluffy cat, warm golden lighting, peaceful happy smile, lazy morning"
    },
    {
        "id": "m_035",
        "category": "少女日常",
        "theme": "手账本贴满闪亮贴纸：盘腿坐在地毯上打开手账本，小心翼翼地把刚买的小草莓贴纸贴在今天的日期格里，写下一句元气口号",
        "elements": [
            "手账本",
            "贴纸",
            "彩色水笔",
            "小目标",
            "仪式感"
        ],
        "sd_hint": "morning, sitting cross-legged on fluffy rug, decorating notebook planner with shiny cute stickers, colorful pens, creative delightful mood"
    },
    {
        "id": "m_036",
        "category": "少女日常",
        "theme": "被窝强力封印术解除中：闹钟响了三次，被窝像有磁铁一样紧紧吸住后背，最后全靠对早餐流心蛋的强烈执念才勉强把自己拔出来",
        "elements": [
            "闹钟",
            "被窝磁铁",
            "打哈欠",
            "艰难起床",
            "拔出自己"
        ],
        "sd_hint": "morning, entangled in fluffy duvet, peeking head out, yawning, sleepy eyes, struggling to get up, messy bed, warm indoor light"
    },
    {
        "id": "m_037",
        "category": "少女日常",
        "theme": "天气预报和衣柜的大纠结：看着手机上的气温发愁，穿厚外套怕中午热，穿单衣怕早晚冻，最后还是套上了最万能的那件针织大开衫",
        "elements": [
            "穿衣纠结",
            "针织开衫",
            "换季天气",
            "试穿",
            "镜前"
        ],
        "sd_hint": "morning, standing in front of open wardrobe, holding two different sweaters in each hand, contemplating expression, bedroom clothes racks"
    },
    {
        "id": "m_038",
        "category": "少女日常",
        "theme": "第一杯温热柠檬水：早起空腹喝一杯加了一片鲜黄柠檬的温水，微酸微甘顺着喉咙滑下去，感觉整个人慢悠悠地重新通上了电",
        "elements": [
            "柠檬水",
            "玻璃杯",
            "温水",
            "通上电",
            "清爽晨间"
        ],
        "sd_hint": "morning, holding clear glass mug with warm water and floating lemon slice, steam rising, taking a sip, refreshed relaxed face, kitchen"
    },
    {
        "id": "m_039",
        "category": "少女日常",
        "theme": "阳台大大的深呼吸与拉伸：走到阳台上把手臂高高举过头顶用力伸了个懒腰，骨头咔吧轻响一声，吸满一肚子的清冽新鲜空气",
        "elements": [
            "阳台",
            "伸懒腰",
            "拉伸",
            "深呼吸",
            "好精神"
        ],
        "sd_hint": "morning, standing on balcony, stretching arms high overhead, yawning slightly, wind blowing hair, sunny sky, refreshed full body pose"
    },
    {
        "id": "m_040",
        "category": "少女日常",
        "theme": "窗外电线上排排坐的胖麻雀：窗台外的电线上并排蹲着三只圆滚滚像毛球一样的小麻雀，小脑袋左晃右晃，好像在开晨间例会",
        "elements": [
            "麻雀",
            "圆滚滚",
            "电线杆",
            "窗外",
            "歪脑袋"
        ],
        "sd_hint": "morning, resting chin on window frame, looking at cute round sparrows perched on outdoor wire, soft cinematic morning light, amused smile"
    },
    {
        "id": "m_041",
        "category": "少女日常",
        "theme": "冰块落进玻璃杯的脆响：把制冰盒里冻得晶莹剔透的方冰块按进玻璃杯，咔哒脆响听着就让人心情愉悦，夏天好像提前到了三秒",
        "elements": [
            "冰块",
            "玻璃杯",
            "制冰盒",
            "咔哒清脆",
            "心情愉悦"
        ],
        "sd_hint": "morning, popping ice cubes from ice tray into transparent tall glass, crystal clear ice, splashes, refreshing vibe, cheerful expression"
    },
    {
        "id": "m_042",
        "category": "少女日常",
        "theme": "挑一个今天幸运发夹：在首饰盒里翻来翻去，最后挑中了那只毛茸茸的小兔耳朵发夹，别在刘海侧面，今天一定要做个幸运满分女孩",
        "elements": [
            "首饰盒",
            "发夹",
            "毛茸茸",
            "刘海",
            "开运小饰品"
        ],
        "sd_hint": "morning, clipping a cute small hair accessory onto bangs in mirror, delicate jewelry box open on dressing table, radiant sweet smile"
    },
    {
        "id": "m_043",
        "category": "少女日常",
        "theme": "阳台挂满晒太阳的白床单：把刚脱水好的床单用力抖开挂在晾衣绳上，微风一吹鼓得像一面白帆，空气里全是阳光晒暖的味道",
        "elements": [
            "晒床单",
            "阳台",
            "抖开",
            "白帆",
            "阳光香味"
        ],
        "sd_hint": "morning, outdoor sunny balcony, hanging clean white bedsheet on clothesline, sheet billowing in wind, bright sunlight, gentle joyful posture"
    },
    {
        "id": "m_044",
        "category": "期待与计划",
        "theme": "把书桌收拾得一尘不染：把散落的彩笔排整齐、电脑屏幕擦得干干净净，看着井井有条的小桌面，学习工作的干劲突然暴涨两百倍",
        "elements": [
            "擦桌子",
            "整齐书桌",
            "彩笔排列",
            "干劲满满",
            "一尘不染"
        ],
        "sd_hint": "morning, neat organized wooden desk, rows of pastel stationery pens, wiping desk with cloth, proud energized smile, modern aesthetic"
    },
    {
        "id": "m_045",
        "category": "期待与计划",
        "theme": "随机播放撞见神仙老歌：耳机里随机到一首好久没听的高中时期老歌，前奏吉他响起的瞬间整个人跟着节奏轻轻晃动起脑袋",
        "elements": [
            "耳机",
            "随机歌单",
            "宝藏老歌",
            "晃脑袋",
            "心情起飞"
        ],
        "sd_hint": "morning, wearing over-ear headphones, closed eyes gently bobbing head to music, cozy room, sunlight dancing on face, blissful mood"
    },
    {
        "id": "m_046",
        "category": "期待与计划",
        "theme": "抢到图书馆靠窗黄金位：清晨一路小跑刚好抢到图书馆采光最好的靠窗大桌子，把水杯和帆布包放下的瞬间获得了全天最高的成就感",
        "elements": [
            "图书馆",
            "靠窗大桌",
            "帆布包",
            "保温杯",
            "成就感"
        ],
        "sd_hint": "morning, library study hall, sitting at quiet desk by huge arched window, canvas tote bag, laptop, satisfied relieved smile"
    },
    {
        "id": "m_047",
        "category": "期待与计划",
        "theme": "晨间手绘板涂鸦热身：泡上热茶握着压感笔在数位板上随手画了几只歪歪扭扭的可爱圆滚小猫，线条格外顺畅，感觉今天手感无敌",
        "elements": [
            "手绘板",
            "压感笔",
            "涂鸦小猫",
            "线条顺畅",
            "手感火热"
        ],
        "sd_hint": "morning, drawing on digital tablet, stylus in hand, screen showing cute doodle sketches, cup of tea steaming, focused happy face"
    },
    {
        "id": "m_048",
        "category": "期待与计划",
        "theme": "翻开一本崭新空白手账：指尖抚过细腻微黄的特种纸张，在新本子的第一页工工整整写下今天的新日期，像开启了一场未知的探险",
        "elements": [
            "新本子",
            "空白页",
            "墨水笔",
            "开篇第一天",
            "仪式感满满"
        ],
        "sd_hint": "morning, opening brand new pristine paper notebook, holding fountain pen poised to write, pristine wooden desk, morning soft shadows"
    },
    {
        "id": "m_049",
        "category": "期待与计划",
        "theme": "红色塑胶跑道踏晨光：操场跑道上还带着露水，换上跑鞋踩在弹力十足的塑胶地面上，耳机里放着节奏感强烈的快歌，脚步越来越轻盈",
        "elements": [
            "操场跑道",
            "跑鞋",
            "快节奏歌",
            "脚步轻盈",
            "露水"
        ],
        "sd_hint": "morning, red athletic track, sports running shoes, active running pose, ponytail bouncing, clear morning sky, athletic vibrant glow"
    },
    {
        "id": "m_050",
        "category": "期待与计划",
        "theme": "整理周末短途小行李箱：把换洗衣物卷成小卷、塞进折叠伞和相机，最后把充电宝充满电，只要想到明天的短途旅行嘴角就压不下来",
        "elements": [
            "行李箱",
            "收拾衣服",
            "相机",
            "期待周末",
            "嘴角上扬"
        ],
        "sd_hint": "morning, packing a small pastel pastel suitcase on floor, rolling cute clothes, camera on bed, excited joyful expression"
    },
    {
        "id": "m_051",
        "category": "期待与计划",
        "theme": "玻璃杯里的明前绿茶：热水倒进透明杯里，原本蜷缩的嫩绿茶叶一根根缓缓竖立、在水中上下翻滚，看着心情也跟着慢了下来",
        "elements": [
            "绿茶",
            "茶叶翻滚",
            "透明玻璃杯",
            "清香",
            "放慢节奏"
        ],
        "sd_hint": "morning, holding clear glass cup with floating tender green tea leaves dancing in water, steam swirling, tranquil expression, tatami room"
    },
    {
        "id": "m_052",
        "category": "户外自然",
        "theme": "薄雾初晴的湖畔划船：清晨租了条小木船荡在静止如镜的湖心，桨尖划破薄雾荡起一圈圈金色水纹，几只白鹭贴着水面掠过",
        "elements": [
            "静水湖泊",
            "木划船",
            "薄雾泛金",
            "划桨水声",
            "晨飞白鹭"
        ],
        "sd_hint": "early morning, calm lake with light mist, rowing a small wooden boat, ripples in golden water, distant egrets flying, holding wooden paddle, serene tranquil vibe"
    },
    {
        "id": "m_053",
        "category": "户外自然",
        "theme": "漫山茶园的微甘晨风：沿着层层叠叠的翠绿梯田茶山走，采茶阿姨们已经戴着斗笠在忙活，指尖掐过嫩芽留下一缕极清爽的茶香",
        "elements": [
            "茶园梯田",
            "薄雾茶山",
            "指尖茶香",
            "微甜晨风",
            "斗笠阿姨"
        ],
        "sd_hint": "morning, terraced green tea plantation, gentle mist on mountain slopes, holding a fresh green tea sprout, smiling peacefully, soft natural lighting"
    },
    {
        "id": "m_054",
        "category": "户外自然",
        "theme": "初雪清晨的冰花玻璃窗：一觉醒来整个世界静得出奇，窗户玻璃结了一整片晶莹剔透的羽毛状冰花，哈一口气融化出一个小圆孔往外看全是白茫茫",
        "elements": [
            "初雪清晨",
            "窗户冰花",
            "哈气成雾",
            "银白世界",
            "羽毛冰晶"
        ],
        "sd_hint": "early morning, breathing warm vapor onto frosted glass window with crystalline feather ice patterns, seeing snowy street outside, warm knit oversized sweater, cozy indoor"
    },
    {
        "id": "m_055",
        "category": "户外自然",
        "theme": "断崖灯塔下的第一阵晨风：站在白色灯塔下的悬崖草甸上，脚下是墨蓝翻涌的海水撞在礁石上碎成白色雪沫，清晨第一道红日破云而出",
        "elements": [
            "白色灯塔",
            "悬崖草甸",
            "惊涛拍岸",
            "初升红日",
            "海风吹拂"
        ],
        "sd_hint": "morning, grassy cliffside beside a white ocean lighthouse, crashing waves below, dramatic sunrise clouds, hair blown by strong wind, long coat, breathtaking scenery"
    },
    {
        "id": "m_056",
        "category": "户外自然",
        "theme": "向日葵花田里的金色早晨：一整片漫无边际的向日葵全部仰着大圆脸朝着东方晨曦，草帽下的碎发被风吹得晃晃悠悠，花瓣上还挂着露珠",
        "elements": [
            "向日葵田",
            "晨露花瓣",
            "草帽碎发",
            "金黄原野",
            "灿烂晨光"
        ],
        "sd_hint": "morning, vast blooming sunflower field, holding yellow straw hat against breeze, bright morning sunlight shining through flower petals, joyful sweet expression"
    },
    {
        "id": "m_057",
        "category": "户外自然",
        "theme": "山谷溪流冰凉水波：清晨踩着露出水面的大圆石过溪，伸手舀了一捧山泉水拍了拍脸，冷冽清澈得整个人灵魂瞬间清醒了",
        "elements": [
            "山谷溪流",
            "冰凉山泉",
            "过河圆石",
            "水花拍脸",
            "清凉透心"
        ],
        "sd_hint": "morning, mountain stream with mossy stepping stones, splashing cold clear water onto face, refreshing smile, hiking shorts and light windbreaker, dappled morning shadows"
    },
    {
        "id": "m_058",
        "category": "户外自然",
        "theme": "樱花初绽的小坡道漫步：清晨无人的坂道两侧樱花缀满了枝头，微风一吹几瓣淡粉花瓣轻轻落在书包拉链上，整条街都是甜甜的春天味道",
        "elements": [
            "樱花坂道",
            "落樱花瓣",
            "清晨街道",
            "粉白花树",
            "春日微风"
        ],
        "sd_hint": "spring morning, quiet sloping asphalt street lined with blooming pink cherry trees, falling sakura petals, casual school bag, catching a petal, soft pastel colors"
    },
    {
        "id": "m_059",
        "category": "户外自然",
        "theme": "清晨竹海沙沙私语：竹林深处石阶湿润，细长翠绿的竹竿在晨风中轻轻摇曳碰撞出笃笃的声音，深吸一口满腔都是青竹的清香",
        "elements": [
            "晨风竹林",
            "翠绿竹海",
            "石阶露水",
            "竹叶沙沙",
            "青竹清香"
        ],
        "sd_hint": "morning, serene green bamboo forest, stone steps winding through trees, morning light filtering through high bamboo leaves, peaceful contemplative mood"
    },
    {
        "id": "m_060",
        "category": "户外自然",
        "theme": "薰衣草农场的紫粉色晨曦：晨曦把整片紫色的花田染成了温柔的丁香粉色，成群的早起蜜蜂已经在花尖上嗡嗡打转，空气里是浓得化不开的草本香",
        "elements": [
            "薰衣草田",
            "粉紫晨光",
            "花间蜜蜂",
            "草本芳香",
            "木围栏"
        ],
        "sd_hint": "early morning, endless purple lavender field at sunrise, soft pink and lilac morning sky, sundress with light cardigan, kneeling to touch flowers, dreamy aesthetic"
    },
    {
        "id": "m_061",
        "category": "户外自然",
        "theme": "靠海电车站台等第一班车：清晨的海风吹得站台顶棚哐当轻响，电车轨道正对着波光粼粼的无垠大海，自动贩卖机吐出一罐暖呼呼的奶茶",
        "elements": [
            "临海电车站",
            "无垠大海",
            "第一班电车",
            "热奶茶铁罐",
            "清爽海风"
        ],
        "sd_hint": "early morning, open-air seaside train platform facing glittering ocean, holding hot canned drink from vending machine, loose scarf, looking down tracks"
    },
    {
        "id": "m_062",
        "category": "户外自然",
        "theme": "湿地芦苇荡清晨飞鸟：金黄色的芦苇絮随风起伏如波浪，几只野鸭在芦苇根部的水泊里划开涟漪，太阳像颗流心蛋黄慢吞吞升起来",
        "elements": [
            "湿地芦苇",
            "金色芦花",
            "水泊野鸭",
            "流心蛋黄日出",
            "木质栈桥"
        ],
        "sd_hint": "morning, vast wetland with golden tall reeds, wooden boardwalk, sunrise glowing like egg yolk on horizon, wild ducks swimming, warm morning palette"
    },
    {
        "id": "m_063",
        "category": "户外自然",
        "theme": "清晨植物园玻璃温室：清晨阳光穿透巨大的白色钢架玻璃穹顶，热带蕨类和巨大龟背竹叶片上聚满晶莹的水珠，空气湿润温暖像热带雨林",
        "elements": [
            "玻璃温室",
            "热带雨林",
            "龟背竹水珠",
            "钢架穹顶",
            "湿润暖意"
        ],
        "sd_hint": "morning, lush botanical greenhouse interior, giant monstera and palm leaves, sunbeams filtering through glass ceiling, wearing linen dress, breathing fresh air"
    },
    {
        "id": "m_064",
        "category": "户外自然",
        "theme": "高原草甸的清凉晨光：远处的雪山尖顶在第一抹粉紫霞光中渐渐染金，脚下的高山草甸上缀满了金黄与浅紫的格桑花，风吹得披肩猎猎作响",
        "elements": [
            "高山草甸",
            "雪山金顶",
            "格桑花海",
            "高原晨曦",
            "羊绒披肩"
        ],
        "sd_hint": "early morning, vast highland plateau, snowcapped mountain peak glowing in sunrise, alpine wildflower meadow, colorful ethnic wool shawl fluttering"
    },
    {
        "id": "m_065",
        "category": "户外自然",
        "theme": "给窗台食盒添加谷物引来山雀：往木质小鸟食盒里撒了一把葵花籽和小米，没过两分钟就有两只胖乎乎的黄腹山雀蹦蹦跳跳来啄食，歪头看人的模样太萌了",
        "elements": [
            "窗台食盒",
            "葵花籽小米",
            "黄腹山雀",
            "歪头啄食",
            "与鸟共处"
        ],
        "sd_hint": "morning, leaning on window sill, watching two chubby little birds eat seeds from wooden feeder, hands propping chin, beaming gentle smile"
    },
    {
        "id": "m_066",
        "category": "户外自然",
        "theme": "海边木栈桥折返慢跑：沿着长长的伸向大海的木码头迎风小跑，耳边只有海水规律拍击桥墩的声响，跑步结束停下来双手叉腰迎着朝霞大口呼吸",
        "elements": [
            "延伸木码头",
            "海浪拍击",
            "迎风慢跑",
            "朝霞漫天",
            "大口呼吸"
        ],
        "sd_hint": "morning, wooden ocean pier stretching into distance, wearing running outfit and visor, hands on hips catching breath, glorious sunrise sky reflected in sea"
    },
    {
        "id": "m_067",
        "category": "户外自然",
        "theme": "清晨果园摘下第一颗带露蜜桔：钻进漫山遍野的柑橘林，伸手剪下一颗挂着露水的青黄蜜桔，指甲掐破果皮的一瞬间，极清香浓郁的柑橘精油汁水四溢",
        "elements": [
            "清晨果园",
            "带露蜜桔",
            "掐破果皮",
            "精油清香",
            "竹编小筐"
        ],
        "sd_hint": "morning, sunny citrus orchard, holding a fresh orange with green leaves just plucked from tree, basket of fruits at feet, overalls, joyful outdoor glow"
    },
    {
        "id": "m_068",
        "category": "城市漫步",
        "theme": "跨江大桥上的薄雾漫步：大桥横跨在大江之上，桥头下还被乳白色的晨雾笼罩，只能听见江轮沉闷悠长的汽笛，整座城市仿佛还在沉睡",
        "elements": [
            "跨江大桥",
            "乳白晨雾",
            "江轮汽笛",
            "清晨微风",
            "城市苏醒"
        ],
        "sd_hint": "early morning, large bridge walkway shrouded in morning fog, railings vanishing into white mist, coat wrapped tight, solitary poetic atmosphere"
    },
    {
        "id": "m_069",
        "category": "城市漫步",
        "theme": "老书店开门前的橱窗驻足：清晨街道还没什么车，早早走到巷子深处那家二手书店前，阳光斜照在贴满旧海报的木门和玻璃橱窗里的猫咪身上",
        "elements": [
            "老书店门前",
            "旧书橱窗",
            "晒太阳猫猫",
            "晨光斜射",
            "无车小街"
        ],
        "sd_hint": "morning, street corner in front of vintage wooden bookstore, cat asleep inside sunny display window, looking at old books through glass, carrying canvas tote"
    },
    {
        "id": "m_070",
        "category": "城市漫步",
        "theme": "清晨花卉批发市场淘花：一大早就钻进潮湿的花市，满地都是刚剪下来的带水滴的尤加利叶和粉雪山玫瑰，抱了一大捧洋牡丹走出市场感觉拥抱了整个春天",
        "elements": [
            "晨早花市",
            "带露鲜花",
            "尤加利叶香",
            "抱着大束花",
            "水淋淋地面"
        ],
        "sd_hint": "early morning, bustling flower market, holding a giant wrapped bouquet of colorful ranunculus and eucalyptus, radiant beaming smile, apron or casual sweater"
    },
    {
        "id": "m_071",
        "category": "城市漫步",
        "theme": "大榕树下看老爷爷打太极：街心小广场的大榕树垂着长长的胡须，几位老爷爷慢悠悠推着太极掌法，鸽子扑棱棱在石砖地上捡面包屑，节奏慢得让人心安",
        "elements": [
            "街心广场",
            "老榕树荫",
            "白鸽吃屑",
            "太极晨练",
            "慢节奏生活"
        ],
        "sd_hint": "morning, city park square with massive old banyan tree, pigeons eating bread crumbs on stone tiles, sitting on park bench, watching gentle morning exercise"
    },
    {
        "id": "m_072",
        "category": "城市漫步",
        "theme": "天台小花园修剪薄荷：爬上天台给一圈小盆栽浇水，掐掉几片干枯的薄荷叶，手指上沾满了浓郁清冽的薄荷油香气，天际线被染成淡橘色",
        "elements": [
            "天台盆栽",
            "浇水水壶",
            "手指薄荷香",
            "淡橘天际线",
            "小花园"
        ],
        "sd_hint": "morning, rooftop garden with potted herbs and plants, holding a metal watering can, water droplets on green leaves, gentle morning skyline in background"
    },
    {
        "id": "m_073",
        "category": "美食手作",
        "theme": "第一批刚出炉的可颂热气：赶在七点半推开街角面包房的门，正好撞见师傅把一盘烤得金黄焦脆的大可颂端上架，油亮酥皮散发的黄油香简直是清晨最大的救赎",
        "elements": [
            "刚出炉可颂",
            "浓郁黄油香",
            "面包房铃铛",
            "焦黄酥皮",
            "热气腾腾"
        ],
        "sd_hint": "morning, vintage bakery interior, fresh golden croissants on wooden trays emitting steam, holding bakery tongs, mouthwatering butter aroma, cozy lighting"
    },
    {
        "id": "m_074",
        "category": "美食手作",
        "theme": "手动打发一碗绵密抹茶奶泡：用茶筅笃笃笃在深口碗里打出细腻泛绿的泡沫，缓缓倒入热燕麦奶，端着大碗喝出一圈可爱的绿色小胡子",
        "elements": [
            "茶筅打沫",
            "手作抹茶",
            "绵密奶泡",
            "热燕麦奶",
            "绿色小胡子"
        ],
        "sd_hint": "morning, kitchen counter, whisking matcha powder with bamboo chasen, cup of layered matcha oat latte, cute green foam mustache, laughing face"
    },
    {
        "id": "m_075",
        "category": "美食手作",
        "theme": "周末手作松软松饼塔：慢火在平底锅里煎出三个圆滚滚的小松饼，摞成小塔浇上一大勺金黄枫糖浆，顶上放两颗红艳艳的鲜草莓，幸福感直接拉满",
        "elements": [
            "手作松饼",
            "枫糖浆流淌",
            "鲜草莓顶饰",
            "平底锅香气",
            "周末仪式感"
        ],
        "sd_hint": "morning, dining table, plate with stack of fluffy pancakes dripping with golden maple syrup and fresh strawberries, fork and knife, proud cute expression"
    },
    {
        "id": "m_076",
        "category": "美食手作",
        "theme": "细嘴壶手冲耶加雪菲：清晨厨房很静，细细的水流在咖啡粉堆上画圈，看着深褐色的咖啡粉膨胀成饱满的汉堡包，柑橘和花果香气瞬间填满了整间屋子",
        "elements": [
            "手冲咖啡",
            "咖啡粉膨胀",
            "细嘴壶注水",
            "柑橘花果香",
            "清晨仪式感"
        ],
        "sd_hint": "morning, pour-over coffee dripper on glass carafe, pouring water from gooseneck kettle, coffee blooming with aroma, sunlight streaming across wooden countertop"
    },
    {
        "id": "m_077",
        "category": "美食手作",
        "theme": "早茶蒸笼里的流沙流心包：掀开竹蒸笼盖子那一瞬水汽扑面，白胖胖的包子撕开一个小口，金黄滚烫的咸蛋黄流沙馅淌在指尖，烫得直吸溜嘴",
        "elements": [
            "竹制蒸笼",
            "白胖包子",
            "咸蛋黄流沙",
            "水汽扑面",
            "烫嘴吸溜"
        ],
        "sd_hint": "morning, dim sum table, opening bamboo steamer with steam rising, biting into golden flowing egg custard bun, blowing on hot food, cute exaggerated expression"
    },
    {
        "id": "m_078",
        "category": "美食手作",
        "theme": "牛油果流心水波蛋吐司：全麦吐司烤得焦香嘎吱响，抹满牛油果泥撒上海盐黑胡椒，小刀轻轻划开水波蛋，金黄蛋液缓缓裹满面包片",
        "elements": [
            "牛油果泥",
            "水波蛋破浆",
            "烤全麦吐司",
            "研磨黑胡椒",
            "健康轻食"
        ],
        "sd_hint": "morning, bright kitchen, plate with avocado toast topped with a poached egg bursting with liquid yolk, sprinkling black pepper, aesthetic food photography"
    },
    {
        "id": "m_079",
        "category": "美食手作",
        "theme": "肉桂苹果热燕麦粥：小锅慢熬出的稠稠燕麦粥，丢进切碎的黄油炒苹果丁，撒上一小撮肉桂粉，暖融融的甜香让整个秋日清晨都变得柔软又安心",
        "elements": [
            "肉桂粉甜香",
            "黄油苹果丁",
            "浓稠燕麦粥",
            "小锅慢煮",
            "秋日暖心"
        ],
        "sd_hint": "morning, ceramic bowl filled with creamy cinnamon apple oatmeal, steam rising, wooden spoon, cozy knit cardigan, warm kitchen window"
    },
    {
        "id": "m_080",
        "category": "美食手作",
        "theme": "华夫饼机叮的一声惊喜：面糊倒进热铁盘压紧，伴随着滋啦滋啦的小声响，叮的一声掀开是焦黄酥脆的格子华夫饼，淋上一圈野花蜜",
        "elements": [
            "华夫饼机",
            "焦脆格子",
            "滋啦滋啦",
            "野花蜜",
            "叮的一声"
        ],
        "sd_hint": "morning, kitchen, opening waffle maker to reveal golden crisp waffle, drizzling wild honey from glass jar, playful proud smile"
    },
    {
        "id": "m_081",
        "category": "美食手作",
        "theme": "早市油锅里刚翻面的现炸油条：菜市场早点摊的大铁锅里菜籽油咕嘟滚沸，长长的面胚丢进去瞬间蓬松膨胀成金黄两截，配上一碗热腾腾现磨咸豆腐脑",
        "elements": [
            "现炸油条",
            "膨胀金黄",
            "早市烟火",
            "咸豆腐脑",
            "滚沸油锅"
        ],
        "sd_hint": "morning, bustling traditional street breakfast market, watching golden fried dough crullers emerge from hot oil, holding bowl of steaming tofu pudding"
    },
    {
        "id": "m_082",
        "category": "美食手作",
        "theme": "刚复烤的贝果抹厚厚一层芝士：把全麦芝麻贝果对半切开烤得外脆里韧，挖出一大勺酸奶风味轻乳酪奶酪抹在切面上，咬下去咔嚓一声麦香炸裂",
        "elements": [
            "复烤贝果",
            "厚抹奶酪",
            "外脆里韧",
            "咔嚓一声",
            "全麦芝麻香"
        ],
        "sd_hint": "morning, kitchen counter, spreading thick cream cheese on a toasted golden bagel slice with butter knife, morning sunlight glinting on plate"
    },
    {
        "id": "m_083",
        "category": "美食手作",
        "theme": "平底锅里滋滋融化的黄油法式吐司：厚切吐司浸满蛋奶液后丢入黄油平底锅，两面煎出诱人的焦糖色，出锅时趁热放上一小块咸黄油看着它慢慢滑落",
        "elements": [
            "法式吐司",
            "蛋奶浸泡",
            "焦糖色泽",
            "黄油滑落",
            "滋滋作响"
        ],
        "sd_hint": "morning, dining table with a thick slice of golden French toast topped with a melting cube of salted butter and powdered sugar, cutting with fork"
    },
    {
        "id": "m_084",
        "category": "美食手作",
        "theme": "煮出掐表六分半的完美溏心蛋：严格掐表六分三十秒捞出过冰水，轻轻敲碎蛋壳剥出一颗白白嫩嫩的小胖子，一刀切开橙红色的溏心浓稠得缓缓流淌",
        "elements": [
            "六分半溏心蛋",
            "冰水过凉",
            "白嫩完整",
            "橙红流心",
            "掐表成就感"
        ],
        "sd_hint": "morning, holding two halves of a perfectly boiled soft egg with runny orange yolk, proud victorious cute expression, small ceramic egg cup on table"
    },
    {
        "id": "m_085",
        "category": "美食手作",
        "theme": "清晨鲜挤柠檬薄荷气泡水：两颗黄柠檬对半切开挤出酸爽汁水，丢进几块透明冰块和薄荷叶，倒进冰镇苏打水那一刻气泡沙沙沙欢快地往上窜",
        "elements": [
            "鲜挤柠檬",
            "薄荷冰块",
            "气泡水沙沙",
            "酸甜激爽",
            "透明玻璃杯"
        ],
        "sd_hint": "morning, pouring sparkling water into tall glass filled with ice, lemon wedges and fresh mint leaves, fizzy bubbles rising, refreshed bright face"
    },
    {
        "id": "m_086",
        "category": "少女日常",
        "theme": "被清晨阳光晒到脚踝的大懒腰：金灿灿的光斑从窗帘缝隙溜进来正好晒在脚丫上暖洋洋的，整个人像小猫一样手脚并用拉长身体伸一个痛快的大懒腰",
        "elements": [
            "阳光晒脚",
            "小猫伸懒腰",
            "窗帘光斑",
            "松软床褥",
            "舒展筋骨"
        ],
        "sd_hint": "morning, messy bed with white sheets, sitting up and stretching arms high overhead in big yawn, sunshine beam across toes, cute oversized pajama, messy hair"
    },
    {
        "id": "m_087",
        "category": "少女日常",
        "theme": "跟死活解不开的耳机线搏斗：戴上运动鞋准备出门，掏出耳机线发现它竟然自动打了一个死扣，站在玄关跟一团乱麻较劲了三分钟，解开时成就感爆棚",
        "elements": [
            "耳机线打结",
            "玄关较劲",
            "死扣解开",
            "换运动鞋",
            "莫名成就感"
        ],
        "sd_hint": "morning, sitting at apartment entryway putting on sneakers, concentrating on untangling a ball of wired earphones, funny determined pout"
    },
    {
        "id": "m_088",
        "category": "少女日常",
        "theme": "低头发现袜子两只花色不一样：在玄关系鞋带时才猛然发现，左脚是一只小鸭子，右脚是一只小草莓，仔细看看居然还挺配，就这么雄赳赳气昂昂地出门啦",
        "elements": [
            "左右脚袜子不同",
            "小鸭与草莓",
            "系鞋带发现",
            "误打误撞可爱",
            "自信出门"
        ],
        "sd_hint": "morning, sitting on floor tying sneakers, looking down at mismatched colorful socks (one duck, one strawberry), quirky proud mischievous grin"
    },
    {
        "id": "m_089",
        "category": "少女日常",
        "theme": "拿滴管给肉嘟嘟多肉喂水：窗台上的多肉胖得像小熊爪子，拿着小挤压瓶小心翼翼对着根部滴水，生怕水珠掉进叶心里，认真的样子像个外科医生",
        "elements": [
            "多肉植物",
            "挤压水壶",
            "小熊爪子",
            "窗台阳光",
            "专注喂水"
        ],
        "sd_hint": "morning, window ledge filled with cute chubby succulents, using small squeeze dropper bottle to water roots, intensely focused cute face"
    },
    {
        "id": "m_090",
        "category": "少女日常",
        "theme": "洁面慕斯搓出巨大白泡沫：按了两下慕斯泵，竟然在手心里搓出了一大团像棉花糖一样绵密雪白的大泡沫，糊在鼻尖上像个滑稽的小雪人",
        "elements": [
            "洁面慕斯",
            "棉花糖泡沫",
            "鼻尖泡泡",
            "镜前雪人",
            "清爽洗脸"
        ],
        "sd_hint": "morning, bathroom mirror, white fluffy cleansing foam piled on cheeks and tip of nose, wide playful eyes, hair held back by plush headband"
    },
    {
        "id": "m_091",
        "category": "少女日常",
        "theme": "摇削笔刀摇出一整条木卷花：清晨坐在书桌前转动削笔刀，竟然摇出了一整条连绵不绝的木质铅笔花，散发着好闻的雪松木香，摆在桌角当艺术品",
        "elements": [
            "削铅笔机",
            "木卷花完整",
            "雪松木香气",
            "清晨书桌",
            "收集小确幸"
        ],
        "sd_hint": "morning, study desk with morning light, holding an intact swirling ribbon of pencil shavings from manual pencil sharpener, delighted admiring expression"
    },
    {
        "id": "m_092",
        "category": "少女日常",
        "theme": "编麻花辫手滑散架重新来过：对着镜子认真编了半天的三股辫，刚准备摸皮筋手一滑整条辫子又散成了波浪卷，对着镜子叹气却被自己的毛躁炸毛逗笑",
        "elements": [
            "编麻花辫",
            "手滑散架",
            "波浪炸毛",
            "对着镜子叹气",
            "呆萌重来"
        ],
        "sd_hint": "morning, looking in vanity mirror, holding ends of half-undone braided hair that slipped loose, funny exasperated pout, soft morning lighting"
    },
    {
        "id": "m_093",
        "category": "少女日常",
        "theme": "在新买的空白手账第一页落笔：挑了一支出水极其顺滑的咖啡色中性笔，在泛着奶白色的厚纸上写下第一句今日计划，笔尖沙沙沙的声音让人心情大好",
        "elements": [
            "空白手账本",
            "顺滑中性笔",
            "沙沙书写声",
            "新一页开始",
            "奶白纸张"
        ],
        "sd_hint": "morning, wooden desk, writing carefully in a fresh blank notebook planner with gel pen, neat handwriting, morning sunbeams, cozy serene focus"
    },
    {
        "id": "m_094",
        "category": "少女日常",
        "theme": "挂烫机给白色衬衫抚平褶皱：蒸汽呲呲地喷出来，把洗皱的白衬衫一点点熨得平整挺括，穿上身上带着微热的阳光晒干气息，整个人气场都变精神了",
        "elements": [
            "挂烫机蒸汽",
            "抚平衬衫",
            "微热棉布香",
            "精神抖擞",
            "清晨穿衣"
        ],
        "sd_hint": "morning, holding garment steamer, steaming wrinkles out of white cotton shirt on hanger, steam floating in air, wearing cozy loungewear"
    },
    {
        "id": "m_095",
        "category": "少女日常",
        "theme": "在穿旧的风衣口袋摸出一枚硬币：伸手掏外套口袋准备拿纸巾，指尖却摸到了冰凉的一枚硬币，像捡到了上个季节留给自己的隐藏彩蛋！",
        "elements": [
            "外套口袋",
            "摸出硬币",
            "隐藏彩蛋",
            "意外小开心",
            "清晨换衣"
        ],
        "sd_hint": "morning, wearing trench coat, pulling hand out of pocket holding a shiny coin between fingers, pleasantly surprised sparkly eyes"
    },
    {
        "id": "m_096",
        "category": "少女日常",
        "theme": "晨起冲澡哼着跑调的歌：热水冲刷掉昨夜残余的所有困意，浴室玻璃门凝满了水雾，一边涂抹柑橘香的沐浴露一边毫无顾忌地大声哼唱小曲",
        "elements": [
            "清晨冲澡",
            "柑橘沐浴露",
            "水汽朦胧",
            "跑调哼歌",
            "神清气爽"
        ],
        "sd_hint": "morning, bathroom doorway, towel wrapped around wet hair, wearing fresh loungewear, flushed pink cheeks, humming happily, vapor in background"
    },
    {
        "id": "m_097",
        "category": "少女日常",
        "theme": "对着墨镜镜片哈一口气仔细擦净：准备出门前发现墨镜上印了个指纹，拿出来哈一口白雾用柔软的麂皮绒布一圈圈擦亮，戴上推了推镜框帅气出发",
        "elements": [
            "墨镜哈气",
            "麂皮布擦拭",
            "推镜框",
            "酷女孩出门",
            "阳光准备"
        ],
        "sd_hint": "morning, standing at door, blowing breath on lenses of sunglasses and polishing with cloth, wearing stylish summer jacket, confident cool smile"
    },
    {
        "id": "m_098",
        "category": "少女日常",
        "theme": "对着镜子反复调整新发夹的位置：新买的一字小雏菊发夹，在刘海左边夹一下觉得太高，右边夹一下觉得太斜，折腾了五分钟终于找到黄金绝美角度",
        "elements": [
            "小雏菊发夹",
            "调整位置",
            "镜前纠结",
            "黄金角度",
            "发丝别致"
        ],
        "sd_hint": "morning, close up in mirror, clipping a delicate daisy hair clip into bangs with both hands, tilting head sideways critically, cute concentrated gaze"
    },
    {
        "id": "m_099",
        "category": "少女日常",
        "theme": "晨间瑜伽后把瑜伽垫卷成整齐圆筒：做完十五分钟晨间苏醒拉伸，浑身微微出了一层薄汗，蹲在地上把粉色瑜伽垫一寸寸卷得极其周正，绑上束带",
        "elements": [
            "晨间瑜伽",
            "卷瑜伽垫",
            "周正圆筒",
            "微汗舒爽",
            "规律生活"
        ],
        "sd_hint": "morning, living room floor, kneeling to roll up a pastel pink yoga mat, wearing sports bra and leggings, healthy natural flush on cheeks"
    },
    {
        "id": "m_100",
        "category": "少女日常",
        "theme": "用羊毛小掸子轻扫一排排旧书脊：晨光斜射进书房，拿着毛茸茸的羊毛掸子轻轻拂过整齐的书脊，看着微小的尘埃在光柱里跳舞，书房变得亮堂堂",
        "elements": [
            "羊毛掸子",
            "书脊除尘",
            "书房晨光",
            "纸香弥漫",
            "干净整洁"
        ],
        "sd_hint": "morning, home library or study, holding fluffy wool duster brushing over spine of hardback books on wooden shelf, serene domestic charm"
    },
    {
        "id": "m_101",
        "category": "少女日常",
        "theme": "系出两只对称端正的蝴蝶结鞋带：今天出门特地把帆布鞋的白色鞋带拆开重新穿，规规矩矩系出两只饱满立体的蝴蝶结，踩踩脚后跟感觉今天能走两万步",
        "elements": [
            "对称蝴蝶结",
            "帆布鞋鞋带",
            "踩踩脚后跟",
            "两万步信心",
            "整装待发"
        ],
        "sd_hint": "morning, one foot resting on park bench tying white shoelaces into neat bow on canvas sneaker, athletic backpack, looking forward with bright anticipation"
    },
    {
        "id": "m_102",
        "category": "期待与计划",
        "theme": "阳台风铃敲出清脆第一响：挂在晾衣架旁边的透明玻璃风铃被掠过的微风撞击，发出叮铃铃极清澈的一声脆响，仿佛宣告着今天会是个超棒的大晴天",
        "elements": [
            "玻璃风铃",
            "叮铃脆响",
            "大晴天宣告",
            "微风拂过",
            "阳台远眺"
        ],
        "sd_hint": "morning, standing on apartment balcony, looking up at glass wind chime tinkling in breeze, clear blue sky, hair softly floating"
    },
    {
        "id": "m_103",
        "category": "期待与计划",
        "theme": "画着火柴人的露营装备清单：在便签条上写写画画周末去郊外野餐的小清单，画了一顶歪歪扭扭的三角小帐篷和一个烤棉花糖，光是想想就已经飞出去了",
        "elements": [
            "野餐清单",
            "便签纸涂鸦",
            "火柴人帐篷",
            "烤棉花糖",
            "期待周末"
        ],
        "sd_hint": "morning, desk with colorful sticky notes, doodling funny stick-figure tent and campfire with colored pencils, daydreaming smile looking upward"
    },
    {
        "id": "m_104",
        "category": "期待与计划",
        "theme": "花盆里悄悄探出头的小嫩芽：上周随手埋在土里的小柠檬籽，今天早上竟然破土钻出了一对嫩黄微绿的豆瓣，蹲在地上看了五分钟感动得像个老母亲",
        "elements": [
            "种子发芽",
            "破土嫩芽",
            "老母亲欣慰",
            "花盆泥土",
            "清晨惊喜"
        ],
        "sd_hint": "morning, squatting next to small terracotta pot on floor, pointing gently at tiny green sprout poking out of soil, proud starry eyes"
    },
    {
        "id": "m_105",
        "category": "期待与计划",
        "theme": "晨间日推挖到了神仙宝藏单曲：戴上耳机随机播放，第一首的前奏吉他扫弦一出来的瞬间，整个人鸡皮疙瘩都起来了，火速点击红心收藏循环一整天",
        "elements": [
            "日推新歌",
            "神仙前奏",
            "吉他扫弦",
            "红心收藏",
            "戴耳机摇晃"
        ],
        "sd_hint": "morning, headphones on, holding phone displaying music player with glowing heart icon, head bobbing to rhythm, blissfully happy expression"
    },
    {
        "id": "m_106",
        "category": "期待与计划",
        "theme": "昨天晒过太阳的蓬松被单香：翻身时鼻尖全都是被阳光烘烤过的棉花干燥清香，像一头扎进了暖烘烘的云朵里，整个人被治愈得浑身软绵绵",
        "elements": [
            "阳光被单香",
            "烘烤棉花味",
            "扎进云朵",
            "治愈软绵绵",
            "清晨回味"
        ],
        "sd_hint": "morning, face buried in freshly sun-dried fluffy white duvet, inhaling comforting scent, soft warm pastel lighting, cozy smile"
    }
]

NIGHT_THEME_POOL = [
    {
        "id": "n_001",
        "category": "自然风景",
        "theme": "海滩粉紫晚霞漫步：潮水一层层漫过光脚踝带来微凉的触感，天边像打翻的调色盘一样晕染开绝美的粉紫与橙黄渐变色晚霞",
        "elements": [
            "海滩",
            "晚霞",
            "粉紫色天空",
            "潮水漫过脚踝",
            "海风拂面"
        ],
        "sd_hint": "evening twilight, walking barefoot on sandy beach, magnificent pink and purple sunset glow over ocean, reflections on wet sand, serene dress"
    },
    {
        "id": "n_002",
        "category": "自然风景",
        "theme": "天台蓝调时刻吹晚风：落日刚刚沉入地平线，天空呈现出深邃通透的静谧靛蓝色，趴在天台栏杆上看整座城市的万家灯火一盏盏点亮",
        "elements": [
            "蓝调时刻",
            "天台栏杆",
            "深蓝天空",
            "万家灯火",
            "吹晚风"
        ],
        "sd_hint": "night, twilight blue hour, rooftop railing, looking out over shimmering city lights below, deep blue sky, wind blowing oversized cardigan"
    },
    {
        "id": "n_003",
        "category": "自然风景",
        "theme": "远离城市的璀璨银河：仰面躺在草坡上，没有城市光污染的夜空里缀满了密密麻麻的繁星，银河像一条发光的白纱横跨天际",
        "elements": [
            "草地",
            "星空",
            "银河",
            "繁星密布",
            "仰望夜空"
        ],
        "sd_hint": "night, lying on grassy hill looking up at breathtaking starry night sky, visible milky way galaxy, magical sparkling stars, peaceful awe"
    },
    {
        "id": "n_004",
        "category": "自然风景",
        "theme": "倚着窗台听夏夜雷雨：窗外暴雨哗哗砸在玻璃和阔叶芭蕉上，屋里只留一盏暗暖的阅读灯，空气里飘进雨水打湿泥土的清凉芳香",
        "elements": [
            "夜雨",
            "窗台水珠",
            "雨声",
            "阅读灯",
            "湿润泥土香"
        ],
        "sd_hint": "night, sitting by window watching rain pouring outside, rain droplets running down glass pane, dim cozy indoor light, listening to thunder"
    },
    {
        "id": "n_005",
        "category": "自然风景",
        "theme": "湖畔露营小篝火：围坐在噼啪作响的暖橘色篝火旁，偶尔有火星轻盈地飞向夜空，拿铁签串着棉花糖烤到表面微黄流心",
        "elements": [
            "篝火",
            "噼啪作响",
            "烤棉花糖",
            "湖面倒影",
            "露营椅"
        ],
        "sd_hint": "night, lakeside camping, glowing warm campfire, roasting marshmallows on stick, sparks flying up, wrapped in wool blanket, cozy warm glow"
    },
    {
        "id": "n_006",
        "category": "自然风景",
        "theme": "麦田尽头的落日熔金：夕阳把广袤麦浪染成炽烈耀眼的火红金光，凉爽的晚风掀起阵阵波浪，站在田埂上久久舍不得眨眼",
        "elements": [
            "麦田落日",
            "落日熔金",
            "晚风掀麦浪",
            "田埂",
            "暮色"
        ],
        "sd_hint": "dusk, vast wheat field under blazing golden sunset, fiery orange and crimson clouds, wind rippling crops, silhouetted gentle figure"
    },
    {
        "id": "n_007",
        "category": "自然风景",
        "theme": "古镇夜巷红灯笼：石板桥下泊着暗影摇曳的乌篷船，屋檐下的红灯笼一串串亮起，水面碎金闪烁，夜游的人声隐隐约约传开",
        "elements": [
            "水乡古镇",
            "红灯笼",
            "石板路",
            "河水倒影",
            "乌篷船"
        ],
        "sd_hint": "night, ancient water town street, glowing red paper lanterns hanging from eaves, reflections dancing on canal water, quiet historical charm"
    },
    {
        "id": "n_008",
        "category": "自然风景",
        "theme": "溪流边闪烁的萤火虫：循着潺潺流水声走到小树林深处，草丛间浮动起星星点点柔绿色的微光，像误入了神秘梦幻的精灵秘境",
        "elements": [
            "小溪流",
            "萤火虫",
            "绿色微光",
            "神秘树林",
            "梦幻童话"
        ],
        "sd_hint": "night, deep forest creek, surrounded by glowing green fireflies dancing in air, magical ethereal lighting, hand outstretched, wonder eyes"
    },
    {
        "id": "n_009",
        "category": "自然风景",
        "theme": "半山腰俯瞰城市星海：夜间爬到半山腰的观景台，脚下是整座城市纵横交错如金色血管般的车流与霓虹，吹着带露水的冷风",
        "elements": [
            "山腰夜景",
            "城市霓虹",
            "车流金线",
            "晚风吹拂",
            "俯瞰"
        ],
        "sd_hint": "night, mountain overlook, viewing glittering sea of city neon lights below, winding roads like gold ribbons, crisp cool wind blowing hair"
    },
    {
        "id": "n_010",
        "category": "自然风景",
        "theme": "路灯下静谧飘落的初雪：深夜推开门，路灯昏黄的光晕里正无声地旋转飘落着大朵大朵的初雪，全世界好像被按下了静音键",
        "elements": [
            "初雪",
            "昏黄路灯",
            "雪花飘落",
            "万籁俱寂",
            "哈气白雾"
        ],
        "sd_hint": "night, standing under warm yellow street lamp, soft big snowflakes falling quietly around, breath visible in cold air, scarf and coat"
    },
    {
        "id": "n_011",
        "category": "少女心情",
        "theme": "3%电量在床缝捞充电线：手机电量只剩3%开始疯狂闪红，充电线却滑进了床头和墙壁最深处的夹缝，趴在床板上捞得满头大汗",
        "elements": [
            "3%电量",
            "床缝捞线",
            "急中生智",
            "趴在床板",
            "红电量焦虑"
        ],
        "sd_hint": "night, lying on messy bed reaching arm deep into crevice behind headboard, phone screen glowing red low battery icon, desperate funny cute face"
    },
    {
        "id": "n_012",
        "category": "少女心情",
        "theme": "脱珊瑚绒睡衣的噼啪静电：关上灯准备钻进被窝，脱掉厚睡衣的瞬间整件衣服噼里啪啦冒火花，头发瞬间全部炸成蒲公英，呆在原地不敢动",
        "elements": [
            "静电火花",
            "珊瑚绒睡衣",
            "炸毛蒲公英",
            "噼里啪啦",
            "不敢动弹"
        ],
        "sd_hint": "night, dark bedroom, tiny blue static electricity sparks crackling, hair standing up like dandelion poof, startled wide eyes, cute funny comic"
    },
    {
        "id": "n_013",
        "category": "少女心情",
        "theme": "深夜冰箱寻宝小贼：蹑手蹑脚拉开冰箱门，冷白的光照亮整张脸，在冷藏室角落成功挖出一盒被遗忘的草莓牛奶布丁，快乐得像中了彩票",
        "elements": [
            "深夜冰箱",
            "冷白光",
            "蹑手蹑脚",
            "布丁",
            "寻宝成功"
        ],
        "sd_hint": "night, dark kitchen illuminated only by open refrigerator glow, crouching in front of fridge, holding small pudding jar, mischievous happy smile"
    },
    {
        "id": "n_014",
        "category": "少女心情",
        "theme": "地毯香薰与深度放空：点上喜欢的白茶淡香氛，抱着圆滚滚的大抱枕坐在毛绒地毯上放空发呆，把一整天转个不停的脑子彻底关机",
        "elements": [
            "毛绒地毯",
            "白茶香薰",
            "大抱枕",
            "大脑关机",
            "深度放空"
        ],
        "sd_hint": "night, sitting on plush white rug hugging a huge round cushion, small aroma diffuser with delicate mist, warm floor lamp, peaceful glazed look"
    },
    {
        "id": "n_015",
        "category": "少女心情",
        "theme": "躺着玩手机正中鼻梁：困得眼皮打架还舍不得放下手机，手一滑手机啪叽一声直直砸在鼻梁上，疼得眼泪瞬间飙出来，立刻老实了",
        "elements": [
            "手滑砸脸",
            "砸鼻梁",
            "飙眼泪",
            "困意全无",
            "老实关灯"
        ],
        "sd_hint": "night, lying on back in bed, phone slipping from hands right above face, comical shocked expression, hands in air, soft blanket, dim light"
    },
    {
        "id": "n_016",
        "category": "少女心情",
        "theme": "热腾腾的泡泡浴放空：整个人泡进散发着薰衣草香气的大浴缸里，把绵密的白泡泡堆在头顶做成小厨师帽，满身疲惫像方糖一样融化了",
        "elements": [
            "泡泡浴",
            "薰衣草香",
            "头顶泡沫帽",
            "方糖融化",
            "彻底放松"
        ],
        "sd_hint": "night, luxurious warm bubble bath, foam piled like a little hat on head, damp rosy cheeks, candlelight around tub, blissful relaxed eyes"
    },
    {
        "id": "n_017",
        "category": "少女心情",
        "theme": "把自己卷成严实大煎饼：抓住被子两角像滚轴一样在床上连滚两圈，把自己从头到脚裹得严丝合缝，只露出一双眼睛，安全感直接拉满",
        "elements": [
            "裹成卷",
            "被子煎饼",
            "只露眼睛",
            "连滚两圈",
            "安全感爆棚"
        ],
        "sd_hint": "night, wrapped tightly like a burrito roll in thick duvet, only round eyes and bangs peeking out, cozy bed, warm gentle moonlight"
    },
    {
        "id": "n_018",
        "category": "少女心情",
        "theme": "半夜醒来那一杯甘甜凉水：半夜口渴迷迷糊糊爬起来倒水，一口气咕嘟咕嘟喝下大半杯凉白开，感觉从喉咙一直凉爽通透到脚趾尖",
        "elements": [
            "半夜喝水",
            "咕嘟咕嘟",
            "喉咙甘冽",
            "月光洒地",
            "通透舒畅"
        ],
        "sd_hint": "night, kitchen illuminated by pale moonlight, drinking a large glass of water, messy bed hair, oversized t-shirt, refreshed relieved expression"
    },
    {
        "id": "n_019",
        "category": "少女心情",
        "theme": "翻过枕头找凉快那一面：脑袋枕热了，双手把蓬松的大枕头翻了个面，脸颊贴上去那一瞬间冰凉细腻的触感，简直是入睡前的人间至宝",
        "elements": [
            "枕头翻面",
            "冰凉面",
            "贴脸颊",
            "细腻触感",
            "瞬间安详"
        ],
        "sd_hint": "night, hugging fluffy pillow, pressing cheek lovingly against cool side of pillow, sleepy satisfied smile, soft warm ambient lighting"
    },
    {
        "id": "n_020",
        "category": "少女心情",
        "theme": "被窝打小手电翻漫画：钻进厚被窝里支起一个秘密小帐篷，就着暖黄色的小阅读灯看最喜欢的那本治愈系漫画，谁也别来打扰我的世界",
        "elements": [
            "被窝帐篷",
            "小手电",
            "看漫画",
            "秘密空间",
            "治愈时光"
        ],
        "sd_hint": "night, under blanket fortress, small flashlight illuminating pages of a manga book, focused cute eyes, knees tucked, safe cozy sanctuary"
    },
    {
        "id": "n_021",
        "category": "城市晚间",
        "theme": "深夜便利店关东煮热汤：推开玻璃门叮咚一响，站在咕嘟冒泡的关东煮格子前，咬一口吸饱了热高汤的白萝卜，暖流顺着胃部散开",
        "elements": [
            "便利店",
            "关东煮",
            "白萝卜热汤",
            "叮咚门铃",
            "深夜暖胃"
        ],
        "sd_hint": "late night, 24h convenience store counter, steaming oden compartment, holding paper cup with skewer, warm illuminated shop window, cold night outside"
    },
    {
        "id": "n_022",
        "category": "城市晚间",
        "theme": "末班公交后排靠窗发呆：坐在空荡荡的末班车最后一排，额头轻轻抵着微震的车窗，看街边璀璨的霓虹光晕被车窗拉成绚丽的光斑",
        "elements": [
            "末班公交",
            "后排靠窗",
            "霓虹光斑",
            "微震车窗",
            "疲惫与宁静"
        ],
        "sd_hint": "night, back seat of nearly empty night bus, leaning head against window glass, city bokeh blur lights outside, earphones in, melancholic peaceful face"
    },
    {
        "id": "n_023",
        "category": "城市晚间",
        "theme": "夜间散步与心动单曲循环：塞着降噪耳机走在安静无人的林荫小路上，晚风把树叶吹得沙沙作响，踩着路灯投下的自己的影子往前跳",
        "elements": [
            "夜间散步",
            "踩影子",
            "降噪耳机",
            "沙沙树叶",
            "独处自在"
        ],
        "sd_hint": "night, quiet suburban street under street lamps, walking while stepping on cast shadows, oversized hoodie, over-ear headphones, playful relaxed walk"
    },
    {
        "id": "n_024",
        "category": "城市晚间",
        "theme": "夜市街角那碗热腾腾的炒粉：大排档铁锅翻炒激起浓烈锅气，热腾腾的鸡蛋豆芽炒粉盛在盘子里，坐在塑料红椅子上大口吃得格外满足",
        "elements": [
            "夜市",
            "铁锅炒粉",
            "大排档锅气",
            "红塑料凳",
            "热气腾腾"
        ],
        "sd_hint": "night, lively night food market, eating hot stir-fried noodles at street stall, vapor rising, red plastic stool, joyful foodie expression"
    },
    {
        "id": "n_025",
        "category": "城市晚间",
        "theme": "深夜超市临期打折抢购：九点半准时守在生鲜区，眼看着阿姨啪啪给豪华刺身和现烤面包贴上五折黄色大标签，抢到了最后一盒寿司",
        "elements": [
            "超市晚间",
            "五折标签",
            "抢打折",
            "最后一盒寿司",
            "战利品"
        ],
        "sd_hint": "night, supermarket aisle, holding a box of discounted sushi with big yellow 50% off sticker, triumphant playful grin, shopping basket on arm"
    },
    {
        "id": "n_026",
        "category": "城市晚间",
        "theme": "阳台远望深夜车流光轨：捧着杯热牛奶站在阳台上，远处环线高架上的车灯拉出长长一条金色红色的流光，整座城市渐渐沉入梦乡",
        "elements": [
            "阳台看车流",
            "光轨",
            "热牛奶",
            "城市夜景",
            "渐渐沉睡"
        ],
        "sd_hint": "late night, high floor balcony, holding warm mug of milk with both hands, distant highway taillight trails, city falling asleep, gentle tranquil gaze"
    },
    {
        "id": "n_027",
        "category": "城市晚间",
        "theme": "夜跑偶遇老面包房开炉：路过深巷里的老面包作坊，虽然卷闸门紧闭，但排气扇正疯狂往外吹出刚烤好的浓烈奶油麦香，香得迈不开腿",
        "elements": [
            "面包排气扇",
            "深夜麦香",
            "停下脚步",
            "深巷老店",
            "肚子咕咕叫"
        ],
        "sd_hint": "night, cobblestone alleyway outside closed bakery door, sniffing sweet warm baking bread smell drifting from vent, funny tempted cute expression"
    },
    {
        "id": "n_028",
        "category": "安睡仪式",
        "theme": "热腾腾的木桶泡脚发汗：把双脚泡进撒了艾草和生姜的滚烫木桶里，热气从脚底板一路往上窜，后背渗出一层薄薄的微汗，通体舒泰",
        "elements": [
            "木桶泡脚",
            "生姜艾草",
            "后背微汗",
            "通体舒泰",
            "热毛巾"
        ],
        "sd_hint": "night, sitting on stool soaking feet in traditional wooden bucket with rising steam, rosy flushed cheeks, cozy soft towel, supreme relaxation"
    },
    {
        "id": "n_029",
        "category": "安睡仪式",
        "theme": "睡前护肤与拍爽肤水：在脸上厚厚抹一层水润的晚安面霜，双手轻轻啪啪拍打着脸颊让它吸收，镜子里自己的脸蛋像刚剥壳的白煮蛋",
        "elements": [
            "睡前护肤",
            "晚安面霜",
            "啪啪拍脸",
            "水润透亮",
            "镜前发带"
        ],
        "sd_hint": "night, bathroom vanity mirror, wearing plush hairband, gently patting moisturizing face cream onto cheeks, dewy glowing skin, cute pajamas"
    },
    {
        "id": "n_030",
        "category": "安睡仪式",
        "theme": "床上毛绒玩偶大点兵：把床头的大白鹅、小熊和长条猫咪玩偶整整齐齐在枕头边排成一排，每一只都揉揉脑袋互道一句晚安再睡觉",
        "elements": [
            "玩偶点兵",
            "大白鹅",
            "揉揉脑袋",
            "枕头边排列",
            "童心安眠"
        ],
        "sd_hint": "night, bedroom, tucking plush toys (giant goose and teddy bear) in beside pillow under duvet, lovingly patting plush heads, childlike sweetness"
    },
    {
        "id": "n_031",
        "category": "安睡仪式",
        "theme": "定时白噪音雨声催眠：在床头音箱放上30分钟定时的森林细雨白噪音，听着雨滴落在落叶上的沉闷沙沙声，眼皮像灌了铅一样合上",
        "elements": [
            "白噪音",
            "森林雨声",
            "定时关闭",
            "眼皮打架",
            "极速入眠"
        ],
        "sd_hint": "night, lying on side in dark cozy bedroom, small bedside speaker emitting faint blue light, closed eyes sinking deep into pillow, deeply asleep"
    },
    {
        "id": "n_032",
        "category": "安睡仪式",
        "theme": "暖胃洋甘菊金黄蜂蜜水：泡一杯温热澄澈的洋甘菊茶，调入一小勺浓稠的金黄椴树蜜，慢慢抿完最后一口，肚子里暖洋洋的踏实感",
        "elements": [
            "洋甘菊茶",
            "蜂蜜",
            "暖胃",
            "金色茶汤",
            "睡前踏实"
        ],
        "sd_hint": "night, sitting on edge of bed holding warm porcelain teacup with golden chamomile tea, honey spoon, steam curling up, soft golden lamp light"
    },
    {
        "id": "n_033",
        "category": "安睡仪式",
        "theme": "熄灭床头最后一盏烛火：用金色灭烛罩轻轻盖在散发着琥珀木质香的蜡烛上，看着细细一缕青烟升起散去，房间彻底归于温软的黑暗",
        "elements": [
            "灭烛罩",
            "木质香蜡烛",
            "一缕青烟",
            "黑暗降临",
            "安心入睡"
        ],
        "sd_hint": "night, bedside table, gently snuffing out scented candle with brass snuffer, delicate curl of smoke rising, warm shadow and moonlight mixture"
    },
    {
        "id": "n_034",
        "category": "安睡仪式",
        "theme": "陷进巨大蓬松软枕里：整张脸轻轻埋进散发着阳光晒过味道的洁白羽绒枕里，深吸一口气慢慢吐出来，今天的所有事情就到此为止啦",
        "elements": [
            "深陷软枕",
            "羽绒枕",
            "阳光晒过味",
            "深呼一口气",
            "到此为止"
        ],
        "sd_hint": "night, sinking face side into massive ultra-soft white fluffy down pillow, closed eyes with long eyelashes, serene peaceful expression, sleep"
    },
    {
        "id": "n_035",
        "category": "自然风景",
        "theme": "港口防波堤与引航灯：海浪轻轻拍打着防波堤的水泥石块，远处的红色引航灯塔一闪一灭，深蓝色的海水里倒映着碎金般波光",
        "elements": [
            "防波堤",
            "引航灯塔",
            "深蓝海水",
            "海浪拍岸",
            "独坐听海"
        ],
        "sd_hint": "night, coastal harbor breakwater, red lighthouse beacon flashing in distance, dark blue ocean reflections, sitting watching waves"
    },
    {
        "id": "n_036",
        "category": "城市晚间",
        "theme": "美术馆奇妙夜延时闭馆：赶在九点闭馆前静静站在最喜欢的那幅莫奈睡莲前，展厅里几乎没有人，柔和的射灯把画布照得格外静谧",
        "elements": [
            "美术馆",
            "睡莲画作",
            "柔和射灯",
            "无人展厅",
            "艺术沉浸"
        ],
        "sd_hint": "night, quiet art museum gallery, standing in front of large impressionist painting, soft spotlight, casual elegant dress, serene wonder"
    },
    {
        "id": "n_037",
        "category": "自然风景",
        "theme": "天台折射望远镜看月亮环形山：在顶楼架起简易小天文望远镜，目镜里月球表面的陨石坑和环形山清晰得触手可及，震撼得屏住呼吸",
        "elements": [
            "天文望远镜",
            "月亮环形山",
            "天台夜空",
            "目镜",
            "屏住呼吸"
        ],
        "sd_hint": "night, rooftop, looking through small astronomical telescope pointing at glowing crescent moon, sparkling stars, joyful surprised look"
    },
    {
        "id": "n_038",
        "category": "安睡仪式",
        "theme": "黑胶唱机放慢摇爵士：把唱针轻轻落在旋转的复古黑胶唱片上，沙沙的底噪伴随着低沉温柔的萨克斯风流淌出来，整个房间变暖了",
        "elements": [
            "黑胶唱机",
            "萨克斯爵士",
            "沙沙底噪",
            "唱针",
            "复古氛围"
        ],
        "sd_hint": "night, wooden turntable spinning vinyl record, arm needle placed on disc, warm dim amber lighting, relaxed posture on armchair"
    },
    {
        "id": "n_039",
        "category": "少女心情",
        "theme": "深夜视察阳台肉嘟嘟多肉：打着手机手电筒检查阳台上的桃蛋和小玉，被夜露滋润过多肉叶片圆滚滚泛着粉霜，像一盒彩色软糖",
        "elements": [
            "阳台多肉",
            "手机手电",
            "夜露",
            "粉霜软糖",
            "偷看植物"
        ],
        "sd_hint": "night, balcony, illuminating small succulent potted plants with phone flashlight, smiling softly, oversized fluffy pajama sweater"
    },
    {
        "id": "n_040",
        "category": "少女心情",
        "theme": "睡前无意识铅笔涂鸦：铅笔在粗糙的速写本上沙沙划过，画了长耳朵的小兔子、咬了一口的草莓蛋糕和歪歪扭扭的星星，困意悄悄蔓延",
        "elements": [
            "速写本",
            "铅笔沙沙声",
            "随笔涂鸦",
            "困意蔓延",
            "乱涂乱画"
        ],
        "sd_hint": "night, leaning on desk sketching cute rabbit and stars on paper notebook with pencil, cozy lamp light, yawning slightly, sleepy eyes"
    },
    {
        "id": "n_041",
        "category": "美食治愈",
        "theme": "小砂锅炖冰糖雪梨汤：砂锅里慢火炖着剔透的银耳雪梨，加了两颗红枣和一小把枸杞，汤汁滑糯清润，喝下去整副嗓子都舒服了",
        "elements": [
            "冰糖雪梨",
            "小砂锅",
            "清润滑糯",
            "红枣枸杞",
            "深夜暖喉"
        ],
        "sd_hint": "night, small ceramic pot of steaming poached pear dessert soup, ceramic spoon, taking a careful warm sip, relieved sweet face"
    },
    {
        "id": "n_042",
        "category": "安睡仪式",
        "theme": "看大豆蜡烛融成透明小池塘：盯着香氛蜡烛芯周围慢慢融化成一汪金黄透明的蜡油池，雪松与微甜香草的气息静静弥漫，心跳彻底平缓",
        "elements": [
            "香氛蜡烛",
            "融化蜡油",
            "雪松香草",
            "火苗跳跃",
            "平息杂念"
        ],
        "sd_hint": "night, staring gently at flickering flame of scented candle melting into wax pool, delicate shadows on wall, serene zen expression"
    },
    {
        "id": "n_043",
        "category": "自然风景",
        "theme": "檐下玻璃风铃叮咚清响：夜风吹起窗帘的一角，挂在屋檐下的透明水滴风铃发出叮铃叮铃的清脆碰撞声，把白天的燥热全吹散了",
        "elements": [
            "玻璃风铃",
            "叮咚清脆",
            "屋檐夜风",
            "飘动窗帘",
            "清凉舒畅"
        ],
        "sd_hint": "night, bedroom window open with billowing sheer curtain, delicate glass wind chime chiming outside under moonlight, peaceful smile"
    },
    {
        "id": "n_044",
        "category": "少女心情",
        "theme": "一千块拼图卡在最后一块：地毯上铺了一千块的梵高星空拼图，眼睛都看花了终于把右下角那块拼上，整副画完整了，心满意足滚去睡",
        "elements": [
            "拼图",
            "最后一小块",
            "大功告成",
            "星空图案",
            "滚去睡觉"
        ],
        "sd_hint": "night, sitting on floor over large 1000-piece puzzle, pressing the final piece in place with two fingers, triumphant relieved grin"
    },
    {
        "id": "n_045",
        "category": "安睡仪式",
        "theme": "戴上真丝遮光眼罩深睡：戴上冰冰凉凉软滑的粉色真丝眼罩，把外界最后一丝光线隔绝开，抱紧长条形小恐龙抱枕，今晚一定会做好梦",
        "elements": [
            "真丝眼罩",
            "彻底黑暗",
            "恐龙抱枕",
            "无梦深睡",
            "晚安世界"
        ],
        "sd_hint": "night, lying comfortably on pillow pulling down soft silk sleep mask over eyes, hugging plush pillow, serene peaceful sleep face"
    },
    {
        "id": "n_046",
        "category": "安睡仪式",
        "theme": "单曲循环一首钢琴纯音乐：把手机放在床头柜上调成飞行模式，空气里只有轻缓空灵的钢琴独奏声，像月光一样无声抚平了所有烦恼",
        "elements": [
            "飞行模式",
            "钢琴独奏",
            "空灵治愈",
            "抚平杂念",
            "渐入梦乡"
        ],
        "sd_hint": "night, cozy bed, smartphone charging on nightstand, soft moonlight illuminating face, tranquil gentle breath, sinking into mattress"
    },
    {
        "id": "n_047",
        "category": "自然风景",
        "theme": "夏夜田埂边的第一只流萤：走过安静的田埂小路，草丛里忽明忽暗飘起两三点微弱的荧绿光芒，像地上碎掉的星星在跳舞",
        "elements": [
            "萤火虫",
            "田埂小路",
            "微弱荧光",
            "夜风轻拂",
            "夏夜静谧"
        ],
        "sd_hint": "night, countryside path near grass, holding cupped hands around glowing green firefly, soft bioluminescence illuminating face, awe expression"
    },
    {
        "id": "n_048",
        "category": "自然风景",
        "theme": "山间小木屋的夜雨打芭蕉：山间夜雨淅淅沥沥敲打着木屋窗檐和宽大的芭蕉叶，壁炉里柴火噼啪作响，裹着粗线毛毯听雨声发呆",
        "elements": [
            "山间木屋",
            "夜雨淅沥",
            "芭蕉叶声",
            "壁炉柴火",
            "粗线毛毯"
        ],
        "sd_hint": "night, cozy wooden mountain cabin interior, rain streaming down windowpane, warm glowing fireplace behind, wrapped in knitted blanket, holding warm mug"
    },
    {
        "id": "n_049",
        "category": "自然风景",
        "theme": "踩上海浪泛光的荧光海滩：赤脚走在微凉的退潮湿沙滩上，每踩一步脚底都泛开一圈浅蓝色的荧光浪花，像走在银河倒影里",
        "elements": [
            "荧光海滩",
            "蓝色荧光浪花",
            "赤脚踩沙",
            "夜空繁星",
            "微凉海风"
        ],
        "sd_hint": "night, barefoot walking on ocean beach edge, glowing blue bioluminescent waves washing over feet, dark starry sky above, magical ethereal atmosphere"
    },
    {
        "id": "n_050",
        "category": "自然风景",
        "theme": "松林吊床仰望银河拱桥：系在两棵大松树之间的吊床轻轻晃荡，透过层层叠叠的针叶缝隙，一条横跨天际的银河白茫茫地铺展在眼前",
        "elements": [
            "松林吊床",
            "银河拱桥",
            "轻轻摇晃",
            "夜空璀璨",
            "防风外套"
        ],
        "sd_hint": "night, lying in outdoor hammock suspended between pine trees, looking up at Milky Way star arch through needle branches, warm sleeping bag, wonder expression"
    },
    {
        "id": "n_051",
        "category": "自然风景",
        "theme": "湖心小筑倒映的冷白圆月：满月高悬，湖面平整得没有一丝波纹，一轮皎洁清冷的白月倒映在湖心，像一块浮在水面的羊脂白玉",
        "elements": [
            "静水湖月",
            "皎洁圆月",
            "羊脂白玉倒影",
            "湖畔栏杆",
            "夜风微寒"
        ],
        "sd_hint": "night, standing on wooden lake dock, perfect reflection of full moon in glassy still water, cool blue night palette, ethereal aesthetic"
    },
    {
        "id": "n_052",
        "category": "自然风景",
        "theme": "天台围栏吹散一天的疲惫：坐在天台栏杆边，初秋夜晚微凉的风穿透衣服把一整天的闷热和疲倦全部吹散，脚下是整座城市流淌的车灯长河",
        "elements": [
            "天台围栏",
            "初秋凉风",
            "车流长河",
            "吹散疲惫",
            "夜景远眺"
        ],
        "sd_hint": "night, sitting on edge of high rooftop, hair blown wildly by cool night wind, looking down at blurry golden river of city traffic lights, relaxed smile"
    },
    {
        "id": "n_053",
        "category": "自然风景",
        "theme": "橘黄路灯下的静默落雪：深夜窗外的昏黄路灯光圈里，大朵大朵蓬松的鹅毛雪无声无息地往下坠落，落在树枝上积出厚厚的棉花糖",
        "elements": [
            "深夜路灯",
            "光圈落雪",
            "鹅毛大雪",
            "无声静谧",
            "树枝积雪"
        ],
        "sd_hint": "night, looking through window at streetlamp beam illuminating thick falling snowflakes against dark street, cozy warm indoor lighting, holding tea"
    },
    {
        "id": "n_054",
        "category": "自然风景",
        "theme": "夜风把落叶卷在路灯下盘旋成小漩涡：深夜站在小区楼下，微凉的晚风把地上的枯黄落叶吹得呼啦啦打转，在橘黄色的路灯光柱下像金色的蝴蝶在跳华尔兹",
        "elements": [
            "夜风落叶",
            "路灯光柱",
            "金色小漩涡",
            "秋意渐浓",
            "华尔兹起舞"
        ],
        "sd_hint": "night, residential street under warm amber streetlamp, swirling golden autumn leaves dancing in breeze around feet, long woolen coat, peaceful face"
    },
    {
        "id": "n_055",
        "category": "自然风景",
        "theme": "把车停在半山腰躺在引擎盖上看满天繁星：远离城市霓虹的半山公路边，躺在尚有余温的引擎盖上裹着厚毯子，满天密密麻麻的银白星斗仿佛触手可及",
        "elements": [
            "半山公路",
            "引擎盖看星",
            "满天繁星",
            "尚存余温",
            "远离霓虹"
        ],
        "sd_hint": "night, lying on hood of vintage car parked on mountain overlook, wrapped in heavy blanket gazing up at dense starry galaxy, vast dark sky, awe expression"
    },
    {
        "id": "n_056",
        "category": "自然风景",
        "theme": "阳台夜开茉莉随风送来第一缕甜香：推开阳台推拉门吹夜风，种在角落的白茉莉竟然悄无声息绽开了几瓣小花，微凉夜风一吹，清雅极了的甜香幽幽钻进鼻尖",
        "elements": [
            "夜开茉莉",
            "阳台推拉门",
            "幽幽甜香",
            "微凉夜风",
            "植物惊喜"
        ],
        "sd_hint": "night, apartment balcony, leaning close to delicate white jasmine blossoms in ceramic pot, inhaling sweet floral aroma, gentle breeze lifting hair"
    },
    {
        "id": "n_057",
        "category": "自然风景",
        "theme": "深夜极远处传来的货运火车悠长汽笛：万籁俱寂的深夜，极遥远的地平线方向传来一声悠长浑厚的火车呜呜声，像在替整个沉睡的平原守夜",
        "elements": [
            "远方火车汽笛",
            "万籁俱寂",
            "平原守夜",
            "黑夜深邃",
            "遥远回声"
        ],
        "sd_hint": "night, standing by window looking out over dark distant horizon, thin curtain drawn, listening intently to distant sound, contemplative gentle eyes"
    },
    {
        "id": "n_058",
        "category": "自然风景",
        "theme": "白月光在木地板上打出工整的窗格阴影：拉开薄纱窗帘，皎洁的冷白月光斜照进来，在浅色木地板上拓印出一个极其清晰修长的窗格子，像是一幅天然的几何地毯",
        "elements": [
            "冷白月光",
            "几何窗格阴影",
            "浅色木地板",
            "薄纱窗帘",
            "天地静谧"
        ],
        "sd_hint": "night, bedroom floor bathed in bright silver moonlight casting stark grid shadows of window frame, barefoot standing in moonbeam, dreamy ethereal tone"
    },
    {
        "id": "n_059",
        "category": "自然风景",
        "theme": "深夜微风把白色纱帘吹得像水波荡漾：窗户留了一条极小的缝隙，清凉夜风溜进来把轻薄的白纱帘吹得如梦似幻地起伏翻涌，月光在地面泛起水纹般的光斑",
        "elements": [
            "白纱帘起伏",
            "水波光斑",
            "窗缝微风",
            "如梦似幻",
            "初夏夜凉"
        ],
        "sd_hint": "night, breezy bedroom, sheer white curtains billowing gently in cool night air, moonlight patterns moving on floorboards, serene ethereal mood"
    },
    {
        "id": "n_060",
        "category": "城市晚间",
        "theme": "深夜居酒屋角落的一碗热拉面：掀开暖帘钻进暖烘烘的狭小居酒屋，柜台端上一碗咕嘟咕嘟冒热气的豚骨拉面，吸溜一口浓汤从喉咙暖到胃底",
        "elements": [
            "深夜居酒屋",
            "掀开暖帘",
            "豚骨拉面",
            "吸溜热汤",
            "治愈胃袋"
        ],
        "sd_hint": "night, small cozy ramen counter under warm paper lanterns, steam rising from ceramic noodle bowl, holding chopsticks, blissful flushed cheeks"
    },
    {
        "id": "n_061",
        "category": "城市晚间",
        "theme": "末班公交车最后一排靠窗：末班车里只有稀稀拉拉两三个乘客，脑门靠着微颤发凉的车窗玻璃，耳机里放着慢歌，看着流动的霓虹灯光晕被拉成彩带",
        "elements": [
            "末班公交",
            "最后一排",
            "额头靠窗",
            "霓虹光晕",
            "耳机慢歌"
        ],
        "sd_hint": "night, sitting in back row of empty night bus, head resting against cool window glass, city lights streaking outside in colorful bokeh, earphones in"
    },
    {
        "id": "n_062",
        "category": "城市晚间",
        "theme": "便利店蒸包机里挑关东煮：叮咚声推开深夜亮堂的便利店，站在滚水咕嘟的关东煮格子前挑了两串吸饱汤汁的福袋和萝卜，捧在手心里冒着白汽",
        "elements": [
            "便利店叮咚",
            "关东煮热气",
            "爆汁福袋",
            "白汽暖手",
            "深夜慰藉"
        ],
        "sd_hint": "night, standing inside brightly lit convenience store, looking at steaming oden pot with tongs, holding paper cup of hot food, happy midnight comfort"
    },
    {
        "id": "n_063",
        "category": "城市晚间",
        "theme": "深夜自助洗衣店的轰鸣与暖风：坐在洗衣店塑料椅上晃着腿，滚筒洗衣机在眼前一圈圈旋转发出规律的嗡鸣，出风口飘出烘干衣物甜暖的柔顺剂香味",
        "elements": [
            "自助洗衣店",
            "滚筒旋转",
            "柔顺剂暖风",
            "晃腿发呆",
            "规律嗡鸣"
        ],
        "sd_hint": "night, laundromat interior, sitting on plastic chair watching dryer drum tumble warmly, laundry basket beside, reading manga, soft ambient lighting"
    },
    {
        "id": "n_064",
        "category": "城市晚间",
        "theme": "走出地铁口迎面的空旷夜风：刷卡走出空荡荡的地下通道，刚迈上台阶就被夜里清冽的空气迎面抱了个满怀，抬头看见几颗很亮的星星正挂在头顶",
        "elements": [
            "地铁出口",
            "空旷街道",
            "清冽夜风",
            "抬头见星",
            "归途轻松"
        ],
        "sd_hint": "night, walking up concrete steps of quiet subway exit onto empty street, looking up at night sky, coat swaying, feeling weight lifted off shoulders"
    },
    {
        "id": "n_065",
        "category": "城市晚间",
        "theme": "深夜在便利店冷柜前挑新出的乳酸菌气泡水：深夜的小超市静悄悄的，只有冷柜低沉的制冷声，在一排排整齐的饮料里挑出一罐冰凉的白桃气泡水，贴在脸颊上冰冰凉",
        "elements": [
            "便利店冷柜",
            "制冷嗡鸣",
            "白桃气泡水",
            "贴脸冰凉",
            "深夜漫步"
        ],
        "sd_hint": "night, convenience store refrigerated section, holding cold aluminum drink can against cheek, blue lighting, relaxed cute expression"
    },
    {
        "id": "n_066",
        "category": "少女心情",
        "theme": "在热牛奶里丢进一颗慢慢化掉的棉花糖：睡前热了一杯厚牛奶，丢进一颗白色大棉花糖，看着它像小冰山一样在热气里慢吞吞软化塌陷，抿一口甜到心尖",
        "elements": [
            "热牛奶",
            "融化棉花糖",
            "陶瓷大马克杯",
            "抿一口甜香",
            "睡前仪式"
        ],
        "sd_hint": "night, kitchen table, dropping a white marshmallow into steaming ceramic mug of hot milk, watching it melt, cute smile, oversized knit sweater"
    },
    {
        "id": "n_067",
        "category": "少女心情",
        "theme": "翻看旧相册被小时候的自己蠢笑：整理书架翻出了厚厚的塑料旧相册，看见自己扎着歪斜冲天辫还缺了颗门牙傻笑的照片，坐在地毯上笑得前仰后合",
        "elements": [
            "旧相册翻看",
            "冲天辫缺牙",
            "蠢照大笑",
            "地毯盘腿",
            "怀旧温暖"
        ],
        "sd_hint": "night, sitting cross-legged on carpet surrounded by open photo albums, pointing at childhood photo and laughing wholeheartedly, floor lamp glowing"
    },
    {
        "id": "n_068",
        "category": "少女心情",
        "theme": "吹风机嗡嗡的热风裹住耳朵：洗完澡把吹风机开到暖风档，热风穿过发丝把潮湿的头发吹得蓬松轻盈，整个脑袋被烘得热热的，困意像潮水一样涌上来",
        "elements": [
            "吹风机暖风",
            "蓬松发丝",
            "脑袋暖烘烘",
            "困意涌上",
            "洗完澡放松"
        ],
        "sd_hint": "night, bedroom vanity mirror, holding hairdryer blowing through fluffy damp hair, steam drifting, eyes half-closed in cozy drowsy comfort"
    },
    {
        "id": "n_069",
        "category": "少女心情",
        "theme": "用彩色铅笔涂鸦今天的笨拙心事：台灯下掏出十二色彩色铅笔，在手账本空白处歪歪扭扭画了一只吃撑翻肚皮的小仓鼠，把今天的全部不开心都画成了笑脸",
        "elements": [
            "十二色铅笔",
            "手账涂鸦",
            "翻肚皮仓鼠",
            "画走不开心",
            "台灯小光圈"
        ],
        "sd_hint": "night, desk with desk lamp, coloring cute round hamster cartoon with colored pencils in sketchbook, resting chin on hand, peaceful soft smile"
    },
    {
        "id": "n_070",
        "category": "少女心情",
        "theme": "给掉在床边的大兔子玩偶盖好被角：睡前发现陪了自己好几年的大白兔玩偶掉在床缝里，把它抱起来拍拍灰尘塞进枕头边，像模像样地也给它拉上被角",
        "elements": [
            "兔子玩偶",
            "拍拍灰尘",
            "拉上被角",
            "床头同伴",
            "孩子气温柔"
        ],
        "sd_hint": "night, tucking a large plush rabbit doll under duvet beside pillow on bed, gentle affectionate expression, soft bedside lamp, pajama"
    },
    {
        "id": "n_071",
        "category": "少女心情",
        "theme": "敷上一片冰冰凉凉的补水面膜：刚从冰箱拿出来的面膜纸啪的一下贴在脸上，冰得整个人倒吸一口凉气，躺平闭眼听白噪音感觉毛孔都在大口喝水",
        "elements": [
            "冰凉面膜",
            "倒吸凉气",
            "听白噪音",
            "毛孔喝水",
            "睡前护肤"
        ],
        "sd_hint": "night, lying flat on pillow wearing a white hydrating sheet mask, earphones on, hands folded on stomach, completely relaxed facial tension"
    },
    {
        "id": "n_072",
        "category": "少女心情",
        "theme": "熄灭香薰蜡烛那一缕白烟：用灭烛罩轻轻盖住跳动的烛芯，看着细细一缕带香味的淡白烟丝在空气中打了个卷散开，整间屋子只剩下月光和甜木香",
        "elements": [
            "熄灭蜡烛",
            "袅袅白烟",
            "灭烛罩",
            "甜木香气",
            "月光倾洒"
        ],
        "sd_hint": "night, using metal candle snuffer to extinguish scented candle, thin white smoke wisp swirling up, soft moonbeam through window, serene atmosphere"
    },
    {
        "id": "n_073",
        "category": "少女心情",
        "theme": "下定决心把手机丢到摸不到的远方：把手机插上充电线，狠狠心塞进三米外的书桌抽屉里，钻回床铺的那一刻终于觉得自己真正属于这个安静的夜晚了",
        "elements": [
            "手机放远",
            "塞进抽屉",
            "断网安宁",
            "属于夜晚",
            "一身轻松"
        ],
        "sd_hint": "night, standing by desk plugging phone into charger, smiling with calm relief, turning toward cozy bed in dim room, carefree mood"
    },
    {
        "id": "n_074",
        "category": "少女心情",
        "theme": "书桌小台灯在墙上投射出暖融融的大圆影：关掉屋顶大灯，只留桌角那一盏复古绿罩台灯，墙壁上投出一大片暖烘烘的椭圆光晕，趴在手臂上看着光晕发呆",
        "elements": [
            "复古绿罩台灯",
            "墙上暖光晕",
            "趴在桌上发呆",
            "安静深夜",
            "思绪放空"
        ],
        "sd_hint": "night, study desk, green banker lamp glowing warmly against dark wall, resting cheek on crossed arms on desk, gazing peacefully into soft light"
    },
    {
        "id": "n_075",
        "category": "少女心情",
        "theme": "睡前把烘干的毛巾叠成一排小豆腐块：刚从烘干机拿出来的白色大浴巾软得像棉花糖，还带着暖热的温度，一块块整整齐齐码在浴室架上，心里特别踏实",
        "elements": [
            "烘干浴巾",
            "软如棉花糖",
            "小豆腐块",
            "心里踏实",
            "睡前整理"
        ],
        "sd_hint": "night, bathroom shelf, neatly stacking fluffy folded pastel towels, smiling with quiet domestic satisfaction, soft warm indoor glow"
    },
    {
        "id": "n_076",
        "category": "少女心情",
        "theme": "深夜坐在地毯上轻轻拨弄吉他空弦：抱起旧木吉他，甚至没有按和弦，只是用指腹极轻极轻地自上而下扫过六根琴弦，低沉共鸣在木地板上回荡，像一句温柔晚安",
        "elements": [
            "木吉他空弦",
            "指腹轻扫",
            "琴箱共鸣",
            "地毯盘腿",
            "无言晚安"
        ],
        "sd_hint": "night, sitting cross-legged on carpet holding acoustic guitar, fingertips gently touching strings, fairy lights strung along wall, dreamy expression"
    },
    {
        "id": "n_077",
        "category": "少女心情",
        "theme": "在速写本上用软炭笔画下熟睡猫咪的大屁股：猫咪在沙发扶手上睡得像个毛茸茸的羊角包，拿软炭笔两分钟快速勾勒出那团圆滚滚的轮廓，画完忍不住摸了一把尾巴尖",
        "elements": [
            "速写本炭笔",
            "毛茸茸羊角包",
            "勾勒轮廓",
            "偷摸尾巴尖",
            "夜间手作"
        ],
        "sd_hint": "night, living room, sketching sleeping curled up cat on sofa in spiral sketchbook with soft pencil, playful fond smile"
    },
    {
        "id": "n_078",
        "category": "少女心情",
        "theme": "踩着毛茸茸兔耳拖鞋在走廊无声滑行：刚洗完脚套上厚厚的兔耳棉拖鞋，在地板上像滑冰一样无声哧溜溜滑进卧室，自己被自己的幼稚举动逗得在黑暗里捂嘴偷笑",
        "elements": [
            "兔耳棉拖鞋",
            "地板滑冰",
            "哧溜溜滑行",
            "捂嘴偷笑",
            "幼稚小快乐"
        ],
        "sd_hint": "night, dark hallway with bedroom doorway emitting golden light, sliding along polished floor in fluffy bunny slippers, covering mouth laughing quietly"
    },
    {
        "id": "n_079",
        "category": "少女心情",
        "theme": "从铁皮盒里抽出一张旧旅行明信片：床头铁盒里收着去年在海边寄给自己的明信片，字迹虽然有点褪色，但上面写着的'要一直快乐'突然狠狠击中了心房",
        "elements": [
            "铁皮收纳盒",
            "旧明信片",
            "褪色字迹",
            "要一直快乐",
            "心头一暖"
        ],
        "sd_hint": "night, propped in bed holding an illustrated vintage postcard with stamps, gentle reflective smile, bedside lamp illuminating card"
    },
    {
        "id": "n_080",
        "category": "少女心情",
        "theme": "在雪松木质香薰烛光下翻看漫画书：点燃带着清冷雪松和琥珀香气的木芯蜡烛，烛火发出轻微噼啪声，整个人窝在地毯大靠枕里津津有味翻看新一期热血漫画",
        "elements": [
            "雪松香薰烛",
            "木芯噼啪",
            "地毯大靠枕",
            "热血漫画",
            "沉浸小世界"
        ],
        "sd_hint": "night, curled up against large floor pillow reading colorful manga volume, scented candle flickering on wooden floor beside, soft shadows, cozy relaxed aura"
    },
    {
        "id": "n_081",
        "category": "少女心情",
        "theme": "在便签纸上写下明天要吃的三样美食：睡前不在手账里写严肃待办，而是笑嘻嘻写下明天要去吃蛋挞、喝奶茶、买焦糖泡芙，光是写完就对明天充满期待",
        "elements": [
            "便签美食心愿",
            "蛋挞与泡芙",
            "笑嘻嘻涂鸦",
            "期待明天",
            "毫无负担"
        ],
        "sd_hint": "night, bedside table, writing in small pastel notepad with colored pen, playful mischievous smile, night lamp glowing warmly, cozy bed ready"
    },
    {
        "id": "n_082",
        "category": "深夜治愈",
        "theme": "深夜阳台捧一杯热柠檬红茶：披着厚披肩站在阳台上，呼出的白气和红茶升腾的热汽融在一起，看着街道最后一班清扫车慢吞吞开过，世界彻底安静下来",
        "elements": [
            "热柠檬红茶",
            "厚披肩",
            "升腾热汽",
            "清扫车",
            "深夜阳台"
        ],
        "sd_hint": "night, apartment balcony, wrapped in cozy wool shawl, holding ceramic mug with slice of lemon floating in steaming dark tea, quiet street below"
    },
    {
        "id": "n_083",
        "category": "深夜治愈",
        "theme": "深夜烤箱里慢慢膨胀的黄油曲奇：睡不着索性去厨房揉面烤了一盘曲奇，坐在烤箱前看着小面团一点点变焦黄，满屋子都是浓郁得让人流口水的香草黄油香",
        "elements": [
            "深夜烤曲奇",
            "烤箱橙光",
            "面团膨胀",
            "香草黄油香",
            "睡不着疗愈"
        ],
        "sd_hint": "night, sitting on kitchen floor watching cookies bake inside glowing oven window, mouthwatering aroma, pajamas, cozy contented expression"
    },
    {
        "id": "n_084",
        "category": "深夜治愈",
        "theme": "深夜小锅慢煮的香浓甜玉米浓汤：小奶锅里咕嘟咕嘟熬着玉米浓汤，撒上一小撮黑胡椒和烤得焦香的面包丁，端在手心里每一口都暖到了心窝里",
        "elements": [
            "玉米浓汤",
            "焦香面包丁",
            "小奶锅咕嘟",
            "暖到心窝",
            "黑胡椒颗粒"
        ],
        "sd_hint": "night, holding wide ceramic bowl of rich yellow sweet corn chowder topped with croutons, steam rising softly, cozy dark kitchen, blissful contented smile"
    },
    {
        "id": "n_085",
        "category": "深夜治愈",
        "theme": "戴着大耳机听着雨声和微醺Lofi节拍：屋檐下的细雨沙沙作响，耳机里是慵懒微醺的慢摇Lofi爵士钢琴，随着节奏轻轻晃动脚尖，身心完全松弛下来",
        "elements": [
            "Lofi爵士",
            "大耳罩耳机",
            "屋檐细雨",
            "晃动脚尖",
            "完全松弛"
        ],
        "sd_hint": "night, sitting by dark window, wearing retro over-ear headphones, rain streams on glass, tapping foot gently to music, serene sleepy half-smile"
    },
    {
        "id": "n_086",
        "category": "深夜治愈",
        "theme": "在黑暗里掰开一颗多汁小砂糖橘：睡前突然馋了，悄悄在床头摸出一颗砂糖橘，清爽的果皮芳香在被窝周围炸开，一瓣冰凉甜润的果肉瞬间唤醒味蕾",
        "elements": [
            "砂糖橘清香",
            "床头偷吃",
            "果汁清甜",
            "冰凉果肉",
            "夜半小窃喜"
        ],
        "sd_hint": "night, sitting up in dim bed holding peeled small orange segment near mouth, citrus peel on small dish, secretive playful happy grin"
    },
    {
        "id": "n_087",
        "category": "深夜治愈",
        "theme": "一杯淡黄色的洋甘菊助眠茶：透明玻璃杯里泡着两朵小小的干洋甘菊，淡黄茶汤散发着微微的苹果清香，小口啜饮让热流从喉咙缓缓漫至全身",
        "elements": [
            "洋甘菊茶",
            "微苹果香",
            "淡黄茶汤",
            "暖流漫延",
            "睡意渐浓"
        ],
        "sd_hint": "night, holding clear glass cup with floating chamomile blossoms, steam rising in soft lamp light, calm tranquil smile, oversized cardigan"
    },
    {
        "id": "n_088",
        "category": "安睡仪式",
        "theme": "定时三十分钟的温和助眠电台：枕头边放着声音极低沉温柔的人声播客，主播慢吞吞讲着遥远森林的植物学故事，听着听着眼皮就沉得像灌了铅",
        "elements": [
            "助眠播客",
            "植物学故事",
            "定时关闭",
            "眼皮沉重",
            "温柔人声"
        ],
        "sd_hint": "night, lying on side on soft pillow, bedside phone screen dimming with audio waveform, eyes gently drooping, peaceful half-asleep expression"
    },
    {
        "id": "n_089",
        "category": "安睡仪式",
        "theme": "在枕头两角喷上微甜薰衣草喷雾：清爽微甜的草本香气在枕边弥散开来，把被子一直拉到下巴，深吸一口气感觉整个人像飘在一片柔软的薰衣草海面上",
        "elements": [
            "薰衣草喷雾",
            "草本香气",
            "拉到下巴",
            "飘在海面",
            "松弛神经"
        ],
        "sd_hint": "night, holding amber glass mist spray bottle over fluffy white pillow, light floral mist in air, soft twilight bedroom, relaxed peaceful smile"
    },
    {
        "id": "n_090",
        "category": "安睡仪式",
        "theme": "套上一双厚厚毛茸茸的羊毛睡眠袜：把冰凉的脚丫塞进软乎乎像小绵羊肚皮一样的厚袜子里，脚底板瞬间被暖和包裹住，舒服得整个人在床单上滚了一圈",
        "elements": [
            "毛茸茸睡眠袜",
            "小绵羊触感",
            "脚丫回暖",
            "床单打滚",
            "冬天幸福"
        ],
        "sd_hint": "night, sitting on bed pulling fluffy pastel wool sleeping sock onto foot, smiling in childish delight, cozy thick blanket beside"
    },
    {
        "id": "n_091",
        "category": "安睡仪式",
        "theme": "只留一盏暖黄小夜灯翻两页诗集：关掉主灯，整个房间只有床头那一小团橘黄色的暖光，翻开纸页发黄的诗集读两行关于星空和飞鸟的短句，心灵被轻轻抚平",
        "elements": [
            "床头暖灯",
            "纸页发黄诗集",
            "关于星空飞鸟",
            "抚平思绪",
            "宁静夜晚"
        ],
        "sd_hint": "night, propped up in bed with pillows, reading small hardcover poetry book under dim warm bedside lamp, serene reflective gaze"
    },
    {
        "id": "n_092",
        "category": "安睡仪式",
        "theme": "在地毯上做十分钟睡前猫咪伸展：在地毯上四肢着地弓起背部再缓缓拉伸脊柱，听见骨头发出轻微咔哒一声舒展的声音，一整天坐着僵硬的身体完全被解放",
        "elements": [
            "睡前拉伸",
            "猫式伸展",
            "脊柱放松",
            "地毯微汗",
            "卸下一天疲劳"
        ],
        "sd_hint": "night, bedroom floor on soft rug, doing gentle yoga cat pose stretch, eyes closed, calm breathing, dim ambient fairy lights"
    },
    {
        "id": "n_093",
        "category": "安睡仪式",
        "theme": "床头玻璃杯里留半杯温水：倒了一杯微温的白开水放在木床头柜上，留给半夜可能口渴醒来的自己，小小的水杯倒映着夜灯温柔的小光环",
        "elements": [
            "床头温水",
            "木床头柜",
            "夜灯倒影",
            "小小关照",
            "安心入眠"
        ],
        "sd_hint": "night, placing clear glass of water on bedside wooden table next to glowing nightlight, tucking hand into cozy sleeve, tranquil bedroom"
    },
    {
        "id": "n_094",
        "category": "安睡仪式",
        "theme": "被重力深睡毯结结实实抱在怀里：七公斤重的深睡毯压在身上有一种不可思议的安全感，就像被一个巨大的温软怀抱紧紧拥抱住，外界的一切喧嚣都被挡在门外",
        "elements": [
            "重力深睡毯",
            "安全感包裹",
            "温软怀抱",
            "阻隔喧嚣",
            "深度放松"
        ],
        "sd_hint": "night, completely snuggled under thick weighted blanket up to nose, eyes peacefully closed, faint smile, serene dark room with moonlight sliver"
    },
    {
        "id": "n_095",
        "category": "安睡仪式",
        "theme": "伴着窗玻璃极轻极细的雨声闭上眼：夜雨越来越小，只剩下零星几个细小雨滴轻轻叩击着窗框，哒...哒...在最天然的安眠曲里把整个人彻底沉入梦乡",
        "elements": [
            "零星细雨",
            "轻叩窗框",
            "天然安眠曲",
            "沉入梦乡",
            "彻底放松"
        ],
        "sd_hint": "night, close up of peaceful sleeping face against soft white pillow, faint rain droplets visible on dark window behind, gentle dream state"
    },
    {
        "id": "n_096",
        "category": "安睡仪式",
        "theme": "睡前厚厚涂一层甜甜的香草润唇膏：拿起香草味的润唇膏在嘴唇上来回抹了三圈，抿一抿满嘴都是微甜像冰淇淋一样的香气，安心钻进被窝闭上眼",
        "elements": [
            "香草润唇膏",
            "厚涂滋润",
            "冰淇淋甜香",
            "抿嘴安心",
            "入睡准备"
        ],
        "sd_hint": "night, sitting in bed applying lip balm from small tube to lips, soft glow on face, mirror reflection, relaxed cozy bedtime aura"
    },
    {
        "id": "n_097",
        "category": "安睡仪式",
        "theme": "热气蒸腾的柠檬海盐泡澡：在浴缸里撒了一把微黄的柠檬海盐，整个人没入滚烫的热水中，浴室水汽弥漫像云雾温泉，洗去一整天紧绷的肌肉酸痛",
        "elements": [
            "海盐浴缸",
            "柠檬果香",
            "云雾温泉",
            "水汽弥漫",
            "酸痛消融"
        ],
        "sd_hint": "night, bathroom doorway, damp rosy glowing skin after warm bath, white towel wrapped around hair, fresh cozy pajamas, inhaling warm vapor with relaxed smile"
    },
    {
        "id": "n_098",
        "category": "安睡仪式",
        "theme": "把手机切到飞行模式那一瞬的绝对清净：滑动屏幕按下飞机小图标，所有消息提示音全部被关在世界之外，房间里只剩自己均匀平稳的呼吸声",
        "elements": [
            "飞行模式",
            "绝对清净",
            "阻隔消息",
            "平稳呼吸",
            "安心归巢"
        ],
        "sd_hint": "night, turning off bedside lamp, screen showing airplane mode enabled, dimming room into soft blue moonlight, peaceful relaxed expression"
    },
    {
        "id": "n_099",
        "category": "安睡仪式",
        "theme": "钻进被窝前把拖鞋在床头摆得整整齐齐：坐在床沿脱下暖融融的毛毛拖鞋，用脚尖把它们拨弄得并拢对齐，一转身像小泥鳅一样哧溜滑进被窝最深处",
        "elements": [
            "拖鞋并拢对齐",
            "小泥鳅滑进被窝",
            "整整齐齐",
            "床沿脱鞋",
            "温暖陷落"
        ],
        "sd_hint": "night, sliding under plush duvet on soft bed, smiling cutely as face sinks into pillow, neat slippers on floor beside bed"
    },
    {
        "id": "n_100",
        "category": "安睡仪式",
        "theme": "把被角严丝合缝一直拉到下巴：调整了一个最舒服的虾米蜷缩姿势，把蓬松的厚棉被严严实实裹住肩膀和下巴，只露出一双眼睛，长长舒了一口气准备入梦",
        "elements": [
            "大棉被裹严实",
            "只露出一双眼",
            "虾米蜷缩",
            "舒一口气",
            "准备入梦"
        ],
        "sd_hint": "night, cozy bed, thick duvet tucked all the way up to chin, eyes softly fluttering shut, dark tranquil bedroom with faint starlight"
    }
]

DAILY_VTUBER_THEMES = [
    {
        "id": "d_001",
        "category": "提问互动",
        "theme": "奶茶甜度终极大调查：站在奶茶店点单屏前陷入沉思，大家喝奶茶到底是坚定的三分糖党还是全糖邪教？今天需要大家帮我决定！",
        "elements": [
            "奶茶",
            "三分糖",
            "点单纠结",
            "提问大家",
            "甜度党争"
        ],
        "sd_hint": "daytime, standing outside boba tea shop holding menu, thoughtful curious cute face, finger on chin, casual street fashion"
    },
    {
        "id": "d_002",
        "category": "日常小确幸",
        "theme": "买到货架上最后一个开心果面包：冲进面包店时开心果巴布卡只剩最后一个了，和身后走过来的大叔对视一秒光速抢下，今日幸运值超标！",
        "elements": [
            "开心果面包",
            "最后一个",
            "小跑步抢到",
            "幸运值拉满",
            "抱着纸袋笑"
        ],
        "sd_hint": "afternoon, bakery interior, hugging a kraft paper bag with delicious bread, victorious proud beaming smile, sparkling background"
    },
    {
        "id": "d_003",
        "category": "小情绪发散",
        "theme": "不想出门的合法理由：窗外淅淅沥沥下起了小雨，立刻名正言顺把出门计划全部取消，赖在沙发里抱着抱枕刷搞笑视频，快乐就是这么简单",
        "elements": [
            "下雨不出门",
            "取消计划",
            "沙发抱枕",
            "刷搞笑视频",
            "合情合理偷懒"
        ],
        "sd_hint": "daytime, curled up on plush living room sofa, holding smartphone, rain streaming outside window, comfy loungewear, giggling happily"
    },
    {
        "id": "d_004",
        "category": "文具生活",
        "theme": "文具店战利品炫耀时刻：本来只是想进去买根黑色水笔，结果出来时手里多了一整袋亮晶晶的激光贴纸和两卷碎花胶带，文具店有黑洞吧！",
        "elements": [
            "文具店黑洞",
            "买了一大袋",
            "激光贴纸",
            "碎花胶带",
            "本来只买笔"
        ],
        "sd_hint": "afternoon, sitting at desk displaying colorful sticker sheets and decorative washi tapes, proud excited eyes, cute room decor"
    },
    {
        "id": "d_005",
        "category": "抬头看天",
        "theme": "天上飘着一只胖猫咪云：过马路抬头看天空，头顶正上方那团巨大的积雨云长了一对尖尖的耳朵和一条弯弯的尾巴，完全就是一只仰天大睡的胖橘猫！",
        "elements": [
            "猫咪形状云",
            "抬头看天",
            "过马路",
            "指着天上",
            "天马行空"
        ],
        "sd_hint": "afternoon, city street crossing, looking up and pointing at fluffy white cloud shaped like sleeping cat, sunny blue sky, delighted child-like smile"
    },
    {
        "id": "d_006",
        "category": "搞笑翻车",
        "theme": "逞强挑战特辣零食现场翻车：包装上写着微辣我就信了，刚嚼两口直接辣到原地起跳疯狂吸气，到处找牛奶，舌头已经不是自己的了！",
        "elements": [
            "信了微辣",
            "辣到起跳",
            "到处找牛奶",
            "吐舌头扇风",
            "翻车现场"
        ],
        "sd_hint": "afternoon, sitting on floor holding empty milk carton, tongue sticking out slightly with tears in eyes from spicy food, cute comical panic"
    },
    {
        "id": "d_007",
        "category": "提问互动",
        "theme": "周末到底去哪玩：本周进度条终于快见底啦，你们周末都打算干嘛呀？是出门吸氧还是跟我一样在被窝里长蘑菇？交出你们的攻略！",
        "elements": [
            "周五心动",
            "周末计划",
            "长蘑菇",
            "求大家攻略",
            "放假前夕"
        ],
        "sd_hint": "Friday afternoon, desk with calendar marked with stars, leaning forward asking with hands on cheeks, sparkling anticipating eyes"
    },
    {
        "id": "d_008",
        "category": "日常折腾",
        "theme": "突然发作的房间大挪移冲动：不知道为什么，突然看书桌的方向不顺眼，一个人吭哧吭哧把书桌从东墙挪到了西墙，累得瘫倒但房间变全新了！",
        "elements": [
            "房间大挪移",
            "搬动书桌",
            "吭哧吭哧",
            "焕然一新",
            "瘫在地上"
        ],
        "sd_hint": "afternoon, bedroom in slight disarray, sitting on floor leaning back against newly moved desk, wiping forehead, tired but satisfied grin"
    },
    {
        "id": "d_009",
        "category": "慌张小确幸",
        "theme": "跟烈日下融化的甜筒抢速度：刚买的双球冰淇淋在阳光下融化得比我吃的还快，粉色草莓奶油顺着蛋卷往下滴，手忙脚乱狂舔手腕",
        "elements": [
            "双球冰淇淋",
            "融化滴手腕",
            "手忙脚乱",
            "跟太阳抢速度",
            "甜甜蜜蜜"
        ],
        "sd_hint": "sunny day, outdoor park bench, holding double scoop ice cream cone melting fast, hastily licking side of ice cream, funny panicked cute"
    },
    {
        "id": "d_010",
        "category": "日常惊喜",
        "theme": "去年冬装口袋摸出一张纸币：天冷翻出压箱底的厚外套套上，手插进口袋居然摸到了一张叠得整整齐齐的二十块钱，感觉是过去的自己给我寄的礼物！",
        "elements": [
            "口袋捡到钱",
            "压箱底外套",
            "过去自己的礼物",
            "天降巨款",
            "偷着乐"
        ],
        "sd_hint": "chilly day, wearing oversized winter coat, holding up a folded 20 banknote pulled from pocket, ecstatic surprised face, glowing joyful vibe"
    },
    {
        "id": "d_011",
        "category": "厨房实验",
        "theme": "神秘厨房自制特饮试毒：把乌龙茶、西柚汁、气泡水和薄荷叶混在一起倒进大玻璃杯，颜色好看得像魔法药水，第一口下去居然意外地好喝！",
        "elements": [
            "自制特饮",
            "魔法药水",
            "气泡水西柚",
            "意外好喝",
            "家庭调酒师"
        ],
        "sd_hint": "afternoon, kitchen counter, holding tall clear glass layered with pink grapefruit and sparkling tea drink, mint leaf on top, proud adventurous smile"
    },
    {
        "id": "d_012",
        "category": "生灵互动",
        "theme": "小巷橘猫终于让我摸下巴了：路口便利店后面那只高冷的大胖橘，我蹲在路边跟它无声对视了整整三分钟，它终于主动走过来用脑门狠狠蹭了我的手！",
        "elements": [
            "收服高冷猫",
            "蹭手心",
            "小巷大胖橘",
            "无声对视",
            "原地融化"
        ],
        "sd_hint": "afternoon, crouching in quiet alleyway, gently scratching chin of a chubby tabby cat leaning into hand, radiant tender heartwarming smile"
    },
    {
        "id": "d_013",
        "category": "解压日常",
        "theme": "捏气泡膜根本停不下来：拆快递剩下的两米长大泡泡纸，本来只想捏一个听个响，结果坐在地上啪啪啪捏了二十分钟，灵魂被洗涤了！",
        "elements": [
            "捏气泡膜",
            "快递包装",
            "停不下来",
            "噼里啪啦",
            "解压神物"
        ],
        "sd_hint": "afternoon, sitting surrounded by shipping boxes, pinching bubble wrap with thumbs, concentrated comical bliss, room floor"
    },
    {
        "id": "d_014",
        "category": "少女日常",
        "theme": "手腕上的皮筋勒出小手镯：摘下手腕上套了一整天的小皮筋，手腕上勒出了一圈粉粉红红的印子，揉了半天像戴了个隐形手镯！",
        "elements": [
            "皮筋勒痕",
            "手腕红印",
            "揉手腕",
            "生活小痕迹",
            "呆呆发笑"
        ],
        "sd_hint": "afternoon, sitting by window, rubbing wrist with cute red indentation from hairband, amused silly smile, casual daily clothes"
    },
    {
        "id": "d_015",
        "category": "文具生活",
        "theme": "手撕胶带撕出完美直角：今天用手撕碎花和纸胶带，竟然一秒撕出了一个极其笔直平整的90度直角！强迫症当场起立鼓掌！",
        "elements": [
            "撕胶带",
            "完美直角",
            "强迫症狂喜",
            "和纸胶带",
            "起立鼓掌"
        ],
        "sd_hint": "afternoon, craft desk, holding decorative washi tape roll with pristine straight cut edge, sparkling proud eyes, triumphant face"
    },
    {
        "id": "d_016",
        "category": "季节小情绪",
        "theme": "出门被冷风吹出土拨鼠尖叫：以为今天是大晴天就只套了薄卫衣，一迈出单元门迎面一阵西北风把我吹得倒退两步，火速逃回家加外套！",
        "elements": [
            "被风吹退",
            "土拨鼠尖叫",
            "降温翻车",
            "逃回家加衣服",
            "瑟瑟发抖"
        ],
        "sd_hint": "morning, outside front doorway, strong gust of wind blowing hair and clothes violently back, shivering funny face, arms crossed"
    },
    {
        "id": "d_017",
        "category": "生灵互动",
        "theme": "离开座位一秒椅子被占领：我就去厨房倒了半杯水，回来发现我的电竞椅正中央已经盘踞了一只假装熟睡的大毛球，怎么推都推不动！",
        "elements": [
            "椅子被抢",
            "装睡猫咪",
            "推不动",
            "倒水回来",
            "只能坐板凳"
        ],
        "sd_hint": "afternoon, standing beside desk chair occupied by curled up sleeping cat, hands on hips looking helpless and amused, cozy room"
    },
    {
        "id": "d_018",
        "category": "日常小牢骚",
        "theme": "最喜欢的青梅果冻停产了：在便利店找了三家都没看到那款青梅味果冻，上网一搜居然停产了，心碎的声音比薯片脆响还清脆！",
        "elements": [
            "果冻停产",
            "心碎声音",
            "找遍便利店",
            "童年回忆",
            "晴天霹雳"
        ],
        "sd_hint": "afternoon, looking down at empty supermarket shelf, hands gripping cheeks in dramatic melodrama shock, tears in anime eyes"
    },
    {
        "id": "d_019",
        "category": "搞笑翻车",
        "theme": "前置摄像头突然打开的死亡角度：躺在沙发上解锁手机，不知怎么点到了前置自拍，屏幕上赫然出现一个双下巴仰角大饼脸，被自己吓死！",
        "elements": [
            "前置摄像头",
            "死亡角度",
            "双下巴仰拍",
            "被自己吓跳",
            "光速划掉"
        ],
        "sd_hint": "afternoon, lounging on couch, smartphone screen reflecting startled wide eyes and funny double chin angle, hilarious cute panic"
    },
    {
        "id": "d_020",
        "category": "提问互动",
        "theme": "站在冰淇淋冰柜前纠结十分钟：焦糖海盐和薄荷巧克力到底选哪个啊啊啊！救命，到底有没有人能懂薄巧派的崇高魅力，评论区快来打一架！",
        "elements": [
            "冰淇淋纠结",
            "薄荷巧克力",
            "焦糖海盐",
            "冰柜前抓狂",
            "呼叫评论区"
        ],
        "sd_hint": "afternoon, standing in front of convenience store ice cream freezer, holding two tubs of ice cream with agonizingly cute indecisive expression"
    },
    {
        "id": "d_021",
        "category": "抬头看天",
        "theme": "抬头看到一块长得极像大胖海豹的云：真的没有夸张！连圆滚滚的小肚腩和胡须尖都一清二楚，抓起手机想拍结果两秒钟就被风吹成了长条抹布...",
        "elements": [
            "海豹云朵",
            "圆滚滚肚腩",
            "拍照慢半拍",
            "被风吹成抹布",
            "抬头看天"
        ],
        "sd_hint": "afternoon, street corner, pointing phone upward at sky with funny disappointed expression, fluffy white clouds against vibrant blue sky"
    },
    {
        "id": "d_022",
        "category": "日常小确幸",
        "theme": "买了十卷花里胡哨的和纸胶带：本来只是路过文具店买个橡皮，出来手里多了五只彩色荧光笔和一堆手账胶带，钱包空了但灵魂得到了升华！",
        "elements": [
            "文具店沦陷",
            "和纸胶带",
            "荧光笔收集",
            "钱包空空",
            "灵魂升华"
        ],
        "sd_hint": "afternoon, holding cute paper shopping bag stuffed with colorful washi tape and cute stationery, triumphant bubbly smile on street"
    },
    {
        "id": "d_023",
        "category": "生灵互动",
        "theme": "跟路边的鸽子比赛谁脖子伸得快：路过花坛看见一只灰鸽子走一步点一下头，忍不住跟在它后面学它走了两米，差点被路过骑单车的小哥当成奇怪人类！",
        "elements": [
            "模仿鸽子走路",
            "点头晃脑",
            "被路人侧目",
            "尴尬快跑",
            "生活小笨蛋"
        ],
        "sd_hint": "afternoon, city sidewalk near park, mimicking a pigeon walking with funny bobbing posture, sudden realization of embarrassment, flushed cheeks"
    },
    {
        "id": "d_024",
        "category": "美食日常",
        "theme": "刚出炉的烤红薯烫手换着拿：路边铁皮桶烤出来的蜜汁红薯，皮薄得像纸还直滋滋冒焦糖油，烫得在左右手之间来回倒腾像在抛杂耍！",
        "elements": [
            "铁皮桶烤红薯",
            "滋滋冒蜜糖",
            "左右手倒腾",
            "烫手杂耍",
            "秋冬快乐"
        ],
        "sd_hint": "chilly afternoon, street side, tossing a hot steaming roasted sweet potato rapidly between gloved hands, blowing warm breath, delicious joy"
    },
    {
        "id": "d_025",
        "category": "下雨天情绪",
        "theme": "踩过倒映着彩虹油光的小水洼：雨刚停太阳就出来了，柏油路面的小水坑里有一圈圈彩色油膜像小彩虹，穿着雨靴咔嚓踩上去溅起小水花！",
        "elements": [
            "彩虹油光水坑",
            "雨靴踩水",
            "溅起小水花",
            "雨后初晴",
            "孩子气踏水"
        ],
        "sd_hint": "afternoon, wet street after rain, wearing cute yellow rain boots, splashing through shallow puddle reflecting rainbow oil film, giggling happily"
    },
    {
        "id": "d_026",
        "category": "日常折腾",
        "theme": "拿湿纸巾给琴叶榕的每一片大叶子擦灰：擦了半个小时擦得手腕发酸，但看着整棵大绿植在阳光下油光发亮像涂了蜡，忍不住对自己肃然起敬！",
        "elements": [
            "擦植物大叶子",
            "琴叶榕",
            "油亮发光",
            "手腕酸痛",
            "肃然起敬"
        ],
        "sd_hint": "afternoon, living room, wiping large green fiddle-leaf fig leaves with damp cloth, leaves shining under sunlight, wiping sweat from forehead with smile"
    },
    {
        "id": "d_027",
        "category": "童心大发",
        "theme": "用两把椅子和床单搭了个秘密小帐篷：突然童心大发把沙发靠垫和床单全搬出来，钻进光线昏暗的小堡垒里吃薯片看漫画，感觉与整个世界隔绝了！",
        "elements": [
            "床单秘密堡垒",
            "椅子搭建",
            "暗光小世界",
            "吃薯片看漫画",
            "避难所安全感"
        ],
        "sd_hint": "afternoon, peeking out from makeshift blanket fort supported by chairs in living room, holding bag of potato chips, flashlight glow inside, playful smirk"
    },
    {
        "id": "d_028",
        "category": "生灵互动",
        "theme": "打字打一半猫咪一屁股坐在回车键上：本来在认真写长篇小论文，一团大白毛球优雅路过顺势一躺，屏幕上瞬间输出了十行连续的字母，怎么推都推不动！",
        "elements": [
            "猫坐键盘",
            "满屏长串字母",
            "优雅一躺",
            "哭笑不得",
            "猫猫统治世界"
        ],
        "sd_hint": "afternoon, computer desk, cat lying squarely across mechanical keyboard, monitor showing repeated characters, holding head in hands with affectionate defeat"
    },
    {
        "id": "d_029",
        "category": "日常小确幸",
        "theme": "在零食柜最深处掏出一包没过期的海苔脆：以为家里零食已经全部阵亡，把手伸进柜子最深处盲摸，居然摸出了一包完好无损的芥末海苔，当场跳了一段庆祝舞！",
        "elements": [
            "零食柜深处",
            "盲摸宝藏",
            "没过期零食",
            "即兴庆祝舞",
            "意外暴富"
        ],
        "sd_hint": "afternoon, kneeling by open kitchen pantry cabinet, holding up unopened seaweed snack pack high in air like a trophy, ecstatic wide smile"
    },
    {
        "id": "d_030",
        "category": "搞笑翻车",
        "theme": "插奶茶吸管一用力把封口膜戳了个对穿：拿着大吸管对准圆心狠狠一怼，不仅没戳出洞还直接把整杯奶茶推倒，桌上漫开一片奶茶海，手忙脚乱抽纸巾救灾！",
        "elements": [
            "戳奶茶翻车",
            "吸管对穿",
            "桌上奶茶海",
            "手忙脚乱抽纸",
            "小笨蛋日常"
        ],
        "sd_hint": "afternoon, cafe table, knocked over boba cup spilling brown liquid, frantically pulling tissues from box with funny panicked wide-eyed expression"
    },
    {
        "id": "d_031",
        "category": "日常折腾",
        "theme": "给笔记本电脑外壳贴满新的动漫贴纸：精心布局了半小时贴了可爱的猫猫头、像素心心和闪光星星，最后一张贴歪了强迫症扣了十分钟手指甲都要抠秃了！",
        "elements": [
            "贴纸装饰电脑",
            "最后一张贴歪",
            "抠指甲强迫症",
            "猫猫头贴纸",
            "少女感满满"
        ],
        "sd_hint": "afternoon, desk, laptop lid covered in colorful cute stickers, concentrating intensely trying to peel off one crooked corner sticker with fingernail"
    },
    {
        "id": "d_032",
        "category": "日常小翻车",
        "theme": "趴在长毛地毯上用手机手电筒找耳钉：刚戴上一只小珍珠耳钉手滑啪嗒掉地上了，趴在地毯上像只警犬一样一寸一寸扫射，最后在自己拖鞋缝里找到了！",
        "elements": [
            "寻找耳钉",
            "长毛地毯警犬",
            "手电筒扫射",
            "拖鞋缝破案",
            "松了一口气"
        ],
        "sd_hint": "afternoon, crouching on living room rug using smartphone flashlight beam to search floor, funny concentrated detective expression"
    },
    {
        "id": "d_033",
        "category": "日常小确幸",
        "theme": "拆盲盒前双手合十摇晃盒子听重量：买了一只盲盒小手办，放在耳边像听西瓜熟没熟一样疯狂摇晃听声音，拆开果然抽到了心心念念的隐藏款大肥啾！",
        "elements": [
            "拆盲盒祈祷",
            "摇晃听声音",
            "隐藏款大肥啾",
            "双手合十",
            "欧气大爆发"
        ],
        "sd_hint": "afternoon, holding cute unopened blind box close to ear shaking it with focused expression, desk covered in packaging, hopeful sparkling eyes"
    },
    {
        "id": "d_034",
        "category": "小恶作剧",
        "theme": "空电梯里飙高音结果门突然开了：以为整部电梯就自己一个人，毫无心理包袱地大声飙海豚音，结果三楼叮的一声门开了，跟外面等电梯的大叔四目相对当场石化！",
        "elements": [
            "电梯飙高音",
            "门突然开了",
            "当场石化",
            "社死瞬间",
            "装作看天花板"
        ],
        "sd_hint": "afternoon, inside elevator facing opening doors, holding hand up as microphone, frozen in mid-song with terrified hilarious wide-eyed blush"
    },
    {
        "id": "d_035",
        "category": "午后放空",
        "theme": "盯着一束阳光里的丁达尔灰尘发呆十分钟：下午两点的斜阳照在客厅茶几上，光柱里无数微小的金色尘埃在缓缓打转沉浮，看发呆了感觉时间都静止了",
        "elements": [
            "丁达尔光束",
            "金色微尘旋转",
            "午后放空发呆",
            "时间静止",
            "宁静下午"
        ],
        "sd_hint": "afternoon, sitting on floor beside coffee table, chin resting on knees, staring mesmerized at sunbeam with floating dust motes, dreamy gentle gaze"
    },
    {
        "id": "d_036",
        "category": "季节小情绪",
        "theme": "冬天走在路上两只手缩进大衣袖子里：风吹得鼻尖通红，把整双手全部缩在长长的毛衣袖子里当成手套，像一只揣手手站在路边等红绿灯的企鹅！",
        "elements": [
            "揣手手企鹅",
            "袖子当手套",
            "鼻尖通红",
            "等红绿灯",
            "冬天碎念"
        ],
        "sd_hint": "winter afternoon, pedestrian crossing, hands tucked completely inside long knit sleeves held against chest, red nose tip, wool scarf, shivering cutely"
    },
    {
        "id": "d_037",
        "category": "厨房实验",
        "theme": "戴着全封闭泳镜切洋葱抗敌：被洋葱辣哭了两次之后痛定思痛，翻出了夏天的深海潜水泳镜戴上切洋葱，造型奇葩但竟然真的完全不流泪，科技改变生活！",
        "elements": [
            "戴泳镜切洋葱",
            "深海潜水镜",
            "全封闭防御",
            "一滴泪没流",
            "胜利姿态"
        ],
        "sd_hint": "afternoon, kitchen cutting board, wearing oversized swimming goggles with chef knife cutting yellow onion, triumphant ridiculous cute grin"
    },
    {
        "id": "d_038",
        "category": "强迫症日常",
        "theme": "把整罐彩虹糖按颜色严谨分类排队：下午摸鱼无聊，把一大罐彩虹豆倒出来，红橙黄绿青蓝紫排得整整齐齐像小阅兵方阵，最后先把最不喜欢的黄豆吃掉！",
        "elements": [
            "彩虹糖分类",
            "颜色阅兵方阵",
            "强迫症解压",
            "吃掉不喜欢的",
            "摸鱼日常"
        ],
        "sd_hint": "afternoon, wooden table, rows of colorful round candies neatly sorted by spectrum colors, holding one yellow candy on fingertip, focused cute face"
    },
    {
        "id": "d_039",
        "category": "日常小确幸",
        "theme": "下班路上给自己买了一小支向日葵：路过街边小花车，花五块钱买了一株金黄饱满的小向日葵插在自行车车把的小筐里，骑车一路迎风感觉整条街都在向我挥手！",
        "elements": [
            "给自己买花",
            "向日葵车筐",
            "自行车微风",
            "五块钱快乐",
            "迎风骑行"
        ],
        "sd_hint": "afternoon, riding bicycle with single bright sunflower bouncing in front wire basket, hair blowing in breeze, carefree radiant smile"
    },
    {
        "id": "d_040",
        "category": "日常折腾",
        "theme": "跟风点了全网推的隐藏奶茶喝法：乌龙茶底加麻薯加豆乳奶盖还要三分糖去冰，吸管用力一吸满嘴都是糯叽叽的麻薯，幸福得原地跺小碎步！",
        "elements": [
            "隐藏奶茶喝法",
            "糯叽叽麻薯",
            "豆乳奶盖",
            "跺小碎步",
            "打卡成功"
        ],
        "sd_hint": "afternoon, walking on street drinking large iced boba cup with colorful layers through thick straw, eyes sparkling with delighted surprise"
    },
    {
        "id": "d_041",
        "category": "文具生活",
        "theme": "拿收据小票折出一只歪脖子千纸鹤：在咖啡馆等朋友无聊，把钱包里的一张长条收据撕成小方块，折了十分钟折出一只翅膀一大一小的残疾小鹤，立在桌角当吉祥物！",
        "elements": [
            "小票折纸",
            "歪脖子千纸鹤",
            "咖啡馆等朋友",
            "大小翅膀",
            "桌角吉祥物"
        ],
        "sd_hint": "afternoon, cafe table beside coffee cup, gently placing an origami crane folded from receipt paper on table with fingertips, amused playful smile"
    },
    {
        "id": "d_042",
        "category": "生灵互动",
        "theme": "抓拍到自家猫咪打大哈欠的惊悚丑照：本来想拍一张仙女猫咪美照，镜头按下的千分之一秒它突然张开血盆大口露出四颗小尖牙，翻看相册笑到腹肌疼！",
        "elements": [
            "猫咪丑照",
            "血盆大口哈欠",
            "小尖牙惊悚",
            "笑到腹肌疼",
            "手抖抓拍"
        ],
        "sd_hint": "afternoon, holding smartphone showing funny photo of cat mid-yawn, holding stomach laughing unstoppably on living room couch"
    },
    {
        "id": "d_043",
        "category": "少女日常",
        "theme": "低头发现今天穿搭的配色极其和谐：燕麦色毛衣配奶油白阔腿裤，脚踝露出一小截抹茶绿袜子正好呼应了帆布包上的绿叶刺绣，走在路边橱窗前忍不住多照了两眼！",
        "elements": [
            "燕麦色与抹茶绿",
            "绝美配色",
            "袜子呼应刺绣",
            "橱窗照镜子",
            "穿搭小骄傲"
        ],
        "sd_hint": "afternoon, city street, pausing beside store display window checking reflection of stylish coordinated pastel outfit, pleased confident smile"
    },
    {
        "id": "d_044",
        "category": "搞笑翻车",
        "theme": "走在无人的林荫道上试图吹口哨结果吹出了口水泡：耳机里放着轻快的小曲，嘟起嘴巴用力吸气呼气想吹出一段绝妙口哨，结果只噗了一声喷出两颗细小口水珠，赶紧四顾无人！",
        "elements": [
            "学吹口哨",
            "噗出一声",
            "口水泡泡",
            "四顾无人",
            "偷偷擦嘴"
        ],
        "sd_hint": "afternoon, tree-lined quiet street, pursing lips trying to whistle, funny puffed cheeks, looking sideways sheepishly"
    },
    {
        "id": "d_045",
        "category": "童心大发",
        "theme": "在空旷超市过道把推车推成滑板车：推着沉甸甸装满零食的购物车，趁着整条货架过道没人，两脚往后一蹬站在车后轴上滑行了整整五米，速度与激情超市版！",
        "elements": [
            "超市推车滑行",
            "两脚蹬地",
            "货架无人",
            "超市版速度与激情",
            "快乐起飞"
        ],
        "sd_hint": "afternoon, supermarket aisle, standing with both feet on rear bar of shopping cart gliding forward playfully, hair fluttering, exhilarated grin"
    },
    {
        "id": "d_046",
        "category": "少女日常",
        "theme": "把所有化妆刷洗得干干净净晾在架子上：花了一个小时把十几把毛茸茸的散粉刷眼影刷全部用洗刷皂洗出脏水，整整齐齐头朝下倒挂在晾刷架上，强迫症得到极大满足！",
        "elements": [
            "洗化妆刷",
            "洗刷皂泡沫",
            "倒挂晾刷架",
            "毛茸茸整齐",
            "治愈强迫症"
        ],
        "sd_hint": "afternoon, bathroom counter, rows of clean fluffy makeup brushes hanging upside down on acrylic drying rack, soap bubbles, wiping hands on towel"
    },
    {
        "id": "d_047",
        "category": "午后放空",
        "theme": "午后公交车橙色窗帘透过来的暖阳：坐在双层巴士二层第一排，橙红色的窗帘被微风吹得轻轻飘荡，把整张脸颊都映成了暖融融的金橙色，整个人摇晃得像在乘船",
        "elements": [
            "双层巴士二层",
            "橙色窗帘晃荡",
            "金橙色暖阳",
            "微风像乘船",
            "午后微醺"
        ],
        "sd_hint": "afternoon, front row of upper deck on double-decker bus, orange sheer curtain floating in breeze, warm golden light on face, tranquil daydreaming"
    },
    {
        "id": "d_048",
        "category": "日常惊喜",
        "theme": "在路边三叶草花坛里真的蹲到了一株四叶草：本来只是蹲在花坛边等红绿灯，眼神随意一扫，竟然真的在一大片三叶草中看见了一个饱满的四瓣叶！今天必定行大运！",
        "elements": [
            "四叶草奇迹",
            "三叶草花坛",
            "等红绿灯发现",
            "小心摘下",
            "欧气爆棚"
        ],
        "sd_hint": "afternoon, kneeling beside roadside clover patch, holding a real four-leaf clover delicately between fingers, radiant sparkling triumphant eyes"
    },
    {
        "id": "d_049",
        "category": "日常小笨蛋",
        "theme": "跟微波炉倒计时赛跑在最后一秒按停：把冷披萨放进微波炉转一分钟，站在微波炉前倒数'三、二、一'，掐在变成00:00前一毫秒啪地拍停按钮，成功阻止了嘀嘀报警声！",
        "elements": [
            "微波炉掐表",
            "最后一毫秒按停",
            "阻止嘀嘀声",
            "特工附体",
            "幼稚小游戏"
        ],
        "sd_hint": "afternoon, kitchen counter, finger poised dramatically on microwave cancel button glowing 00:01, intense comedic secret agent focus on face"
    },
    {
        "id": "d_050",
        "category": "日常小确幸",
        "theme": "发现朋友手机壳上贴了跟我同款的傻沙雕贴纸：一见面掏出手机同时拍在桌上，两个人的手机背面居然贴了一模一样的那只翻白眼蠢鸭子，当场笑到拍桌子！",
        "elements": [
            "同款沙雕贴纸",
            "翻白眼蠢鸭",
            "同时拍在桌上",
            "默契拍桌大笑",
            "神仙闺蜜"
        ],
        "sd_hint": "afternoon, cafe table, two smartphones side by side showing matching silly duck stickers, laughing and pointing fingers, energetic vibrant vibe"
    },
    {
        "id": "d_051",
        "category": "搞笑翻车",
        "theme": "对着卫生间大镜子试图自己修刘海：拿着小剪刀小心翼翼剪了一刀，左边好像长了点，补一刀右边又短了，再补一刀...救命！变成了眉上二次元锅盖头！",
        "elements": [
            "自己剪刘海",
            "越剪越短",
            "眉上锅盖头",
            "手残翻车",
            "照镜子生无可恋"
        ],
        "sd_hint": "afternoon, bathroom mirror, holding small scissors near forehead with comically ultra-short blunt bangs, wide shocked eyes, hilarious dismay"
    },
    {
        "id": "d_052",
        "category": "生灵互动",
        "theme": "路边小修车铺的短腿小狗把尾巴摇成了螺旋桨：刚蹲下冲它拍了拍手，那只圆滚滚的小柯基立刻踩着小碎步狂奔过来，小尾巴摇得飞起简直能当场起飞！",
        "elements": [
            "短腿小柯基",
            "尾巴螺旋桨",
            "小碎步飞奔",
            "拍手呼唤",
            "当场起飞"
        ],
        "sd_hint": "afternoon, squatting on street corner petting a joyful stubby-legged corgi whose tail is a blur of motion, wide sunny laughing face"
    },
    {
        "id": "d_053",
        "category": "日常小确幸",
        "theme": "拆快递发现卖家悄悄送了两张绝美闪卡和跳跳糖：买了一盒普通的画笔，箱子底下竟然塞了一张手写感谢卡和两包童年跳跳糖，小小的善意让人开心一整下午！",
        "elements": [
            "卖家小赠品",
            "童年跳跳糖",
            "手写感谢卡",
            "拆箱惊喜",
            "一整下午好心情"
        ],
        "sd_hint": "afternoon, floor covered in cardboard packaging, holding small cute handwritten note and popping candy packet with starry delighted eyes"
    },
    {
        "id": "d_054",
        "category": "日常小笨蛋",
        "theme": "走路哼歌哼到高潮突然把歌词忘得一干二净：前面一直唱得神采飞扬，一到最激动的高潮部分脑子突然空白，只能顺着调子疯狂'啦啦啦啦啦'强行蒙混过关！",
        "elements": [
            "哼歌忘词",
            "脑子突然空白",
            "疯狂啦啦啦",
            "蒙混过关",
            "边走边晃"
        ],
        "sd_hint": "afternoon, sidewalk walking, one hand gesturing dramatically while laughing at own lyric stumble, cute playful expression"
    },
    {
        "id": "d_055",
        "category": "美食日常",
        "theme": "面包房刚出炉的葡挞酥皮掉了一身：刚拿到手热得烫嘴，咬下第一口奶香浓郁的蛋挞心，酥脆的千层皮扑簌簌掉得毛衣上全都是，手忙脚乱在身上拍碎渣！",
        "elements": [
            "刚出炉葡挞",
            "千层酥皮碎屑",
            "烫嘴奶香",
            "掉一身碎渣",
            "手忙脚乱拍衣服"
        ],
        "sd_hint": "afternoon, standing on street holding a golden Portuguese egg tart, dusting flaky crust crumbs off knit sweater, mouth full of delicious custard"
    },
    {
        "id": "d_056",
        "category": "文具生活",
        "theme": "把彩色便签条在墙上贴出一面渐变小彩虹：把马卡龙色系的便签纸按粉、黄、薄荷绿、天蓝一片片贴在白墙上当备忘，远远看过去像一面小彩虹墙！",
        "elements": [
            "马卡龙便签纸",
            "白墙彩虹",
            "渐变色排布",
            "文具控治愈",
            "生活仪式感"
        ],
        "sd_hint": "afternoon, standing in front of wall covered in neat grid of colorful pastel sticky notes, holding a pen, stepping back with proud admiring smile"
    },
    {
        "id": "d_057",
        "category": "童心大发",
        "theme": "公园里一群小朋友吹泡泡我偷偷用手指接住一个：大大小小的彩色泡泡在阳光下慢悠悠飘，伸出食指小心翼翼凑上去，竟然稳稳接住了一个没破，阳光在上面折射出彩虹！",
        "elements": [
            "阳光肥皂泡",
            "手指稳稳接住",
            "彩虹折射",
            "童心大发",
            "公园微风"
        ],
        "sd_hint": "afternoon, sunny park lawn, a shimmering translucent soap bubble resting delicately on outstretched fingertip, eyes wide with childlike magic"
    },
    {
        "id": "d_058",
        "category": "美食日常",
        "theme": "挑战特辣火鸡面辣到狂灌冰牛奶：明明吃不了太辣还硬要挑战，两口下去舌头开始喷火，鼻尖直冒汗，一边吸溜着哈气一边抓起冰牛奶咕嘟咕嘟往肚子里灌！",
        "elements": [
            "特辣火鸡面",
            "舌头喷火",
            "鼻尖冒汗",
            "狂灌冰牛奶",
            "又菜又爱吃"
        ],
        "sd_hint": "afternoon, kitchen table with bowl of spicy red noodles, fanning mouth with one hand while chugging glass of cold milk, teary laughing eyes"
    },
    {
        "id": "d_059",
        "category": "午后放空",
        "theme": "阳台支起手机架拍天上的积雨云赛跑：巨大的白色积云在深蓝天空里像翻滚的棉花山一样快速变幻形状，坐在小马扎上一边啃西瓜一边看云朵奔跑，舒服得不想动",
        "elements": [
            "积雨云赛跑",
            "棉花山翻滚",
            "阳台啃西瓜",
            "手机延时摄影",
            "夏日长昼"
        ],
        "sd_hint": "afternoon, sitting on small stool on balcony, eating a slice of fresh red watermelon, phone on tripod capturing dramatic summer clouds"
    },
    {
        "id": "d_060",
        "category": "生灵互动",
        "theme": "自家猫咪把自己端端正正揣成了一个四方小面包：四只爪子和尾巴全部整整齐齐收在肚子底下，趴在飘窗上像一坨刚出炉的金黄吐司，忍不住从侧面疯狂拍照！",
        "elements": [
            "猫咪揣手手",
            "四方小面包",
            "金黄吐司猫",
            "飘窗晒太阳",
            "疯狂连拍"
        ],
        "sd_hint": "afternoon, leaning close to a chubby loafing cat on windowsill with all paws hidden, framing shot with phone camera, giggling adoration"
    }
]

THEME_MUTATION_DIRECTIVES = [
    {
        "type": "意外惊喜反转",
        "directive": "【意外惊喜反转】：在当前生活场景的基础上，突然遭遇了一件完全预料之外又让人忍俊不禁的小插曲（比如猫咪突然跳上了桌子打翻水彩、微风卷起书页正好翻到奇怪的一页、偶遇一只不怕人的小松鼠），让整体情节发生自然、生动的转折。"
    },
    {
        "type": "极致五感放大",
        "directive": "【极致五感放大】：不要泛泛而谈，将注意力聚焦在当前场景极微小的一处感官细节上（如初晨冰镇汽水开盖瞬间的气泡刺痛感、被窝深处被体温烘得暖绒绒的棉麻气味、雨滴打在雨伞铁骨上的微震、刚出炉面包外皮酥脆崩裂的细响），写出超高分辨率的生活真实感。"
    },
    {
        "type": "天马行空脑内剧场",
        "directive": "【天马行空脑内剧场】：由眼前平常的景象展开一段少女独有的天马行空浪漫狂想或奇思妙想（比如怀疑云朵是天上的巨型棉花糖工厂掉下来的残次品、怀疑水坑倒影里藏着另一个平行世界的倒立城市、觉得街角橘猫戴着隐形王冠），充满灵动与趣味。"
    },
    {
        "type": "生活小笨蛋瞬间",
        "directive": "【生活小笨蛋瞬间】：流露出一点点笨拙又可爱的糊涂瞬间（比如把两只不同的袜子穿反了还觉得挺好看、试图帅气单手开瓶盖失败、倒牛奶差点倒到杯子外面、走路太专心看天空被路边小花坛轻轻碰了一下脚），不要完美偶像感，要鲜活的真实活人感。"
    },
    {
        "type": "双向真实生活征集",
        "directive": "【双向真实生活征集】：在记录自己当下的状态后，自然向大家抛出一个充满烟火气、让人极想在评论区热烈讨论的生活小话题（如'大家的睡前保留曲目是什么呀'、'你们吃泡面是先放酱包还是蔬菜包？'、'要是能带一样甜点去无人岛你们带什么！'），增强互动与日常温度。"
    },
    {
        "type": "电影胶片定格感",
        "directive": "【电影胶片定格感】：像独立日系胶片电影镜头一样定格当前瞬间，用温柔克制、极富画面留白与空气感的笔触记录光影、微风与心跳（如傍晚街道被夕阳拉得很长的影子、风吹动风铃叮当一声轻响的停顿、窗外掠过的飞鸟影子投在墙壁上的一瞬）。"
    },
    {
        "type": "微小娇憨发牢骚",
        "directive": "【微小娇憨发牢骚】：带着一点点软糯委屈或可爱的无伤大雅小吐槽（比如'闹钟到底凭什么可以在我刚做美梦的时候响'、'为什么秋天的蚊子动作比我还快啊气死我了'、'烤吐司又稍微糊了一点点边边，但只要把黑边剥掉就等于完美对吧！'）。"
    },
    {
        "type": "微气候与时令通感",
        "directive": "【微气候与时令通感】：把当前季节与微气候带来的心绪变化与场景深度交融（如深秋傍晚泛着冷意的蓝紫色天空让人好想喝一口热可可、初夏微热柏油路散发的气息预示着大雨将至、晴朗冬日午后阳光晒得毛衣散发出干燥温暖的气味）。"
    },
    {
        "type": "穿搭与色彩风格变体",
        "directive": "【穿搭与色彩风格变体】：特别留意并生动描写自己此刻的着装穿搭与色彩氛围（如换上了一件暖杏色针织毛衣、偷穿了宽大的鼠尾草绿落肩卫衣、或是轻盈的淡薰衣草紫碎花衬衫裙），将衣服的材质触感（软糯毛线、清凉亚麻、蓬松棉布）与当前时节心境自然融为一体。"
    },
    {
        "type": "时令色调与视觉心境",
        "directive": "【时令色调与视觉心境】：将视线聚焦在周围环境与自身衣着的色彩碰撞上（如清冷深蓝暮色里的奶油白围巾、初夏阳光下薄荷绿冰饮与纯白T恤的清爽映衬、秋日金黄落叶堆中温暖的焦糖驼色大衣），营造出鲜明生动的画面色调与情绪共鸣。"
    }
]

# =====================================================================
# 少女穿搭风格与色彩库 (Outfit and Color Palette Diversity Pool)
# 用于 Stable Diffusion 绘图提示词变体引导，彻底摆脱固定服饰和单一色彩
# =====================================================================

OUTFIT_STYLE_POOLS = [
    {
        "category": "针织与毛衣 (Knitwear / Sweaters)",
        "styles": [
            "oversized cream cable-knit sweater, pleated brown plaid skirt, beige ankle boots",
            "dusty blue turtleneck sweater, off-white corduroy pants, cozy warm vibe",
            "mint green loose cardigan over white camisole, light denim shorts",
            "lavender fluffy mohair sweater, pearl white midi skirt, gentle sweet aesthetic",
            "mustard yellow knitted pullover, dark navy pleated skirt, vintage beret",
            "pastel pink ribbed knit sweater, gray wool shorts, cute knitted leg warmers",
            "warm beige v-neck knit vest over crisp white collared shirt, pleated skirt",
            "emerald green chunky knit sweater, off-white casual trousers, relaxed fit"
        ]
    },
    {
        "category": "连身裙与裙装 (Dresses / Skirts)",
        "styles": [
            "light blue floral sundress, puff sleeves, delicate white ribbon waist tie",
            "vintage beige prairie dress, square neckline, lace trim, wooden buttons",
            "navy blue sailor collar dress, white stripes, red neckerchief tie, preppy look",
            "sage green tier-layered slip dress over cream long-sleeve blouse",
            "dusty rose chiffon dress, ruffled hem, romantic gentle breeze silhouette",
            "pale yellow gingham cotton dress, frilled shoulder straps, sweet cottagecore style",
            "black velvet mini dress with white Peter Pan collar, cuff lace details"
        ]
    },
    {
        "category": "街头休闲与卫衣 (Streetwear / Hoodies)",
        "styles": [
            "pastel lilac oversized hoodie, black bike shorts, chunky sneakers",
            "cropped faded denim jacket, white crewneck tee, high-waisted beige cargo pants",
            "charcoal grey zip-up hoodie, striped tank top inside, loose washed jeans",
            "creamy white baseball varsity jacket, navy pleated tennis skirt, tube socks",
            "matcha green relaxed sweatshirt, raw-edge denim skirt, canvas tote bag",
            "oversized pastel color-block windbreaker, black leggings, sporty dynamic vibe",
            "light grey slouchy crewneck pullover, relaxed denim overalls with one strap undone"
        ]
    },
    {
        "category": "居家与睡衣 (Loungewear / Nightwear)",
        "styles": [
            "soft fleece pastel pink bear-ear hoodie pajamas, matching fluffy shorts",
            "light grey oversized slouchy waffle-knit loungewear set, cozy indoor softness",
            "silky cream ivory pajama shirt and shorts set, contrast navy piping",
            "sky blue striped oversized cotton boyfriend shirt, cozy white thigh-high socks",
            "soft yellow flannel pajama set, loose fit, fuzzy sheep slippers",
            "lavender cotton camisole and loose lounge pants, matching light wrap cardigan"
        ]
    },
    {
        "category": "衬衫与学院风 (Shirts / Academy)",
        "styles": [
            "crisp white button-up blouse, knitted navy houndstooth sweater vest, pleated skirt",
            "light brown oversized linen shirt unbuttoned over white graphic tee, khaki shorts",
            "soft pink Peter Pan collar blouse, brown suspender pinafore skirt",
            "plaid flannel oversized shirt in teal and beige, dark gray denim skirt",
            "chambray blue button-down shirt tucked into high-waist white pleated skirt"
        ]
    },
    {
        "category": "秋冬外套与大衣 (Outerwear / Coats)",
        "styles": [
            "camel beige double-breasted trench coat, warm red plaid wool scarf",
            "olive green quilted liner jacket, off-white turtleneck, dark brown trousers",
            "dusty blue duffle coat with horn toggles, cream fluffy ear muffs, plaid skirt",
            "fluffy white teddy bear fleece jacket, pastel pink knit beanie, jeans",
            "chocolate brown tailored wool coat, ivory knit turtleneck sweater, beret"
        ]
    }
]

OUTFIT_COLOR_PALETTES = [
    "cream white and pastel mint green",
    "soft lavender and ivory beige",
    "dusty rose pink and warm pearl white",
    "navy blue and crisp pure white",
    "mustard yellow and charcoal grey",
    "sage olive green and warm oatmeal cream",
    "baby blue and light heather grey",
    "caramel brown and warm apricot",
    "lilac purple and pale vanilla yellow",
    "matcha green and linen beige",
    "powder pink and soft sky blue",
    "soft mocha brown and creamy milk white"
]

def get_random_outfit_guidance() -> str:
    """随机挑选一种穿搭和配色建议，作为 SD prompt 提取的引导语"""
    import random
    cat_obj = random.choice(OUTFIT_STYLE_POOLS)
    style = random.choice(cat_obj["styles"])
    palette = random.choice(OUTFIT_COLOR_PALETTES)
    return f"{style}, palette: {palette}"
