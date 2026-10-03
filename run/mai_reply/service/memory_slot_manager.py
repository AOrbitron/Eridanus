# -*- coding: utf-8 -*-
"""
memory_slot_manager.py
结构化固定记忆槽位管理层（用户专属10槽位 + Bot全局独立生活10槽位）
- 底层 SQLite 持久化 + Redis 高速缓存
- 无损自动扩展数据库（不破坏任何原有 kv_store 数据）
- 自动平滑迁移旧版全局记忆 (memory:global) 到动态槽位
- 导出 Function Calling 工具供印象更新时自动增删改
- 与 QQ 空间动态联动，自动维护 Bot 自身独立生活足迹
"""

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

from framework_common.utils.system_logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------------------
# 预设槽位蓝图规划
# ------------------------------------------------------------------------------

DEFAULT_USER_SLOT_BLUEPRINTS = [
    {
        "slot_id": 1,
        "category": "基础个人档案",
        "description": "城市/常住地/留学地、时区时差（如莫斯科UTC+3比国内慢5小时）、学校学历、年龄、性别称谓等基础常住信息",
    },
    {
        "slot_id": 2,
        "category": "深度喜好偏好",
        "description": "饮食口味、偏好食物、喜爱动漫作品、游戏、音乐、生活嗜好等",
    },
    {
        "slot_id": 3,
        "category": "雷区禁忌点",
        "description": "讨厌忌口的食物、反感的话题、容易引起不快或避讳的雷区",
    },
    {
        "slot_id": 4,
        "category": "日常作息规律",
        "description": "作息节奏、早起/常熬夜习惯、学习/打工/工作作息与日常生活习惯",
    },
    {
        "slot_id": 5,
        "category": "性格特质风格",
        "description": "性格特质（幽默/内向/傲娇/敏感）、说话风格、习惯口头禅",
    },
    {
        "slot_id": 6,
        "category": "重要人际社会",
        "description": "重要亲友、宠物名字（如猫狗）、重要工作/学业伙伴等社会关系",
    },
    {
        "slot_id": 7,
        "category": "契约约定承诺",
        "description": "与Bot共同约定好的事情、承诺做到的事情、共同秘密或专属暗号",
    },
    {
        "slot_id": 8,
        "category": "重大生平里程1",
        "description": "过往关键生平大事件与大致时间（如2026年求学/考研/秋招/里程碑成就）",
    },
    {
        "slot_id": 9,
        "category": "重大生平里程2",
        "description": "过往难忘转折经历、关键挫折或重要经历，附带大致时间",
    },
    {
        "slot_id": 10,
        "category": "近期核心焦点",
        "description": "近期正全力攻关或牵挂的现实大事件（考试、面试、项目、身体状况等）",
    },
]

DEFAULT_GLOBAL_SLOT_BLUEPRINTS = [
    {
        "slot_id": 1,
        "category": "Bot独立生活状态",
        "description": "Bot自身日常作息规律、起居生活状态与独立于用户的独立日常生活",
    },
    {
        "slot_id": 2,
        "category": "Bot个人兴趣爱好",
        "description": "Bot自己热衷的消遣（追的番剧、在打的游戏、爱喝的饮品、烹饪等）",
    },
    {
        "slot_id": 3,
        "category": "Bot世界观个性",
        "description": "Bot对世界人事的独立见解、人生态度与鲜活的傲娇/温柔/随性个性",
    },
    {
        "slot_id": 4,
        "category": "Bot自发心愿目标",
        "description": "Bot自己想学的新技能、想去旅游打卡的地方、自发的长远愿望",
    },
    {
        "slot_id": 5,
        "category": "Bot社交日常圈子",
        "description": "Bot在生活里接触的朋友圈、同伴或搭档（展现真实饱满的社交生活）",
    },
    {
        "slot_id": 6,
        "category": "Bot空间生活动态1",
        "description": "最新发布的QQ空间动态或生活日常足迹（包含[MM-DD HH:MM]时间戳）",
    },
    {
        "slot_id": 7,
        "category": "Bot空间生活动态2",
        "description": "前次发布的QQ空间动态或生活日常足迹（包含[MM-DD HH:MM]时间戳）",
    },
    {
        "slot_id": 8,
        "category": "Bot空间生活动态3",
        "description": "较早前的QQ空间动态或生活日常足迹（包含[MM-DD HH:MM]时间戳）",
    },
    {
        "slot_id": 9,
        "category": "Bot空间生活动态4",
        "description": "历史QQ空间动态或生活日常足迹（包含[MM-DD HH:MM]时间戳）",
    },
    {
        "slot_id": 10,
        "category": "Bot近期心境感悟",
        "description": "Bot近期独立经历所产生的深刻生活心境、季节感慨或自我思考",
    },
]


