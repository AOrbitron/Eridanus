# -*- coding: utf-8 -*-
"""
中国农历历法、二十四节气与节假日高精度离线计算辅助模块
完全摆脱对不稳定第三方 HTTP 老黄历接口的依赖。
支持：
1. 1900~2100 年精准公历转农历（含闰月计算、平闰小月判断）；
2. 除夕精准判断（彻底解决腊月二十九或三十非固定问题，自动向前探测）；
3. 二十四节气高精度天文计算（基于 VSOP/Meeus 太阳视黄经模型，精确到日）；
4. 传统农历节日（除夕、春节、元宵、龙抬头、上巳节、端午、七夕、中元、中秋、重阳、寒衣、下元、腊八、小年等）；
5. 现代公历重要节日（元旦、情人节、妇女节、植树节、劳动节、青年节、儿童节、建党节、建军节、教师节、国庆节、圣诞节等）。
"""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple, List

# 1900-2100 年农历数据压缩编码表
# 每个元素记录当年农历信息:
# bit 0-3: 闰月月份(0为无闰月)
# bit 4-15: 1-12月的各月大小月(1为30天大月, 0为29天小月)
# bit 16: 闰月大小月(1为30天, 0为29天)
CHINESEYEARCODE = [
    19416, 19168, 42352, 21717, 53856, 55632, 91476, 22176, 39632, 21970,
    19168, 42422, 42192, 53840, 119381, 46400, 54944, 44450, 38320, 84343,
    18800, 42160, 46261, 27216, 27968, 109396, 11104, 38256, 21234, 18800,
    25958, 54432, 59984, 92821, 23248, 11104, 100067, 37600, 116951, 51536,
    54432, 120998, 46416, 22176, 107956, 9680, 37584, 53938, 43344, 46423,
    27808, 46416, 86869, 19872, 42416, 83315, 21168, 43432, 59728, 27296,
    44710, 43856, 19296, 43748, 42352, 21088, 62051, 55632, 23383, 22176,
    38608, 19925, 19152, 42192, 54484, 53840, 54616, 46400, 46752, 103846,
    38320, 18864, 43380, 42160, 45690, 27216, 27968, 44870, 43872, 38256,
    19189, 18800, 25776, 29859, 59984, 27480, 23232, 43872, 38613, 37600,
    51552, 55636, 54432, 55888, 30034, 22176, 43959, 9680, 37584, 51893,
    43344, 46240, 47780, 44368, 21977, 19360, 42416, 86390, 21168, 43312,
    31060, 27296, 44368, 23378, 19296, 42726, 42208, 53856, 60005, 54576,
    23200, 30371, 38608, 19195, 19152, 42192, 118966, 53840, 54560, 56645,
    46496, 22224, 21938, 18864, 42359, 42160, 43600, 111189, 27936, 44448,
    84835, 37744, 18936, 18800, 25776, 92326, 59984, 27296, 108228, 43744,
    37600, 53987, 51552, 54615, 54432, 55888, 23893, 22176, 42704, 21972,
    21200, 43448, 43344, 46240, 46758, 44368, 21920, 43940, 42416, 21168,
    45683, 26928, 29495, 27296, 44368, 84821, 19296, 42352, 21732, 53600,
    59752, 54560, 55968, 92838, 22224, 19168, 43476, 41680, 53584, 62034,
    54560
]

START_DATE = date(1900, 1, 31)

