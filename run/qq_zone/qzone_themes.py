# -*- coding: utf-8 -*-
"""
QQ 空间海量动态场景与主题库（涵盖早安、晚安、日常 Vtuber 互动）
专为少女心情日记、风景旅行与真实生活切面打造，包含 SD tags 映射。
"""

MORNING_THEME_POOL = [    # --- 1. 自然风景、户外探索与看日出 ---
    {
        "id": "m_sea_sunrise",
        "category": "户外自然",
        "theme": "海边栈道看日出：微咸微凉的海风吹乱头发，海平面尽头第一缕橙红色的金光把浪花和沙滩全染成了温柔的蜜桃粉",
        "elements": ["海边", "日出", "栈道", "海浪晨光", "海风"],
        "sd_hint": "early morning, coastal wooden boardwalk, watching sunrise over ocean horizon, golden orange sky, gentle sea breeze, casual jacket, serene happy smile"
    },
    {
        "id": "m_mountain_cloudsea",
        "category": "户外自然",
        "theme": "山顶看壮丽云海：裹紧厚厚的外套站在山顶观景台，脚下是翻滚如白浪般的无边云海，天边泛起淡金色的光芒",
        "elements": ["山顶", "云海", "晨曦", "厚外套", "观景台"],
        "sd_hint": "morning, mountaintop viewpoint, sea of clouds below, glowing dawn light, wearing cozy thick windbreaker, looking into distance, awe expression"
    },
    {
        "id": "m_pine_forest_mist",
        "category": "户外自然",
        "theme": "冷杉林晨雾漫步：漫步在清晨的冷杉针叶林间，空气里满是冷冽的松针与潮湿泥土香，丁达尔光束穿透薄雾洒在脚边",
        "elements": ["冷杉林", "晨雾", "松针香", "丁达尔光", "漫步"],
        "sd_hint": "morning, pine forest, morning mist, crepuscular rays, pine needles on ground, casual walking outfit, fresh peaceful atmosphere"
    },
    {
        "id": "m_golden_wheat_field",
        "category": "户外自然",
        "theme": "晨光中的金黄麦田：清晨的风吹过连绵的麦浪发出沙沙声，露水还挂在麦芒上，整片原野在晨光下泛着柔软的金黄",
        "elements": ["麦田", "麦浪", "晨露", "原野", "金光"],
        "sd_hint": "morning, golden wheat field, vast countryside, morning dew sparkling, gentle breeze, straw hat, sundress, warm sunshine"
    },
    {
        "id": "m_water_town_bridge",
        "category": "户外自然",
        "theme": "古镇石桥与水波晨雾：江南水乡石板路上还泛着潮气，摇橹船划开晨雾泛起一圈圈涟漪，街巷里飘出刚蒸好的青团香",
        "elements": ["古镇", "石拱桥", "晨雾水乡", "摇橹船", "石板路"],
        "sd_hint": "early morning, traditional water town, ancient stone bridge, mist over canal, quiet riverside street, delicate pastel lighting"
    },
    {
        "id": "m_island_ferry_morning",
        "category": "户外自然",
        "theme": "清晨海岛轮渡甲板：吹着略带凉意的初晨海风，栏杆旁盘旋着两三只白色海鸥，看着对岸小岛的轮廓逐渐在晨曦中清晰",
        "elements": ["轮渡", "海鸥", "海岛", "甲板", "晨光"],
        "sd_hint": "morning, ferry deck, sea seagulls flying around, ocean breeze blowing hair, morning sunlight, holding railing, bright eyes"
    },
    {
        "id": "m_countryside_dew",
        "category": "户外自然",
        "theme": "乡间小径与带露野花：路边不知名的淡蓝色野花上缀着晶莹的露珠，脚底踩着松软的草叶，远处农舍升起第一缕淡白炊烟",
        "elements": ["乡间小路", "野花", "露珠", "炊烟", "青草香"],
        "sd_hint": "morning, countryside path, blooming small wildflowers with dew drops, grassy field, distant farmhouse, peaceful country morning"
    },
    {
        "id": "m_river_morning_glow",
        "category": "户外自然",
        "theme": "江畔慢跑与晨光微风：沿着波光粼粼的江边慢跑，两岸的晨雾刚刚散去，江面映着浅金色的波纹，整个人神清气爽",
        "elements": ["江畔", "慢跑", "波光", "运动耳机", "江风"],
        "sd_hint": "morning, riverside jogging trail, sparkling river reflection, wearing sportswear and earbuds, healthy light blush, energetic smile"
    },
    {
        "id": "m_autumn_gingko_morning",
        "category": "户外自然",
        "theme": "满地金黄银杏道：一整夜的风吹落了一地金灿灿的扇形银杏叶，踩上去沙沙作响，忍不住捡起一片最好看的夹进书里",
        "elements": ["银杏", "落叶", "金黄", "晨光", "捡树叶"],
        "sd_hint": "morning, street covered with golden ginkgo leaves, holding a yellow ginkgo leaf, warm autumn knit sweater, golden sunlight filter"
    },
    {
        "id": "m_cherry_blossom_morning",
        "category": "户外自然",
        "theme": "春晨落樱小道：微风掠过枝头，粉白色的樱花瓣像细雪一样飘在发梢和肩头，清晨的整条小街静悄悄的只有鸟鸣",
        "elements": ["樱花", "花瓣雨", "春晨", "长椅", "安静小街"],
        "sd_hint": "morning, cherry blossom street, falling sakura petals, pink and white flowers, soft spring light, lovely cute dress, poetic atmosphere"
    },
    {
        "id": "m_lakeside_reflection",
        "category": "户外自然",
        "theme": "静谧湖畔如镜倒影：清晨的湖面没有一丝波纹，像一面澄澈的大镜子倒映着蓝天白云和远处的青山，空气清新得想装一罐带走",
        "elements": ["静水湖泊", "倒影", "倒映蓝天", "草甸", "清新空气"],
        "sd_hint": "morning, crystal clear mountain lake, mirror-like lake reflection of sky and mountains, wooden pier, tranquil and breathtaking"
    },
    {
        "id": "m_camp_tent_sunrise",
        "category": "户外自然",
        "theme": "露营帐篷拉链初开：拉开帐篷拉链的一瞬间，冷冽清新的山间空气涌了进来，金色的晨光正穿透树梢落在睡袋边缘",
        "elements": ["露营", "帐篷", "清晨山风", "睡袋", "山间晨曦"],
        "sd_hint": "early morning, peeking out of camping tent, mountain sunrise through trees, sleepy cute face, warm sleeping bag, camping mug"
    },    # --- 2. 城市漫步、早市与小店探寻 ---
    {
        "id": "m_bakery_croissant",
        "category": "城市漫步",
        "theme": "街角面包房第一炉可颂：踩着刚开门的时间溜进街角老面包店，刚出炉的黄油牛角包香气浓郁得让人走不动路，外壳金黄酥脆",
        "elements": ["面包房", "刚出炉", "牛角包", "黄油香", "纸袋"],
        "sd_hint": "morning, quaint bakery shop, holding warm brown paper bag with freshly baked croissants, butter aroma, casual street outfit, blissful smile"
    },
    {
        "id": "m_morning_market_steamer",
        "category": "城市漫步",
        "theme": "早市热气腾腾的小笼包：早市摊位巨大的竹蒸笼揭开盖子，滚滚白汽伴随着葱油和小笼包的香气扑面而来，最是人间烟火气",
        "elements": ["早市", "竹蒸笼", "白汽", "小笼包", "烟火气"],
        "sd_hint": "morning, lively morning street market, steam billowing from bamboo dim sum steamers, food stall, warm bustling atmosphere, cute foodie face"
    },
    {
        "id": "m_flower_market_tulip",
        "category": "城市漫步",
        "theme": "晨光花市挑郁金香：清晨批发花市水灵灵的，给房间挑了一束还带着水珠的奶油黄郁金香，抱着走在路上心情像踩着跳跳糖",
        "elements": ["花市", "郁金香", "水珠", "牛皮纸包装", "明快心情"],
        "sd_hint": "morning, flower market, holding a bouquet of fresh yellow tulips wrapped in kraft paper, soft pastel tones, bright sunny day"
    },
    {
        "id": "m_tram_first_train",
        "category": "城市漫步",
        "theme": "空荡荡的清晨有轨电车：坐上清晨第一班绿皮有轨电车，车厢里空荡荡的，阳光透过车窗在地板上拉出长长的金色斜影",
        "elements": ["有轨电车", "第一班车", "空荡车厢", "车窗斜光", "看风景"],
        "sd_hint": "morning, inside vintage tram car, sitting by window, morning sunlight streaming through windows, empty seats, earphones, peaceful contemplation"
    },
    {
        "id": "m_city_coffee_window",
        "category": "城市漫步",
        "theme": "沿街咖啡馆靠窗高脚凳：点一杯热燕麦拿铁坐在临街的高脚凳上，看着街上匆匆走过的路人，享受难得的慢吞吞偷闲时光",
        "elements": ["街边咖啡馆", "高脚凳", "燕麦拿铁", "观察街景", "慢节奏"],
        "sd_hint": "morning, modern cozy cafe, sitting on barstool by large glass window, ceramic coffee cup with latte art, watching street, warm aesthetic"
    },
    {
        "id": "m_bike_river_breeze",
        "category": "城市漫步",
        "theme": "骑单车迎着晨风飞驰：蹬着小单车穿过林荫道，微凉的风灌进袖口，车筐里放着刚买的橙汁和两支法棍，轻快得想哼歌",
        "elements": ["骑单车", "车筐", "林荫道", "法棍", "晨风灌袖口"],
        "sd_hint": "morning, riding bicycle along tree-lined avenue, front basket with bread and flowers, wind in hair, dynamic cheerful pose, vibrant light"
    },
    {
        "id": "m_morning_bookstore",
        "category": "城市漫步",
        "theme": "早开的书店角落：钻进刚刚开门还没什么人的旧书店，被陈旧纸张与墨水的好闻味道包围，站在窗边翻看一本有趣的画册",
        "elements": ["书店", "翻书", "纸墨香", "靠窗角落", "安静"],
        "sd_hint": "morning, quiet classic bookstore, wooden bookshelves, reading an open book near window, dust motes dancing in sunlight, gentle cute smile"
    },
    {
        "id": "m_rooftop_city_view",
        "category": "城市漫步",
        "theme": "天台眺望苏醒的城市：站在顶楼天台俯瞰，整座城市的大楼玻璃幕墙正一座接着一座被晨曦照亮，像沉睡的巨人慢慢醒来",
        "elements": ["天台", "俯瞰城市", "玻璃反光", "晨曦", "风吹刘海"],
        "sd_hint": "morning, rooftop railing, panoramic city skyline waking up, golden light reflecting on skyscrapers, wind blowing bangs, oversized hoodie"
    },    # --- 3. 晨间厨房美味、做饭与手作 ---
    {
        "id": "m_kitchen_toast_egg",
        "category": "美食手作",
        "theme": "香脆厚吐司与溏心蛋：平底锅上的黄油融化出诱人的坚果香，两颗溏心蛋煎得边缘微脆，趁热在烤得金黄的厚吐司上切开流心",
        "elements": ["平底锅", "煎蛋", "溏心蛋", "厚吐司", "黄油香"],
        "sd_hint": "morning, home kitchen, wearing cute apron, cooking sunny-side up eggs on frying pan, golden toast, steam, appetizing breakfast"
    },
    {
        "id": "m_matcha_latte_froth",
        "category": "美食手作",
        "theme": "打泡器与浓郁抹茶拿铁：用电动打泡器把燕麦奶打出细腻绵密如云朵般的奶泡，缓缓倒进浓绿的抹茶里，拉出歪歪扭扭的小爱心",
        "elements": ["抹茶拿铁", "奶泡", "打泡器", "马克杯", "心形拉花"],
        "sd_hint": "morning, kitchen counter, making matcha latte, pouring dense milk foam into mug, cute messy heart latte art, soft lighting, cozy sweater"
    },
    {
        "id": "m_fruit_yogurt_bowl",
        "category": "美食手作",
        "theme": "五彩斑斓的燕麦酸奶碗：把浓稠的希腊酸奶倒进玻璃碗，铺上满满的蓝莓、红草莓切片和香脆的坚果碎，看着就让人食指大动",
        "elements": ["酸奶碗", "草莓", "蓝莓", "坚果麦片", "玻璃碗"],
        "sd_hint": "morning, wooden dining table, colorful yogurt bowl topped with berries and granola, silver spoon, sunny windowsill background, appetizing"
    },
    {
        "id": "m_fluffy_pancakes",
        "category": "美食手作",
        "theme": "松软舒芙蕾松饼：慢火烘烤出两面金黄的小松饼，高高叠在一起，顶上放一块融化的黄油，淋上晶莹剔透、香气扑鼻的枫糖浆",
        "elements": ["松饼", "舒芙蕾", "枫糖浆", "黄油块", "甜点早餐"],
        "sd_hint": "morning, plate of fluffy pancake stack with melting butter cube and maple syrup drizzle, fork in hand, happy sparkling eyes, kitchen"
    },
    {
        "id": "m_warm_oatmeal_apple",
        "category": "美食手作",
        "theme": "肉桂烤苹果热燕麦粥：小锅里咕嘟咕嘟煮着香浓的牛奶燕麦，撒上一小勺肉桂粉和清甜的焦糖苹果粒，整个厨房都是温暖的气息",
        "elements": ["热燕麦粥", "肉桂香", "烤苹果", "咕嘟咕嘟", "暖烘烘"],
        "sd_hint": "morning, stove with simmering small pot, holding wooden spoon, bowl of warm oatmeal with cinnamon and apple slices, warm homey light"
    },
    {
        "id": "m_handdrip_coffee_bloom",
        "category": "美食手作",
        "theme": "手冲咖啡的焖蒸香气：细口壶注入热水，新鲜研磨的深烘咖啡粉在滤杯里像小蘑菇一样高高膨胀焖蒸，整个屋子弥漫着浓郁坚果醇香",
        "elements": ["手冲咖啡", "手冲壶", "滤杯", "膨胀焖蒸", "咖啡香"],
        "sd_hint": "morning, brewing pourover drip coffee, slender goose-neck kettle pouring water, coffee blooming in filter, aromatic steam, morning sun"
    },
    {
        "id": "m_fresh_orange_juice",
        "category": "美食手作",
        "theme": "现榨多汁橙汁：咔嚓切开两颗汁水饱满的甜橙，在榨汁器上用力旋转，清冽微酸的果香瞬间爆开，一杯倒满阳光的维C能量",
        "elements": ["鲜榨橙汁", "切橙子", "玻璃杯", "果汁飞溅", "维C满满"],
        "sd_hint": "morning, bright kitchen, slicing fresh juicy oranges, glass of freshly squeezed orange juice with ice cube, energetic cheerful vibe"
    },
    {
        "id": "m_waffle_baking_scent",
        "category": "美食手作",
        "theme": "华夫饼机叮的一声：华夫饼机散发出浓郁的香草奶香，伴随着清脆的叮当提示音，打开盖子是一块烤得格外均匀的焦糖色格子华夫",
        "elements": ["华夫饼", "华夫饼机", "香草味", "焦糖色", "格子"],
        "sd_hint": "morning, waffle maker with fresh golden checkered waffle, steam rising, sweet expression, wearing cozy domestic clothes, bright sunlight"
    },    # --- 4. 少女日常心情、生活小烦恼与小确幸（参考 jelly / 真实日记） ---
    {
        "id": "m_ahoge_hair_battle",
        "category": "少女日常",
        "theme": "镜子前跟顽固呆毛搏斗：今天头顶正中间不知为何倔强地翘起了一大撮呆毛，拿水抹、用夹子压，一松手它又弹起来，绝望了",
        "elements": ["镜子", "呆毛", "发夹", "梳子", "搏斗十分钟"],
        "sd_hint": "morning, bathroom mirror, holding hair clip and spray bottle, prominent funny ahoge bouncing up, funny troubled cute face, pajamas"
    },
    {
        "id": "m_backward_pajamas",
        "category": "少女日常",
        "theme": "迷迷糊糊把睡衣穿反了：坐在床沿揉了半天眼睛，喝了半杯水才突然发现自己居然把睡裤的正反面穿反了，怪不得前面兜鼓鼓的",
        "elements": ["穿反衣服", "迷迷糊糊", "揉眼睛", "床沿", "犯傻"],
        "sd_hint": "morning, sitting on bed edge, messy hair, rubbing eyes, wearing cute pajamas backward, sheepish silly cute smile, soft morning light"
    },
    {
        "id": "m_single_sock_missing",
        "category": "少女日常",
        "theme": "单只小猫袜子神秘失踪案：衣柜里明明洗好的小猫图案棉袜只剩下一只，翻遍床缝、沙发底和洗衣机筒都不见踪影，它是离家出走了吗",
        "elements": ["找袜子", "单只袜子", "翻找", "床底下", "小谜题"],
        "sd_hint": "morning, kneeling on carpet looking under bed, holding a single striped sock with cat print, puzzled confused expression, cute casual"
    },
    {
        "id": "m_plant_new_sprout",
        "category": "少女日常",
        "theme": "窗台绿植冒出小嫩芽：早起给窗台那盆半死不活的绿萝浇水，竟然在最底下的老茎上发现了一个米粒大小的新绿嫩芽，开心了一上午",
        "elements": ["盆栽", "嫩芽", "浇水壶", "窗台", "小惊喜"],
        "sd_hint": "morning, holding small pastel watering can, leaning over windowsill looking closely at tiny green sprout in ceramic pot, radiant happy face"
    },
    {
        "id": "m_tangled_earphones",
        "category": "少女日常",
        "theme": "有线耳机打了八十八个结：准备出门戴耳机听歌，从口袋里掏出来的有线耳机竟然打成了世界上最复杂死结，耐着性子解了整整五分钟",
        "elements": ["有线耳机", "解死结", "口袋里", "耐心告罄", "出门前"],
        "sd_hint": "morning, holding tangled white earphone wires, trying to untangle them, slight cute frown and puffed cheeks, entrance hallway"
    },
    {
        "id": "m_sunny_spot_cat",
        "category": "少女日常",
        "theme": "在地板光斑里抢地盘的小猫：地板上刚好有一块被窗框切出的长方形阳光，家里的猫已经先一步摊成了一张猫饼，忍不住凑过去一起蹭太阳",
        "elements": ["地板光斑", "猫咪", "晒太阳", "懒洋洋", "趴在地板上"],
        "sd_hint": "morning, lying on wooden floor in sunlight patch next to a sleeping fluffy cat, warm golden lighting, peaceful happy smile, lazy morning"
    },
    {
        "id": "m_journal_sticker_planner",
        "category": "少女日常",
        "theme": "手账本贴满闪亮贴纸：盘腿坐在地毯上打开手账本，小心翼翼地把刚买的小草莓贴纸贴在今天的日期格里，写下一句元气口号",
        "elements": ["手账本", "贴纸", "彩色水笔", "小目标", "仪式感"],
        "sd_hint": "morning, sitting cross-legged on fluffy rug, decorating notebook planner with shiny cute stickers, colorful pens, creative delightful mood"
    },
    {
        "id": "m_bed_seal_struggle",
        "category": "少女日常",
        "theme": "被窝强力封印术解除中：闹钟响了三次，被窝像有磁铁一样紧紧吸住后背，最后全靠对早餐流心蛋的强烈执念才勉强把自己拔出来",
        "elements": ["闹钟", "被窝磁铁", "打哈欠", "艰难起床", "拔出自己"],
        "sd_hint": "morning, entangled in fluffy duvet, peeking head out, yawning, sleepy eyes, struggling to get up, messy bed, warm indoor light"
    },
    {
        "id": "m_weather_dress_dilemma",
        "category": "少女日常",
        "theme": "天气预报和衣柜的大纠结：看着手机上的气温发愁，穿厚外套怕中午热，穿单衣怕早晚冻，最后还是套上了最万能的那件针织大开衫",
        "elements": ["穿衣纠结", "针织开衫", "换季天气", "试穿", "镜前"],
        "sd_hint": "morning, standing in front of open wardrobe, holding two different sweaters in each hand, contemplating expression, bedroom clothes racks"
    },
    {
        "id": "m_warm_water_lemon",
        "category": "少女日常",
        "theme": "第一杯温热柠檬水：早起空腹喝一杯加了一片鲜黄柠檬的温水，微酸微甘顺着喉咙滑下去，感觉整个人慢悠悠地重新通上了电",
        "elements": ["柠檬水", "玻璃杯", "温水", "通上电", "清爽晨间"],
        "sd_hint": "morning, holding clear glass mug with warm water and floating lemon slice, steam rising, taking a sip, refreshed relaxed face, kitchen"
    },
    {
        "id": "m_balcony_stretch",
        "category": "少女日常",
        "theme": "阳台大大的深呼吸与拉伸：走到阳台上把手臂高高举过头顶用力伸了个懒腰，骨头咔吧轻响一声，吸满一肚子的清冽新鲜空气",
        "elements": ["阳台", "伸懒腰", "拉伸", "深呼吸", "好精神"],
        "sd_hint": "morning, standing on balcony, stretching arms high overhead, yawning slightly, wind blowing hair, sunny sky, refreshed full body pose"
    },
    {
        "id": "m_sparrow_outside_window",
        "category": "少女日常",
        "theme": "窗外电线上排排坐的胖麻雀：窗台外的电线上并排蹲着三只圆滚滚像毛球一样的小麻雀，小脑袋左晃右晃，好像在开晨间例会",
        "elements": ["麻雀", "圆滚滚", "电线杆", "窗外", "歪脑袋"],
        "sd_hint": "morning, resting chin on window frame, looking at cute round sparrows perched on outdoor wire, soft cinematic morning light, amused smile"
    },
    {
        "id": "m_ice_cube_plink",
        "category": "少女日常",
        "theme": "冰块落进玻璃杯的脆响：把制冰盒里冻得晶莹剔透的方冰块按进玻璃杯，咔哒脆响听着就让人心情愉悦，夏天好像提前到了三秒",
        "elements": ["冰块", "玻璃杯", "制冰盒", "咔哒清脆", "心情愉悦"],
        "sd_hint": "morning, popping ice cubes from ice tray into transparent tall glass, crystal clear ice, splashes, refreshing vibe, cheerful expression"
    },
    {
        "id": "m_hair_accessory_pick",
        "category": "少女日常",
        "theme": "挑一个今天幸运发夹：在首饰盒里翻来翻去，最后挑中了那只毛茸茸的小兔耳朵发夹，别在刘海侧面，今天一定要做个幸运满分女孩",
        "elements": ["首饰盒", "发夹", "毛茸茸", "刘海", "开运小饰品"],
        "sd_hint": "morning, clipping a cute small hair accessory onto bangs in mirror, delicate jewelry box open on dressing table, radiant sweet smile"
    },
    {
        "id": "m_clean_bedsheet_sun",
        "category": "少女日常",
        "theme": "阳台挂满晒太阳的白床单：把刚脱水好的床单用力抖开挂在晾衣绳上，微风一吹鼓得像一面白帆，空气里全是阳光晒暖的味道",
        "elements": ["晒床单", "阳台", "抖开", "白帆", "阳光香味"],
        "sd_hint": "morning, outdoor sunny balcony, hanging clean white bedsheet on clothesline, sheet billowing in wind, bright sunlight, gentle joyful posture"
    },    # --- 5. 学习、创作与今日期待 ---
    {
        "id": "m_desk_stationery_neat",
        "category": "期待与计划",
        "theme": "把书桌收拾得一尘不染：把散落的彩笔排整齐、电脑屏幕擦得干干净净，看着井井有条的小桌面，学习工作的干劲突然暴涨两百倍",
        "elements": ["擦桌子", "整齐书桌", "彩笔排列", "干劲满满", "一尘不染"],
        "sd_hint": "morning, neat organized wooden desk, rows of pastel stationery pens, wiping desk with cloth, proud energized smile, modern aesthetic"
    },
    {
        "id": "m_morning_playlist_tune",
        "category": "期待与计划",
        "theme": "随机播放撞见神仙老歌：耳机里随机到一首好久没听的高中时期老歌，前奏吉他响起的瞬间整个人跟着节奏轻轻晃动起脑袋",
        "elements": ["耳机", "随机歌单", "宝藏老歌", "晃脑袋", "心情起飞"],
        "sd_hint": "morning, wearing over-ear headphones, closed eyes gently bobbing head to music, cozy room, sunlight dancing on face, blissful mood"
    },
    {
        "id": "m_library_first_row",
        "category": "期待与计划",
        "theme": "抢到图书馆靠窗黄金位：清晨一路小跑刚好抢到图书馆采光最好的靠窗大桌子，把水杯和帆布包放下的瞬间获得了全天最高的成就感",
        "elements": ["图书馆", "靠窗大桌", "帆布包", "保温杯", "成就感"],
        "sd_hint": "morning, library study hall, sitting at quiet desk by huge arched window, canvas tote bag, laptop, satisfied relieved smile"
    },
    {
        "id": "m_art_sketch_warmup",
        "category": "期待与计划",
        "theme": "晨间手绘板涂鸦热身：泡上热茶握着压感笔在数位板上随手画了几只歪歪扭扭的可爱圆滚小猫，线条格外顺畅，感觉今天手感无敌",
        "elements": ["手绘板", "压感笔", "涂鸦小猫", "线条顺畅", "手感火热"],
        "sd_hint": "morning, drawing on digital tablet, stylus in hand, screen showing cute doodle sketches, cup of tea steaming, focused happy face"
    },
    {
        "id": "m_fresh_notebook_open",
        "category": "期待与计划",
        "theme": "翻开一本崭新空白手账：指尖抚过细腻微黄的特种纸张，在新本子的第一页工工整整写下今天的新日期，像开启了一场未知的探险",
        "elements": ["新本子", "空白页", "墨水笔", "开篇第一天", "仪式感满满"],
        "sd_hint": "morning, opening brand new pristine paper notebook, holding fountain pen poised to write, pristine wooden desk, morning soft shadows"
    },
    {
        "id": "m_running_track_breeze",
        "category": "期待与计划",
        "theme": "红色塑胶跑道踏晨光：操场跑道上还带着露水，换上跑鞋踩在弹力十足的塑胶地面上，耳机里放着节奏感强烈的快歌，脚步越来越轻盈",
        "elements": ["操场跑道", "跑鞋", "快节奏歌", "脚步轻盈", "露水"],
        "sd_hint": "morning, red athletic track, sports running shoes, active running pose, ponytail bouncing, clear morning sky, athletic vibrant glow"
    },
    {
        "id": "m_weekend_trip_packing",
        "category": "期待与计划",
        "theme": "整理周末短途小行李箱：把换洗衣物卷成小卷、塞进折叠伞和相机，最后把充电宝充满电，只要想到明天的短途旅行嘴角就压不下来",
        "elements": ["行李箱", "收拾衣服", "相机", "期待周末", "嘴角上扬"],
        "sd_hint": "morning, packing a small pastel pastel suitcase on floor, rolling cute clothes, camera on bed, excited joyful expression"
    },
    {
        "id": "m_green_tea_steam",
        "category": "期待与计划",
        "theme": "玻璃杯里的明前绿茶：热水倒进透明杯里，原本蜷缩的嫩绿茶叶一根根缓缓竖立、在水中上下翻滚，看着心情也跟着慢了下来",
        "elements": ["绿茶", "茶叶翻滚", "透明玻璃杯", "清香", "放慢节奏"],
        "sd_hint": "morning, holding clear glass cup with floating tender green tea leaves dancing in water, steam swirling, tranquil expression, tatami room"
    }
]

