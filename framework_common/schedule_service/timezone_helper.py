# -*- coding: utf-8 -*-
"""
timezone_helper.py
时区与城市换算辅助模块：
- 支持城市名与主流中英文城市字典匹配
- 支持中文时区描述（东八区、西五区等）与 UTC/GMT 偏移量智能解析
- 支持非主要城市/小镇（如 Castro Valley、Irvine、Waterloo、Cupertino 等）通过 Open-Meteo 全球地理编码 API 自动查询并本地数据库持久化缓存
- 自动将目标时区的指定时间换算为 Bot 所在服务器时区（默认 Asia/Shanghai，东八区）的执行时间
- 城市/IANA 时区按执行日期自动适配夏令时；UTC/GMT 数字偏移保持固定
"""

import os
import re
import sqlite3
import datetime
from typing import Optional, Tuple, Dict, Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dateutil import tz

try:
    import requests
except ImportError:
    requests = None

DEFAULT_BOT_TZ_NAME = "Asia/Shanghai"
DEFAULT_BOT_OFFSET_HOURS = 8.0

CACHE_DB_PATH = os.path.join("data", "dataBase", "dynamic_schedules.db")

# 常见城市/地区到 IANA 时区名称映射表
CITY_TO_TZ_MAP: Dict[str, str] = {
    # 中国主要城市（统一中国标准时间 UTC+8）
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "广州": "Asia/Shanghai",
    "深圳": "Asia/Shanghai",
    "杭州": "Asia/Shanghai",
    "成都": "Asia/Shanghai",
    "重庆": "Asia/Shanghai",
    "武汉": "Asia/Shanghai",
    "西安": "Asia/Shanghai",
    "南京": "Asia/Shanghai",
    "天津": "Asia/Shanghai",
    "郑州": "Asia/Shanghai",
    "长沙": "Asia/Shanghai",
    "沈阳": "Asia/Shanghai",
    "青岛": "Asia/Shanghai",
    "济南": "Asia/Shanghai",
    "哈尔滨": "Asia/Shanghai",
    "大连": "Asia/Shanghai",
    "厦门": "Asia/Shanghai",
    "福州": "Asia/Shanghai",
    "通辽": "Asia/Shanghai",
    "苏州": "Asia/Shanghai",
    "合肥": "Asia/Shanghai",
    "东莞": "Asia/Shanghai",
    "佛山": "Asia/Shanghai",
    "无锡": "Asia/Shanghai",
    "昆明": "Asia/Shanghai",
    "长春": "Asia/Shanghai",
    "石家庄": "Asia/Shanghai",
    "南昌": "Asia/Shanghai",
    "贵阳": "Asia/Shanghai",
    "南宁": "Asia/Shanghai",
    "乌鲁木齐": "Asia/Shanghai",
    "兰州": "Asia/Shanghai",
    "呼和浩特": "Asia/Shanghai",
    "海口": "Asia/Shanghai",
    "三亚": "Asia/Shanghai",
    "银川": "Asia/Shanghai",
    "西宁": "Asia/Shanghai",
    "拉萨": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "澳门": "Asia/Macau",
    "台北": "Asia/Taipei",
    "台湾": "Asia/Taipei",

    # 俄罗斯主要城市
    "莫斯科": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "圣彼得堡": "Europe/Moscow",
    "saint petersburg": "Europe/Moscow",
    "符拉迪沃斯托克": "Asia/Vladivostok",
    "海参崴": "Asia/Vladivostok",
    "vladivostok": "Asia/Vladivostok",
    "新西伯利亚": "Asia/Novosibirsk",
    "novosibirsk": "Asia/Novosibirsk",
    "叶卡捷琳堡": "Asia/Yekaterinburg",
    "伊尔库茨克": "Asia/Irkutsk",
    "irkutsk": "Asia/Irkutsk",
    "下诺夫哥罗德": "Europe/Moscow",
    "喀山": "Europe/Moscow",
    "索契": "Europe/Moscow",

    # 日本
    "东京": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "大阪": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "京都": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "名古屋": "Asia/Tokyo",
    "横滨": "Asia/Tokyo",
    "福冈": "Asia/Tokyo",
    "札幌": "Asia/Tokyo",

    # 韩国
    "首尔": "Asia/Seoul",
    "seoul": "Asia/Seoul",
    "釜山": "Asia/Seoul",
    "仁川": "Asia/Seoul",

    # 英国 & 欧洲
    "伦敦": "Europe/London",
    "london": "Europe/London",
    "巴黎": "Europe/Paris",
    "paris": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "斯图加特": "Europe/Berlin",
    "stuttgart": "Europe/Berlin",
    "法兰克福": "Europe/Berlin",
    "罗马": "Europe/Rome",
    "rome": "Europe/Rome",
    "马德里": "Europe/Madrid",
    "阿姆斯特丹": "Europe/Amsterdam",
    "维也纳": "Europe/Vienna",
    "苏黎世": "Europe/Zurich",
    "日内瓦": "Europe/Zurich",
    "斯德哥尔摩": "Europe/Stockholm",
    "华沙": "Europe/Warsaw",
    "基辅": "Europe/Kyiv",

    # 北美主要城市及常见华人/留学生聚居区
    "纽约": "America/New_York",
    "new york": "America/New_York",
    "华盛顿": "America/New_York",
    "washington": "America/New_York",
    "波士顿": "America/New_York",
    "boston": "America/New_York",
    "费城": "America/New_York",
    "philadelphia": "America/New_York",
    "芝加哥": "America/Chicago",
    "chicago": "America/Chicago",
    "休斯顿": "America/Chicago",
    "houston": "America/Chicago",
    "达拉斯": "America/Chicago",
    "dallas": "America/Chicago",
    "奥斯汀": "America/Chicago",
    "austin": "America/Chicago",
    "洛杉矶": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "湾区": "America/Los_Angeles",
    "硅谷": "America/Los_Angeles",
    "西雅图": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "圣何塞": "America/Los_Angeles",
    "san jose": "America/Los_Angeles",
    "尔湾": "America/Los_Angeles",
    "irvine": "America/Los_Angeles",
    "库比蒂诺": "America/Los_Angeles",
    "cupertino": "America/Los_Angeles",
    "山景城": "America/Los_Angeles",
    "mountain view": "America/Los_Angeles",
    "帕罗奥拓": "America/Los_Angeles",
    "palo alto": "America/Los_Angeles",
    "桑尼维尔": "America/Los_Angeles",
    "sunnyvale": "America/Los_Angeles",
    "伯克利": "America/Los_Angeles",
    "berkeley": "America/Los_Angeles",
    "弗里蒙特": "America/Los_Angeles",
    "fremont": "America/Los_Angeles",
    "castro valley": "America/Los_Angeles",
    "卡斯特罗谷": "America/Los_Angeles",
    "奥克兰市": "America/Los_Angeles",
    "oakland": "America/Los_Angeles",
    "圣地亚哥": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "多伦多": "America/Toronto",
    "toronto": "America/Toronto",
    "滑铁卢": "America/Toronto",
    "waterloo": "America/Toronto",
    "温哥华": "America/Vancouver",
    "vancouver": "America/Vancouver",

    # 东南亚 & 澳洲
    "新加坡": "Asia/Singapore",
    "singapore": "Asia/Singapore",
    "吉隆坡": "Asia/Kuala_Lumpur",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "曼谷": "Asia/Bangkok",
    "bangkok": "Asia/Bangkok",
    "清迈": "Asia/Bangkok",
    "雅加达": "Asia/Jakarta",
    "悉尼": "Australia/Sydney",
    "sydney": "Australia/Sydney",
    "墨尔本": "Australia/Melbourne",
    "melbourne": "Australia/Melbourne",
    "布里斯班": "Australia/Brisbane",
    "珀斯": "Australia/Perth",
    "奥克兰": "Pacific/Auckland",

    # 中东
    "迪拜": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "阿布扎比": "Asia/Dubai",
}