LUNAR_MONTH_NAMES = ["", "正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "冬月", "腊月"]
LUNAR_DAY_NAMES = [
    "", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"
]

def solar_to_lunar(d: date) -> Tuple[int, int, int, bool, str]:
    """
    将公历日期转换为农历信息。
    返回: (lunar_year, lunar_month, lunar_day, is_leap, lunar_name_str)
    例如: (2024, 8, 15, False, '八月十五')
    """
    offset = (d - START_DATE).days
    if offset < 0:
        raise ValueError("暂不支持 1900-01-31 之前的日期")

    year = 1900
    while year < 2100:
        year_code = CHINESEYEARCODE[year - 1900]
        days_in_year = 0
        for m in range(1, 13):
            days_in_year += 30 if (year_code & (0x10000 >> m)) else 29
        leap_m = year_code & 0xf
        if leap_m > 0:
            days_in_year += 30 if (year_code & (1 << 16)) else 29

        if offset < days_in_year:
            break
        offset -= days_in_year
        year += 1

    year_code = CHINESEYEARCODE[year - 1900]
    leap_m = year_code & 0xf
    is_leap = False
    lunar_m = 1

    for m in range(1, 13):
        days_in_m = 30 if (year_code & (0x10000 >> m)) else 29
        if offset < days_in_m:
            lunar_m = m
            break
        offset -= days_in_m

        if leap_m == m:
            days_in_leap = 30 if (year_code & (1 << 16)) else 29
            if offset < days_in_leap:
                lunar_m = m
                is_leap = True
                break
            offset -= days_in_leap

    lunar_d = offset + 1
    m_name = ("闰" if is_leap else "") + LUNAR_MONTH_NAMES[lunar_m]
    d_name = LUNAR_DAY_NAMES[lunar_d]
    return year, lunar_m, lunar_d, is_leap, f"{m_name}{d_name}"

def get_lunar_date_str(d: Optional[date] = None) -> str:
    """返回农历日期中文描述，如 '农历八月十五'"""
    if d is None:
        d = date.today()
    try:
        _, _, _, _, name = solar_to_lunar(d)
        return f"农历{name}"
    except Exception:
        return ""

# -------------------------------------------------------------
# 二十四节气高精度天文视黄经模型 (基于 VSOP/Meeus 天文算法)
# -------------------------------------------------------------
def _get_solar_longitude(d: datetime) -> float:
    """计算指定 UTC 时间的太阳视黄经 (0~360度)"""
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t = (d - j2000).total_seconds() / 86400.0 / 36525.0
    M = 357.52910 + 35999.05030 * t - 0.0001559 * t * t - 0.00000048 * t * t * t
    M = math.radians(M % 360)
    L0 = 280.46645 + 36000.76983 * t + 0.0003032 * t * t
    C = (1.914600 - 0.004817 * t - 0.000014 * t * t) * math.sin(M) \
        + (0.019993 - 0.000101 * t) * math.sin(2 * M) \
        + 0.000290 * math.sin(3 * M)
    true_long = (L0 + C) % 360
    omega = math.radians(125.04 - 1934.136 * t)
    apparent_long = (true_long - 0.00569 - 0.00478 * math.sin(omega)) % 360
    return apparent_long

SOLAR_TERMS_ANGLES = [
    ('春分', 0), ('清明', 15), ('谷雨', 30), ('立夏', 45), ('小满', 60), ('芒种', 75),
    ('夏至', 90), ('小暑', 105), ('大暑', 120), ('立秋', 135), ('处暑', 150), ('白露', 165),
    ('秋分', 180), ('寒露', 195), ('霜降', 210), ('立冬', 225), ('小雪', 240), ('大雪', 255),
    ('冬至', 270), ('小寒', 285), ('大寒', 300), ('立春', 315), ('雨水', 330), ('惊蛰', 345)
]

TZ_BEIJING = timezone(timedelta(hours=8))

def get_solar_term(d: date) -> Optional[str]:
    """判断公历当天是否属于二十四节气之一，若是则返回节气名称，否则返回 None"""
    start_dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ_BEIJING).astimezone(timezone.utc)
    end_dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ_BEIJING).astimezone(timezone.utc)
    deg_start = _get_solar_longitude(start_dt)
    deg_end = _get_solar_longitude(end_dt)

    for name, target_deg in SOLAR_TERMS_ANGLES:
        if target_deg == 0:
            if deg_start > 350 and deg_end < 10:
                return name
        else:
            if deg_start <= target_deg < deg_end:
                return name
    return None

