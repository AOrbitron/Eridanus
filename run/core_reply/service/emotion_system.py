"""
emotion_system.py
情绪系统 —— 维护bot的当前情绪状态，随时间自然衰减
情绪会影响persona prompt中的{mood}字段
"""

import random
import time
from typing import Optional

from framework_common.database_util.RedisCacheManager import create_custom_cache_manager


class EmotionSystem:
    """
    bot情绪状态管理器。
    使用Redis存储当前情绪，支持TTL自动衰减。
    每个bot实例共享一个全局情绪（不区分群/用户）。
    """

    EMOTION_KEY = "core_reply:emotion:current"
    EMOTION_SCORE_KEY = "core_reply:emotion:score"  # -100 ~ 100 的数值情绪

    def __init__(self, config):
        self.cfg = config
        ecfg = config.core_reply.config.get("emotion", {})
        self.enable = ecfg.get("enable", True)
        self.decay_rate_min = ecfg.get("decay_rate_min", 20)
        self.default_mood = ecfg.get("default_mood", "还行，没啥特别的")
        self.moods: list = ecfg.get("moods", [self.default_mood])
        db = ecfg.get("redis_db", 4)
        # TTL = decay_rate_min * len(moods) 分钟，确保全衰减到默认
        ttl = self.decay_rate_min * max(len(self.moods), 1) * 60
        self._cache = create_custom_cache_manager(db_number=db, cache_ttl=ttl)

    # ------------------------------------------------------------------
    def get_mood(self) -> str:
        """获取当前情绪描述字符串"""
        if not self.enable:
            return self.default_mood
        cached = self._cache.get(self.EMOTION_KEY)
        if cached:
            return cached
        return self.default_mood

    def get_score(self) -> int:
        """获取当前情绪分数（-100 ~ 100）"""
        if not self.enable:
            return 0
        val = self._cache.get(self.EMOTION_SCORE_KEY)
        if val is not None:
            try:
                return int(val)
            except Exception:
                pass
        return 0

    def apply_llm_delta(self, delta: int) -> None:
        """
        接收 LLM 传入的情绪波动值 (通常在 -10 到 10 之间)
        负数表示被骂/遇到负面事件，正数表示被夸/开心
        """
        if not self.enable or delta == 0:
            return

        score = self.get_score()
        score = max(-100, min(100, score + delta))
        self._set_score(score)
        self._update_mood_from_score(score)

    def _set_score(self, score: int) -> None:
        ttl = self.decay_rate_min * max(len(self.moods), 1) * 60
        self._cache.set(self.EMOTION_SCORE_KEY, score, ttl=ttl)

    def _update_mood_from_score(self, score: int) -> None:
        """将数值情绪映射到语言描述，存入Redis"""
        if not self.moods:
            mood = self.default_mood
        else:
            # score -100~100 → index 0~len-1
            idx = int((score + 100) / 200 * (len(self.moods) - 1))
            idx = max(0, min(len(self.moods) - 1, idx))
            mood = self.moods[idx]

        ttl = self.decay_rate_min * max(len(self.moods), 1) * 60
        self._cache.set(self.EMOTION_KEY, mood, ttl=ttl)

    def random_drift(self) -> None:
        """随机小幅漂移情绪（每次bot启动或定时调用，模拟日常情绪波动）"""
        if not self.enable:
            return
        delta = random.randint(-5, 5)
        score = self.get_score() + delta
        score = max(-100, min(100, score))
        self._set_score(score)
        self._update_mood_from_score(score)