# 中文数字转数字映射
CHINESE_ZONE_MAP: Dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


class TimezoneHelper:
    """时区识别与时间换算辅助类"""

    _mem_cache: Dict[str, str] = {}
    _db_initialized: bool = False

    @classmethod
    def _get_timezone(cls, timezone_name: str) -> Optional[datetime.tzinfo]:
        """优先使用现有系统 IANA 数据，缺失时沿用原有 dateutil 解析。"""
        try:
            return ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return tz.gettz(timezone_name)

    @classmethod
    def _init_cache_db(cls):
        """初始化持久化时区缓存表"""
        if cls._db_initialized:
            return
        try:
            os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
            with sqlite3.connect(CACHE_DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS city_timezone_cache (
                        city_query TEXT PRIMARY KEY,
                        timezone_name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            cls._db_initialized = True
        except Exception:
            pass

    @classmethod
    def _get_cached_tz(cls, city_query: str) -> Optional[str]:
        """从内存或数据库缓存中读取城市时区"""
        key = city_query.strip().lower()
        if key in cls._mem_cache:
            return cls._mem_cache[key]
        cls._init_cache_db()
        try:
            with sqlite3.connect(CACHE_DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT timezone_name FROM city_timezone_cache WHERE city_query = ?", (key,))
                row = cur.fetchone()
                if row and row[0]:
                    cls._mem_cache[key] = row[0]
                    return row[0]
        except Exception:
            pass
        return None

    @classmethod
    def _save_cached_tz(cls, city_query: str, timezone_name: str):
        """写入内存和数据库缓存"""
        key = city_query.strip().lower()
        cls._mem_cache[key] = timezone_name
        cls._init_cache_db()
        try:
            with sqlite3.connect(CACHE_DB_PATH) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO city_timezone_cache (city_query, timezone_name) VALUES (?, ?)",
                    (key, timezone_name)
                )
        except Exception:
            pass

    @classmethod
    def _query_remote_geocoding_tz(cls, city_name: str) -> Optional[str]:
        """使用 Open-Meteo 免费全球地理编码 API 自动查询城市对应 IANA 时区"""
        if not requests or not city_name or len(city_name.strip()) < 2:
            return None
        clean_name = city_name.strip()
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            params = {
                "name": clean_name,
                "count": 1,
                "language": "zh",
                "format": "json",
            }
            resp = requests.get(url, params=params, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results and isinstance(results, list):
                    tz_name = results[0].get("timezone")
                    if tz_name:
                        cls._save_cached_tz(clean_name, tz_name)
                        return tz_name
        except Exception:
            pass
        return None

    @classmethod
    def get_bot_timezone(cls) -> datetime.tzinfo:
        """获取 Bot 默认运行所在时区（Asia/Shanghai，UTC+8）"""
        return cls._get_timezone(DEFAULT_BOT_TZ_NAME) or datetime.timezone(datetime.timedelta(hours=8))

    @classmethod
    def resolve_timezone(
        cls,
        city_or_tz: Optional[str]
    ) -> Tuple[datetime.tzinfo, str, float]:
        """
        解析用户所在城市或时区，返回三元组：
        返回值: (tzinfo 对象, 标准名称, 当前 UTC 偏移小时数)。
        夏令时换算必须使用 tzinfo 和目标日期，不能固定使用此处的当前偏移。
        """
        bot_tz = cls.get_bot_timezone()
        if not city_or_tz or not city_or_tz.strip():
            return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

        raw = city_or_tz.strip().lower()

        # 1. 尝试直接查静态常见城市/地区表
        if raw in CITY_TO_TZ_MAP:
            tz_name = CITY_TO_TZ_MAP[raw]
            zone = cls._get_timezone(tz_name)
            if zone is not None:
                now = datetime.datetime.now(zone)
                offset = (now.utcoffset() or datetime.timedelta()).total_seconds() / 3600.0
                return zone, tz_name, offset

        # 2. 中文时区表达（例如“东八区”、“西五区”、“东9区”）
        m_cn = re.search(r"([东西])([0-9零一二三四五六七八九十]+)区?", raw)
        if m_cn:
            direction, num_str = m_cn.groups()
            num = int(num_str) if num_str.isdigit() else CHINESE_ZONE_MAP.get(num_str, 8)
            offset = num if direction == "东" else -num
            zone = datetime.timezone(datetime.timedelta(hours=offset))
            sign = "+" if offset >= 0 else ""
            return zone, f"UTC{sign}{int(offset)}", float(offset)

        # 3. 常见 UTC / GMT 偏移字符串（如 UTC+8, UTC+03:00, GMT-5, +8, -3）
        if raw in ("utc", "gmt", "z"):
            return datetime.timezone.utc, "UTC", 0.0

        m_utc = re.search(r"^(?:utc|gmt)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$", raw)
        if m_utc:
            sign, hours_str, mins_str = m_utc.groups()
            hours = int(hours_str)
            mins = int(mins_str or 0)
            if hours >= 24 or mins >= 60:
                raise ValueError("UTC/GMT 偏移量的小时必须小于 24，分钟必须小于 60")
            total_minutes = (hours * 60 + mins) * (-1 if sign == "-" else 1)
            zone = datetime.timezone(datetime.timedelta(minutes=total_minutes))
            tz_name = f"UTC{sign}{hours}" + (f":{mins:02d}" if mins else "")
            return zone, tz_name, total_minutes / 60.0

        # 4. 直接尝试 IANA/兼容时区表达（如 "Europe/Moscow", "America/New_York"）
        direct_zone = cls._get_timezone(city_or_tz.strip())
        if direct_zone is not None:
            now = datetime.datetime.now(direct_zone)
            offset = (now.utcoffset() or datetime.timedelta()).total_seconds() / 3600.0
            return direct_zone, city_or_tz.strip(), offset

        # 5. 城市名包含匹配放在明确时区解析之后，避免 Europe/Bratislava 被 "la" 匹配。
        # 英文按完整单词匹配，中文允许“德国斯图加特”等自然表达；不再反向匹配城市片段。
        for city, tz_name in sorted(CITY_TO_TZ_MAP.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"[a-z]", city):
                matched = re.search(r"(?<![a-z0-9äöüß])" + re.escape(city) + r"(?![a-z0-9äöüß])", raw)
            else:
                matched = len(city) >= 2 and city in raw
            if matched:
                zone = cls._get_timezone(tz_name)
                if zone is not None:
                    now = datetime.datetime.now(zone)
                    offset = (now.utcoffset() or datetime.timedelta()).total_seconds() / 3600.0
                    return zone, tz_name, offset

        # 6. 从本地持久化缓存中查询
        cached_tz_name = cls._get_cached_tz(raw)
        if cached_tz_name:
            cached_zone = cls._get_timezone(cached_tz_name)
            if cached_zone is not None:
                now = datetime.datetime.now(cached_zone)
                offset = (now.utcoffset() or datetime.timedelta()).total_seconds() / 3600.0
                return cached_zone, cached_tz_name, offset

        # 7. 请求地理编码接口解析非主要城市/小镇（如 Castro Valley 等小镇）
        remote_tz_name = cls._query_remote_geocoding_tz(city_or_tz.strip())
        if remote_tz_name:
            remote_zone = cls._get_timezone(remote_tz_name)
            if remote_zone is not None:
                now = datetime.datetime.now(remote_zone)
                offset = (now.utcoffset() or datetime.timedelta()).total_seconds() / 3600.0
                return remote_zone, remote_tz_name, offset

        # 兜底返回 Bot 默认时区
        return bot_tz, DEFAULT_BOT_TZ_NAME, DEFAULT_BOT_OFFSET_HOURS

    @classmethod
    def normalize_local_datetime(cls, local_dt: datetime.datetime) -> datetime.datetime:
        """统一夏令时边界：跳过的钟点按时差顺延，重复的钟点只取第一次。"""
        if local_dt.tzinfo is None or local_dt.utcoffset() is None:
            raise ValueError("当地时间必须携带时区信息")
        return tz.resolve_imaginary(tz.enfold(local_dt, fold=0))

    @classmethod
    def get_user_local_time(
        cls,
        city_or_tz: Optional[str],
        base_time: Optional[datetime.datetime] = None,
    ) -> datetime.datetime:
        """获取用户当地时间（若 base_time 为空则取当前时刻）"""
        zone, _, _ = cls.resolve_timezone(city_or_tz)
        if base_time is None:
            return datetime.datetime.now(zone)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=cls.get_bot_timezone())
        return base_time.astimezone(zone)

    @classmethod
    def is_user_current_time(
        cls,
        city_or_tz: Optional[str],
        target_hour: int,
        target_minute: int,
        tolerance_minutes: int = 1,
        now_dt: Optional[datetime.datetime] = None,
    ) -> bool:
        """
        判断用户当地时间是否正处于 target_hour:target_minute 附近。
        tolerance_minutes: 允许的时间误差范围（分钟）
        """
        user_now = cls.get_user_local_time(city_or_tz, base_time=now_dt)
        current_minute_of_day = user_now.hour * 60 + user_now.minute
        target_minute_of_day = target_hour * 60 + target_minute
        return abs(current_minute_of_day - target_minute_of_day) <= tolerance_minutes

    @classmethod
    def compute_next_bot_run_time(
        cls,
        target_hour: int,
        target_minute: int,
        city_or_tz: Optional[str],
        weekdays: Optional[List[int]] = None,
        from_bot_dt: Optional[datetime.datetime] = None,
    ) -> datetime.datetime:
        """
        计算目标城市当地时间到达 target_hour:target_minute 时，对应的 Bot 时区（datetime 对象）。
        weekdays: 指定星期几（0=周一, 6=周日），若为 None 则表示每天。
        春季跳过的时间向后顺延（如 02:30 → 03:30），秋季重复时间只执行第一次。
        """
        bot_tz = cls.get_bot_timezone()
        user_tz, _, _ = cls.resolve_timezone(city_or_tz)

        if from_bot_dt is None:
            from_bot_dt = datetime.datetime.now(bot_tz)
        elif from_bot_dt.tzinfo is None:
            from_bot_dt = from_bot_dt.replace(tzinfo=bot_tz)

        user_now = from_bot_dt.astimezone(user_tz)
        now_utc = from_bot_dt.astimezone(datetime.timezone.utc)

        # 向上搜寻接下来 14 天中最快满足条件的时间
        for day_offset in range(14):
            candidate_date = user_now.date() + datetime.timedelta(days=day_offset)
            if weekdays is not None and candidate_date.weekday() not in weekdays:
                continue

            candidate_user_dt = datetime.datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                target_hour,
                target_minute,
                0,
                tzinfo=user_tz,
            )
            candidate_user_dt = cls.normalize_local_datetime(candidate_user_dt)

            # 按真实时刻比较，避免秋季回拨时把已经过去的第一次 02:30 判为未来。
            if candidate_user_dt.astimezone(datetime.timezone.utc) > now_utc:
                return candidate_user_dt.astimezone(bot_tz)

        # 兜底返回明天
        fallback = user_now + datetime.timedelta(days=1)
        fallback_dt = datetime.datetime(
            fallback.year, fallback.month, fallback.day,
            target_hour, target_minute, 0, tzinfo=user_tz
        )
        return cls.normalize_local_datetime(fallback_dt).astimezone(bot_tz)