# -------------------------------------------------------------
# 传统农历节日与法定公历节日对照
# -------------------------------------------------------------
LUNAR_FESTIVALS = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (2, 2): "龙抬头",
    (3, 3): "上巳节",
    (5, 5): "端午节",
    (7, 7): "七夕节",
    (7, 15): "中元节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
    (10, 1): "寒衣节",
    (10, 15): "下元节",
    (12, 8): "腊八节",
    (12, 23): "小年",
    (12, 24): "小年",
}

SOLAR_FESTIVALS = {
    (1, 1): "元旦",
    (2, 14): "情人节",
    (3, 8): "妇女节",
    (3, 12): "植树节",
    (4, 1): "愚人节",
    (5, 1): "劳动节",
    (5, 4): "青年节",
    (6, 1): "儿童节",
    (7, 1): "建党节",
    (8, 1): "建军节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
    (10, 31): "万圣夜",
    (11, 1): "万圣节",
    (12, 24): "平安夜",
    (12, 25): "圣诞节",
}

def get_chinese_calendar_info(d: Optional[date] = None, include_lunar_if_none: bool = False) -> Optional[str]:
    """
    判断指定日期（默认当天）在中国日历中的节假日或节气名称。
    支持：
    1. 农历传统节日（除夕、春节、元宵、端午、中秋、七夕、重阳、腊八、小年等）；
    2. 二十四节气（立春、清明节、冬至、夏至、秋分、春分等）；
    3. 公历重要节日（元旦、五一劳动节、国庆节、儿童节等）。

    返回值：
    - 若当天为节日/节气，返回其名称（如存在重合则以顿号分隔，如 '国庆节、中秋节'）；
    - 若非节日/节气且 include_lunar_if_none 为 True，返回当前农历日期如 '农历八月廿一'；
    - 若非节日/节气且 include_lunar_if_none 为 False，返回 None。
    """
    if d is None:
        d = date.today()

    festivals: List[str] = []

    # 1. 精准判断除夕：只要明天是正月初一，今天就是除夕（兼顾腊月二十九或三十）
    tomorrow = d + timedelta(days=1)
    try:
        _, t_m, t_d, _, _ = solar_to_lunar(tomorrow)
        if t_m == 1 and t_d == 1:
            festivals.append("除夕")
    except Exception:
        pass

    # 2. 判断常规农历节日与春节黄金周
    try:
        _, l_m, l_d, is_leap, _ = solar_to_lunar(d)
        if not is_leap:
            l_fest = LUNAR_FESTIVALS.get((l_m, l_d))
            if l_fest and l_fest not in festivals:
                festivals.append(l_fest)
            # 春节长假假期 (正月初二至初七)
            if l_m == 1 and 2 <= l_d <= 7:
                if '春节长假' not in festivals and '春节' not in festivals:
                    festivals.append('春节长假')
    except Exception:
        pass

    # 3. 判断二十四节气
    try:
        st = get_solar_term(d)
        if st:
            if st == "清明":
                term_name = "清明节"
            else:
                term_name = st
            if term_name not in festivals:
                festivals.append(term_name)
    except Exception:
        pass

    # 4. 判断公历节日及法定长假黄金周
    s_fest = SOLAR_FESTIVALS.get((d.month, d.day))
    if s_fest and s_fest not in festivals:
        festivals.append(s_fest)

    # 十一国庆黄金周 (10月1日~10月7日)
    if d.month == 10 and 2 <= d.day <= 7:
        if '国庆长假（十一黄金周）' not in festivals and '国庆节' not in festivals:
            festivals.append('国庆长假（十一黄金周）')
    # 五一劳动节长假 (5月1日~5月5日)
    elif d.month == 5 and 2 <= d.day <= 5:
        if '五一劳动节长假' not in festivals and '劳动节' not in festivals:
            festivals.append('五一劳动节长假')
    # 元旦假期 (1月1日~1月3日)
    elif d.month == 1 and 2 <= d.day <= 3:
        if '元旦假期' not in festivals and '元旦' not in festivals:
            festivals.append('元旦假期')

    if festivals:
        return "、".join(festivals)

    if include_lunar_if_none:
        return get_lunar_date_str(d)

    return None


