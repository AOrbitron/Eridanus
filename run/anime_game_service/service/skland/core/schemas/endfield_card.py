"""终末地实时信息，兼容旧统计字段与新增的 items 展示项。"""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field


class EndfieldCount(BaseModel):
    current: int
    total: int


class EndfieldDungeon(EndfieldCount):
    maxTs: str = "0"


class EndfieldItem(BaseModel):
    id: str = ""
    type: str = ""
    name: str = ""
    icon: str = ""
    count: EndfieldCount | None = None
    image: dict[str, str] = Field(default_factory=dict)


class EndfieldStatus(BaseModel):
    bp: EndfieldCount | None = None
    dailyMission: EndfieldCount | None = None
    weeklyMission: EndfieldCount | None = None
    dungeon: EndfieldDungeon | None = None
    pic: str = ""
    signIn: bool | None = None
    items: list[EndfieldItem] = Field(default_factory=list)


class EndfieldCard(BaseModel):
    data: EndfieldStatus
    currentTs: str = "0"

    @property
    def updated_at(self) -> str:
        try:
            timestamp = int(self.currentTs)
            if timestamp > 0:
                return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OverflowError, OSError):
            pass
        return "未公开"

    @property
    def recovery(self) -> str:
        stamina = self.data.dungeon
        if stamina is None:
            return "恢复时间未公开"
        if stamina.current >= stamina.total and stamina.total > 0:
            return "体力已回满"
        try:
            now, maximum = int(self.currentTs), int(stamina.maxTs)
        except (TypeError, ValueError):
            return "恢复时间未公开"
        if now <= 0 or maximum <= 0:
            return "恢复时间未公开"
        minutes = max(0, (maximum - now + 59) // 60)
        if not minutes:
            return "体力已回满"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}小时{minutes}分钟后回满" if hours else f"{minutes}分钟后回满"

    @property
    def counters(self) -> list[tuple[str, str]]:
        """同名旧字段和 items 只展示一次，未公开字段不当作零。"""
        definitions = (
            ("REALTIME_MODULE_DAILY_MISSION", "日常活跃度", self.data.dailyMission),
            ("REALTIME_MODULE_WEEKLY_MISSION", "每周事务", self.data.weeklyMission),
            ("REALTIME_MODULE_BP_SYSTEM", "通行证等级", self.data.bp),
        )
        items = {item.id: item for item in self.data.items if item.id}
        rows = [("体力", self._count(self.data.dungeon))]
        for key, label, fallback in definitions:
            item = items.get(key)
            title = (item.name or label) if item else label
            rows.append((title, self._count(item.count if item and item.count is not None else fallback)))
        seen = {key for key, _, _ in definitions}
        for item in self.data.items:
            if item.count is not None and item.id not in seen:
                rows.append((item.name or "活动进度", self._count(item.count)))
                if item.id:
                    seen.add(item.id)
        signed = self.data.signIn
        rows.append(("今日签到", "已签到" if signed is True else "未签到" if signed is False else "未公开"))
        return rows

    @staticmethod
    def _count(value: EndfieldCount | None) -> str:
        return f"{value.current} / {value.total}" if value is not None else "未公开"
