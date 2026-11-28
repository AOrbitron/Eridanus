from urllib.parse import quote
import urllib.request
from pydantic import BaseModel

from .base import Equip
from ...config import RES_DIR, CACHE_DIR
from developTools.utils.logger import get_logger
logger=get_logger('skland')
import os
def download_file(url, save_path):
    try:
        # 使用 urllib.request.urlretrieve 下载文件
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        urllib.request.urlretrieve(url, save_path)
        logger.info(f"文件已成功保存到 {save_path}")
    except Exception as e:
        logger.error(f"下载失败: {e}")

class AssistChar(BaseModel):
    """
    助战干员

    Attributes:
        charId : 干员 ID
        skinId : 皮肤 ID
        level : 等级
        evolvePhase : 升级阶段
        potentialRank : 潜能等级
        skillId : 技能 ID
        mainSkillLvl : 主技能等级
        specializeLevel : 专精等级
        equip : 装备技能
    """

    charId: str
    skinId: str
    level: int
    evolvePhase: int
    potentialRank: int
    skillId: str
    mainSkillLvl: int
    specializeLevel: int
    equip: Equip | None = None
    uniequip: str | None = None

    @property
    def portrait(self) -> str:
        portrait_id = next(
            (self.skinId.replace(symbol, "_", 1) for symbol in ("@", "#") if symbol in self.skinId),
            self.skinId,
        )
        img_path = CACHE_DIR / "portrait" / f"{portrait_id}.png"
        if not img_path.is_file():
            encoded_id = quote(self.skinId, safe="")
            img_url = f"https://web.hycdn.cn/arknights/game/assets/char_skin/portrait/{encoded_id}.png"
            logger.info(f"Portrait not found locally, using URL: {img_url}")
            download_file(img_url, img_path)
            # A Path object is treated as base64 by the drawing pipeline.
            # Return the cached path as text after a successful first download.
            if not img_path.is_file():
                return img_url
        return img_path.as_posix()

    @property
    def potential(self) -> str:
        img_path = RES_DIR / "images" / "ark_card" / "potential" / f"potential_{self.potentialRank}.png"
        return img_path.as_posix()

    @property
    def skill(self) -> str:
        img_path = CACHE_DIR / "skill" / f"skill_icon_{self.skillId}.png"
        if not img_path.exists():
            encoded_id = quote(self.skillId, safe="")
            img_url = f"https://web.hycdn.cn/arknights/game/assets/char_skill/{encoded_id}.png"
            logger.info(f"Skill icon not found locally, using URL: {img_url}")
            download_file(img_url, img_path)
            return img_url
        return img_path.as_posix()

    @property
    def evolve(self) -> str:
        img_path = RES_DIR / "images" / "ark_card" / "elite" / f"elite_{self.evolvePhase}.png"
        return img_path.as_posix()


class Equipment(BaseModel):
    id: str
    name: str
    typeIcon: str
