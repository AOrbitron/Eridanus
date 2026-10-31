# -*- coding: utf-8 -*-
"""Scoped conversation episodes, provider adapters, Mem0 integration and quota-conscious retrieval."""
import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

import httpx
import numpy as np

from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.rag_archive import EpisodeArchive
from run.mai_reply.service.rag_retrieval import EpisodeRetrieval, RAG_PREFIX

logger = get_logger(__name__)


def trim_tokens(text: str, budget: int) -> str:
    """UTF-8 byte length upper-bounds tokens for the supported byte tokenizers."""
    return text.encode("utf-8")[:max(0, budget)].decode("utf-8", errors="ignore")


class RAGMemory(EpisodeArchive, EpisodeRetrieval):
    _instance = None
    _initialized = False

    def __new__(cls, config=None, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(RAGMemory, cls).__new__(cls)
        return cls._instance
    """
    MaiReply 核心长期记忆系统 (Mem0 + RAG 架构)
    - 支持多范围隔离与跨会话贯通 (user:{id}, group:{id}, agent:global, private:{id})
    - 结合 LLM 原子事实抽取 (ADD / UPDATE / DELETE 状态机) 与历史片段归档
    - 兼容本地与远程 OpenAI 格式 Embedding 服务 (如 qwen3-embedding-4b)
    - 数据库自动拓展与热迁移
    """

    def __init__(self, config):
        if self._initialized:
            return
        self.cfg = dict(getattr(config.mai_reply, "rag", None) or {})
        self.enable = bool(self.cfg.get("enable", False))
        self._log_enabled = bool(self.cfg.get("logging", {}).get("enable", True))
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._worker: Optional[threading.Thread] = None
        self._client: Optional[httpx.Client] = None
        self._closed = False
        self._cooldown = 0.0
        self._generation = 0

        self._init_retrieval()
        self._init_archive(config)

        self._embedding_cfg = self.cfg.get("embedding", {})
        e = self._embedding_cfg
        self._provider = str(e.get("provider", "openai")).strip().lower()
        self._cloudflare_cfg = e.get("cloudflare", {})

        # 命名空间隔离：基于模型、维度、端点哈希
        identity = [
            self._provider,
            e.get("base_url"),
            e.get("endpoint", "embeddings"),
            e.get("model"),
            e.get("dimensions"),
        ]
        if self._provider != "openai":
            cf = self._cloudflare_cfg
            identity = [self._provider, cf.get("account_id"), cf.get("model", "@cf/baai/bge-m3")]
        self._namespace = hashlib.sha256(json.dumps(identity).encode()).hexdigest()

        if self.enable:
            try:
                self._db_path = Path(self.cfg.get("db_path", "data/dataBase/mai_rag_memory.db"))
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(
                    str(self._db_path),
                    check_same_thread=False,
                    timeout=30.0,
                    isolation_level=None
                )
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
                
                # 初始化或迁移表结构
                self._init_db_schema()

                self.start()
            except Exception as exc:
                self.enable = False
                logger.error("[MaiReply RAG] 数据库初始化失败 (%s)，已禁用 RAG", type(exc).__name__, exc_info=True)

        group = self.cfg.get("group", {})
        logger.info(
            "[MaiReply RAG] 就绪 | 状态=%s | 模式=%s | 库=%s | 私聊=%s | 群聊=%s | 模型=%s/%s",
            "启用" if self.enable else "禁用",
            self.cfg.get("integration_mode", "replace"),
            self.cfg.get("db_path", "(内存)"),
            "开启" if self.cfg.get("private", {}).get("enable", True) else "关闭",
            ("白名单(%d个)" % len(group.get("whitelist", []))
             if group.get("whitelist_enabled", True) else "全开"),
            self._provider,
            e.get("model", "默认"),
        )

        self._initialized = True

    def _init_db_schema(self):
        """自动迁移表结构，兼容旧版本与 Mem0 扩展字段"""
        with self._lock:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    text TEXT NOT NULL,
                    vector BLOB,
                    created REAL NOT NULL,
                    ended REAL,
                    user_id TEXT,
                    message_id TEXT,
                    namespace TEXT NOT NULL,
                    fact_type TEXT DEFAULT 'episode',
                    category TEXT DEFAULT 'conversation',
                    target_id TEXT,
                    target_name TEXT,
                    updated_at REAL,
                    participants TEXT
                )
            """)
            # 检查已有表的字段并进行自动补全拓展
            cursor = self._db.execute("PRAGMA table_info(memories)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            needed_cols = [
                ("fact_type", "TEXT DEFAULT 'episode'"),
                ("category", "TEXT DEFAULT 'conversation'"),
                ("target_id", "TEXT"),
                ("target_name", "TEXT"),
                ("updated_at", "REAL"),
                ("ended", "REAL"),
                ("user_id", "TEXT"),
                ("message_id", "TEXT"),
                ("participants", "TEXT"),
            ]
            for col_name, col_def in needed_cols:
                if col_name not in existing_cols:
                    try:
                        self._db.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.warning(f"[MaiReply RAG] ALTER TABLE 添加列 {col_name} 警告: {e}")

            self._db.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope_ns ON memories (scope, namespace)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_memories_ns_time ON memories (namespace, COALESCE(ended, created))")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_memories_target ON memories (target_id, fact_type)")

    def _log(self, msg: str, *args):
        if self._log_enabled:
            logger.info(msg, *args)

    def _warn(self, msg: str, *args):
        logger.warning(msg, *args)

    def scope_for(self, group_id: Optional[str], user_id: Any) -> str:
        return f"group:{group_id}" if group_id is not None else f"private:{user_id}"

    @property
    def replaces_legacy(self) -> bool:
        mode = str(self.cfg.get("integration_mode", "replace")).strip().lower()
        return mode == "replace"

    def allowed(self, group_id: Optional[str] = None) -> bool:
        if not self.enable:
            return False
        if group_id is None:
            return bool(self.cfg.get("private", {}).get("enable", True))
        gcfg = self.cfg.get("group", {})
        if not gcfg.get("enable", True):
            return False
        if not gcfg.get("whitelist_enabled", True):
            return True
        wl = [str(x) for x in gcfg.get("whitelist", [])]
        return str(group_id) in wl

    def _run_db(self, fn, *args, **kwargs):
        with self._lock:
            if self._db is None:
                raise RuntimeError("Database connection closed")
            return fn(self._db, *args, **kwargs)

    async def _embed(self, texts: List[str], is_query: bool = False) -> List[np.ndarray]:
        if not texts:
            return []
        cfg = self._embedding_cfg
        if is_query:
            inst = str(cfg.get("query_instruction", "")).strip()
            if inst:
                texts = [f"{inst}: {t}" for t in texts]
        timeout = float(cfg.get("timeout_seconds", 15.0))
        if self._provider == "openai":
            base_url = str(cfg.get("base_url", "http://api.apollodorus.xyz/v1")).rstrip("/")
            endpoint = str(cfg.get("endpoint", "embeddings")).strip("/")
            url = f"{base_url}/{endpoint}"
            model = str(cfg.get("model", "qwen3-embedding-4b")).strip()
            api_key = str(cfg.get("api_key", "")).strip()
            env_name = str(cfg.get("api_key_env", "MAI_RAG_API_KEY")).strip()
            if not api_key and env_name:
                api_key = os.environ.get(env_name, "")

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {"model": model, "input": texts}

            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Embedding API HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
                vecs = []
                for it in items:
                    v = np.array(it.get("embedding", []), dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if norm > 1e-12:
                        v = v / norm
                    vecs.append(v)
                if len(vecs) != len(texts):
                    raise RuntimeError(f"Expected {len(texts)} embeddings, got {len(vecs)}")
                return vecs
        else:
            # Cloudflare Workers AI 保底
            account_id = str(self._cloudflare_cfg.get("account_id", "")).strip()
            model = str(self._cloudflare_cfg.get("model", "@cf/baai/bge-m3")).strip()
            token = str(self._cloudflare_cfg.get("api_token", "")).strip()
            env_name = str(self._cloudflare_cfg.get("api_token_env", "CLOUDFLARE_API_TOKEN")).strip()
            if not token and env_name:
                token = os.environ.get(env_name, "")
            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json={"text": texts})
                if resp.status_code != 200:
                    raise RuntimeError(f"Cloudflare AI HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json().get("result", {}).get("data", [])
                vecs = []
                for row in data:
                    v = np.array(row, dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if norm > 1e-12:
                        v = v / norm
                    vecs.append(v)
                return vecs

    def _index_worker(self):
        """后台守护线程：消费未向量化的记忆并批量调用 Embedding API"""
        batch_size = max(1, int(self.cfg.get("index", {}).get("batch_size", 16)))
        retry_seconds = max(5.0, float(self.cfg.get("index", {}).get("retry_seconds", 60.0)))
        while not self._closed:
            try:
                if self._cooldown > time.monotonic():
                    time.sleep(1.0)
                    continue

                pending = self._run_db(self._pending, batch_size)
                if not pending:
                    time.sleep(2.0)
                    continue

                # 每次最多处理 batch_size 条，避免阻塞与长时间并发；短轮询等待 1.0 秒
                if len(pending) < batch_size:
                    time.sleep(1.0)
                    pending = self._run_db(self._pending, batch_size)
                    if not pending:
                        continue

                # 1. 整理待处理条目
                row_items = []
                for r in pending:
                    row_id = r[0]
                    raw_text = r[1]
                    ft = r[3] if len(r) > 3 else "episode"
                    t = self._embedding_text(raw_text, ft)
                    row_items.append((row_id, raw_text, ft, t))

                # 2. 优先检查本地数据库中是否已存在相同文本的向量，避免重复调用远程 API
                text_to_vec: Dict[str, np.ndarray] = {}
                def check_existing(db):
                    found = {}
                    for _, raw_text, _, t in row_items:
                        if t in text_to_vec or t in found:
                            continue
                        row = db.execute(
                            "SELECT vector FROM memories WHERE (text=? OR text=?) AND namespace=? AND vector IS NOT NULL LIMIT 1",
                            (t, raw_text, self._namespace)
                        ).fetchone()
                        if row and row[0]:
                            v = np.frombuffer(row[0], dtype=np.float32)
                            found[t] = v
                    return found

                existing_map = self._run_db(check_existing)
                text_to_vec.update(existing_map)

                # 3. 仅对本地未曾计算过向量的唯一文本发起远程 Embedding 请求
                unembedded_unique = []
                for _, _, _, t in row_items:
                    if t not in text_to_vec and t not in unembedded_unique:
                        unembedded_unique.append(t)

                if unembedded_unique:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        new_vecs = loop.run_until_complete(self._embed(unembedded_unique, is_query=False))
                    finally:
                        loop.close()
                    for t, v in zip(unembedded_unique, new_vecs):
                        text_to_vec[t] = v

                # 4. 批量写回数据库更新向量
                updates = []
                for row_id, _, _, t in row_items:
                    vec = text_to_vec.get(t)
                    if vec is not None:
                        updates.append((vec.tobytes(), self._namespace, row_id))

                if updates:
                    def save(db):
                        return db.executemany(
                            "UPDATE memories SET vector=?, namespace=? WHERE id=?",
                            updates
                        ).rowcount
                    saved = self._run_db(save)
                    self._log("[MaiReply RAG] 成功向量化索引 %d 条记忆 (API调用=%d, 复用=%d)", saved, len(unembedded_unique), len(updates) - len(unembedded_unique))
            except Exception as exc:
                self._cooldown = time.monotonic() + retry_seconds
                self._warn("[MaiReply RAG] 向量化索引发生异常 (%s)，冷却等待 %.0fs: %s", type(exc).__name__, retry_seconds, exc)
                time.sleep(2.0)

    def start(self):
        if self._worker is None and self.enable:
            self._worker = threading.Thread(target=self._index_worker, name="rag_index_worker", daemon=True)
            self._worker.start()

    def close(self):
        self._closed = True
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None

    async def aclose(self):
        self.close()

    async def wait_indexing(self, timeout: float = 30.0) -> bool:
        """等待所有待索引的记忆完成向量化入库"""
        start_t = time.time()
        while time.time() - start_t < timeout:
            pending = self._run_db(lambda db: db.execute(
                "SELECT COUNT(*) FROM memories WHERE vector IS NULL AND namespace=?",
                (self._namespace,)
            ).fetchone()[0])
            if pending == 0:
                return True
            await asyncio.sleep(0.5)
        return False

    async def recall(self, group_id: Optional[str], user_id: Any, query: str, recent_context=None, now=None) -> str:
        if not self.allowed(group_id):
            return ""
        return await self._recall(group_id, user_id, query, recent_context=recent_context, now=now)
