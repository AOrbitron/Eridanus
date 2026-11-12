"""
context_manager.py
上下文/记忆管理 —— Redis 热缓存 + SQLite 冷存储双层持久化
- Redis 负责快速读写（TTL 热缓存）
- SQLite 负责永久落盘（重启/缓存清理后自动恢复）
- 写入时同时写 Redis + SQLite
- 读取时 Redis miss 则从 SQLite 回填
- 新增：群聊气氛印象（group_impression）存储
- 新增：群聊最近发言者追踪（用于批量读取 impression）
"""

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Optional

from framework_common.database_util.RedisCacheManager import create_custom_cache_manager
from framework_common.utils.system_logger import get_logger
from run.core_reply.service.memory_slot_manager import MemorySlotManager

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# SQLite 持久层（独立辅助类，方便测试和替换）
# ──────────────────────────────────────────────────────────────────────────────

class SQLitePersistence:
    """
    极简 KV 持久层，使用 SQLite。
    value 统一存 TEXT（调用方负责 JSON 序列化）。
    线程安全：使用 check_same_thread=False + WAL 模式。
    """

    def __init__(self, db_path: str = "context_store.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, int(time.time())),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        self._conn.commit()

    def keys_like(self, pattern: str) -> List[str]:
        sql_pattern = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%")
        rows = self._conn.execute(
            "SELECT key FROM kv_store WHERE key LIKE ? ESCAPE '\\'", (sql_pattern,)
        ).fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        self._conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# ContextManager 主类
# ──────────────────────────────────────────────────────────────────────────────

class ContextManager:

    def __init__(self, config):
        self.cfg = config
        ccfg = config.core_reply.config.get("context", {})
        self.max_turns: int = ccfg.get("max_turns", 20)
        self.group_window: int = ccfg.get("group_context_window", 15)
        self.session_ttl: int = ccfg.get("session_ttl", 7200)

        imp_cfg = ccfg.get("Impression") or ccfg.get("impression") or {}
        slots_cfg = ccfg.get("Slots") or ccfg.get("slots") or {}

        self.impression_ttl: int = int(imp_cfg.get("impression_ttl", ccfg.get("impression_ttl", 604800)))
        self.group_impression_ttl: int = self.impression_ttl
        # 群聊记忆白名单配置（通用支持群生态特征槽位与群整体印象）
        self.group_memory_whitelist_enabled: bool = bool(
            ccfg.get(
                "group_memory_whitelist_enabled",
                ccfg.get("group_impression_whitelist_enabled", True),
            )
        )
        raw_gwl = ccfg.get("group_memory_whitelist", ccfg.get("group_impression_whitelist", []))
        self.group_memory_whitelist: list = [
            int(x) for x in raw_gwl if str(x).isdigit()
        ]
        self.group_impression_whitelist_enabled: bool = self.group_memory_whitelist_enabled
        self.group_impression_whitelist: list = self.group_memory_whitelist
        # 群聊回复时，最多读取最近 N 位发言者的记忆（槽位特征或主观印象）
        self.group_reply_speaker_memory_count: int = int(
            ccfg.get("group_reply_speaker_memory_count", ccfg.get("group_reply_impression_count", 3))
        )
        self.group_reply_impression_count: int = self.group_reply_speaker_memory_count

        db_cfg = config.core_reply.config.get("redis", {})
        ctx_db = db_cfg.get("context_db", 5)
        imp_db = db_cfg.get("impression_db", 6)

        self._ctx_cache = create_custom_cache_manager(db_number=ctx_db, cache_ttl=self.session_ttl)
        self._imp_cache = create_custom_cache_manager(db_number=imp_db, cache_ttl=self.impression_ttl)

        # SQLite 持久层
        sqlite_cfg = config.core_reply.config.get("sqlite", {})
        ctx_sqlite_path  = sqlite_cfg.get("context_db_path",    "data/context_store.db")
        imp_sqlite_path  = sqlite_cfg.get("impression_db_path", "data/impression_store.db")

        self._ctx_sqlite = SQLitePersistence(ctx_sqlite_path)
        self._imp_sqlite = SQLitePersistence(imp_sqlite_path)

        # 记忆模式主控与槽位/印象归一化解析（memory_mode 为最高主控，slots 与 impression 严格互斥，仅 both 时兼备）
        self.group_memory_slot_count: int = int(slots_cfg.get("group_memory_slot_count", ccfg.get("group_memory_slot_count", 10)))
        self.group_user_context_turns: int = int(slots_cfg.get("group_user_context_turns", ccfg.get("group_user_context_turns", 3)))
        self._warned_user_mode: bool = False
        self._warned_group_mode: bool = False

        # 1. 用户记忆模式解析与归一化（优先从嵌套的 Impression/Slots 提取，兼顾扁平配置）
        raw_user_mode = str(ccfg.get("user_memory_mode", "")).strip().lower()
        cfg_imp = bool(imp_cfg.get("enable_impression", ccfg.get("enable_impression", False)))
        cfg_slots = bool(slots_cfg.get("enable_memory_slots", ccfg.get("enable_memory_slots", True)))
        self.enable_global_memory_slots = bool(slots_cfg.get(
            "enable_global_memory_slots", ccfg.get("enable_global_memory_slots", True)
        ))

        if raw_user_mode == "slots":
            self.user_memory_mode = "slots"
            self.enable_memory_slots = cfg_slots
            self.enable_impression = False
            if cfg_imp:
                logger.warning("[MaiReply] user_memory_mode 设为 'slots'，主观印象(Impression)配置视同关闭以节省API token。")
        elif raw_user_mode == "impression":
            self.user_memory_mode = "impression"
            self.enable_memory_slots = False
            self.enable_impression = cfg_imp
            if cfg_slots:
                logger.warning("[MaiReply] user_memory_mode 设为 'impression'，记忆槽位(Slots)配置视同关闭。")
        elif raw_user_mode == "both":
            self.user_memory_mode = "both"
            self.enable_memory_slots = cfg_slots
            self.enable_impression = cfg_imp
        elif raw_user_mode == "none":
            self.user_memory_mode = "none"
            self.enable_memory_slots = False
            self.enable_impression = False
        else:
            if cfg_slots and cfg_imp:
                self.user_memory_mode = "slots"
                self.enable_memory_slots = True
                self.enable_impression = False
                logger.warning("[MaiReply] 未显式配置 user_memory_mode，默认采用 'slots' 并视同关闭主观印象以节省API token。")
            elif cfg_slots:
                self.user_memory_mode = "slots"
                self.enable_memory_slots = True
                self.enable_impression = False
            elif cfg_imp:
                self.user_memory_mode = "impression"
                self.enable_memory_slots = False
                self.enable_impression = True
            else:
                self.user_memory_mode = "none"
                self.enable_memory_slots = False
                self.enable_impression = False

        # 2. 群聊记忆模式解析与归一化（优先从嵌套的 Impression/Slots 提取，兼顾扁平配置）
        raw_group_mode = str(ccfg.get("group_memory_mode", "")).strip().lower()
        cfg_grp_imp = bool(imp_cfg.get("enable_group_impression", ccfg.get("enable_group_impression", False)))
        cfg_grp_slots = bool(slots_cfg.get("enable_group_memory_slots", ccfg.get("enable_group_memory_slots", True)))

        if raw_group_mode == "slots":
            self.group_memory_mode = "slots"
            self.enable_group_memory_slots = cfg_grp_slots
            self.enable_group_impression = False
            if cfg_grp_imp:
                logger.warning("[MaiReply] group_memory_mode 设为 'slots'，群印象(Group Impression)配置视同关闭以节省API token。")
        elif raw_group_mode == "impression":
            self.group_memory_mode = "impression"
            self.enable_group_memory_slots = False
            self.enable_group_impression = cfg_grp_imp
            if cfg_grp_slots:
                logger.warning("[MaiReply] group_memory_mode 设为 'impression'，群生态槽位(Group Slots)配置视同关闭。")
        elif raw_group_mode == "both":
            self.group_memory_mode = "both"
            self.enable_group_memory_slots = cfg_grp_slots
            self.enable_group_impression = cfg_grp_imp
        elif raw_group_mode == "none":
            self.group_memory_mode = "none"
            self.enable_group_memory_slots = False
            self.enable_group_impression = False
        else:
            if cfg_grp_slots and cfg_grp_imp:
                self.group_memory_mode = "slots"
                self.enable_group_memory_slots = True
                self.enable_group_impression = False
                logger.warning("[MaiReply] 未显式配置 group_memory_mode，默认采用 'slots' 并视同关闭群印象以节省API token。")
            elif cfg_grp_slots:
                self.group_memory_mode = "slots"
                self.enable_group_memory_slots = True
                self.enable_group_impression = False
            elif cfg_grp_imp:
                self.group_memory_mode = "impression"
                self.enable_group_memory_slots = False
                self.enable_group_impression = True
            else:
                self.group_memory_mode = "none"
                self.enable_group_memory_slots = False
                self.enable_group_impression = False

        self.memory_slots = MemorySlotManager(
            db_path=imp_sqlite_path,
            cache_manager=self._imp_cache,
            config=config,
        )
        self.memory_slots.enable = self.enable_memory_slots
        self.memory_slots.enable_global_slots = self.enable_global_memory_slots
        self.memory_slots.enable_group_slots = self.enable_group_memory_slots

    # ------------------------------------------------------------------ 内部读写辅助（带双层 fallback）

    def _ctx_get(self, key: str) -> Optional[str]:
        value = self._ctx_cache.get(key)
        if value:
            return value if isinstance(value, str) else None
        value = self._ctx_sqlite.get(key)
        if value:
            self._ctx_cache.set(key, value, ttl=self.session_ttl)
        return value

    def _ctx_set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        self._ctx_cache.set(key, value, ttl=ttl or self.session_ttl)
        self._ctx_sqlite.set(key, value)

    def _ctx_delete(self, key: str) -> None:
        self._ctx_cache.delete(key)
        self._ctx_sqlite.delete(key)

    def _ctx_keys(self, pattern: str) -> List[str]:
        keys = set()
        try:
            keys.update(key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in self._ctx_cache.get_keys(pattern))
        except Exception:
            pass
        keys.update(self._ctx_sqlite.keys_like(pattern))
        return sorted(keys)

    def _ctx_exists(self, key: str) -> bool:
        if self._ctx_cache.exists(key):
            return True
        return self._ctx_sqlite.get(key) is not None

    def _imp_get(self, key: str) -> Optional[str]:
        value = self._imp_cache.get(key)
        if value:
            return value if isinstance(value, str) else None
        value = self._imp_sqlite.get(key)
        if value:
            self._imp_cache.set(key, value, ttl=self.impression_ttl)
        return value

    def _imp_set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        self._imp_cache.set(key, value, ttl=ttl or self.impression_ttl)
        self._imp_sqlite.set(key, value)

    def _imp_delete(self, key: str) -> None:
        self._imp_cache.delete(key)
        self._imp_sqlite.delete(key)

    def _imp_keys(self, pattern: str) -> List[str]:
        keys = set()
        try:
            keys.update(key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in self._imp_cache.get_keys(pattern))
        except Exception:
            pass
        keys.update(self._imp_sqlite.keys_like(pattern))
        return sorted(keys)

    # ------------------------------------------------------------------ Bot 发送消息 ID 追踪

    def record_bot_message(self, msg_id: str) -> None:
        if not msg_id:
            return
        self._ctx_cache.set(f"bot_msg:{msg_id}", "1", ttl=86400)

    def is_bot_message(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        return bool(self._ctx_cache.exists(f"bot_msg:{msg_id}"))

    # ------------------------------------------------------------------ Keys

    @staticmethod
    def _private_key(user_id: int) -> str:
        return f"ctx:private:{user_id}"

    @staticmethod
    def _group_key(group_id: int, user_id: int) -> str:
        return f"ctx:group:{group_id}:{user_id}"

    @staticmethod
    def _group_window_key(group_id: int) -> str:
        return f"ctx:gwin:{group_id}"

    @staticmethod
    def _impression_key(user_id: int) -> str:
        return f"imp:{user_id}"

    @staticmethod
    def _group_impression_key(group_id: int) -> str:
        return f"imp:group:{group_id}"

    @staticmethod
    def _group_recent_speakers_key(group_id: int) -> str:
        """追踪群内最近发言的 user_id 列表（有序，新的在后）"""
        return f"ctx:speakers:{group_id}"

    @staticmethod
    def _lock_key(session_key: str) -> str:
        return f"lock:{session_key}"

    # ------------------------------------------------------------------ 历史读写

    def _load_history(self, key: str) -> List[Dict]:
        raw = self._ctx_get(key)
        if not raw:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self, key: str, history: List[Dict]) -> None:
        trimmed = history[-(self.max_turns * 2):]
        self._ctx_set(key, json.dumps(trimmed, ensure_ascii=False))

    def get_session_history(self, group_id: Optional[int], user_id: int) -> List[Dict]:
        key = self._group_key(group_id, user_id) if group_id else self._private_key(user_id)
        return self._load_history(key)

    def append_to_session(
        self,
        group_id: Optional[int],
        user_id: int,
        user_message: str,
        assistant_message: str,
    ) -> None:
        key = self._group_key(group_id, user_id) if group_id else self._private_key(user_id)
        history = self._load_history(key)
        now = int(time.time())
        history.append({"role": "user", "content": user_message, "ts": now, "hour": time.localtime(now).tm_hour})
        history.append({"role": "assistant", "content": assistant_message, "ts": int(time.time())})
        self._save_history(key, history)

    def clear_session(self, group_id: Optional[int], user_id: int) -> None:
        key = self._group_key(group_id, user_id) if group_id else self._private_key(user_id)
        self._ctx_delete(key)

    def clear_user_all_sessions(self, user_id: int) -> int:
        patterns = [
            self._private_key(user_id),
            f"ctx:group:*:{user_id}",
        ]
        keys = set()
        for pattern in patterns:
            keys.update(self._ctx_keys(pattern))

        count = 0
        for key in keys:
            self._ctx_delete(key)
            count += 1
        return count

    def clear_all_sessions(self, group_id: Optional[int] = None) -> int:
        if group_id is not None:
            patterns = [f"ctx:group:{group_id}:*"]
        else:
            patterns = ["ctx:private:*", "ctx:group:*"]

        keys = set()
        for pattern in patterns:
            keys.update(self._ctx_keys(pattern))

        count = 0
        for key in keys:
            if key.startswith("lock:"):
                continue
            self._ctx_delete(key)
            count += 1
        return count

    def clear_all_group_windows(self, group_id: Optional[int] = None) -> int:
        patterns = [self._group_window_key(group_id), self._group_recent_speakers_key(group_id)] if group_id is not None else ["ctx:gwin:*", "ctx:speakers:*"]
        keys = set()
        for pattern in patterns:
            keys.update(self._ctx_keys(pattern))

        count = 0
        for key in keys:
            self._ctx_delete(key)
            count += 1
        return count

    # ------------------------------------------------------------------ 群聊窗口 + 发言者追踪

    def push_group_window(self, group_id: int, sender_name: str, text: str, user_id: Optional[int] = None) -> None:
        key = self._group_window_key(group_id)
        window: List[Dict] = self._load_group_window(group_id)
        entry = {"sender": sender_name, "text": text, "ts": int(time.time())}
        if user_id is not None:
            entry["user_id"] = user_id
        window.append(entry)
        window = window[-self.group_window:]
        self._ctx_set(key, json.dumps(window, ensure_ascii=False))

        # 同步更新最近发言者列表（如果有 user_id）
        if user_id is not None:
            self._update_recent_speakers(group_id, user_id, sender_name)

    def _update_recent_speakers(self, group_id: int, user_id: int, sender_name: str) -> None:
        """维护最近发言者的有序列表（去重，新的置末尾）"""
        key = self._group_recent_speakers_key(group_id)
        raw = self._ctx_get(key)
        try:
            speakers: List[Dict] = json.loads(raw) if raw else []
        except Exception:
            speakers = []

        # 去重：先移除旧记录
        speakers = [s for s in speakers if s.get("user_id") != user_id]
        speakers.append({"user_id": user_id, "name": sender_name, "ts": int(time.time())})
        # 只保留最近 20 个，节省空间
        speakers = speakers[-20:]
        self._ctx_set(key, json.dumps(speakers, ensure_ascii=False))

    def get_recent_speakers(
        self, group_id: int, limit: Optional[int] = None, exclude_user_id: Optional[int] = None
    ) -> List[Dict]:
        """
        获取群内最近发言的成员列表（从新到旧）。
        每项结构：{"user_id": int, "name": str, "ts": int}
        """
        key = self._group_recent_speakers_key(group_id)
        raw = self._ctx_get(key)
        try:
            speakers: List[Dict] = json.loads(raw) if raw else []
        except Exception:
            speakers = []
        # 最新的在末尾，反转后先过滤掉 exclude_user_id，再截取 limit 个
        speakers = list(reversed(speakers))
        if exclude_user_id is not None:
            speakers = [s for s in speakers if s.get("user_id") != exclude_user_id]
        if limit is not None:
            speakers = speakers[:limit]
        return speakers

    def _load_group_window(self, group_id: int) -> List[Dict]:
        key = self._group_window_key(group_id)
        raw = self._ctx_get(key)
        if not raw:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def build_group_context_snippet(self, group_id: int, bot_name: str, max_lines: Optional[int] = None) -> str:
        window = self._load_group_window(group_id)
        if not window:
            return ""
        if max_lines is not None and max_lines > 0:
            window = window[-max_lines:]
        lines = []
        for item in window:
            sender = item.get("sender", "?")
            text   = item.get("text", "")
            if sender == bot_name:
                lines.append(f"你说：{text}")
                continue
            # Include the stable account identifier when available.  Older
            # persisted entries may not have user_id, so keep their nickname
            # rendering unchanged.
            user_id = item.get("user_id")
            sender_label = f"{sender}（用户ID: {user_id}）" if user_id is not None else sender
            lines.append(f"{sender_label}：{text}")
        return "【群里最近的聊天记录】\n" + "\n".join(lines)

    # ------------------------------------------------------------------ 用户印象

    def get_impression(self, user_id: int) -> str:
        if not self.enable_impression:
            return ""
        raw = self._imp_get(self._impression_key(user_id))
        return raw if isinstance(raw, str) else ""

    def update_impression(self, user_id: int, summary: str) -> None:
        if not self.enable_impression:
            return
        self._imp_set(self._impression_key(user_id), summary)

    def clear_impression(self, user_id: int, clear_slots: bool = False) -> None:
        """清除对某个用户的印象记忆（Redis + SQLite 双层同步删除）"""
        self._imp_delete(self._impression_key(user_id))
        if clear_slots and self.enable_memory_slots:
            self.memory_slots.clear_all_user_slots(user_id)

    def clear_user_memory_slots(self, user_id: int) -> int:
        """专门清空某个用户的结构化固定记忆槽位"""
        if self.enable_memory_slots:
            return self.memory_slots.clear_all_user_slots(user_id)
        return 0

    def get_user_memory(self, user_id: int) -> str:
        """获取用户的结构化固定记忆槽位文本（用于 prompt 注入）"""
        if not self.enable_memory_slots:
            return ""
        return self.memory_slots.format_user_slots_for_prompt(user_id)

    def clear_all_user_impressions(self) -> int:
        keys = self._imp_keys("imp:*")
        count = 0
        for key in keys:
            if key.startswith("imp:group:"):
                continue
            self._imp_delete(key)
            count += 1
        return count

    # ------------------------------------------------------------------ 群聊印象（新增）

    def is_group_memory_enabled(self, group_id: int) -> bool:
        """
        判断指定群聊是否允许启用群聊记忆体系（通用控制群生态槽位与群整体印象）：
        1. 若当前生效群记忆模式为 'none'，直接禁用；
        2. 若 group_memory_whitelist_enabled 为 True（白名单模式）：
           - 若填写了 group_memory_whitelist，仅在该列表中的群生效；
           - 若 group_memory_whitelist 为 []（未填写），自动使用 trigger_llm 配置的 whitelist；
        3. 若 group_memory_whitelist_enabled 为 False（全局模式）：
           - 对所有群生效。
        """
        if self.get_effective_group_memory_mode() == 'none':
            return False

        if not group_id:
            return False

        try:
            gid = int(group_id)
        except (ValueError, TypeError):
            return False

        # 白名单模式
        if self.group_memory_whitelist_enabled:
            if self.group_memory_whitelist:
                return gid in self.group_memory_whitelist

            # 若未填写，自动使用 trigger_llm 配置的 whitelist
            trig_cfg = self.cfg.core_reply.config.get('trigger_llm', {})
            trig_whitelist = [
                int(x) for x in trig_cfg.get('whitelist', []) if str(x).isdigit()
            ]
            return gid in trig_whitelist

        # 全局模式（group_memory_whitelist_enabled=False，对所有群生效）
        return True

    def is_group_impression_enabled(self, group_id: int) -> bool:
        """判断指定群是否启用了群印象（仅在 group_memory_mode 包含 impression 且群白名单通过时为 True）"""
        if not self.enable_group_impression:
            return False
        return self.is_group_memory_enabled(group_id)

    def get_group_impression(self, group_id: int) -> str:
        """获取对某个群的整体氛围/主观印象（仅在启用群印象时有效）"""
        if not self.enable_group_impression:
            return ''
        if not self.is_group_memory_enabled(group_id):
            return ''
        raw = self._imp_get(self._group_impression_key(group_id))
        return raw if isinstance(raw, str) else ''

    def update_group_impression(self, group_id: int, summary: str) -> None:
        """更新群聊气氛/话题印象"""
        if not self.is_group_impression_enabled(group_id):
            return
        self._imp_set(
            self._group_impression_key(group_id),
            summary,
            ttl=self.group_impression_ttl,
        )

    def clear_group_impression(self, group_id: int) -> None:
        """清除某个群的气氛/话题印象（Redis + SQLite 双层同步删除）"""
        self._imp_delete(self._group_impression_key(group_id))

    def clear_all_group_impressions(self) -> int:
        keys = self._imp_keys("imp:group:*")
        count = 0
        for key in keys:
            self._imp_delete(key)
            count += 1
        return count


    # ------------------------------------------------------------------ 记忆模式解析与群槽位支持

    def get_effective_user_memory_mode(self) -> str:
        """
        解析当前生效的用户记忆模式：
        - slots: 仅启用结构化槽位事实，主观印象彻底关闭；
        - impression: 仅启用主观印象，槽位事实彻底关闭；
        - both: 两者兼备；
        - none: 彻底关闭记忆。
        """
        return getattr(self, "user_memory_mode", "slots")

    def get_effective_group_memory_mode(self) -> str:
        """
        解析当前生效的群聊记忆模式：
        - slots: 仅启用群生态10槽位，群整体印象彻底关闭；
        - impression: 仅启用群整体印象，群生态槽位彻底关闭；
        - both: 两者兼备；
        - none: 彻底关闭群记忆。
        """
        return getattr(self, "group_memory_mode", "slots")

    def get_group_memory_slots(self, group_id: int) -> str:
        """获取群专属结构化固定记忆槽位文本（用于 prompt 注入）"""
        if not self.is_group_memory_enabled(group_id):
            return ''
        if not getattr(self, "enable_group_memory_slots", False) or not hasattr(self, "memory_slots"):
            return ""
        return self.memory_slots.format_group_slots_for_prompt(group_id)

    def clear_group_memory_slots(self, group_id: Optional[int] = None) -> int:
        """清空群专属结构化固定记忆槽位"""
        if hasattr(self, "memory_slots"):
            return self.memory_slots.clear_all_group_slots(group_id)
        return 0

    def get_recent_speaker_memories(
        self, group_id: int, exclude_user_id: Optional[int] = None
    ) -> List[Dict]:
        """
        批量读取群内最近 group_reply_impression_count 位发言者的记忆。
        支持根据用户记忆模式动态返回：
        - impression 模式: 仅返回主观印象
        - slots 模式: 仅返回结构化槽位事实
        - both 模式: 同时返回印象与槽位事实
        返回: [{"name": str, "user_id": int, "impression": str, "slots": str}, ...]
        """
        speakers = self.get_recent_speakers(
            group_id, limit=self.group_reply_speaker_memory_count, exclude_user_id=exclude_user_id
        )
        mode = self.get_effective_user_memory_mode()
        result = []
        for s in speakers:
            uid = s.get("user_id")
            name = s.get("name", str(uid))
            if uid is None:
                continue

            entry = {"name": name, "user_id": uid, "impression": "", "slots": ""}
            has_data = False

            if mode in ("impression", "both"):
                imp = self.get_impression(uid)
                if imp:
                    entry["impression"] = imp
                    has_data = True

            if mode in ("slots", "both") and self.enable_memory_slots and hasattr(self, "memory_slots"):
                slots_text = self.memory_slots.format_user_slots_summary(uid)
                if slots_text:
                    entry["slots"] = slots_text
                    has_data = True

            if has_data:
                result.append(entry)
        return result

    def get_group_user_session_context(
        self, group_id: int, user_id: int, max_turns: Optional[int] = None, *args, **kwargs
    ) -> List[Dict]:
        """
        获取群聊被 @ 时针对当前用户的上下文历史：
        群聊不需要让用户单独的私聊历史占据空间，仅提取该用户在群内的最近少量轮数（默认2-3轮），
        彻底去除私聊上下文引入，将宝贵的上下文窗口留给群公屏消息与群记忆。
        """
        turns = max_turns if max_turns is not None else self.group_user_context_turns
        max_msgs = max(1, turns) * 2
        group_history = self.get_session_history(group_id, user_id)
        return group_history[-max_msgs:]

    def get_recent_speaker_impressions(
        self, group_id: int, exclude_user_id: Optional[int] = None
    ) -> List[Dict]:
        """
        批量读取群内最近 group_reply_impression_count 位发言者的用户印象。
        返回：[{"name": str, "user_id": int, "impression": str}, ...]
        只返回实际有印象记录的成员（跳过空印象）。
        """
        speakers = self.get_recent_speakers(
            group_id, limit=self.group_reply_speaker_memory_count, exclude_user_id=exclude_user_id
        )
        result = []
        for s in speakers:
            uid = s.get("user_id")
            name = s.get("name", str(uid))
            if uid is None:
                continue
            imp = self.get_impression(uid)
            if imp:
                result.append({"name": name, "user_id": uid, "impression": imp})
        return result

    # ------------------------------------------------------------------ 分布式锁

    async def acquire_lock(self, session_key: str, timeout: int = 30) -> bool:
        lock_key = self._lock_key(session_key)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._ctx_cache.exists(lock_key):
                self._ctx_cache.set(lock_key, "1", ttl=timeout)
                return True
            await asyncio.sleep(0.1)
        return False

    def release_lock(self, session_key: str) -> None:
        self._ctx_cache.delete(self._lock_key(session_key))

    def session_key_for(self, group_id: Optional[int], user_id: int) -> str:
        return self._group_key(group_id, user_id) if group_id else self._private_key(user_id)

    # ------------------------------------------------------------------ 生命周期


    def _global_memory_key(self) -> str:
        return "memory:global"

    def get_global_memory(self) -> str:
        """获取全局独立生活记忆（优先结构化记忆槽位，降级回退旧版字符串）"""
        if not self.enable_global_memory_slots:
            return ""
        formatted = self.memory_slots.format_global_slots_for_prompt()
        if formatted:
            return formatted

        raw = self._imp_get(self._global_memory_key())
        if not raw:
            return ""
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return "\n".join(data)
        except Exception:
            pass
        return str(raw)

    def update_global_memory(self, content: str, max_items: int = 5) -> None:
        """更新全局生活记忆（与 qq_zone 联动，自动推入槽位并兼顾旧版存储）"""
        if not self.enable_global_memory_slots or not content or not content.strip():
            return
        self.memory_slots.add_global_event(content)

        raw = self._imp_get(self._global_memory_key())
        history_items = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    history_items = parsed
                elif isinstance(parsed, str):
                    history_items = [parsed]
            except Exception:
                history_items = [str(raw)]
        clean_item = content.strip()
        if clean_item not in history_items:
            history_items.append(clean_item)
        if len(history_items) > max_items:
            history_items = history_items[-max_items:]
        self._imp_set(self._global_memory_key(), json.dumps(history_items, ensure_ascii=False))

    def clear_global_memory(self) -> None:
        self.memory_slots.clear_all_global_slots()
        self._imp_delete(self._global_memory_key())

    def close(self) -> None:
        if hasattr(self, "memory_slots"):
            self.memory_slots.close()
        self._ctx_sqlite.close()
        self._imp_sqlite.close()