# -------------------------------------------------------------
# 四季与时令高精度天文视黄经划分
# -------------------------------------------------------------
def get_season_info(d: Optional[date] = None) -> dict:
    """
    高精度计算公历日期对应的季节与时令信息（基于 VSOP 太阳视黄经模型，精确到日）。
    划分规则遵循中国传统天文学四立（立春、立夏、立秋、立冬）与二十四节气：
    - 春季: 315° <= 太阳视黄经 < 45° (立春至立夏前)
      - 初春 (315°~345°): 立春、雨水
      - 仲春 (345°~15°): 惊蛰、春分
      - 暮春 (15°~45°): 清明、谷雨
    - 夏季: 45° <= 太阳视黄经 < 135° (立夏至立秋前)
      - 初夏 (45°~75°): 立夏、小满
      - 盛夏 (75°~105°): 芒种、夏至
      - 晚夏 (105°~135°): 小暑、大暑
    - 秋季: 135° <= 太阳视黄经 < 225° (立秋至立冬前)
      - 初秋 (135°~165°): 立秋、处暑
      - 仲秋 (165°~195°): 白露、秋分
      - 深秋 (195°~225°): 寒露、霜降
    - 冬季: 225° <= 太阳视黄经 < 315° (立冬至立春前)
      - 初冬 (225°~255°): 立冬、小雪
      - 隆冬 (255°~285°): 大雪、冬至
      - 暮冬 (285°~315°): 小寒、大寒

    返回字典结构：
    - season: '春季' | '夏季' | '秋季' | '冬季'
    - sub_season: '初春' | '仲春' | '暮春' ...
    - full_name: '春季（初春）' ...
    - description: 气候特征与体感描写
    - solar_longitude: 太阳视黄经浮点数
    """
    if d is None:
        d = date.today()

    try:
        dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=TZ_BEIJING).astimezone(timezone.utc)
        deg = _get_solar_longitude(dt)
        if deg >= 315 or deg < 45:
            season = "春季"
            if 315 <= deg < 345:
                sub = "初春"
            elif deg >= 345 or deg < 15:
                sub = "仲春"
            else:
                sub = "暮春"
            desc = "气温渐暖，草木复苏萌芽，春风拂面，适宜外出踏青与春茶萌发"
        elif deg < 135:
            season = "夏季"
            if deg < 75:
                sub = "初夏"
            elif deg < 105:
                sub = "盛夏"
            else:
                sub = "晚夏"
            desc = "天气炎热，阳光强烈，蝉鸣雷雨，适宜冷饮解暑、防晒透气"
        elif deg < 225:
            season = "秋季"
            if deg < 165:
                sub = "初秋"
            elif deg < 195:
                sub = "仲秋"
            else:
                sub = "深秋"
            desc = "天高气爽，渐带凉意微寒，草木渐黄落叶，需添衣防凉、热饮温汤"
        else:
            season = "冬季"
            if deg < 255:
                sub = "初冬"
            elif deg < 285:
                sub = "隆冬"
            else:
                sub = "暮冬"
            desc = "天寒地冻，草木凋零，需厚衣围巾保暖防寒，热食热饮暖手，严禁反季活动"
    except Exception:
        deg = 0.0
        m = d.month
        if m in (3, 4, 5):
            season, sub, desc = "春季", "春季", "气温渐暖，草木萌芽，微风温和"
        elif m in (6, 7, 8):
            season, sub, desc = "夏季", "夏季", "天气炎热，阳光强烈，注意防暑"
        elif m in (9, 10, 11):
            season, sub, desc = "秋季", "秋季", "天高气爽，渐带凉意，添衣防寒"
        else:
            season, sub, desc = "冬季", "冬季", "天寒地冻，草木凋零，注意保暖防寒"

    return {
        "season": season,
        "sub_season": sub,
        "full_name": f"{season}（{sub}）",
        "description": desc,
        "solar_longitude": round(deg, 2)
    }

def get_season_name(d: Optional[date] = None) -> str:
    """返回当前季节的完整描述名称，如 '冬季（隆冬）'"""
    info = get_season_info(d)
    return info.get("full_name", "")
