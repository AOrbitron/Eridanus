# -*- coding: utf-8 -*-
"""
scheduler_engine.py
框架级动态定时调度引擎：
- 基于 aiosqlite 进行持久化存储（支持进程重启后恢复）
- 支持多循环类型：一次性(once)、每天循环(daily)、每周特定天(weekly)、工作日(workday)、周末(weekend)
- 结合 TimezoneHelper，原生支持多用户时区差异化换算
- 支持预输入 Function Calling 嵌套工具执行（到点执行任意已注册 Function，如 call_asmr 等）
- 支持自然语言 Prompt 驱动生成个性化问候/提醒消息
- 支持与 mai_reply 深度联动的主动私聊排期 (proactive_chat)
- 提供统一的增删改查及全局单例调度器
"""

import asyncio
import datetime
import importlib
import inspect
import json
from developTools.utils.logger import get_logger
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union, Tuple

import aiosqlite

from developTools.message.message_components import Text
from framework_common.framework_util.any_event import AnyEvent
from framework_common.schedule_service.timezone_helper import TimezoneHelper

logger = get_logger("DynamicScheduler")

DB_DIR = "data/dataBase"
DB_PATH = os.path.join(DB_DIR, "dynamic_schedules.db")


@dataclass
class ScheduledTask:
    task_id: str
    creator_id: int
    target_type: str  # "private" or "group"
    target_id: int    # user_id or group_id
    task_type: str    # "reminder", "wake_up", "asmr", "proactive_chat", "tool_call", "custom"
    recur_type: str   # "once", "daily", "weekly", "workday", "weekend", "yearly", "interval"
    weekdays: Optional[str]  # e.g. "0,2,4" (0=Monday, 6=Sunday)
    time_str: str     # e.g. "08:30" or "2026-10-12 09:00:00"
    target_city: str
    target_timezone: str
    action_type: str  # "message", "tool", "proactive_chat"
    action_payload: str  # JSON-encoded dictionary
    description: str
    status: str       # "active", "completed", "cancelled"
    next_run_timestamp: float
    created_at: str
    last_run_at: str = ""

    def get_payload_dict(self) -> Dict[str, Any]:
        if isinstance(self.action_payload, dict):
            return self.action_payload
        if not self.action_payload:
            return {}
        try:
            if isinstance(self.action_payload, (str, bytes, bytearray)):
                return json.loads(self.action_payload)
            return {}
        except Exception:
            return {}

    def get_weekdays_list(self) -> Optional[List[int]]:
        if not self.weekdays:
            return None
        try:
            return [int(w.strip()) for w in self.weekdays.split(",") if w.strip().isdigit()]
        except Exception:
            return None


