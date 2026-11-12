# -*- coding: utf-8 -*-
"""Scoped conversation episodes, provider adapters, Mem0 integration and quota-conscious retrieval."""
import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Union

import httpx
import numpy as np

from framework_common.utils.system_logger import get_logger
from run.core_reply.service.rag_archive import EpisodeArchive
from run.core_reply.service.rag_retrieval import EpisodeRetrieval, RAG_PREFIX

logger = get_logger(__name__)


def trim_tokens(text: str, budget: int) -> str:
    """UTF-8 byte length upper-bounds tokens for the supported byte tokenizers."""
    return text.encode("utf-8")[:max(0, budget)].decode("utf-8", errors="ignore")


def _get_process_in_flight():
    import sys
    ids = getattr(sys, "_mai_rag_in_flight_ids", None)
    lock = getattr(sys, "_mai_rag_in_flight_lock", None)
    if ids is None or lock is None:
        ids = set()
        lock = threading.Lock()
        sys._mai_rag_in_flight_ids = ids
        sys._mai_rag_in_flight_lock = lock
    return ids, lock


class RAGMemory(EpisodeArchive, EpisodeRetrieval):
    _instance = None
    _initialized = False

    def __new__(cls, config=None, *args, **kwargs):
        import sys
        existing = getattr(sys, "_mai_rag_memory_singleton", None)
        if existing is not None:
            return existing
        if cls._instance is None:
            cls._instance = super(RAGMemory, cls).__new__(cls)
            sys._mai_rag_memory_singleton = cls._instance
        return cls._instance
    """
    MaiReply 核心长期记忆系统 (Mem0 + RAG 架构)
    - 支持多范围隔离与跨会话贯通 (user:{id}, group:{id}, agent:global, private:{id})
    - 结合 LLM 原子事实抽取 (ADD / UPDATE / DELETE 状态机) 与历史片段归档
    - 兼容本地与远程 OpenAI 格式 Embedding 服务 (如 qwen3-embedding-4b)
    - 数据库自动拓展与热迁移
    """

    def __init__(self, config):
        self.config = config
        if getattr(self, "_initialized", False):
            return
        self.cfg = dict(getattr(config.core_reply, "rag", None) or {})
        self.enable = bool(self.cfg.get("enable", False))
        self._log_enabled = bool(self.cfg.get("logging", {}).get("enable", True))
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._worker: Optional[threading.Thread] = None
        self._client: Optional[httpx.Client] = None
        self._closed = False
        self.knowledge = None
        self._cooldown = 0.0
        self._embedding_http_state = threading.local()
        self._embedding_batch_limit = 0
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

                pending_count = self._db.execute(
                    "SELECT COUNT(*) FROM memories WHERE vector IS NULL AND namespace=?",
                    (self._namespace,)
                ).fetchone()[0]
                self._log(
                    "[MaiReply RAG] 索引队列就绪 provider=%s namespace=%s 待索引=%d "
                    "（已有向量不重算；队列清空后仅本地轮询）",
                    self._provider, self._namespace[:12], pending_count)
                self.start()
            except Exception as exc:
                self.enable = False
                logger.error("[MaiReply RAG] 数据库初始化失败 (%s)，已禁用 RAG", type(exc).__name__, exc_info=True)

        knowledge_cfg = self.cfg.get("knowledge_base")
        if self.enable and isinstance(knowledge_cfg, Mapping) and knowledge_cfg.get("enable") is True:
            try:
                from run.core_reply.service.rag_knowledge import RAGKnowledge

                knowledge = RAGKnowledge(self, knowledge_cfg)
                knowledge.init_schema()
                self.knowledge = knowledge
                knowledge.start()
            except Exception as exc:
                self.knowledge = None
                self._warn("[MaiReply 知识库] 初始化失败，已禁用知识库 (%s): %s", type(exc).__name__, exc)

        group = self.cfg.get("group", {})
        wl_enabled = bool(group.get("whitelist_enabled", False))
        wl = group.get("whitelist", [])
        if wl_enabled:
            wl_desc = ("白名单(%d个)" % len(wl)) if wl else "白名单(回退trigger_llm)"
        else:
            wl_desc = "全开"

        logger.info(
            "[MaiReply RAG] 就绪 | 状态=%s | 模式=%s | 库=%s | 私聊=%s | 群聊=%s | 模型=%s/%s",
            "启用" if self.enable else "禁用",
            self.cfg.get("integration_mode", "replace"),
            self.cfg.get("db_path", "(内存)"),
            "开启" if self.cfg.get("private", {}).get("enable", True) else "关闭",
            wl_desc,
            self._provider,
            (self._cloudflare_cfg if self._provider == "cloudflare" else e).get("model", "默认"),
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

    def record_bot_experience(self, content: str, category: str = "qzone_daily") -> bool:
        """Store a Bot-owned experience independently of user/group conversation archives."""
        text = " ".join((content or "").split())[:160]
        if not self.enable or not text or self._db is None:
            return False
        now = time.time()

        def save(db):
            self._apply_mem0_fact(db, {
                "action": "ADD", "target_type": "bot", "target_id": "global",
                "target_name": "Bot", "category": category, "content": text,
            }, "agent:global", now)
            if category == "qzone_daily":
                db.execute("""
                    UPDATE memories SET ended=? WHERE id IN (
                        SELECT id FROM memories
                        WHERE scope='agent:global' AND namespace=? AND fact_type='fact'
                          AND category='qzone_daily' AND target_id='global' AND ended IS NULL
                        ORDER BY updated_at DESC, id DESC LIMIT -1 OFFSET 4
                    )
                """, (now, self._namespace))

        self._run_db(save)
        return True

    @property
    def replaces_legacy(self) -> bool:
        mode = str(self.cfg.get("integration_mode", "replace")).strip().lower()
        return mode == "replace"

    def allowed(self, group_id: Optional[Union[str, int]] = None) -> bool:
        if not self.enable:
            return False
        if group_id is None:
            return bool(self.cfg.get("private", {}).get("enable", True))
        gcfg = self.cfg.get("group", {})
        if not gcfg.get("enable", True):
            return False
        if not gcfg.get("whitelist_enabled", False):
            return True
        wl = [str(x) for x in gcfg.get("whitelist", []) if str(x).strip()]
        if wl:
            return str(group_id) in wl

        # 当开启白名单模式，且whitelist为空列表时，自动使用run/core_reply/config.yaml中trigger_llm的whitelist
        trig_cfg = {}
        cfg_obj = getattr(self, "config", None)
        if cfg_obj is not None:
            core_reply_obj = getattr(cfg_obj, "core_reply", None)
            if core_reply_obj is not None and hasattr(core_reply_obj, "config"):
                trig_cfg = core_reply_obj.config.get("trigger_llm", {}) or {}
            elif isinstance(cfg_obj, dict):
                trig_cfg = cfg_obj.get("trigger_llm", {}) or cfg_obj.get("config", {}).get("trigger_llm", {}) or {}
        trig_wl = [str(x) for x in trig_cfg.get("whitelist", []) if str(x).strip()]
        return str(group_id) in trig_wl

    def _run_db(self, fn, *args, **kwargs):
        with self._lock:
            if self._db is None:
                raise RuntimeError("Database connection closed")
            return fn(self._db, *args, **kwargs)

    async def _embed(self, texts: List[str], is_query: bool = False) -> List[np.ndarray]:
        if not texts:
            return []
        provider = self._provider
        if provider not in ('openai', 'cloudflare'):
            raise ValueError(f'Unsupported embedding provider: {provider}')
        cfg = self._cloudflare_cfg if provider == 'cloudflare' else self._embedding_cfg
        model = str(cfg.get('model') or ('@cf/baai/bge-m3' if provider == 'cloudflare' else 'qwen3-embedding-4b')).strip()
        instruction = str(cfg.get('query_instruction') or '').strip()
        if is_query and instruction:
            texts = [f'{instruction}: {text}' for text in texts]
        timeout = float(cfg.get('timeout_seconds', 30.0 if provider == 'cloudflare' else 15.0))
        headers = {'Content-Type': 'application/json'}

        # Only the wire format differs. Indexing, recall and prompt injection
        # always use this same adapter and the same normalized vector result.
        if provider == 'cloudflare':
            account = str(cfg.get('account_id') or '').strip()
            key = str(cfg.get('api_token') or '').strip()
            if not account or not key:
                raise ValueError('Cloudflare embedding requires account_id and api_token in rag.yaml')
            url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}'
            payload = {'text': texts}
        else:
            key = str(cfg.get('api_key') or '').strip()
            base = str(cfg.get('base_url', 'http://api.apollodorus.xyz/v1')).rstrip('/')
            endpoint = str(cfg.get('endpoint', 'embeddings')).strip('/')
            url = f'{base}/{endpoint}'
            payload = {'model': model, 'input': texts}
        if key:
            headers['Authorization'] = f'Bearer {key}'

        # One request path for both providers. A context-length rejection is
        # deterministic: split the batch now instead of retrying it unchanged.
        request_count = 0
        state = getattr(self, '_embedding_http_state', None)
        if state is not None:
            state.count = 0

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async def request_batch(batch, allow_fallback=True):
                nonlocal request_count
                limit = getattr(self, '_embedding_batch_limit', 0)
                if limit and len(batch) > limit:
                    result = []
                    for offset in range(0, len(batch), limit):
                        result.extend(await request_batch(batch[offset:offset + limit], allow_fallback))
                    return result

                wire = dict(payload)
                wire['text' if provider == 'cloudflare' else 'input'] = batch
                request_count += 1
                if state is not None:
                    state.count = request_count
                response = await client.post(url, headers=headers, json=wire)
                if response.status_code != 200:
                    error = response.text.lower()
                    context_error = response.status_code in (400, 413) and any(
                        marker in error for marker in (
                            'max context reached', 'maximum context length',
                            'context length exceeded', 'too many tokens',
                            'maximum number of tokens', 'input is too long'))
                    if context_error and len(batch) > 1 and allow_fallback:
                        middle = len(batch) // 2
                        learned = max(1, middle)
                        old_limit = getattr(self, '_embedding_batch_limit', 0)
                        self._embedding_batch_limit = min(old_limit, learned) if old_limit else learned
                        self._warn(
                            "[MaiReply RAG] Embedding输入超限，拆批 %d -> %d+%d；"
                            "原文不截断，后续请求最多 %d 条",
                            len(batch), middle, len(batch) - middle,
                            self._embedding_batch_limit)
                        return await request_batch(batch[:middle], False) + await request_batch(batch[middle:], False)
                    detail = (' (single text exceeds model context; not truncated)' if len(batch) == 1
                              else ' (context fallback exhausted; no further immediate retry)') if context_error else ''
                    raise RuntimeError(
                        f'Embedding API HTTP {response.status_code}{detail}: {response.text[:200]}')
                body = response.json()

                if provider == 'cloudflare':
                    if body.get('success') is False:
                        raise RuntimeError('Embedding API returned success=false')
                    values = body.get('result', {}).get('data', [])
                else:
                    items = sorted(body.get('data', []), key=lambda item: item.get('index', 0))
                    values = [item.get('embedding', []) for item in items]

                if len(values) != len(batch):
                    raise RuntimeError(f'Expected {len(batch)} embeddings, got {len(values)}')
                vectors = []
                for value in values:
                    vector = np.asarray(value, dtype=np.float32)
                    norm = np.linalg.norm(vector)
                    if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 1e-12:
                        raise RuntimeError('Embedding API returned an invalid vector')
                    if vectors and vector.size != vectors[0].size:
                        raise RuntimeError('Embedding API returned inconsistent vector dimensions')
                    vectors.append(vector / norm)
                return vectors

            vectors = await request_batch(texts)
        if vectors and any(v.size != vectors[0].size for v in vectors):
            raise RuntimeError('Embedding API returned inconsistent vector dimensions across batches')
        return vectors


    def _index_worker(self):
        """后台守护线程：消费未向量化的记忆并批量调用 Embedding API"""
        batch_size = max(1, int(self.cfg.get("index", {}).get("batch_size", 16)))
        retry_seconds = max(5.0, float(self.cfg.get("index", {}).get("retry_seconds", 60.0)))
        in_flight_ids, in_flight_lock = _get_process_in_flight()
        while not self._closed:
            claimed_ids = set()
            try:
                if self._cooldown > time.monotonic():
                    time.sleep(1.0)
                    continue

                with in_flight_lock:
                    exclude = set(in_flight_ids)

                pending = self._run_db(lambda db: self._pending(db, batch_size, exclude_ids=exclude))
                if not pending:
                    time.sleep(2.0)
                    continue

                # 每次最多处理 batch_size 条，避免阻塞与长时间并发；短轮询等待 1.0 秒以聚拢并发写入
                if len(pending) < batch_size:
                    time.sleep(1.0)
                    with in_flight_lock:
                        exclude = set(in_flight_ids)
                    pending = self._run_db(lambda db: self._pending(db, batch_size, exclude_ids=exclude))
                    if not pending:
                        continue

                # 立即认领本次待处理的所有 row_id，防止其他并发工作线程或重载实例重复抓取
                with in_flight_lock:
                    claimed = [r for r in pending if r[0] not in in_flight_ids]
                    if not claimed:
                        continue
                    for r in claimed:
                        in_flight_ids.add(r[0])
                        claimed_ids.add(r[0])
                    pending = claimed

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
                    remaining = self._run_db(lambda db: db.execute(
                        "SELECT COUNT(*) FROM memories WHERE vector IS NULL AND namespace=?",
                        (self._namespace,)
                    ).fetchone()[0])
                    self._log(
                        "[MaiReply RAG] 索引进度 namespace=%s 本批ID=%s 写入=%d "
                        "HTTP请求=%d 请求文本=%d 复用=%d 待索引=%d",
                        self._namespace[:12], [r[0] for r in pending], saved,
                        getattr(self._embedding_http_state, "count", 0) if unembedded_unique else 0, len(unembedded_unique),
                        len(updates) - len(unembedded_unique), remaining)
                    if remaining == 0:
                        self._log(
                            "[MaiReply RAG] 索引队列已清空 namespace=%s；"
                            "无待索引记录时不发起索引API请求（聊天检索请求另计）",
                            self._namespace[:12])
            except Exception as exc:
                self._cooldown = time.monotonic() + retry_seconds
                self._warn("[MaiReply RAG] 向量化索引发生异常 (%s)，冷却等待 %.0fs: %s", type(exc).__name__, retry_seconds, exc)
                time.sleep(2.0)
            finally:
                if claimed_ids:
                    with in_flight_lock:
                        in_flight_ids.difference_update(claimed_ids)
    def start(self):
        with self._lock:
            if self.enable and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(target=self._index_worker, name="rag_index_worker", daemon=True)
                self._worker.start()
            if self.knowledge is not None:
                self.knowledge.start()

    def close(self):
        self._closed = True
        if self.knowledge is not None:
            self.knowledge.stop()
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None
            self._worker = None
    async def aclose(self):
        if self.knowledge is not None:
            self.knowledge.stop()
            await self.knowledge.wait_stopped()
        # SQLite shares a threading lock with workers: never wait for it on the Bot loop.
        await asyncio.to_thread(self.close)

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

    async def query_user_facts(self, group_id, user_id) -> str:
        """List this user's active facts only; no semantic search or embedding API."""
        if not self.allowed(group_id) or self._db is None:
            return ""
        uid = str(user_id)
        scope = self.scope_for(group_id, user_id)
        def fetch(db):
            return db.execute("""
                SELECT text FROM memories
                WHERE scope IN (?, ?) AND namespace=? AND target_id=?
                  AND fact_type='fact' AND ended IS NULL
                ORDER BY created DESC, text
            """, (scope, f"user:{uid}", self._namespace, uid)).fetchall()
        rows = await asyncio.to_thread(self._run_db, fetch)
        return "\n".join(dict.fromkeys(row[0].strip() for row in rows if row[0] and row[0].strip()))

    async def recall(self, group_id: Optional[str], user_id: Any, query: str, recent_context=None, now=None) -> str:
        if not self.allowed(group_id):
            return ""
        return await self._recall(group_id, user_id, query, recent_context=recent_context, now=now)