class MemorySlotManager:
    """
    结构化固定记忆槽位管理器
    负责用户专属事实记忆槽位与 Bot 全局独立生活记忆槽位的维护与持久化
    """

    def __init__(
        self,
        db_path: str = "data/database/impression_store.db",
        cache_manager=None,
        config=None,
    ):
        self.db_path = db_path
        self._cache = cache_manager
        self._cfg = config

        # 读取配置项
        ccfg = {}
        if config:
            if hasattr(config, "mai_reply") and hasattr(config.mai_reply, "config"):
                ccfg = config.mai_reply.config.get("context", {})
            elif isinstance(config, dict):
                ccfg = config.get("context", {})

        self.enable: bool = ccfg.get("enable_memory_slots", True)
        self.global_slot_count: int = int(ccfg.get("global_memory_slot_count", 10))
        self.user_slot_count: int = int(ccfg.get("user_memory_slot_count", 10))
        self.slot_max_chars: int = int(ccfg.get("memory_slot_max_chars", 120))
        self.cache_ttl: int = int(ccfg.get("impression_ttl", 604800))

        # 确保数据库目录存在并建立 SQLite 连接
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()

    def _init_db(self) -> None:
        """自动无损扩展数据表（完全保留原有 kv_store 数据）"""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_slots (
                owner_type TEXT NOT NULL,
                owner_id   TEXT NOT NULL,
                slot_id    INTEGER NOT NULL,
                category   TEXT NOT NULL DEFAULT '',
                content    TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (owner_type, owner_id, slot_id)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_slots_owner ON memory_slots (owner_type, owner_id)"
        )
        self._conn.commit()

        # 尝试自动平滑迁移旧版全局记忆
        self._migrate_legacy_global_memory()

    def _migrate_legacy_global_memory(self) -> None:
        """将旧版 kv_store 中的 memory:global 平滑迁移到全局槽位 6..9"""
        try:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM memory_slots WHERE owner_type = 'global' AND content != ''"
            )
            count = cur.fetchone()[0]
            if count > 0:
                return

            # 查询 kv_store 是否存在且有数据
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='kv_store'"
            )
            if not cur.fetchone():
                return

            cur = self._conn.execute(
                "SELECT value FROM kv_store WHERE key = 'memory:global'"
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return

            raw = row[0]
            items = []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    items = [str(x).strip() for x in parsed if str(x).strip()]
                elif isinstance(parsed, str) and parsed.strip():
                    items = [parsed.strip()]
            except Exception:
                if raw.strip():
                    items = [raw.strip()]

            if not items:
                return

            logger.info(f"[MemorySlots] 检测到旧版全局记忆 {len(items)} 条，正在平滑迁移至独立生活槽位...")
            target_slot = 6
            now_ts = int(time.time())
            for item in items[-4:]:
                if target_slot > 9:
                    break
                cat = f"Bot空间生活动态{target_slot - 5}"
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_slots 
                    (owner_type, owner_id, slot_id, category, content, updated_at)
                    VALUES ('global', 'global', ?, ?, ?, ?)
                    """,
                    (target_slot, cat, item[:self.slot_max_chars], now_ts),
                )
                target_slot += 1
            self._conn.commit()
            logger.info("[MemorySlots] 旧版全局记忆平滑迁移完成！")
        except Exception as e:
            logger.warning(f"[MemorySlots] 平滑迁移旧版全局记忆跳过或忽略: {e}")

    # --------------------------------------------------------------------------
    # 蓝图定义获取
    # --------------------------------------------------------------------------

    def get_user_blueprints(self) -> List[Dict[str, Any]]:
        bps = []
        for i in range(1, self.user_slot_count + 1):
            if i <= len(DEFAULT_USER_SLOT_BLUEPRINTS):
                bps.append(dict(DEFAULT_USER_SLOT_BLUEPRINTS[i - 1]))
            else:
                bps.append({
                    "slot_id": i,
                    "category": f"重要事实记忆{i}",
                    "description": "用户专属重要事实记录",
                })
        return bps

    def get_global_blueprints(self) -> List[Dict[str, Any]]:
        bps = []
        for i in range(1, self.global_slot_count + 1):
            if i <= len(DEFAULT_GLOBAL_SLOT_BLUEPRINTS):
                bps.append(dict(DEFAULT_GLOBAL_SLOT_BLUEPRINTS[i - 1]))
            else:
                bps.append({
                    "slot_id": i,
                    "category": f"Bot独立生活记忆{i}",
                    "description": "Bot自身独立经历记忆",
                })
        return bps

    # --------------------------------------------------------------------------
    # 底层读写与缓存
    # --------------------------------------------------------------------------

    def _cache_key(self, owner_type: str, owner_id: str) -> str:
        return f"memslot:{owner_type}:{owner_id}"

    def _load_slots_from_db(self, owner_type: str, owner_id: str) -> Dict[int, Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT slot_id, category, content, updated_at 
            FROM memory_slots 
            WHERE owner_type = ? AND owner_id = ?
            """,
            (owner_type, str(owner_id)),
        ).fetchall()
        result = {}
        for r in rows:
            result[r[0]] = {
                "slot_id": r[0],
                "category": r[1],
                "content": r[2],
                "updated_at": r[3],
            }
        return result

    def _get_all_slots(
        self, owner_type: str, owner_id: str, blueprints: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        cache_key = self._cache_key(owner_type, owner_id)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached:
                try:
                    data = json.loads(cached)
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass

        db_slots = self._load_slots_from_db(owner_type, owner_id)
        final_list = []
        for bp in blueprints:
            sid = bp["slot_id"]
            if sid in db_slots:
                item = db_slots[sid]
                final_list.append({
                    "slot_id": sid,
                    "category": item["category"] or bp["category"],
                    "content": item["content"] or "",
                    "description": bp.get("description", ""),
                    "updated_at": item["updated_at"],
                })
            else:
                final_list.append({
                    "slot_id": sid,
                    "category": bp["category"],
                    "content": "",
                    "description": bp.get("description", ""),
                    "updated_at": 0,
                })

        if self._cache:
            try:
                self._cache.set(cache_key, json.dumps(final_list, ensure_ascii=False), ttl=self.cache_ttl)
            except Exception:
                pass
        return final_list

    def _invalidate_cache(self, owner_type: str, owner_id: str) -> None:
        if self._cache:
            try:
                self._cache.delete(self._cache_key(owner_type, owner_id))
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # 用户事实记忆槽位操作
    # --------------------------------------------------------------------------

    def get_user_slots(self, user_id: int) -> List[Dict[str, Any]]:
        if not self.enable:
            return []
        return self._get_all_slots("user", str(user_id), self.get_user_blueprints())

    def set_user_slot(
        self, user_id: int, slot_id: int, content: str, category: Optional[str] = None
    ) -> bool:
        if not self.enable:
            return False
        slot_id = int(slot_id)
        if slot_id < 1 or slot_id > self.user_slot_count:
            logger.warning(f"[MemorySlots] 槽位超出范围: {slot_id} (有效范围 1..{self.user_slot_count})")
            return False

        clean_content = content.strip()[:self.slot_max_chars]
        if not category:
            bps = self.get_user_blueprints()
            category = bps[slot_id - 1]["category"] if slot_id <= len(bps) else f"槽位{slot_id}"

        now_ts = int(time.time())
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_slots 
            (owner_type, owner_id, slot_id, category, content, updated_at)
            VALUES ('user', ?, ?, ?, ?, ?)
            """,
            (str(user_id), slot_id, category, clean_content, now_ts),
        )
        self._conn.commit()
        self._invalidate_cache("user", str(user_id))
        logger.info(f"[MemorySlots] 用户 {user_id} 槽位 {slot_id} [{category}] 写入: {clean_content}")
        return True

    def clear_user_slot(self, user_id: int, slot_id: int) -> bool:
        slot_id = int(slot_id)
        self._conn.execute(
            "DELETE FROM memory_slots WHERE owner_type = 'user' AND owner_id = ? AND slot_id = ?",
            (str(user_id), slot_id),
        )
        self._conn.commit()
        self._invalidate_cache("user", str(user_id))
        logger.info(f"[MemorySlots] 用户 {user_id} 槽位 {slot_id} 已清空")
        return True

    def clear_all_user_slots(self, user_id: int) -> int:
        cur = self._conn.execute(
            "DELETE FROM memory_slots WHERE owner_type = 'user' AND owner_id = ?",
            (str(user_id),),
        )
        count = cur.rowcount
        self._conn.commit()
        self._invalidate_cache("user", str(user_id))
        logger.info(f"[MemorySlots] 用户 {user_id} 共 {count} 个槽位已全部清空")
        return count

    # --------------------------------------------------------------------------
    # Bot 全局独立生活记忆槽位操作
    # --------------------------------------------------------------------------

    def get_global_slots(self) -> List[Dict[str, Any]]:
        if not self.enable:
            return []
        return self._get_all_slots("global", "global", self.get_global_blueprints())

    def set_global_slot(
        self, slot_id: int, content: str, category: Optional[str] = None
    ) -> bool:
        if not self.enable:
            return False
        slot_id = int(slot_id)
        if slot_id < 1 or slot_id > self.global_slot_count:
            logger.warning(f"[MemorySlots] 槽位超出范围: {slot_id} (有效范围 1..{self.global_slot_count})")
            return False

        clean_content = content.strip()[:self.slot_max_chars]
        if not category:
            bps = self.get_global_blueprints()
            category = bps[slot_id - 1]["category"] if slot_id <= len(bps) else f"槽位{slot_id}"

        now_ts = int(time.time())
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_slots 
            (owner_type, owner_id, slot_id, category, content, updated_at)
            VALUES ('global', 'global', ?, ?, ?, ?)
            """,
            (slot_id, category, clean_content, now_ts),
        )
        self._conn.commit()
        self._invalidate_cache("global", "global")
        logger.info(f"[MemorySlots] Bot全局生活槽位 {slot_id} [{category}] 写入: {clean_content}")
        return True

    def clear_global_slot(self, slot_id: int) -> bool:
        slot_id = int(slot_id)
        self._conn.execute(
            "DELETE FROM memory_slots WHERE owner_type = 'global' AND owner_id = 'global' AND slot_id = ?",
            (slot_id,),
        )
        self._conn.commit()
        self._invalidate_cache("global", "global")
        logger.info(f"[MemorySlots] Bot全局生活槽位 {slot_id} 已清空")
        return True

    def clear_all_global_slots(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM memory_slots WHERE owner_type = 'global' AND owner_id = 'global'"
        )
        count = cur.rowcount
        self._conn.commit()
        self._invalidate_cache("global", "global")
        logger.info(f"[MemorySlots] Bot全局生活槽位共 {count} 条已全部清空")
        return count

    def add_global_event(self, content: str, timestamp_str: Optional[str] = None) -> bool:
        """
        与 QQ 空间动态及日常事件联动：
        将新的生活日常或空间动态推入槽位 6..9，依次后移淘汰最老记录
        """
        if not self.enable or not content or not content.strip():
            return False

        clean_text = content.strip()
        if not clean_text.startswith("["):
            ts = timestamp_str or datetime.now().strftime("%m-%d %H:%M")
            clean_text = f"[{ts}] {clean_text}"

        clean_text = clean_text[:self.slot_max_chars]

        # 读取 6 至 9 槽位并后移
        slots = {s["slot_id"]: s for s in self.get_global_slots()}
        s6 = slots.get(6, {}).get("content", "")
        s7 = slots.get(7, {}).get("content", "")
        s8 = slots.get(8, {}).get("content", "")

        # 依次向下平移: 8->9, 7->8, 6->7, 新事件->6
        if s8:
            self.set_global_slot(9, s8, "Bot空间生活动态4")
        if s7:
            self.set_global_slot(8, s7, "Bot空间生活动态3")
        if s6:
            self.set_global_slot(7, s6, "Bot空间生活动态2")

        self.set_global_slot(6, clean_text, "Bot空间生活动态1")
        logger.info(f"[MemorySlots Qzone联动] 成功记录Bot生活日常: {clean_text}")
        return True

    # --------------------------------------------------------------------------
    # 文本格式化与注入
    # --------------------------------------------------------------------------

    def format_user_slots_for_prompt(self, user_id: int) -> str:
        """格式化用户专属长期事实记忆，注入到回复时的 system prompt"""
        if not self.enable:
            return ""
        slots = self.get_user_slots(user_id)
        lines = []
        for s in slots:
            content = s.get("content", "").strip()
            if content:
                cat = s.get("category", "").strip() or f"槽位{s['slot_id']}"
                lines.append(f"- [{cat}] {content}")
        return "\n".join(lines)

    def format_global_slots_for_prompt(self) -> str:
        """格式化 Bot 全局独立生活记忆，注入到回复时的 system prompt"""
        if not self.enable:
            return ""
        slots = self.get_global_slots()
        lines = []
        for s in slots:
            content = s.get("content", "").strip()
            if content:
                cat = s.get("category", "").strip() or f"生活记忆{s['slot_id']}"
                lines.append(f"- [{cat}] {content}")
        return "\n".join(lines)

    def format_user_slots_for_updater(self, user_id: int) -> str:
        """格式化给印象更新器查看的当前 1..10 槽位现状与规划提示"""
        slots = self.get_user_slots(user_id)
        lines = []
        for s in slots:
            sid = s["slot_id"]
            cat = s.get("category", "")
            content = s.get("content", "").strip()
            desc = s.get("description", "")
            val = content if content else "（空）"
            lines.append(f"槽位{sid} [{cat}]：{val} （槽位规划建议：{desc}）")
        return "\n".join(lines)

    def format_global_slots_for_updater(self) -> str:
        """格式化给印象更新器查看的当前 Bot 全局生活槽位"""
        slots = self.get_global_slots()
        lines = []
        for s in slots:
            sid = s["slot_id"]
            cat = s.get("category", "")
            content = s.get("content", "").strip()
            desc = s.get("description", "")
            val = content if content else "（空）"
            lines.append(f"槽位{sid} [{cat}]：{val} （槽位规划建议：{desc}）")
        return "\n".join(lines)

    # --------------------------------------------------------------------------
    # Function Calling 工具集生成
    # --------------------------------------------------------------------------

    def build_updater_tools(self, user_id: int, user_name: str) -> Dict[str, Any]:
        """
        为 ImpressionUpdater 构造 Function Calling 工具字典
        自动绑定特定 user_id，LLM 仅需提供 slot_id 与 content
        """
        manager = self

        async def set_user_memory_slot(slot_id: int, content: str, category: str = "", **kwargs) -> str:
            try:
                sid = int(slot_id)
            except Exception:
                return f"错误：slot_id 必须为整数数字，收到: {slot_id}"
            ok = manager.set_user_slot(user_id, sid, content, category)
            if ok:
                return f"成功记录用户 {user_name} 事实记忆槽位 {sid} 为: {content}"
            return f"写入失败，slot_id 须在 1..{manager.user_slot_count} 范围内"

        async def clear_user_memory_slot(slot_id: int, **kwargs) -> str:
            try:
                sid = int(slot_id)
            except Exception:
                return f"错误：slot_id 必须为整数数字，收到: {slot_id}"
            manager.clear_user_slot(user_id, sid)
            return f"成功清空用户 {user_name} 事实记忆槽位 {sid}"

        async def set_global_memory_slot(slot_id: int, content: str, category: str = "", **kwargs) -> str:
            try:
                sid = int(slot_id)
            except Exception:
                return f"错误：slot_id 必须为整数数字，收到: {slot_id}"
            ok = manager.set_global_slot(sid, content, category)
            if ok:
                return f"成功记录Bot自身全局生活记忆槽位 {sid} 为: {content}"
            return f"写入失败，slot_id 须在 1..{manager.global_slot_count} 范围内"

        async def clear_global_memory_slot(slot_id: int, **kwargs) -> str:
            try:
                sid = int(slot_id)
            except Exception:
                return f"错误：slot_id 必须为整数数字，收到: {slot_id}"
            manager.clear_global_slot(sid)
            return f"成功清空Bot自身全局生活记忆槽位 {sid}"

        tools = {
            "set_user_memory_slot": {
                "func": set_user_memory_slot,
                "declaration": {
                    "name": "set_user_memory_slot",
                    "description": (
                        f"记录或更新关于用户 {user_name} 的长期客观事实记忆槽位（1至{self.user_slot_count}）。"
                        "用于沉淀该用户的硬事实（如所在地/城市/留学地、时差时区、学校学历、职业、喜好/雷区、重要纪念日/经历里程碑、彼此约定等）。"
                        "单条记忆内容务必精炼客观（建议30-80字），突出重要事实。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slot_id": {
                                "type": "integer",
                                "description": f"记忆槽位编号（1至{self.user_slot_count}）",
                            },
                            "content": {
                                "type": "string",
                                "description": "客观事实记忆内容（简短精炼，建议30-80字）",
                            },
                            "category": {
                                "type": "string",
                                "description": "记忆分类标签（可选，留空则使用默认蓝图规划）",
                            },
                        },
                        "required": ["slot_id", "content"],
                    },
                },
            },
            "clear_user_memory_slot": {
                "func": clear_user_memory_slot,
                "declaration": {
                    "name": "clear_user_memory_slot",
                    "description": f"清空关于用户 {user_name} 的某个过期或失效的客观事实记忆槽位（1至{self.user_slot_count}）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slot_id": {
                                "type": "integer",
                                "description": f"要清空的记忆槽位编号（1至{self.user_slot_count}）",
                            },
                        },
                        "required": ["slot_id"],
                    },
                },
            },
            "set_global_memory_slot": {
                "func": set_global_memory_slot,
                "declaration": {
                    "name": "set_global_memory_slot",
                    "description": (
                        f"记录或更新Bot自身的全局独立生活与人生经历记忆槽位（1至{self.global_slot_count}）。"
                        "用于沉淀Bot自己独立经历过的事件、生活作息、兴趣爱好、深刻感悟或自发愿望，体现Bot独立人格。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slot_id": {
                                "type": "integer",
                                "description": f"记忆槽位编号（1至{self.global_slot_count}）",
                            },
                            "content": {
                                "type": "string",
                                "description": "Bot自身的生活经历或感悟（30-80字内）",
                            },
                            "category": {
                                "type": "string",
                                "description": "分类标签（可选）",
                            },
                        },
                        "required": ["slot_id", "content"],
                    },
                },
            },
            "clear_global_memory_slot": {
                "func": clear_global_memory_slot,
                "declaration": {
                    "name": "clear_global_memory_slot",
                    "description": f"清空Bot自身全局独立生活记忆槽位（1至{self.global_slot_count}）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slot_id": {
                                "type": "integer",
                                "description": f"要清空的记忆槽位编号（1至{self.global_slot_count}）",
                            },
                        },
                        "required": ["slot_id"],
                    },
                },
            },
        }

        return tools

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass