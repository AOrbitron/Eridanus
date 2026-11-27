from datetime import datetime

from pydantic import BaseModel


class BubbleInfo(BaseModel):
    add: int
    ts: int


class Bubble(BaseModel):
    normal: BubbleInfo
    assist: BubbleInfo


class BuildingChar(BaseModel):
    """基建进驻干员信息"""

    charId: str
    ap: int
    lastApAddTime: int
    index: int
    bubble: Bubble
    workTime: int


class Labor(BaseModel):
    """无人机"""

    maxValue: int
    value: int
    lastUpdateTime: int
    remainSecs: int

    @property
    def labor_now(self) -> int:
        remaining = self.maxValue - self.value
        if remaining <= 0:
            return self.maxValue
        # Some API payloads report zero remaining time while the stored value
        # is still below the cap. Keep the reported value instead of dividing
        # by a zero-duration interval and failing the entire information card.
        if self.remainSecs <= 0:
            return self.value
        elapsed_time = datetime.now().timestamp() - self.lastUpdateTime
        labor_increment = elapsed_time / (self.remainSecs / remaining)
        return min(int(labor_increment + self.value), self.maxValue)


class Furniture(BaseModel):
    """家具持有数"""

    total: int
