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
        ccfg = config.mai_reply.config.get("context", {})
        self.max_turns: int = ccfg.get("max_turns", 20)
        self.group_window: int = ccfg.get("group_context_window", 15)
        self.session_ttl: int = ccfg.get("session_ttl", 7200)
        self.enable_impression: bool = ccfg.get("enable_impression", True)
        self.impression_ttl: int = ccfg.get("impression_ttl", 604800)

        # 群聊印象配置

        self.enable_group_impression: bool = ccfg.get("enable_impression", True)
        self.group_impression_ttl: int = ccfg.get("impression_ttl", 604800)
        # 构建回复时，最多读取最近 N 位发言者的 impression
        self.group_reply_impression_count: int = ccfg.get("group_reply_impression_count", 3)

        db_cfg = config.mai_reply.config.get("redis", {})
        ctx_db = db_cfg.get("context_db", 5)
        imp_db = db_cfg.get("impression_db", 6)

        self._ctx_cache = create_custom_cache_manager(db_number=ctx_db, cache_ttl=self.session_ttl)
        self._imp_cache = create_custom_cache_manager(db_number=imp_db, cache_ttl=self.impression_ttl)

        # SQLite 持久层
        sqlite_cfg = config.mai_reply.config.get("sqlite", {})
        ctx_sqlite_path  = sqlite_cfg.get("context_db_path",    "data/context_store.db")
        imp_sqlite_path  = sqlite_cfg.get("impression_db_path", "data/impression_store.db")

        self._ctx_sqlite = SQLitePersistence(ctx_sqlite_path)
        self._imp_sqlite = SQLitePersistence(imp_sqlite_path)

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

    def get_recent_speakers(self, group_id: int, limit: Optional[int] = None) -> List[Dict]:
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
        # 最新的在末尾，反转后取 limit 个
        speakers = list(reversed(speakers))
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

    def build_group_context_snippet(self, group_id: int, bot_name: str) -> str:
        window = self._load_group_window(group_id)
        if not window:
            return ""
        lines = []
        for item in window:
            sender = item.get("sender", "?")
            text   = item.get("text", "")
            lines.append(f"你说：{text}" if sender == bot_name else f"{sender}：{text}")
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

    def clear_impression(self, user_id: int) -> None:
        """清除对某个用户的印象记忆（Redis + SQLite 双层同步删除）"""
        self._imp_delete(self._impression_key(user_id))

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

    def get_group_impression(self, group_id: int) -> str:
        """获取对某个群的整体气氛/话题印象"""
        if not self.enable_group_impression:
            return ""
        raw = self._imp_get(self._group_impression_key(group_id))
        return raw if isinstance(raw, str) else ""

    def update_group_impression(self, group_id: int, summary: str) -> None:
        """更新群聊气氛/话题印象"""
        if not self.enable_group_impression:
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

    def get_recent_speaker_impressions(self, group_id: int) -> List[Dict]:
        """
        批量读取群内最近 group_reply_impression_count 位发言者的用户印象。
        返回：[{"name": str, "user_id": int, "impression": str}, ...]
        只返回实际有印象记录的成员（跳过空印象）。
        """
        speakers = self.get_recent_speakers(group_id, limit=self.group_reply_impression_count)
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

    def close(self) -> None:
        self._ctx_sqlite.close()
        self._imp_sqlite.close()