NIGHT_THEME_POOL = [    # --- 1. 大自然风景、星空、晚霞与户外野趣 ---
    {
        "id": "n_beach_sunset_glow",
        "category": "自然风景",
        "theme": "海滩粉紫晚霞漫步：潮水一层层漫过光脚踝带来微凉的触感，天边像打翻的调色盘一样晕染开绝美的粉紫与橙黄渐变色晚霞",
        "elements": ["海滩", "晚霞", "粉紫色天空", "潮水漫过脚踝", "海风拂面"],
        "sd_hint": "evening twilight, walking barefoot on sandy beach, magnificent pink and purple sunset glow over ocean, reflections on wet sand, serene dress"
    },
    {
        "id": "n_rooftop_blue_hour",
        "category": "自然风景",
        "theme": "天台蓝调时刻吹晚风：落日刚刚沉入地平线，天空呈现出深邃通透的静谧靛蓝色，趴在天台栏杆上看整座城市的万家灯火一盏盏点亮",
        "elements": ["蓝调时刻", "天台栏杆", "深蓝天空", "万家灯火", "吹晚风"],
        "sd_hint": "night, twilight blue hour, rooftop railing, looking out over shimmering city lights below, deep blue sky, wind blowing oversized cardigan"
    },
    {
        "id": "n_stargazing_milky_way",
        "category": "自然风景",
        "theme": "远离城市的璀璨银河：仰面躺在草坡上，没有城市光污染的夜空里缀满了密密麻麻的繁星，银河像一条发光的白纱横跨天际",
        "elements": ["草地", "星空", "银河", "繁星密布", "仰望夜空"],
        "sd_hint": "night, lying on grassy hill looking up at breathtaking starry night sky, visible milky way galaxy, magical sparkling stars, peaceful awe"
    },
    {
        "id": "n_summer_night_rain",
        "category": "自然风景",
        "theme": "倚着窗台听夏夜雷雨：窗外暴雨哗哗砸在玻璃和阔叶芭蕉上，屋里只留一盏暗暖的阅读灯，空气里飘进雨水打湿泥土的清凉芳香",
        "elements": ["夜雨", "窗台水珠", "雨声", "阅读灯", "湿润泥土香"],
        "sd_hint": "night, sitting by window watching rain pouring outside, rain droplets running down glass pane, dim cozy indoor light, listening to thunder"
    },
    {
        "id": "n_lakeside_campfire",
        "category": "自然风景",
        "theme": "湖畔露营小篝火：围坐在噼啪作响的暖橘色篝火旁，偶尔有火星轻盈地飞向夜空，拿铁签串着棉花糖烤到表面微黄流心",
        "elements": ["篝火", "噼啪作响", "烤棉花糖", "湖面倒影", "露营椅"],
        "sd_hint": "night, lakeside camping, glowing warm campfire, roasting marshmallows on stick, sparks flying up, wrapped in wool blanket, cozy warm glow"
    },
    {
        "id": "n_wheat_field_dusk",
        "category": "自然风景",
        "theme": "麦田尽头的落日熔金：夕阳把广袤麦浪染成炽烈耀眼的火红金光，凉爽的晚风掀起阵阵波浪，站在田埂上久久舍不得眨眼",
        "elements": ["麦田落日", "落日熔金", "晚风掀麦浪", "田埂", "暮色"],
        "sd_hint": "dusk, vast wheat field under blazing golden sunset, fiery orange and crimson clouds, wind rippling crops, silhouetted gentle figure"
    },
    {
        "id": "n_old_town_lanterns",
        "category": "自然风景",
        "theme": "古镇夜巷红灯笼：石板桥下泊着暗影摇曳的乌篷船，屋檐下的红灯笼一串串亮起，水面碎金闪烁，夜游的人声隐隐约约传开",
        "elements": ["水乡古镇", "红灯笼", "石板路", "河水倒影", "乌篷船"],
        "sd_hint": "night, ancient water town street, glowing red paper lanterns hanging from eaves, reflections dancing on canal water, quiet historical charm"
    },
    {
        "id": "n_forest_fireflies",
        "category": "自然风景",
        "theme": "溪流边闪烁的萤火虫：循着潺潺流水声走到小树林深处，草丛间浮动起星星点点柔绿色的微光，像误入了神秘梦幻的精灵秘境",
        "elements": ["小溪流", "萤火虫", "绿色微光", "神秘树林", "梦幻童话"],
        "sd_hint": "night, deep forest creek, surrounded by glowing green fireflies dancing in air, magical ethereal lighting, hand outstretched, wonder eyes"
    },
    {
        "id": "n_mountain_night_view",
        "category": "自然风景",
        "theme": "半山腰俯瞰城市星海：夜间爬到半山腰的观景台，脚下是整座城市纵横交错如金色血管般的车流与霓虹，吹着带露水的冷风",
        "elements": ["山腰夜景", "城市霓虹", "车流金线", "晚风吹拂", "俯瞰"],
        "sd_hint": "night, mountain overlook, viewing glittering sea of city neon lights below, winding roads like gold ribbons, crisp cool wind blowing hair"
    },
    {
        "id": "n_winter_snow_night",
        "category": "自然风景",
        "theme": "路灯下静谧飘落的初雪：深夜推开门，路灯昏黄的光晕里正无声地旋转飘落着大朵大朵的初雪，全世界好像被按下了静音键",
        "elements": ["初雪", "昏黄路灯", "雪花飘落", "万籁俱寂", "哈气白雾"],
        "sd_hint": "night, standing under warm yellow street lamp, soft big snowflakes falling quietly around, breath visible in cold air, scarf and coat"
    },    # --- 2. 少女深夜心情日记、生活小烦恼与小确幸（深度参考 jelly） ---
    {
        "id": "n_bed_gap_cable_rescue",
        "category": "少女心情",
        "theme": "3%电量在床缝捞充电线：手机电量只剩3%开始疯狂闪红，充电线却滑进了床头和墙壁最深处的夹缝，趴在床板上捞得满头大汗",
        "elements": ["3%电量", "床缝捞线", "急中生智", "趴在床板", "红电量焦虑"],
        "sd_hint": "night, lying on messy bed reaching arm deep into crevice behind headboard, phone screen glowing red low battery icon, desperate funny cute face"
    },
    {
        "id": "n_static_electricity_shock",
        "category": "少女心情",
        "theme": "脱珊瑚绒睡衣的噼啪静电：关上灯准备钻进被窝，脱掉厚睡衣的瞬间整件衣服噼里啪啦冒火花，头发瞬间全部炸成蒲公英，呆在原地不敢动",
        "elements": ["静电火花", "珊瑚绒睡衣", "炸毛蒲公英", "噼里啪啦", "不敢动弹"],
        "sd_hint": "night, dark bedroom, tiny blue static electricity sparks crackling, hair standing up like dandelion poof, startled wide eyes, cute funny comic"
    },
    {
        "id": "n_midnight_fridge_hunt",
        "category": "少女心情",
        "theme": "深夜冰箱寻宝小贼：蹑手蹑脚拉开冰箱门，冷白的光照亮整张脸，在冷藏室角落成功挖出一盒被遗忘的草莓牛奶布丁，快乐得像中了彩票",
        "elements": ["深夜冰箱", "冷白光", "蹑手蹑脚", "布丁", "寻宝成功"],
        "sd_hint": "night, dark kitchen illuminated only by open refrigerator glow, crouching in front of fridge, holding small pudding jar, mischievous happy smile"
    },
    {
        "id": "n_aroma_carpet_spacing_out",
        "category": "少女心情",
        "theme": "地毯香薰与深度放空：点上喜欢的白茶淡香氛，抱着圆滚滚的大抱枕坐在毛绒地毯上放空发呆，把一整天转个不停的脑子彻底关机",
        "elements": ["毛绒地毯", "白茶香薰", "大抱枕", "大脑关机", "深度放空"],
        "sd_hint": "night, sitting on plush white rug hugging a huge round cushion, small aroma diffuser with delicate mist, warm floor lamp, peaceful glazed look"
    },
    {
        "id": "n_phone_drop_face",
        "category": "少女心情",
        "theme": "躺着玩手机正中鼻梁：困得眼皮打架还舍不得放下手机，手一滑手机啪叽一声直直砸在鼻梁上，疼得眼泪瞬间飙出来，立刻老实了",
        "elements": ["手滑砸脸", "砸鼻梁", "飙眼泪", "困意全无", "老实关灯"],
        "sd_hint": "night, lying on back in bed, phone slipping from hands right above face, comical shocked expression, hands in air, soft blanket, dim light"
    },
    {
        "id": "n_hot_bath_bubble_daze",
        "category": "少女心情",
        "theme": "热腾腾的泡泡浴放空：整个人泡进散发着薰衣草香气的大浴缸里，把绵密的白泡泡堆在头顶做成小厨师帽，满身疲惫像方糖一样融化了",
        "elements": ["泡泡浴", "薰衣草香", "头顶泡沫帽", "方糖融化", "彻底放松"],
        "sd_hint": "night, luxurious warm bubble bath, foam piled like a little hat on head, damp rosy cheeks, candlelight around tub, blissful relaxed eyes"
    },
    {
        "id": "n_blanket_burrito_roll",
        "category": "少女心情",
        "theme": "把自己卷成严实大煎饼：抓住被子两角像滚轴一样在床上连滚两圈，把自己从头到脚裹得严丝合缝，只露出一双眼睛，安全感直接拉满",
        "elements": ["裹成卷", "被子煎饼", "只露眼睛", "连滚两圈", "安全感爆棚"],
        "sd_hint": "night, wrapped tightly like a burrito roll in thick duvet, only round eyes and bangs peeking out, cozy bed, warm gentle moonlight"
    },
    {
        "id": "n_midnight_water_crisp",
        "category": "少女心情",
        "theme": "半夜醒来那一杯甘甜凉水：半夜口渴迷迷糊糊爬起来倒水，一口气咕嘟咕嘟喝下大半杯凉白开，感觉从喉咙一直凉爽通透到脚趾尖",
        "elements": ["半夜喝水", "咕嘟咕嘟", "喉咙甘冽", "月光洒地", "通透舒畅"],
        "sd_hint": "night, kitchen illuminated by pale moonlight, drinking a large glass of water, messy bed hair, oversized t-shirt, refreshed relieved expression"
    },
    {
        "id": "n_pillow_cold_side_flip",
        "category": "少女心情",
        "theme": "翻过枕头找凉快那一面：脑袋枕热了，双手把蓬松的大枕头翻了个面，脸颊贴上去那一瞬间冰凉细腻的触感，简直是入睡前的人间至宝",
        "elements": ["枕头翻面", "冰凉面", "贴脸颊", "细腻触感", "瞬间安详"],
        "sd_hint": "night, hugging fluffy pillow, pressing cheek lovingly against cool side of pillow, sleepy satisfied smile, soft warm ambient lighting"
    },
    {
        "id": "n_rainy_blanket_reading",
        "category": "少女心情",
        "theme": "被窝打小手电翻漫画：钻进厚被窝里支起一个秘密小帐篷，就着暖黄色的小阅读灯看最喜欢的那本治愈系漫画，谁也别来打扰我的世界",
        "elements": ["被窝帐篷", "小手电", "看漫画", "秘密空间", "治愈时光"],
        "sd_hint": "night, under blanket fortress, small flashlight illuminating pages of a manga book, focused cute eyes, knees tucked, safe cozy sanctuary"
    },    # --- 3. 街市夜色、便利店暖光与归途 ---
    {
        "id": "n_convenience_store_oden",
        "category": "城市晚间",
        "theme": "深夜便利店关东煮热汤：推开玻璃门叮咚一响，站在咕嘟冒泡的关东煮格子前，咬一口吸饱了热高汤的白萝卜，暖流顺着胃部散开",
        "elements": ["便利店", "关东煮", "白萝卜热汤", "叮咚门铃", "深夜暖胃"],
        "sd_hint": "late night, 24h convenience store counter, steaming oden compartment, holding paper cup with skewer, warm illuminated shop window, cold night outside"
    },
    {
        "id": "n_late_bus_window_lights",
        "category": "城市晚间",
        "theme": "末班公交后排靠窗发呆：坐在空荡荡的末班车最后一排，额头轻轻抵着微震的车窗，看街边璀璨的霓虹光晕被车窗拉成绚丽的光斑",
        "elements": ["末班公交", "后排靠窗", "霓虹光斑", "微震车窗", "疲惫与宁静"],
        "sd_hint": "night, back seat of nearly empty night bus, leaning head against window glass, city bokeh blur lights outside, earphones in, melancholic peaceful face"
    },
    {
        "id": "n_night_walk_music",
        "category": "城市晚间",
        "theme": "夜间散步与心动单曲循环：塞着降噪耳机走在安静无人的林荫小路上，晚风把树叶吹得沙沙作响，踩着路灯投下的自己的影子往前跳",
        "elements": ["夜间散步", "踩影子", "降噪耳机", "沙沙树叶", "独处自在"],
        "sd_hint": "night, quiet suburban street under street lamps, walking while stepping on cast shadows, oversized hoodie, over-ear headphones, playful relaxed walk"
    },
    {
        "id": "n_night_snack_street",
        "category": "城市晚间",
        "theme": "夜市街角那碗热腾腾的炒粉：大排档铁锅翻炒激起浓烈锅气，热腾腾的鸡蛋豆芽炒粉盛在盘子里，坐在塑料红椅子上大口吃得格外满足",
        "elements": ["夜市", "铁锅炒粉", "大排档锅气", "红塑料凳", "热气腾腾"],
        "sd_hint": "night, lively night food market, eating hot stir-fried noodles at street stall, vapor rising, red plastic stool, joyful foodie expression"
    },
    {
        "id": "n_late_supermarket_clearance",
        "category": "城市晚间",
        "theme": "深夜超市临期打折抢购：九点半准时守在生鲜区，眼看着阿姨啪啪给豪华刺身和现烤面包贴上五折黄色大标签，抢到了最后一盒寿司",
        "elements": ["超市晚间", "五折标签", "抢打折", "最后一盒寿司", "战利品"],
        "sd_hint": "night, supermarket aisle, holding a box of discounted sushi with big yellow 50% off sticker, triumphant playful grin, shopping basket on arm"
    },
    {
        "id": "n_balcony_night_city_hum",
        "category": "城市晚间",
        "theme": "阳台远望深夜车流光轨：捧着杯热牛奶站在阳台上，远处环线高架上的车灯拉出长长一条金色红色的流光，整座城市渐渐沉入梦乡",
        "elements": ["阳台看车流", "光轨", "热牛奶", "城市夜景", "渐渐沉睡"],
        "sd_hint": "late night, high floor balcony, holding warm mug of milk with both hands, distant highway taillight trails, city falling asleep, gentle tranquil gaze"
    },
    {
        "id": "n_midnight_bakery_whiff",
        "category": "城市晚间",
        "theme": "夜跑偶遇老面包房开炉：路过深巷里的老面包作坊，虽然卷闸门紧闭，但排气扇正疯狂往外吹出刚烤好的浓烈奶油麦香，香得迈不开腿",
        "elements": ["面包排气扇", "深夜麦香", "停下脚步", "深巷老店", "肚子咕咕叫"],
        "sd_hint": "night, cobblestone alleyway outside closed bakery door, sniffing sweet warm baking bread smell drifting from vent, funny tempted cute expression"
    },    # --- 4. 睡前仪式、治愈手作与深度安宁 ---
    {
        "id": "n_footbath_wooden_bucket",
        "category": "安睡仪式",
        "theme": "热腾腾的木桶泡脚发汗：把双脚泡进撒了艾草和生姜的滚烫木桶里，热气从脚底板一路往上窜，后背渗出一层薄薄的微汗，通体舒泰",
        "elements": ["木桶泡脚", "生姜艾草", "后背微汗", "通体舒泰", "热毛巾"],
        "sd_hint": "night, sitting on stool soaking feet in traditional wooden bucket with rising steam, rosy flushed cheeks, cozy soft towel, supreme relaxation"
    },
    {
        "id": "n_night_skincare_pats",
        "category": "安睡仪式",
        "theme": "睡前护肤与拍爽肤水：在脸上厚厚抹一层水润的晚安面霜，双手轻轻啪啪拍打着脸颊让它吸收，镜子里自己的脸蛋像刚剥壳的白煮蛋",
        "elements": ["睡前护肤", "晚安面霜", "啪啪拍脸", "水润透亮", "镜前发带"],
        "sd_hint": "night, bathroom vanity mirror, wearing plush hairband, gently patting moisturizing face cream onto cheeks, dewy glowing skin, cute pajamas"
    },
    {
        "id": "n_bedtime_plushie_rollcall",
        "category": "安睡仪式",
        "theme": "床上毛绒玩偶大点兵：把床头的大白鹅、小熊和长条猫咪玩偶整整齐齐在枕头边排成一排，每一只都揉揉脑袋互道一句晚安再睡觉",
        "elements": ["玩偶点兵", "大白鹅", "揉揉脑袋", "枕头边排列", "童心安眠"],
        "sd_hint": "night, bedroom, tucking plush toys (giant goose and teddy bear) in beside pillow under duvet, lovingly patting plush heads, childlike sweetness"
    },
    {
        "id": "n_white_noise_rain_app",
        "category": "安睡仪式",
        "theme": "定时白噪音雨声催眠：在床头音箱放上30分钟定时的森林细雨白噪音，听着雨滴落在落叶上的沉闷沙沙声，眼皮像灌了铅一样合上",
        "elements": ["白噪音", "森林雨声", "定时关闭", "眼皮打架", "极速入眠"],
        "sd_hint": "night, lying on side in dark cozy bedroom, small bedside speaker emitting faint blue light, closed eyes sinking deep into pillow, deeply asleep"
    },
    {
        "id": "n_camomile_honey_tea",
        "category": "安睡仪式",
        "theme": "暖胃洋甘菊金黄蜂蜜水：泡一杯温热澄澈的洋甘菊茶，调入一小勺浓稠的金黄椴树蜜，慢慢抿完最后一口，肚子里暖洋洋的踏实感",
        "elements": ["洋甘菊茶", "蜂蜜", "暖胃", "金色茶汤", "睡前踏实"],
        "sd_hint": "night, sitting on edge of bed holding warm porcelain teacup with golden chamomile tea, honey spoon, steam curling up, soft golden lamp light"
    },
    {
        "id": "n_bedside_candle_snuff",
        "category": "安睡仪式",
        "theme": "熄灭床头最后一盏烛火：用金色灭烛罩轻轻盖在散发着琥珀木质香的蜡烛上，看着细细一缕青烟升起散去，房间彻底归于温软的黑暗",
        "elements": ["灭烛罩", "木质香蜡烛", "一缕青烟", "黑暗降临", "安心入睡"],
        "sd_hint": "night, bedside table, gently snuffing out scented candle with brass snuffer, delicate curl of smoke rising, warm shadow and moonlight mixture"
    },
    {
        "id": "n_soft_pillow_deep_breath",
        "category": "安睡仪式",
        "theme": "陷进巨大蓬松软枕里：整张脸轻轻埋进散发着阳光晒过味道的洁白羽绒枕里，深吸一口气慢慢吐出来，今天的所有事情就到此为止啦",
        "elements": ["深陷软枕", "羽绒枕", "阳光晒过味", "深呼一口气", "到此为止"],
        "sd_hint": "night, sinking face side into massive ultra-soft white fluffy down pillow, closed eyes with long eyelashes, serene peaceful expression, sleep"
    },

    # --- 5. 更多深度安宁与旅行夜景扩充 ---
    {
        "id": "n_harbor_light_reflection",
        "category": "自然风景",
        "theme": "港口防波堤与引航灯：海浪轻轻拍打着防波堤的水泥石块，远处的红色引航灯塔一闪一灭，深蓝色的海水里倒映着碎金般波光",
        "elements": ["防波堤", "引航灯塔", "深蓝海水", "海浪拍岸", "独坐听海"],
        "sd_hint": "night, coastal harbor breakwater, red lighthouse beacon flashing in distance, dark blue ocean reflections, sitting watching waves"
    },
    {
        "id": "n_night_art_museum",
        "category": "城市晚间",
        "theme": "美术馆奇妙夜延时闭馆：赶在九点闭馆前静静站在最喜欢的那幅莫奈睡莲前，展厅里几乎没有人，柔和的射灯把画布照得格外静谧",
        "elements": ["美术馆", "睡莲画作", "柔和射灯", "无人展厅", "艺术沉浸"],
        "sd_hint": "night, quiet art museum gallery, standing in front of large impressionist painting, soft spotlight, casual elegant dress, serene wonder"
    },
    {
        "id": "n_rooftop_telescope",
        "category": "自然风景",
        "theme": "天台折射望远镜看月亮环形山：在顶楼架起简易小天文望远镜，目镜里月球表面的陨石坑和环形山清晰得触手可及，震撼得屏住呼吸",
        "elements": ["天文望远镜", "月亮环形山", "天台夜空", "目镜", "屏住呼吸"],
        "sd_hint": "night, rooftop, looking through small astronomical telescope pointing at glowing crescent moon, sparkling stars, joyful surprised look"
    },
    {
        "id": "n_vintage_record_jazz",
        "category": "安睡仪式",
        "theme": "黑胶唱机放慢摇爵士：把唱针轻轻落在旋转的复古黑胶唱片上，沙沙的底噪伴随着低沉温柔的萨克斯风流淌出来，整个房间变暖了",
        "elements": ["黑胶唱机", "萨克斯爵士", "沙沙底噪", "唱针", "复古氛围"],
        "sd_hint": "night, wooden turntable spinning vinyl record, arm needle placed on disc, warm dim amber lighting, relaxed posture on armchair"
    },
    {
        "id": "n_balcony_succulent_night",
        "category": "少女心情",
        "theme": "深夜视察阳台肉嘟嘟多肉：打着手机手电筒检查阳台上的桃蛋和小玉，被夜露滋润过多肉叶片圆滚滚泛着粉霜，像一盒彩色软糖",
        "elements": ["阳台多肉", "手机手电", "夜露", "粉霜软糖", "偷看植物"],
        "sd_hint": "night, balcony, illuminating small succulent potted plants with phone flashlight, smiling softly, oversized fluffy pajama sweater"
    },
    {
        "id": "n_night_sketch_doodle",
        "category": "少女心情",
        "theme": "睡前无意识铅笔涂鸦：铅笔在粗糙的速写本上沙沙划过，画了长耳朵的小兔子、咬了一口的草莓蛋糕和歪歪扭扭的星星，困意悄悄蔓延",
        "elements": ["速写本", "铅笔沙沙声", "随笔涂鸦", "困意蔓延", "乱涂乱画"],
        "sd_hint": "night, leaning on desk sketching cute rabbit and stars on paper notebook with pencil, cozy lamp light, yawning slightly, sleepy eyes"
    },
    {
        "id": "n_hot_honey_pear_soup",
        "category": "美食治愈",
        "theme": "小砂锅炖冰糖雪梨汤：砂锅里慢火炖着剔透的银耳雪梨，加了两颗红枣和一小把枸杞，汤汁滑糯清润，喝下去整副嗓子都舒服了",
        "elements": ["冰糖雪梨", "小砂锅", "清润滑糯", "红枣枸杞", "深夜暖喉"],
        "sd_hint": "night, small ceramic pot of steaming poached pear dessert soup, ceramic spoon, taking a careful warm sip, relieved sweet face"
    },
    {
        "id": "n_night_scented_candle_wax",
        "category": "安睡仪式",
        "theme": "看大豆蜡烛融成透明小池塘：盯着香氛蜡烛芯周围慢慢融化成一汪金黄透明的蜡油池，雪松与微甜香草的气息静静弥漫，心跳彻底平缓",
        "elements": ["香氛蜡烛", "融化蜡油", "雪松香草", "火苗跳跃", "平息杂念"],
        "sd_hint": "night, staring gently at flickering flame of scented candle melting into wax pool, delicate shadows on wall, serene zen expression"
    },
    {
        "id": "n_wind_chime_night_breeze",
        "category": "自然风景",
        "theme": "檐下玻璃风铃叮咚清响：夜风吹起窗帘的一角，挂在屋檐下的透明水滴风铃发出叮铃叮铃的清脆碰撞声，把白天的燥热全吹散了",
        "elements": ["玻璃风铃", "叮咚清脆", "屋檐夜风", "飘动窗帘", "清凉舒畅"],
        "sd_hint": "night, bedroom window open with billowing sheer curtain, delicate glass wind chime chiming outside under moonlight, peaceful smile"
    },
    {
        "id": "n_puzzle_last_piece",
        "category": "少女心情",
        "theme": "一千块拼图卡在最后一块：地毯上铺了一千块的梵高星空拼图，眼睛都看花了终于把右下角那块拼上，整副画完整了，心满意足滚去睡",
        "elements": ["拼图", "最后一小块", "大功告成", "星空图案", "滚去睡觉"],
        "sd_hint": "night, sitting on floor over large 1000-piece puzzle, pressing the final piece in place with two fingers, triumphant relieved grin"
    },
    {
        "id": "n_silk_eyemask_sleep",
        "category": "安睡仪式",
        "theme": "戴上真丝遮光眼罩深睡：戴上冰冰凉凉软滑的粉色真丝眼罩，把外界最后一丝光线隔绝开，抱紧长条形小恐龙抱枕，今晚一定会做好梦",
        "elements": ["真丝眼罩", "彻底黑暗", "恐龙抱枕", "无梦深睡", "晚安世界"],
        "sd_hint": "night, lying comfortably on pillow pulling down soft silk sleep mask over eyes, hugging plush pillow, serene peaceful sleep face"
    },
    {
        "id": "n_sleeping_music_loop",
        "category": "安睡仪式",
        "theme": "单曲循环一首钢琴纯音乐：把手机放在床头柜上调成飞行模式，空气里只有轻缓空灵的钢琴独奏声，像月光一样无声抚平了所有烦恼",
        "elements": ["飞行模式", "钢琴独奏", "空灵治愈", "抚平杂念", "渐入梦乡"],
        "sd_hint": "night, cozy bed, smartphone charging on nightstand, soft moonlight illuminating face, tranquil gentle breath, sinking into mattress"
    }
]