class DynamicScheduler:
    _instance: Optional["DynamicScheduler"] = None
    _custom_tools: Dict[str, Any] = {}

    @classmethod
    def register_tool(cls, name: str, func: Any):
        """手动注册自定义可调用工具"""
        cls._custom_tools[name] = func

    def __init__(self, bot=None, config=None, db_path: str = DB_PATH):
        self.bot = bot
        self.config = config
        self.db_path = db_path
        self._running = False
        self._bg_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._tick_lock = asyncio.Lock()
        self._running_tasks: set[str] = set()
        self._initialized = False

    @classmethod
    def get_instance(cls, bot=None, config=None, db_path: str = DB_PATH) -> "DynamicScheduler":
        if cls._instance is None:
            cls._instance = cls(bot=bot, config=config, db_path=db_path)
        else:
            if bot is not None:
                cls._instance.bot = bot
            if config is not None:
                cls._instance.config = config
        return cls._instance

    async def init_db(self):
        """
        初始化数据库表结构：
        1. 自动创建表结构（首次运行）。
        2. 若为现有数据库，自动检测现有列结构；
           若发现缺少新版本的字段（例如 weekdays, target_city, target_timezone 等），
           自动执行 ALTER TABLE ADD COLUMN 增量补齐，实现无损平滑迁移，绝不需要用户手动删库！
        """
        if self._initialized:
            return

        db_path = getattr(self, "db_path", DB_PATH)
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        EXPECTED_COLUMNS = {
            "task_id": "TEXT PRIMARY KEY",
            "creator_id": "INTEGER DEFAULT 0",
            "target_type": "TEXT DEFAULT 'private'",
            "target_id": "INTEGER DEFAULT 0",
            "task_type": "TEXT DEFAULT 'message'",
            "recur_type": "TEXT DEFAULT 'once'",
            "weekdays": "TEXT DEFAULT ''",
            "time_str": "TEXT DEFAULT ''",
            "target_city": "TEXT DEFAULT ''",
            "target_timezone": "TEXT DEFAULT ''",
            "action_type": "TEXT DEFAULT 'message'",
            "action_payload": "TEXT DEFAULT '{}'",
            "description": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'active'",
            "next_run_timestamp": "REAL DEFAULT 0.0",
            "created_at": "TEXT DEFAULT ''",
            "last_run_at": "TEXT DEFAULT ''"
        }

        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")

            # 检查表是否存在
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dynamic_tasks';")
            table_row = await cursor.fetchone()

            if not table_row:
                col_defs = ", ".join([f"{k} {v}" for k, v in EXPECTED_COLUMNS.items()])
                await db.execute(f"CREATE TABLE dynamic_tasks ({col_defs});")
                logger.info(f"[DynamicScheduler] 定时任务数据库表 dynamic_tasks 初始化新建成功: {db_path}")
            else:
                # 现有数据库：智能检查并自动增量追加缺失列
                cursor = await db.execute("PRAGMA table_info(dynamic_tasks);")
                existing_rows = await cursor.fetchall()
                existing_cols = {row[1].lower() for row in existing_rows}

                for col_name, col_def in EXPECTED_COLUMNS.items():
                    if col_name.lower() not in existing_cols:
                        alter_type = col_def.replace(" PRIMARY KEY", "")
                        try:
                            await db.execute(f"ALTER TABLE dynamic_tasks ADD COLUMN {col_name} {alter_type};")
                            logger.info(f"[DynamicScheduler] 数据库热迁移：已自动追加缺失列 [{col_name}]")
                        except Exception as e:
                            logger.warning(f"[DynamicScheduler] 尝试追加列 {col_name} 失败: {e}")

            await db.execute("CREATE INDEX IF NOT EXISTS idx_status_next ON dynamic_tasks(status, next_run_timestamp);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_target ON dynamic_tasks(target_type, target_id);")
            await db.commit()

        self._initialized = True
        logger.info(f"[DynamicScheduler] 定时任务持久化引擎已就绪: {db_path}")

    # -------------------------------------------------------------------------
    @staticmethod
    def is_system_task(task: "ScheduledTask") -> bool:
        """判断是否为代码或配置层面的系统后台常驻守护任务（如 QQ 空间巡检、保活等）"""
        tt = (task.task_type or "").lower()
        tid = (task.task_id or "").lower()
        return (
            tt.startswith("qzone_")
            or tid.startswith("qzone_")
            or tt.startswith("system_")
            or tid.startswith("system_")
        )

    @classmethod
    def parse_yearly_date(cls, time_str: str) -> Tuple[int, int, int, int]:
        """
        从时间字符串中解析出年度循环任务的 (month, day, hour, minute)
        支持格式例如：
        - "2026-10-24 08:30" / "2026/10/24 08:30"
        - "10-24 08:30" / "10/24 08:30" / "10.24 08:30"
        - "10月24日 8点30分" / "10月24号 8:30" / "10月24日 8点"
        - "10-24" / "10月24日" (缺省小时分钟则默认为 08:00)
        """
        s = str(time_str).strip()
        full_m = re.search(r"\d{4}[-/年\.]\s*(\d{1,2})[-/月\.]\s*(\d{1,2})(?:日|号)?(?:\s+(\d{1,2})(?:[:/点](\d{1,2})?)?)?", s)
        if full_m:
            month = int(full_m.group(1))
            day = int(full_m.group(2))
            h = int(full_m.group(3)) if full_m.group(3) else 8
            minute = int(full_m.group(4)) if full_m.group(4) else 0
            return max(1, min(12, month)), max(1, min(31, day)), max(0, min(23, h)), max(0, min(59, minute))

        cn_m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})(?:日|号)?(?:\s*(\d{1,2})(?:[:/点](\d{1,2})?)?)?", s)
        if cn_m:
            month = int(cn_m.group(1))
            day = int(cn_m.group(2))
            h = int(cn_m.group(3)) if cn_m.group(3) else 8
            minute = int(cn_m.group(4)) if cn_m.group(4) else 0
            return max(1, min(12, month)), max(1, min(31, day)), max(0, min(23, h)), max(0, min(59, minute))

        slash_m = re.search(r"(\d{1,2})[-/\.](\d{1,2})(?:\s+(\d{1,2})(?:[:/点](\d{1,2})?)?)?", s)
        if slash_m:
            month = int(slash_m.group(1))
            day = int(slash_m.group(2))
            h = int(slash_m.group(3)) if slash_m.group(3) else 8
            minute = int(slash_m.group(4)) if slash_m.group(4) else 0
            return max(1, min(12, month)), max(1, min(31, day)), max(0, min(23, h)), max(0, min(59, minute))

        now = datetime.datetime.now()
        h, minute = cls.parse_time_str_to_hour_minute(s)
        return now.month, now.day, h, minute

    # 时间与下次触发时间计算
    # -------------------------------------------------------------------------
    @staticmethod
    def parse_interval_seconds(time_str: str, default: int = 60) -> int:
        """解析定时间隔字符串，如 '180', '180s', '60m', '30分钟', '1h' -> 秒数"""
        s = str(time_str).strip().lower()
        if s.isdigit():
            return max(1, int(s))
        m = re.match(r'^(\d+)\s*(s|sec|second|seconds|秒|m|min|minute|minutes|分|分钟|h|hour|hours|小时|d|day|days|天)?$', s)
        if m:
            val = int(m.group(1))
            unit = m.group(2) or 's'
            if unit in ('s', 'sec', 'second', 'seconds', '秒'):
                return max(1, val)
            elif unit in ('m', 'min', 'minute', 'minutes', '分', '分钟'):
                return max(1, val * 60)
            elif unit in ('h', 'hour', 'hours', '小时'):
                return max(1, val * 3600)
            elif unit in ('d', 'day', 'days', '天'):
                return max(1, val * 86400)
        return max(1, default)

    @staticmethod
    def parse_time_str_to_hour_minute(time_str: str) -> Tuple[int, int]:
        """从各种格式解析出小时与分钟，默认 08:00"""
        s = time_str.strip()
        # 匹配如 "8:30", "08:30", "8/3", "8点30分", "8点"
        m = re.search(r"(\d{1,2})[:/点](\d{1,2})?", s)
        if m:
            h = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            return max(0, min(23, h)), max(0, min(59, minute))
        return 8, 0

    @classmethod
    def calculate_initial_next_run(
        cls,
        time_str: str,
        recur_type: str,
        weekdays: Optional[List[int]],
        city_or_tz: Optional[str]
    ) -> float:
        """根据循环模式和时区计算任务的下一个触发时间戳 (UTC epoch seconds)"""
        now_ts = time.time()
        user_tz, _, _ = TimezoneHelper.resolve_timezone(city_or_tz)

        # 0. 间隔循环类型 (recur_type == 'interval')
        if recur_type == "interval":
            interval_sec = cls.parse_interval_seconds(time_str, default=60)
            return now_ts + interval_sec

        # 0.1 年度循环类型 (recur_type == 'yearly')
        if recur_type == "yearly":
            month, day, target_h, target_m = cls.parse_yearly_date(time_str)
            now_user_dt = datetime.datetime.now(user_tz)
            current_year = now_user_dt.year

            def _build_yearly_dt(year, m, d, hh, mm):
                try:
                    return datetime.datetime(year, m, d, hh, mm, 0, tzinfo=user_tz)
                except ValueError:
                    if m == 2 and d == 29:
                        return datetime.datetime(year, 2, 28, hh, mm, 0, tzinfo=user_tz)
                    return datetime.datetime(year, m, min(d, 28), hh, mm, 0, tzinfo=user_tz)

            candidate = TimezoneHelper.normalize_local_datetime(
                _build_yearly_dt(current_year, month, day, target_h, target_m)
            )
            if candidate.timestamp() <= now_ts:
                candidate = TimezoneHelper.normalize_local_datetime(
                    _build_yearly_dt(current_year + 1, month, day, target_h, target_m)
                )
            return candidate.timestamp()

        # 1. 相对时间匹配（如 "now", "立即", "马上", "30m", "30分钟后", "2小时后", "+15m"）
        if recur_type == "once" and time_str.strip().lower() in ("now", "立即", "马上", "立刻", "当前"):
            return now_ts

        rel_match = re.search(r"(\d+)\s*(分钟|小时|秒|m|h|s)", time_str)
        if recur_type == "once" and rel_match:
            num = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if unit in ("小时", "h"):
                return now_ts + num * 3600
            elif unit in ("分钟", "m"):
                return now_ts + num * 60
            elif unit in ("秒", "s"):
                return now_ts + num

        # 2. 如果包含明确日期（如 "2026-10-12 09:30:00"）
        date_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", time_str)
        if date_match:
            y, m, d, h, minute = map(int, date_match.groups())
            dt = datetime.datetime(y, m, d, h, minute, 0, tzinfo=user_tz)
            dt = TimezoneHelper.normalize_local_datetime(dt)
            return dt.timestamp()

        # 3. 提取小时与分钟
        target_h, target_m = cls.parse_time_str_to_hour_minute(time_str)

        # 循环类型标准化
        target_weekdays = weekdays
        if recur_type == "workday":
            target_weekdays = [0, 1, 2, 3, 4]
        elif recur_type == "weekend":
            target_weekdays = [5, 6]

        next_bot_dt = TimezoneHelper.compute_next_bot_run_time(
            target_hour=target_h,
            target_minute=target_m,
            city_or_tz=city_or_tz,
            weekdays=target_weekdays,
        )
        return next_bot_dt.timestamp()

    @classmethod
    def calculate_next_recur_run(cls, task: ScheduledTask) -> Optional[float]:
        """当一个任务触发完毕后，计算其下一次触发时间"""
        if task.recur_type == "once":
            return None

        if task.recur_type == "interval":
            interval_sec = cls.parse_interval_seconds(task.time_str, default=60)
            return time.time() + interval_sec

        if task.recur_type == "yearly":
            user_tz, _, _ = TimezoneHelper.resolve_timezone(task.target_city or task.target_timezone)
            month, day, target_h, target_m = cls.parse_yearly_date(task.time_str)
            now_user_dt = datetime.datetime.now(user_tz)
            base_year = now_user_dt.year
            if task.next_run_timestamp > 0:
                try:
                    prev_dt = datetime.datetime.fromtimestamp(task.next_run_timestamp, tz=user_tz)
                    base_year = max(base_year, prev_dt.year)
                except Exception:
                    pass
            next_year = base_year + 1

            def _build_next_yearly_dt(year, m, d, hh, mm):
                try:
                    return datetime.datetime(year, m, d, hh, mm, 0, tzinfo=user_tz)
                except ValueError:
                    if m == 2 and d == 29:
                        return datetime.datetime(year, 2, 28, hh, mm, 0, tzinfo=user_tz)
                    return datetime.datetime(year, m, min(d, 28), hh, mm, 0, tzinfo=user_tz)

            next_candidate = TimezoneHelper.normalize_local_datetime(
                _build_next_yearly_dt(next_year, month, day, target_h, target_m)
            )
            return next_candidate.timestamp()

        weekdays = task.get_weekdays_list()
        if task.recur_type == "workday":
            weekdays = [0, 1, 2, 3, 4]
        elif task.recur_type == "weekend":
            weekdays = [5, 6]

        target_h, target_m = cls.parse_time_str_to_hour_minute(task.time_str)

        # 从当前时间算起
        next_bot_dt = TimezoneHelper.compute_next_bot_run_time(
            target_hour=target_h,
            target_minute=target_m,
            city_or_tz=task.target_city or task.target_timezone,
            weekdays=weekdays,
        )
        return next_bot_dt.timestamp()

    # -------------------------------------------------------------------------
    async def add_task(
        self,
        creator_id: int,
        target_type: str,
        target_id: int,
        task_type: str,
        time_str: str,
        recur_type: str = "once",
        weekdays: Optional[Union[str, List[int]]] = None,
        city: Optional[str] = None,
        action_type: str = "message",
        action_payload: Optional[Dict[str, Any]] = None,
        description: str = "",
        task_id: Optional[str] = None,
        next_run_ts: Optional[float] = None,
    ) -> ScheduledTask:
        await self.init_db()

        # 解析星期
        weekdays_str = None
        weekdays_list = None
        if isinstance(weekdays, list):
            weekdays_list = weekdays
            weekdays_str = ",".join(map(str, weekdays))
        elif isinstance(weekdays, str) and weekdays.strip():
            parsed = []
            cn_week = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
            for part in weekdays.replace("，", ",").split(","):
                part = part.strip()
                if part.isdigit():
                    num = int(part)
                    if 1 <= num <= 7:
                        num = num - 1 if num <= 6 else 6
                    parsed.append(num)
                else:
                    for cn_k, cn_v in cn_week.items():
                        if cn_k in part:
                            parsed.append(cn_v)
                            break
            if parsed:
                weekdays_list = sorted(list(set(parsed)))
                weekdays_str = ",".join(map(str, weekdays_list))

        # 时区信息解析
        _, tz_name, _ = TimezoneHelper.resolve_timezone(city)
        target_city = (city or "").strip()

        if next_run_ts is not None:
            next_ts = float(next_run_ts)
        else:
            next_ts = self.calculate_initial_next_run(
                time_str=time_str,
                recur_type=recur_type,
                weekdays=weekdays_list,
                city_or_tz=target_city or tz_name
            )

        final_task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload_str = json.dumps(action_payload or {}, ensure_ascii=False)

        task = ScheduledTask(
            task_id=final_task_id,
            creator_id=creator_id,
            target_type=target_type,
            target_id=target_id,
            task_type=task_type,
            recur_type=recur_type,
            weekdays=weekdays_str,
            time_str=time_str,
            target_city=target_city,
            target_timezone=tz_name,
            action_type=action_type,
            action_payload=payload_str,
            description=description or f"{task_type} 定时任务",
            status="active",
            next_run_timestamp=next_ts,
            created_at=now_iso,
            last_run_at="",
        )

        async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
            await db.execute("""
            INSERT OR REPLACE INTO dynamic_tasks (
                task_id, creator_id, target_type, target_id, task_type,
                recur_type, weekdays, time_str, target_city, target_timezone,
                action_type, action_payload, description, status,
                next_run_timestamp, created_at, last_run_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id, task.creator_id, task.target_type, task.target_id,
                task.task_type, task.recur_type, task.weekdays, task.time_str,
                task.target_city, task.target_timezone, task.action_type,
                task.action_payload, task.description, task.status,
                task.next_run_timestamp, task.created_at, task.last_run_at
            ))
            await db.commit()

        logger.info(f"[DynamicScheduler] 成功创建任务: {task.task_id} ({task.description}), 下次触发: {datetime.datetime.fromtimestamp(next_ts)}")
        return task

    async def cancel_tasks(
        self,
        task_id_or_keyword: str,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None,
        creator_id: Optional[int] = None
    ) -> List[ScheduledTask]:
        """根据关键词或ID取消任务，严格限定会话范围（支持全部/all/清空等模式）"""
        await self.init_db()
        matched_tasks: List[ScheduledTask] = []
        kw = (task_id_or_keyword or "").strip().lower()
        is_all = kw in ["all", "全部", "所有", "清空", "取消全部", "全部取消", "全部闹钟", "所有任务"]

        async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM dynamic_tasks WHERE status = 'active'"
            params = []
            if target_id is not None:
                query += " AND target_id = ?"
                params.append(target_id)
            if target_type is not None:
                query += " AND target_type = ?"
                params.append(target_type)
            if creator_id is not None:
                query += " AND creator_id = ?"
                params.append(creator_id)

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    t = ScheduledTask(**dict(row))
                    if is_all:
                        # 保护机制：批量取消全部时，自动豁免系统后台常驻守护任务（如 QQ 空间巡检、保活等）
                        if not self.is_system_task(t):
                            matched_tasks.append(t)
                    else:
                        payload_str = str(t.action_payload or "").lower()
                        if (t.task_id.lower() == kw or
                            kw in t.description.lower() or
                            kw in t.task_type.lower() or
                            kw in t.time_str.lower() or
                            kw in payload_str):
                            matched_tasks.append(t)

            if matched_tasks:
                ids = [t.task_id for t in matched_tasks]
                placeholders = ",".join("?" for _ in ids)
                await db.execute(
                    f"UPDATE dynamic_tasks SET status = 'cancelled' WHERE task_id IN ({placeholders})",
                    tuple(ids)
                )
                await db.commit()

        logger.info(f"[DynamicScheduler] 已取消 {len(matched_tasks)} 个任务: {[t.task_id for t in matched_tasks]}")
        return matched_tasks

    async def list_active_tasks(
        self,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None,
        creator_id: Optional[int] = None
    ) -> List[ScheduledTask]:
        """查询当前会话生效中的任务：群聊查询本群任务，私聊查询该用户私聊任务，支持按 creator_id 过滤"""
        await self.init_db()
        tasks = []
        async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM dynamic_tasks WHERE status = 'active'"
            params = []
            if target_id is not None:
                query += " AND target_id = ?"
                params.append(target_id)
            if target_type is not None:
                query += " AND target_type = ?"
                params.append(target_type)
            if creator_id is not None:
                query += " AND creator_id = ?"
                params.append(creator_id)
            query += " ORDER BY next_run_timestamp ASC"

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    tasks.append(ScheduledTask(**dict(row)))
        return tasks

    async def list_all_tasks(
        self,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None,
        creator_id: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[ScheduledTask]:
        """查询指定维度的所有任务（包括 active / completed / cancelled）"""
        await self.init_db()
        tasks = []
        async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM dynamic_tasks WHERE 1=1"
            params = []
            if status is not None:
                query += " AND status = ?"
                params.append(status)
            if target_id is not None:
                query += " AND target_id = ?"
                params.append(target_id)
            if target_type is not None:
                query += " AND target_type = ?"
                params.append(target_type)
            if creator_id is not None:
                query += " AND creator_id = ?"
                params.append(creator_id)
            query += " ORDER BY next_run_timestamp ASC"

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    tasks.append(ScheduledTask(**dict(row)))
        return tasks

    def _find_callable_tool(cls, tool_name: str) -> Optional[Any]:
        """从自定义注册表、func_map 或框架各模块中反射定位可执行的函数对象"""
        clean_name = tool_name.strip()
        if not clean_name:
            return None

        # 0. 优先从 DynamicScheduler 显式注册的自定义工具集中查找
        alias_map = {
            "qzone_早安": "qzone_morning",
            "qzone_morning": "qzone_早安",
            "qzone_晚安": "qzone_night",
            "qzone_night": "qzone_晚安",
        }
        if clean_name in cls._custom_tools:
            return cls._custom_tools[clean_name]
        alt_alias = alias_map.get(clean_name)
        if alt_alias and alt_alias in cls._custom_tools:
            return cls._custom_tools[alt_alias]
        if f"call_{clean_name}" in cls._custom_tools:
            return cls._custom_tools[f"call_{clean_name}"]
        if clean_name.startswith("call_") and clean_name[5:] in cls._custom_tools:
            return cls._custom_tools[clean_name[5:]]
        for k, v in cls._custom_tools.items():
            if k.lower() == clean_name.lower():
                return v

        # 1. 从项目全局 build_tool_map 中查找
        try:
            from framework_common.framework_util.func_map_loader import build_tool_map
            tools = build_tool_map()
            if clean_name in tools:
                return tools[clean_name]
            if f"call_{clean_name}" in tools:
                return tools[f"call_{clean_name}"]
            if clean_name.startswith("call_") and clean_name[5:] in tools:
                return tools[clean_name[5:]]
            for k, v in tools.items():
                if k.lower() == clean_name.lower():
                    return v
        except Exception as e:
            logger.warning(f"[DynamicScheduler] build_tool_map 查找工具失败: {e}")

        # 2. 动态模块路径导入 (如 "run.resource_collector.service.asmr.asmr100.random_asmr_100")
        if "." in clean_name:
            try:
                mod_name, func_name = clean_name.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                if hasattr(mod, func_name):
                    return getattr(mod, func_name)
            except Exception:
                pass

        # 3. 框架常见内置业务工具直通映射
        KNOWN_TOOL_MAP = {
            "asmr": "run.resource_collector.service.asmr.asmr100.random_asmr_100",
            "call_asmr": "run.resource_collector.service.asmr.asmr100.random_asmr_100",
            "random_asmr": "run.resource_collector.service.asmr.asmr100.random_asmr_100",
            "bing": "run.basic_plugin.service.life_service.bingEveryDay",
            "danxiangli": "run.basic_plugin.service.life_service.danxianglii",
            "weather": "run.basic_plugin.service.weather_query.free_weather_query",
            "free_weather_query": "run.basic_plugin.service.weather_query.free_weather_query",
            "epic": "run.anime_game_service.service.epicfree.epic_free_game_get",
            "nasa": "run.basic_plugin.service.nasa_api.get_nasa_apod",
            "jm_comic": "run.resource_collector.service.jmComic.jmComic.JM_ranking_today",
            "bangumi": "run.streaming_media.service.Link_parsing.Link_parsing.bangumi_PILimg",
        }
        if clean_name in KNOWN_TOOL_MAP:
            try:
                target = KNOWN_TOOL_MAP[clean_name]
                mod_name, func_name = target.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                if hasattr(mod, func_name):
                    return getattr(mod, func_name)
            except Exception:
                pass

        return None

    # -------------------------------------------------------------------------
    # 执行逻辑：支持嵌套 Function Calling、LLM 智能消息生成与主动对话
    # -------------------------------------------------------------------------
    async def execute_task(self, task: ScheduledTask):
        """执行单个任务的具体动作"""
        if task.task_id in self._running_tasks:
            logger.warning(f"[DynamicScheduler] 任务 {task.task_id} 正在执行中，跳过重复并发执行")
            return
        self._running_tasks.add(task.task_id)

        bot = self.bot
        config = self.config
        payload = task.get_payload_dict()

        logger.info(f"[DynamicScheduler] 开始执行任务 {task.task_id}: {task.description} (action={task.action_type})")

        # 构造虚拟事件
        event = AnyEvent()
        event.user_id = task.target_id if task.target_type == "private" else task.creator_id
        if task.target_type == "group":
            event.group_id = task.target_id

        try:
            # 1. 嵌套工具调用（执行任意已注册 Function，如 call_asmr 或其他 tool）
            if task.action_type in ("tool", "function_call"):
                tool_name = payload.get("tool_name", "")
                tool_params = payload.get("tool_params") or payload.get("tool_args") or {}
                # 若因历史数据或解析问题缺少 tool_name，根据 task_type/task_id/description 智能回退识别
                if not tool_name:
                    if task.task_type == "qzone_post":
                        kw = f"{task.task_id} {task.description}".lower()
                        if "早安" in kw or "morning" in kw:
                            tool_name = "qzone_早安"
                        elif "晚安" in kw or "night" in kw:
                            tool_name = "qzone_晚安"
                        else:
                            tool_name = "qzone_post_task"
                    elif task.task_type in ("qzone_vtuber_daily", "qzone_comment_reply", "qzone_keepalive"):
                        tool_name = task.task_type

                func = self._find_callable_tool(tool_name) if tool_name else None
                if func and callable(func):
                    logger.info(f"[DynamicScheduler] 触发嵌套工具 {tool_name} (参数: {tool_params})")

                    sig = inspect.signature(func)
                    kwargs_to_pass = dict(tool_params)
                    if "bot" in sig.parameters and "bot" not in kwargs_to_pass:
                        kwargs_to_pass["bot"] = bot
                    if "event" in sig.parameters and "event" not in kwargs_to_pass:
                        kwargs_to_pass["event"] = event
                    if "config" in sig.parameters and "config" not in kwargs_to_pass:
                        kwargs_to_pass["config"] = config

                    # 参数过滤：如果函数不接收 **kwargs，过滤掉未声明的参数
                    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                    if not has_var_kw:
                        kwargs_to_pass = {k: v for k, v in kwargs_to_pass.items() if k in sig.parameters}

                    if asyncio.iscoroutinefunction(func):
                        res = await func(**kwargs_to_pass)
                    else:
                        res = func(**kwargs_to_pass)
                        if inspect.isawaitable(res):
                            res = await res

                    # 若工具返回了字符串或消息结果，协助发送
                    if res is not None and bot:
                        if isinstance(res, str) and res.strip():
                            if task.target_type == "private":
                                await bot.send_friend_message(task.target_id, [Text(res)])
                            else:
                                await bot.send_group_message(task.target_id, [Text(res)])
                        elif isinstance(res, (list, tuple)) and len(res) > 0:
                            if task.target_type == "private":
                                await bot.send_friend_message(task.target_id, list(res))
                            else:
                                await bot.send_group_message(task.target_id, list(res))
                else:
                    logger.error(f"[DynamicScheduler] 工具 {tool_name} 未找到或不可调用")

            # 2. 自然语言 / 提示词触发生成个性化消息（早安、叫起床、喝水提醒等）或需要由LLM生成的任务
            elif task.action_type in ("message", "prompt", "reminder", "morning_greeting", "night_greeting"):
                prompt = payload.get("prompt") or payload.get("message") or task.description
                sent = False

                # 优先走 mai_reply 的 ReplyEngine.handle 核心流程：
                # 保持上下文记忆追踪、人设印象、TTS语音及情绪管理；
                # 关键优化：
                # 1. include_tools=False：纯提醒/消息生成不注入庞大的工具列表，节约大量 token 并彻底杜绝幻觉乱调用工具；
                # 2. 若任务在 payload 中特别指定了 target_tools / tools_override，则通过 tools_override 针对性开放工具；
                # 3. system_prompt_prefix 强指令：明确告知这是系统定时触发，严禁误判为对方发言（彻底根除“你怎么抢我台词”的误解）。
                if config and hasattr(config, "mai_reply") and config.mai_reply.config.get("enable", False):
                    try:
                        from run.mai_reply.service.reply_engine import ReplyEngine
                        engine = ReplyEngine(config)

                        # 构造系统提示前缀，防误判
                        sys_instruction_prefix = (
                            "【重要系统事件指令 - 严禁误判为对方发言】\n"
                            f"当前时间到达了之前设置的定时提醒/问候触发时刻。\n"
                            f"任务描述: {task.description}\n"
                            "【核心要求】\n"
                            "1. 本消息为系统内部到期自动触发，绝不是对话方对你说的台词！严禁回复诸如'你怎么抢我台词'或将本指令当成对方发言。\n"
                            "2. 请直接以你的人设口吻，主动向对话方发出亲切、自然、生动的提醒或问候内容。"
                        )

                        user_prompt = f"【系统定时任务触发】到期提醒：{prompt}"

                        # 检查是否有显式指定的特定工具覆盖需求
                        target_tools = payload.get("target_tools") or payload.get("tools")
                        tools_override = None
                        include_tools = False

                        if target_tools:
                            # 如果指定了某些特定工具
                            all_tools = engine._active_tools() or {}
                            if isinstance(target_tools, list):
                                tools_override = {k: v for k, v in all_tools.items() if k in target_tools or f"call_{k}" in target_tools}
                            elif isinstance(target_tools, dict):
                                tools_override = target_tools
                            if tools_override:
                                include_tools = True

                        logger.info(f"[DynamicScheduler] 通过 ReplyEngine.handle 执行定时任务 (task_id={task.task_id}, include_tools={include_tools})")
                        await engine.handle(
                            bot=bot,
                            event=event,
                            clean_text=user_prompt,
                            include_tools=include_tools,
                            tools_override=tools_override,
                            system_prompt_prefix=sys_instruction_prefix,
                        )
                        sent = True
                    except Exception as e:
                        logger.warning(f"[DynamicScheduler] 调用 ReplyEngine.handle 执行任务失败: {e}，尝试使用 aiReplyCore 兜底", exc_info=True)

                if not sent:
                    # 降级备用：调用 aiReplyCore 进行拟人回复生成
                    try:
                        from run.ai_llm.service.aiReplyCore import aiReplyCore
                        text = await aiReplyCore([{"text": prompt}], task.target_id, config, bot=bot)
                    except Exception as fallback_err:
                        logger.warning(f"[DynamicScheduler] 降级调用 aiReplyCore 异常: {fallback_err}，直接发送原始提示词")
                        text = prompt

                    if bot and text:
                        if task.target_type == "private":
                            await bot.send_friend_message(task.target_id, [Text(text)] if isinstance(text, str) else text)
                        else:
                            await bot.send_group_message(task.target_id, [Text(text)] if isinstance(text, str) else text)
            # 3. 主动私聊决策联动 (proactive_chat)
            elif task.action_type == "proactive_chat":
                if config and hasattr(config, "mai_reply") and config.mai_reply.config.get("enable", False):
                    from run.mai_reply.service.proactive_service import ProactiveService
                    from run.mai_reply.service.reply_engine import ReplyEngine
                    engine = ReplyEngine(config)
                    proactive_svc = ProactiveService(engine)

                    user_name = f"用户_{task.target_id}"
                    if bot and hasattr(bot, "get_stranger_info"):
                        try:
                            info = await bot.get_stranger_info(user_id=task.target_id)
                            if isinstance(info, dict) and info.get("nickname"):
                                user_name = info["nickname"]
                        except Exception:
                            pass

                    user_impression = engine.context.get_impression(task.target_id) if hasattr(engine.context, "get_impression") else ""
                    topic = payload.get("topic") or task.description
                    care_points = payload.get("care_points") or f"约定的定时互动：{task.description}"
                    decision = {
                        "should_care": True,
                        "topic": topic,
                        "time_perception_note": payload.get("time_note", f"距离约定时间已到，主动找用户聊天：{task.description}"),
                        "care_points": care_points
                    }
                    segments = await proactive_svc.generate_proactive_message(
                        user_name=user_name,
                        decision=decision,
                        search_result=payload.get("search_result", ""),
                        user_impression=user_impression,
                        user_id=task.target_id
                    )
                    if segments:
                        await proactive_svc.send_proactive_care(bot, task.target_id, segments)

        except Exception as e:
            logger.error(f"[DynamicScheduler] 执行任务 {task.task_id} 出错: {e}", exc_info=True)
        finally:
            self._running_tasks.discard(task.task_id)

    # -------------------------------------------------------------------------
    # 调度扫描循环 (Tick Loop)
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # 早晚安时区同步逻辑
    # -------------------------------------------------------------------------
    async def sync_daily_greetings_from_config(self):
        """
        从 scheduled_tasks 配置文件中读取早安和晚安配置，
        结合用户数据库中的 city 属性自动计算时区，
        为每位好友或受信任用户安排差异化时区的早晚安定时任务。
        避免 Bot 统一在东八区同时推送造成的时间错乱。
        """
        if not self.config or not hasattr(self.config, "scheduled_tasks"):
            logger.info("[DynamicScheduler] 未找到 scheduled_tasks 配置，跳过同步")
            return

        try:
            scheduled_tasks_cfg = self.config.scheduled_tasks.config.get("scheduledTasks", {})
        except Exception as e:
            logger.warning(f"[DynamicScheduler] 读取 scheduledTasks 配置失败: {e}")
            return

        morning_cfg = scheduled_tasks_cfg.get("早安问候", {})
        night_cfg = scheduled_tasks_cfg.get("晚安问候", {})

        morning_enable = morning_cfg.get("enable", False)
        night_enable = night_cfg.get("enable", False)

        if not morning_enable and not night_enable:
            logger.info("[DynamicScheduler] 早安问候与晚安问候均未启用")
            return

        from framework_common.database_util.User import get_users_with_permission_above, get_user

        friend_ids = set()
        if self.bot and hasattr(self.bot, "get_friend_list"):
            try:
                friend_list_resp = await self.bot.get_friend_list()
                if isinstance(friend_list_resp, dict) and "data" in friend_list_resp:
                    for item in friend_list_resp["data"]:
                        if "user_id" in item:
                            friend_ids.add(int(item["user_id"]))
            except Exception as e:
                logger.warning(f"[DynamicScheduler] 获取用户或好友列表异常: {e}")

        if not friend_ids:
            try:
                trusted_users = await get_users_with_permission_above(0)
                friend_ids = set(trusted_users)
            except Exception as e:
                logger.warning(f"[DynamicScheduler] 获取用户或好友列表异常: {e}")

        logger.info(f"[DynamicScheduler] 准备为 {len(friend_ids)} 位好友配置差异化时区早晚安任务...")

        # 1. 注册早安问候
        if morning_enable:
            m_time = morning_cfg.get("time", "8/0")
            m_hour, m_minute = self.parse_time_str_to_hour_minute(m_time.replace("/", ":"))
            m_time_str = f"{m_hour:02d}:{m_minute:02d}"
            m_only_trust = morning_cfg.get("onlyTrustUser", False)
            m_threshold = morning_cfg.get("trustThreshold", 20)

            trusted_set = set()
            if m_only_trust:
                try:
                    trusted_set = set(await get_users_with_permission_above(m_threshold))
                except Exception:
                    trusted_set = set()

            for uid in friend_ids:
                if m_only_trust and uid not in trusted_set:
                    continue
                try:
                    u_info = await get_user(uid)
                    city = (u_info.city or "").strip() if u_info else ""
                    task_id = f"daily_morning_{uid}"
                    await self.add_task(
                        creator_id=0,
                        target_type="private",
                        target_id=uid,
                        task_type="morning_greeting",
                        time_str=m_time_str,
                        recur_type="daily",
                        city=city,
                        action_type="morning_greeting",
                        action_payload={"city": city},
                        description=f"对用户 {uid} 的差异化问候",
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"[DynamicScheduler] 为用户 {uid} 安排问候任务失败: {e}")

        # 2. 注册晚安问候
        if night_enable:
            n_time = night_cfg.get("time", "23/30")
            n_hour, n_minute = self.parse_time_str_to_hour_minute(n_time.replace("/", ":"))
            n_time_str = f"{n_hour:02d}:{n_minute:02d}"
            n_only_trust = night_cfg.get("onlyTrustUser", False)
            n_threshold = night_cfg.get("trustThreshold", 20)

            trusted_set = set()
            if n_only_trust:
                try:
                    trusted_set = set(await get_users_with_permission_above(n_threshold))
                except Exception:
                    trusted_set = set()

            for uid in friend_ids:
                if n_only_trust and uid not in trusted_set:
                    continue
                try:
                    u_info = await get_user(uid)
                    city = (u_info.city or "").strip() if u_info else ""
                    task_id = f"daily_night_{uid}"
                    await self.add_task(
                        creator_id=0,
                        target_type="private",
                        target_id=uid,
                        task_type="night_greeting",
                        time_str=n_time_str,
                        recur_type="daily",
                        city=city,
                        action_type="night_greeting",
                        action_payload={"city": city},
                        description=f"对用户 {uid} 的差异化问候",
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"[DynamicScheduler] 为用户 {uid} 安排问候任务失败: {e}")

    async def sync_qzone_tasks_from_config(self):
        """
        从 qq_zone 插件配置文件中读取任务配置并动态同步到调度表中：
        - 定时发空间（早安/晚安等每日任务，每天定时触发 tool: qzone_morning / qzone_night）
        - vtuber日常互动（巡检间隔，interval 周期触发 tool: qzone_vtuber_daily）
        - 动态互动（空间好友评论巡检，interval 周期触发 tool: qzone_comment_reply）
        - cookie设置（保活探测，interval 周期触发 tool: qzone_keepalive）
        """
        if not self.config or not hasattr(self.config, "qq_zone"):
            logger.info("[DynamicScheduler] 未找到 qq_zone 配置，跳过同步")
            return

        try:
            qzone_cfg = getattr(self.config.qq_zone, "config", {}) or {}
        except Exception as e:
            logger.warning(f"[DynamicScheduler] 读取 qq_zone 配置失败: {e}")
            return

        master_id = 0
        try:
            if hasattr(self.config, "common_config"):
                master_id = int(self.config.common_config.basic_config.get("master", {}).get("id", 0) or 0)
        except Exception:
            pass

        # 1. 同步【定时发空间】任务（如早安、晚安）
        scheduled_posts = qzone_cfg.get("定时发空间", {})
        for task_name, task_info in scheduled_posts.items():
            task_id = f"qzone_post_{task_name}"
            tool_name = f"qzone_{task_name}" if task_name in ("早安", "晚安") else "qzone_post_task"
            if not task_info.get("enable", False):
                await self.remove_task(task_id)
                continue

            raw_time = str(task_info.get("time", "8/30"))
            hour, minute = self.parse_time_str_to_hour_minute(raw_time)
            time_str = f"{hour:02d}:{minute:02d}"

            await self.add_task(
                creator_id=master_id,
                target_type="private",
                target_id=master_id,
                task_type="qzone_post",
                time_str=time_str,
                recur_type="daily",
                city="Asia/Shanghai",
                action_type="tool",
                action_payload={
                    "tool_name": tool_name,
                    "tool_params": {"task_name": task_name, "task_info": dict(task_info)}
                },
                description=f"QQ空间定时说说 [{task_name}] (每天 {time_str})",
                task_id=task_id,
            )
            logger.info(f"[DynamicScheduler] QQ空间定时任务已同步: {task_id} -> 每天 {time_str}")

        # 2. 同步【vtuber日常互动】
        vtuber_cfg = qzone_cfg.get("vtuber日常互动", {})
        vtuber_task_id = "qzone_vtuber_daily"
        if vtuber_cfg.get("enable", True):
            interval_min = max(10, int(vtuber_cfg.get("巡检间隔_分钟", 60)))
            vtuber_time_str = f"{interval_min * 60}s"
            await self.add_task(
                creator_id=master_id,
                target_type="private",
                target_id=master_id,
                task_type="qzone_vtuber_daily",
                time_str=vtuber_time_str,
                recur_type="interval",
                action_type="tool",
                action_payload={"tool_name": "qzone_vtuber_daily"},
                description=f"QQ空间Vtuber日常巡检 (每 {interval_min} 分钟)",
                task_id=vtuber_task_id,
            )
            logger.info(f"[DynamicScheduler] QQ空间Vtuber日常巡检已同步: {vtuber_task_id} -> 每 {interval_min} 分钟")
        else:
            await self.remove_task(vtuber_task_id)

        # 3. 同步【动态互动】（好友评论自动回复巡检）
        inter_cfg = qzone_cfg.get("动态互动", {})
        comment_task_id = "qzone_comment_reply"
        if inter_cfg.get("enable_comment_reply", True):
            interval_sec = max(60, int(inter_cfg.get("check_interval_秒", 180)))
            comment_time_str = f"{interval_sec}s"
            await self.add_task(
                creator_id=master_id,
                target_type="private",
                target_id=master_id,
                task_type="qzone_comment_reply",
                time_str=comment_time_str,
                recur_type="interval",
                action_type="tool",
                action_payload={"tool_name": "qzone_comment_reply"},
                description=f"QQ空间动态评论回复巡检 (每 {interval_sec} 秒)",
                task_id=comment_task_id,
            )
            logger.info(f"[DynamicScheduler] QQ空间评论回复巡检已同步: {comment_task_id} -> 每 {interval_sec} 秒")
        else:
            await self.remove_task(comment_task_id)

        # 4. 同步【cookie设置】保活探测
        cookie_cfg = qzone_cfg.get("cookie设置", {})
        keepalive_task_id = "qzone_keepalive"
        if cookie_cfg.get("保活", True):
            keepalive_sec = max(600, int(cookie_cfg.get("保活间隔_秒", 1800)))
            keepalive_time_str = f"{keepalive_sec}s"
            await self.add_task(
                creator_id=master_id,
                target_type="private",
                target_id=master_id,
                task_type="qzone_keepalive",
                time_str=keepalive_time_str,
                recur_type="interval",
                action_type="tool",
                action_payload={"tool_name": "qzone_keepalive"},
                description=f"QQ空间Cookie温和保活巡检 (每 {keepalive_sec} 秒)",
                task_id=keepalive_task_id,
            )
            logger.info(f"[DynamicScheduler] QQ空间保活巡检已同步: {keepalive_task_id} -> 每 {keepalive_sec} 秒")
        else:
            await self.remove_task(keepalive_task_id)

    async def tick(self):
        """单次调度扫描：检测到达触发时间的任务并执行，更新下一次触发时间"""
        if self._tick_lock.locked():
            return

        async with self._tick_lock:
            await self.init_db()
            now_ts = time.time()

            tasks_to_run = []
            async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM dynamic_tasks WHERE status = 'active' AND next_run_timestamp <= ?",
                    (now_ts,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        t = ScheduledTask(**dict(row))
                        if t.task_id not in self._running_tasks:
                            tasks_to_run.append(t)

            if not tasks_to_run:
                return

            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for task in tasks_to_run:
                # 立即计算并更新下一次触发状态，防止重复扫描
                next_ts = self.calculate_next_recur_run(task)
                async with aiosqlite.connect(getattr(self, 'db_path', DB_PATH)) as db:
                    if next_ts is not None:
                        await db.execute(
                            "UPDATE dynamic_tasks SET next_run_timestamp = ?, last_run_at = ? WHERE task_id = ?",
                            (next_ts, now_iso, task.task_id)
                        )
                        next_dt_str = datetime.datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(f"[DynamicScheduler] 循环任务 [{task.task_id}] ({task.description}) 到期执行，下一次触发时间: {next_dt_str}")
                    else:
                        await db.execute(
                            "UPDATE dynamic_tasks SET status = 'completed', last_run_at = ? WHERE task_id = ?",
                            (now_iso, task.task_id)
                        )
                        logger.info(f"[DynamicScheduler] 一次性任务 [{task.task_id}] ({task.description}) 到期执行完毕，已持久化标记为完成 (status='completed')，移出待执行队列")
                    await db.commit()

                asyncio.create_task(self.execute_task(task))

    async def _scheduler_loop(self):
        logger.info("[DynamicScheduler] 核心调度监控循环已启动")
        try:
            active_tasks = await self.list_active_tasks()
            logger.info(f"[DynamicScheduler] 启动持久化恢复完毕：成功载入 {len(active_tasks)} 个生效中的持久化定时任务")
            for t in active_tasks:
                next_time_str = datetime.datetime.fromtimestamp(t.next_run_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"  -> 持久化任务 [{t.task_id}] | 描述: {t.description} | 下次执行: {next_time_str} | 动作: {t.action_type}")
        except Exception as e:
            logger.warning(f"[DynamicScheduler] 启动加载持久化任务列表异常: {e}")

        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DynamicScheduler] 扫描循环异常: {e}", exc_info=True)
            await asyncio.sleep(10)

    def start(self):
        if self._running:
            return
        self._running = True
        self._bg_task = asyncio.create_task(self._scheduler_loop(), name="dynamic-scheduler-loop")

    def stop(self):
        self._running = False
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()


def get_scheduler(bot=None, config=None, db_path: str = DB_PATH) -> DynamicScheduler:
    return DynamicScheduler.get_instance(bot=bot, config=config, db_path=db_path)