DAILY_VTUBER_THEMES = [
    # --- 少女日常生活心情、提问互动与趣味翻车（参考 @moonjelly0 / @jellyhoshiumi） ---
    {
        "id": "v_boba_sugar_level",
        "category": "提问互动",
        "theme": "奶茶甜度终极大调查：站在奶茶店点单屏前陷入沉思，大家喝奶茶到底是坚定的三分糖党还是全糖邪教？今天需要大家帮我决定！",
        "elements": ["奶茶", "三分糖", "点单纠结", "提问大家", "甜度党争"],
        "sd_hint": "daytime, standing outside boba tea shop holding menu, thoughtful curious cute face, finger on chin, casual street fashion"
    },
    {
        "id": "v_last_bread_miracle",
        "category": "日常小确幸",
        "theme": "买到货架上最后一个开心果面包：冲进面包店时开心果巴布卡只剩最后一个了，和身后走过来的大叔对视一秒光速抢下，今日幸运值超标！",
        "elements": ["开心果面包", "最后一个", "小跑步抢到", "幸运值拉满", "抱着纸袋笑"],
        "sd_hint": "afternoon, bakery interior, hugging a kraft paper bag with delicious bread, victorious proud beaming smile, sparkling background"
    },
    {
        "id": "v_rainy_day_stay_in",
        "category": "小情绪发散",
        "theme": "不想出门的合法理由：窗外淅淅沥沥下起了小雨，立刻名正言顺把出门计划全部取消，赖在沙发里抱着抱枕刷搞笑视频，快乐就是这么简单",
        "elements": ["下雨不出门", "取消计划", "沙发抱枕", "刷搞笑视频", "合情合理偷懒"],
        "sd_hint": "daytime, curled up on plush living room sofa, holding smartphone, rain streaming outside window, comfy loungewear, giggling happily"
    },
    {
        "id": "v_new_sticker_haul",
        "category": "文具生活",
        "theme": "文具店战利品炫耀时刻：本来只是想进去买根黑色水笔，结果出来时手里多了一整袋亮晶晶的激光贴纸和两卷碎花胶带，文具店有黑洞吧！",
        "elements": ["文具店黑洞", "买了一大袋", "激光贴纸", "碎花胶带", "本来只买笔"],
        "sd_hint": "afternoon, sitting at desk displaying colorful sticker sheets and decorative washi tapes, proud excited eyes, cute room decor"
    },
    {
        "id": "v_cloud_cat_shape",
        "category": "抬头看天",
        "theme": "天上飘着一只胖猫咪云：过马路抬头看天空，头顶正上方那团巨大的积雨云长了一对尖尖的耳朵和一条弯弯的尾巴，完全就是一只仰天大睡的胖橘猫！",
        "elements": ["猫咪形状云", "抬头看天", "过马路", "指着天上", "天马行空"],
        "sd_hint": "afternoon, city street crossing, looking up and pointing at fluffy white cloud shaped like sleeping cat, sunny blue sky, delighted child-like smile"
    },
    {
        "id": "v_spicy_snack_regret",
        "category": "搞笑翻车",
        "theme": "逞强挑战特辣零食现场翻车：包装上写着微辣我就信了，刚嚼两口直接辣到原地起跳疯狂吸气，到处找牛奶，舌头已经不是自己的了！",
        "elements": ["信了微辣", "辣到起跳", "到处找牛奶", "吐舌头扇风", "翻车现场"],
        "sd_hint": "afternoon, sitting on floor holding empty milk carton, tongue sticking out slightly with tears in eyes from spicy food, cute comical panic"
    },
    {
        "id": "v_weekend_plans_ask",
        "category": "提问互动",
        "theme": "周末到底去哪玩：本周进度条终于快见底啦，你们周末都打算干嘛呀？是出门吸氧还是跟我一样在被窝里长蘑菇？交出你们的攻略！",
        "elements": ["周五心动", "周末计划", "长蘑菇", "求大家攻略", "放假前夕"],
        "sd_hint": "Friday afternoon, desk with calendar marked with stars, leaning forward asking with hands on cheeks, sparkling anticipating eyes"
    },
    {
        "id": "v_room_rearrange_surge",
        "category": "日常折腾",
        "theme": "突然发作的房间大挪移冲动：不知道为什么，突然看书桌的方向不顺眼，一个人吭哧吭哧把书桌从东墙挪到了西墙，累得瘫倒但房间变全新了！",
        "elements": ["房间大挪移", "搬动书桌", "吭哧吭哧", "焕然一新", "瘫在地上"],
        "sd_hint": "afternoon, bedroom in slight disarray, sitting on floor leaning back against newly moved desk, wiping forehead, tired but satisfied grin"
    },
    {
        "id": "v_ice_cream_dripping",
        "category": "慌张小确幸",
        "theme": "跟烈日下融化的甜筒抢速度：刚买的双球冰淇淋在阳光下融化得比我吃的还快，粉色草莓奶油顺着蛋卷往下滴，手忙脚乱狂舔手腕",
        "elements": ["双球冰淇淋", "融化滴手腕", "手忙脚乱", "跟太阳抢速度", "甜甜蜜蜜"],
        "sd_hint": "sunny day, outdoor park bench, holding double scoop ice cream cone melting fast, hastily licking side of ice cream, funny panicked cute"
    },
    {
        "id": "v_coin_in_winter_coat",
        "category": "日常惊喜",
        "theme": "去年冬装口袋摸出一张纸币：天冷翻出压箱底的厚外套套上，手插进口袋居然摸到了一张叠得整整齐齐的二十块钱，感觉是过去的自己给我寄的礼物！",
        "elements": ["口袋捡到钱", "压箱底外套", "过去自己的礼物", "天降巨款", "偷着乐"],
        "sd_hint": "chilly day, wearing oversized winter coat, holding up a folded 20 banknote pulled from pocket, ecstatic surprised face, glowing joyful vibe"
    },
    {
        "id": "v_diy_drink_concoction",
        "category": "厨房实验",
        "theme": "神秘厨房自制特饮试毒：把乌龙茶、西柚汁、气泡水和薄荷叶混在一起倒进大玻璃杯，颜色好看得像魔法药水，第一口下去居然意外地好喝！",
        "elements": ["自制特饮", "魔法药水", "气泡水西柚", "意外好喝", "家庭调酒师"],
        "sd_hint": "afternoon, kitchen counter, holding tall clear glass layered with pink grapefruit and sparkling tea drink, mint leaf on top, proud adventurous smile"
    },
    {
        "id": "v_stray_cat_friendship",
        "category": "生灵互动",
        "theme": "小巷橘猫终于让我摸下巴了：路口便利店后面那只高冷的大胖橘，我蹲在路边跟它无声对视了整整三分钟，它终于主动走过来用脑门狠狠蹭了我的手！",
        "elements": ["收服高冷猫", "蹭手心", "小巷大胖橘", "无声对视", "原地融化"],
        "sd_hint": "afternoon, crouching in quiet alleyway, gently scratching chin of a chubby tabby cat leaning into hand, radiant tender heartwarming smile"
    },
    # --- 更多日常爆笑与治愈碎片 ---
    {
        "id": "v_bubble_wrap_pop",
        "category": "解压日常",
        "theme": "捏气泡膜根本停不下来：拆快递剩下的两米长大泡泡纸，本来只想捏一个听个响，结果坐在地上啪啪啪捏了二十分钟，灵魂被洗涤了！",
        "elements": ["捏气泡膜", "快递包装", "停不下来", "噼里啪啦", "解压神物"],
        "sd_hint": "afternoon, sitting surrounded by shipping boxes, pinching bubble wrap with thumbs, concentrated comical bliss, room floor"
    },
    {
        "id": "v_hair_tie_wrist_mark",
        "category": "少女日常",
        "theme": "手腕上的皮筋勒出小手镯：摘下手腕上套了一整天的小皮筋，手腕上勒出了一圈粉粉红红的印子，揉了半天像戴了个隐形手镯！",
        "elements": ["皮筋勒痕", "手腕红印", "揉手腕", "生活小痕迹", "呆呆发笑"],
        "sd_hint": "afternoon, sitting by window, rubbing wrist with cute red indentation from hairband, amused silly smile, casual daily clothes"
    },
    {
        "id": "v_stationery_tape_cut",
        "category": "文具生活",
        "theme": "手撕胶带撕出完美直角：今天用手撕碎花和纸胶带，竟然一秒撕出了一个极其笔直平整的90度直角！强迫症当场起立鼓掌！",
        "elements": ["撕胶带", "完美直角", "强迫症狂喜", "和纸胶带", "起立鼓掌"],
        "sd_hint": "afternoon, craft desk, holding decorative washi tape roll with pristine straight cut edge, sparkling proud eyes, triumphant face"
    },
    {
        "id": "v_cold_breeze_shiver",
        "category": "季节小情绪",
        "theme": "出门被冷风吹出土拨鼠尖叫：以为今天是大晴天就只套了薄卫衣，一迈出单元门迎面一阵西北风把我吹得倒退两步，火速逃回家加外套！",
        "elements": ["被风吹退", "土拨鼠尖叫", "降温翻车", "逃回家加衣服", "瑟瑟发抖"],
        "sd_hint": "morning, outside front doorway, strong gust of wind blowing hair and clothes violently back, shivering funny face, arms crossed"
    },
    {
        "id": "v_cat_stealing_seat",
        "category": "生灵互动",
        "theme": "离开座位一秒椅子被占领：我就去厨房倒了半杯水，回来发现我的电竞椅正中央已经盘踞了一只假装熟睡的大毛球，怎么推都推不动！",
        "elements": ["椅子被抢", "装睡猫咪", "推不动", "倒水回来", "只能坐板凳"],
        "sd_hint": "afternoon, standing beside desk chair occupied by curled up sleeping cat, hands on hips looking helpless and amused, cozy room"
    },
    {
        "id": "v_favorite_snack_discontinued",
        "category": "日常小牢骚",
        "theme": "最喜欢的青梅果冻停产了：在便利店找了三家都没看到那款青梅味果冻，上网一搜居然停产了，心碎的声音比薯片脆响还清脆！",
        "elements": ["果冻停产", "心碎声音", "找遍便利店", "童年回忆", "晴天霹雳"],
        "sd_hint": "afternoon, looking down at empty supermarket shelf, hands gripping cheeks in dramatic melodrama shock, tears in anime eyes"
    },
    {
        "id": "v_camera_roll_accidental_selfie",
        "category": "搞笑翻车",
        "theme": "前置摄像头突然打开的死亡角度：躺在沙发上解锁手机，不知怎么点到了前置自拍，屏幕上赫然出现一个双下巴仰角大饼脸，被自己吓死！",
        "elements": ["前置摄像头", "死亡角度", "双下巴仰拍", "被自己吓跳", "光速划掉"],
        "sd_hint": "afternoon, lounging on couch, smartphone screen reflecting startled wide eyes and funny double chin angle, hilarious cute panic"
    }
]