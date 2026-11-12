"""知识库的离线回归测试，覆盖文档同步、向量检索与 RAG 兼容性。"""

import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
from ruamel.yaml import YAML

from run.core_reply.service import rag_knowledge
from run.core_reply.service.rag_knowledge import RAGKnowledge, _chunks
from run.core_reply.service.rag_memory import RAGMemory


class KnowledgeTests(unittest.IsolatedAsyncioTestCase):
    def test_shipped_schema_preserves_knowledge_settings_on_update(self):
        from framework_common.framework_util.config_migrations import merge_config_values
        template = YAML().load((Path(__file__).resolve().parents[1] / 'run/core_reply/rag.yaml').read_text(encoding='utf-8'))
        previous = {'knowledge_base': {
            'enable': True, 'root_dir': 'data/custom_knowledge',
            'libraries': [self.alpha], 'sync': {'interval_seconds': 42},
            'chunk': {'max_chars': 200, 'overlap_chars': 20},
            'retrieval': {'max_prompt_chars': 800},
            'reranker': {'enable': True, 'api_key': 'fixture-key', 'base_url': 'https://rerank.example/v1'},
        }}
        merged = merge_config_values(template, previous)['knowledge_base']
        self.assertEqual(merged['root_dir'], 'data/custom_knowledge')
        self.assertEqual(merged['libraries'], [self.alpha])
        self.assertEqual(merged['sync']['interval_seconds'], 42)
        self.assertEqual(merged['chunk']['max_chars'], 200)
        self.assertEqual(merged['retrieval']['max_prompt_chars'], 800)
        self.assertEqual(merged['reranker']['api_key'], 'fixture-key')
        self.assertEqual(merged['reranker']['base_url'], 'https://rerank.example/v1')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.db_path = self.project / "data/dataBase/mai_rag_memory.db"
        self.alpha = self.library("alpha")
        self.beta = self.library("beta")

    @staticmethod
    def library(name, enable=True, path=None):
        return {"name": name, "path": path or f"data/knowledge/{name}", "enable": enable}

    def write(self, library, name, content):
        path = self.project / f"data/knowledge/{library}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def open_memory(self, *, knowledge=None, rag=None, core=None):
        knowledge_cfg = {
            "enable": True, "libraries": [self.alpha, self.beta],
            "sync": {"on_startup": False, "interval_seconds": 0},
            **(knowledge or {}),
        }
        cfg = {
            "enable": True, "db_path": str(self.db_path),
            "knowledge_base": knowledge_cfg, **(rag or {}),
        }
        memory = object.__new__(RAGMemory)
        config = SimpleNamespace(core_reply=SimpleNamespace(rag=cfg, config=core or {}))
        with patch.object(RAGMemory, "_index_worker", lambda _: None), patch.object(
            rag_knowledge, "RAGKnowledge", partial(RAGKnowledge, project_root=self.project)
        ):
            memory.__init__(config)
        self.addAsyncCleanup(memory.aclose)
        return memory

    @staticmethod
    async def embed(texts, is_query=False):
        def vector(text):
            if is_query or "管理员" in text:
                return [1, 0]
            if "launch" in text.lower():
                return [0.6, 0.8]
            return [0, 1]
        return [np.array(vector(text), dtype=np.float32) for text in texts]

    def offline(self, **kwargs):
        memory = self.open_memory(**kwargs)
        memory._embed = AsyncMock(side_effect=self.embed)
        return memory

    @staticmethod
    def query(memory, sql, params=()):
        return memory._run_db(lambda db: db.execute(sql, params).fetchall())

    def test_markdown_keeps_sections_lists_and_fences(self):
        fenced = "```text\n# 不是标题\n\n    command --help\n```"
        text = f"# 手册\n\n权限\n----\n\n- 一项\n- Two\n\n{fenced}\n\n### FAQ\nMixed 中文 and English."
        chunks = list(_chunks(text, True, 44, 8))
        self.assertIn(("手册 / 权限", "- 一项\n- Two"), chunks)
        self.assertIn(("手册 / 权限", fenced), chunks)
        self.assertIn(("手册 / 权限 / FAQ", "Mixed 中文 and English."), chunks)
        self.assertTrue(all(0 < len(chunk) <= 44 for _, chunk in chunks))

    def test_text_prefers_sentences_and_limits_overlap(self):
        text = "第一句话非常明确。第二句话也很清晰。第三句是中文。 English follows here."
        chunks = [value for _, value in _chunks(text, False, 18, 3)]
        self.assertTrue(chunks[0].endswith("。"))
        self.assertEqual(chunks[0][-3:], chunks[1][:3])
        self.assertTrue(all(0 < len(chunk) <= 18 for chunk in chunks))
        self.assertEqual(len(chunks), len(set(chunks)))
        self.assertEqual(list(_chunks("  \n\n", False, 10, 3)), [])

    async def test_existing_database_is_migrated_and_memory_scopes_still_recall(self):
        self.db_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("""
                CREATE TABLE memories (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, text TEXT NOT NULL,
                    vector BLOB, created REAL NOT NULL, namespace TEXT NOT NULL)
            """)
            db.execute("INSERT INTO memories VALUES (1, 'private:7', '旧私聊记录', NULL, 1, 'legacy')")
        memory = self.offline(knowledge={"libraries": [self.alpha]})
        self.assertEqual(self.query(memory, "SELECT id, text, namespace FROM memories"), [(1, "旧私聊记录", "legacy")])
        memory.knowledge.init_schema()
        self.write("alpha", "commands.txt", "管理员操作文档")
        await memory.knowledge.sync()

        vector = np.array([1, 0], dtype=np.float32).tobytes()
        rows = [("private:7", "私聊对话片段"), ("group:42", "群聊对话片段"), ("group:99", "其他群片段")]
        for scope, content in rows:
            self.query(memory, "INSERT INTO memories(scope,text,vector,created,namespace) VALUES(?,?,?,1,?)",
                       (scope, content, vector, memory._namespace))
        private = await memory.recall(None, 7, "管理员")
        group = await memory.recall(42, 7, "管理员")
        self.assertIn("私聊对话片段", private)
        self.assertNotIn("群聊对话片段", private)
        self.assertIn("群聊对话片段", group)
        self.assertNotIn("其他群片段", group)
        self.assertNotIn("管理员操作文档", private + group)
        self.assertEqual(self.query(memory, "SELECT COUNT(*) FROM memories"), [(4,)])
        self.assertEqual(list(self.db_path.parent.glob("*.db")), [self.db_path])

    async def test_sync_updates_deletes_and_reuses_vectors_within_a_library(self):
        a = self.write("alpha", "sub/commands.TXT", b"\xef\xbb\xbf" + "管理员命令".encode())
        self.write("alpha", "duplicate.txt", "管理员命令")
        self.write("alpha", "ignored.pdf", "ignored")
        b = self.write("beta", "guide.MD", "# Guide\n\n管理员命令")
        self.write("unregistered", "secret.txt", "管理员未注册资料")
        memory = self.offline()
        kb = memory.knowledge
        await kb.sync()
        self.assertEqual(memory._embed.await_count, 2)
        self.assertEqual(self.query(memory, """
            SELECT d.library, d.path, c.text, c.section FROM kb_documents d JOIN kb_chunks c
            ON d.id=c.document_id ORDER BY d.library, d.path
        """), [("alpha", "duplicate.txt", "管理员命令", ""), ("alpha", "sub/commands.TXT", "管理员命令", ""),
               ("beta", "guide.MD", "管理员命令", "Guide")])
        await kb.sync()
        self.assertEqual(memory._embed.await_count, 2)

        a.unlink()
        b.write_text("# Launch\n\nlaunch the client 中文。", encoding="utf-8")
        self.write("beta", "new.txt", "管理员权限")
        await kb.sync()
        self.assertEqual(self.query(memory, "SELECT path FROM kb_documents ORDER BY path"),
                         [("duplicate.txt",), ("guide.MD",), ("new.txt",)])
        self.assertEqual(self.query(memory, "SELECT COUNT(*) FROM kb_chunks"), [(3,)])

    async def test_invalid_encoding_failed_embedding_and_sql_write_preserve_index(self):
        a = self.write("alpha", "a.txt", "管理员旧文档")
        self.write("alpha", "b.txt", "launch old client")
        memory = self.offline(knowledge={"libraries": [self.alpha]}, rag={"index": {"batch_size": 1}})
        kb = memory.knowledge
        await kb.sync()
        original = self.query(memory, "SELECT path, content_hash, indexed_at FROM kb_documents ORDER BY path")
        a.write_bytes(b"\xff\xfe\x00")
        await kb.sync()
        self.assertEqual(self.query(memory, "SELECT path, content_hash, indexed_at FROM kb_documents ORDER BY path"), original)

        self.write("alpha", "a.txt", "管理员新文档")
        self.write("alpha", "b.txt", "launch new client")
        memory._embed.side_effect = [RuntimeError("offline"), [np.array([0.6, 0.8], dtype=np.float32)]]
        await kb.sync()
        self.assertEqual(self.query(memory, "SELECT text FROM kb_chunks ORDER BY document_id"),
                         [("管理员旧文档",), ("launch new client",)])

        memory._embed.side_effect = self.embed
        self.query(memory, """
            CREATE TRIGGER reject_chunk BEFORE INSERT ON kb_chunks
            BEGIN SELECT RAISE(ABORT, 'test write failure'); END
        """)
        await kb.sync()
        self.assertIn("管理员旧文档", await kb.recall(None, "管理员"))
        self.assertEqual(self.query(memory, "SELECT path, content_hash, indexed_at FROM kb_documents WHERE path='a.txt'"),
                         original[:1])
        self.query(memory, "DROP TRIGGER reject_chunk")
        await kb.sync()
        self.assertIn("管理员新文档", await kb.recall(None, "管理员"))

    async def test_unavailable_directories_and_symlinks(self):
        path = self.write("alpha", "ok.txt", "管理员旧索引")
        outside = self.project / "unregistered.txt"
        outside.write_text("管理员库外文件", encoding="utf-8")
        (path.parent / "link.txt").symlink_to(outside)
        (path.parent / "link-dir").symlink_to(self.project, target_is_directory=True)
        self.write("beta", "active.txt", "launch elsewhere")
        memory = self.offline()
        await memory.knowledge.sync()
        self.assertEqual(self.query(memory, "SELECT path FROM kb_documents ORDER BY path"), [("active.txt",), ("ok.txt",)])
        path.parent.rename(path.parent.with_name("unavailable"))
        self.write("beta", "new.txt", "管理员新增资料")
        await memory.knowledge.sync()
        self.assertEqual(self.query(memory, "SELECT path FROM kb_documents ORDER BY path"),
                         [("active.txt",), ("new.txt",), ("ok.txt",)])

    async def test_disabled_libraries_and_path_reassignment(self):
        self.write("alpha", "manual.md", "# 指令\n\n管理员操作手册")
        self.write("beta", "guide.txt", "launch notes")
        memory = self.offline()
        await memory.knowledge.sync()
        await memory.aclose()

        beta_only = self.offline(knowledge={"libraries": [{**self.alpha, "enable": False}, self.beta]})
        self.write("alpha", "manual.md", "# 指令\n\n管理员新手册")
        await beta_only.knowledge.sync()
        self.assertNotIn("操作手册", await beta_only.knowledge.recall(None, "管理员"))
        self.assertEqual(self.query(beta_only, "SELECT text FROM kb_chunks ORDER BY text"),
                         [("launch notes",), ("管理员操作手册",)])
        await beta_only.aclose()

        self.write("replacement", "manual.md", "# 指令\n\n管理员新目录")
        moved = self.library("alpha", path="data/knowledge/replacement")
        new_path = self.offline(knowledge={"libraries": [moved]})
        self.assertEqual(await new_path.knowledge.recall(None, "管理员"), "")
        await new_path.knowledge.sync()
        self.assertIn("管理员新目录", await new_path.knowledge.recall(None, "管理员"))
        await new_path.aclose()

        reenabled = self.offline()
        await reenabled.knowledge.sync()
        self.assertIn("管理员新手册", await reenabled.knowledge.recall(None, "管理员"))
        self.assertNotIn("新目录", await reenabled.knowledge.recall(None, "管理员"))

    async def test_configuration_and_rag_permission_gates(self):
        disabled = self.open_memory(rag={"enable": False})
        self.assertIsNone(disabled.knowledge)
        self.assertFalse(self.db_path.exists())
        for cfg in (None, {"enable": False}, {"enable": "false"}):
            memory = self.open_memory(rag={"knowledge_base": cfg})
            self.assertIsNone(memory.knowledge)
            self.assertEqual(self.query(memory, "SELECT name FROM sqlite_master WHERE name LIKE 'kb_%'"), [])
            await memory.aclose()

        self.write("alpha", "manual.txt", "管理员不应出现")
        self.write("beta", "manual.txt", "管理员操作")
        rejected = self.library("ALPHA", path="data/knowledge/third")
        escaped = self.library("escape", path="../outside")
        memory = self.offline(
            knowledge={"libraries": [self.alpha, rejected, self.beta, escaped]},
            rag={"private": {"enable": False}, "group": {"enable": True, "whitelist_enabled": True}},
            core={"trigger_llm": {"whitelist": [42]}},
        )
        kb = memory.knowledge
        self.assertEqual([library.name for library in kb.libraries], ["beta"])
        await kb.sync()
        self.assertEqual(await kb.recall(None, "管理员"), "")
        self.assertEqual(await kb.recall(99, "管理员"), "")
        self.assertEqual(memory._embed.await_count, 1)
        self.assertIn("管理员操作", await kb.recall(42, "管理员"))

    async def test_namespace_change_reindexes_using_existing_provider_adapters(self):
        self.write("alpha", "manual.md", "# Commands\n\n管理员命令 and launch")
        cfg = {"libraries": [self.alpha]}
        client = httpx.AsyncClient
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append((str(request.url), payload, request.headers.get("Authorization")))
            if request.url.host == "embedding.example":
                return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3, 0]}]})
            return httpx.Response(200, json={"success": True, "result": {"data": [[2, 0, 0]]}})

        def mocked_client(**kwargs):
            return client(transport=httpx.MockTransport(handle), **kwargs)

        openai = self.open_memory(knowledge=cfg, rag={"embedding": {
            "base_url": "https://embedding.example/v1/", "endpoint": "/embeddings/", "model": "m",
        }})
        with patch.object(httpx, "AsyncClient", side_effect=mocked_client):
            await openai.knowledge.sync()
            self.assertIn("管理员命令 and launch", await openai.knowledge.recall(None, "管理员"))
        self.assertEqual(requests[0], ("https://embedding.example/v1/embeddings",
                                       {"model": "m", "input": ["管理员命令 and launch"]}, None))
        old_namespace = openai._namespace
        await openai.aclose()

        cloudflare = self.open_memory(knowledge=cfg, rag={"embedding": {
            "provider": "cloudflare", "cloudflare": {"account_id": "acct", "api_token": "token"},
        }})
        with patch.object(httpx, "AsyncClient", side_effect=mocked_client):
            self.assertEqual(await cloudflare.knowledge.recall(None, "管理员"), "")
            await cloudflare.knowledge.sync()
            self.assertIn("管理员命令", await cloudflare.knowledge.recall(None, "管理员"))
        self.assertEqual(requests[2], ("https://api.cloudflare.com/client/v4/accounts/acct/ai/run/@cf/baai/bge-m3",
                                       {"text": ["管理员命令 and launch"]}, "Bearer token"))
        self.assertNotEqual(cloudflare._namespace, old_namespace)
        self.assertEqual(self.query(cloudflare, "SELECT namespace, length(vector) FROM kb_chunks"),
                         [(cloudflare._namespace, 12)])

    async def test_cosine_candidates_deduplicate_and_enforce_prompt_budget(self):
        self.write("alpha", "a.md", "# 指南\n\n管理员手册提供所有权限设置")
        self.write("alpha", "b.txt", "管理员手册提供所有权限设置。")
        self.write("alpha", "c.txt", "launch client in safe mode")
        self.write("alpha", "d.txt", "irrelevant")
        self.write("beta", "a.txt", "launch client in safe mode")
        settings = YAML().load("min_similarity: 0.50\ncandidate_k: 2\ntop_k: 2\nmax_prompt_chars: 160\n")
        memory = self.offline(knowledge={"retrieval": settings})
        kb = memory.knowledge
        await kb.sync()
        self.assertEqual(kb.min_similarity, 0.50)
        candidates = await kb._retrieve("管理员")
        self.assertEqual([item.path for item in candidates], ["a.md", "c.txt"])
        context = await kb.recall(None, "管理员")
        self.assertIn("知识库：alpha\n文件：a.md\n章节：指南", context)
        self.assertLessEqual(len(context), 160)
        kb.prompt_chars = len(context) - 1
        self.assertLessEqual(len(await kb.recall(None, "管理员")), kb.prompt_chars)

        self.query(memory, "UPDATE kb_chunks SET vector=? WHERE text LIKE '管理员%'", (np.ones(3, dtype=np.float32).tobytes(),))
        self.assertEqual([item.path for item in await kb._retrieve("管理员")], ["c.txt"])
        kb.min_similarity = 0.9
        self.assertEqual(await kb.recall(None, "管理员"), "")

    async def test_reranker_request_and_validated_fallback(self):
        self.write("alpha", "a.txt", "管理员手册")
        self.write("alpha", "b.txt", "launch client")
        self.write("beta", "c.txt", "launch game")
        memory = self.offline(knowledge={
            "retrieval": {"candidate_k": 2, "top_k": 1},
            "reranker": {"enable": True, "base_url": "https://rank.example/v1/", "endpoint": "/rerank/",
                         "model": "ranking-model", "api_key": "fixture"},
        })
        kb = memory.knowledge
        await kb.sync()
        client = httpx.AsyncClient
        requests = []
        status = 200
        response = {"results": [{"index": 1, "relevance_score": 0.98, "document": "不可信响应文本"}]}

        def handler(request):
            requests.append((str(request.url), json.loads(request.content), request.headers["Authorization"]))
            return httpx.Response(status, json=response)

        def mocked_client(**kwargs):
            return client(transport=httpx.MockTransport(handler), **kwargs)

        with patch.object(httpx, "AsyncClient", side_effect=mocked_client):
            context = await kb.recall(None, "管理员")
            self.assertIn("文件：b.txt", context)
            self.assertNotIn("不可信响应文本", context)
            self.assertEqual(requests[0], ("https://rank.example/v1/rerank", {
                "model": "ranking-model", "query": "管理员", "documents": ["管理员手册", "launch client"],
                "top_n": 1, "return_documents": False,
            }, "Bearer fixture"))

            for result in ([], [{"index": True, "relevance_score": 0.98}],
                           [{"index": 2, "relevance_score": 0.98}], [{"index": 1, "relevance_score": "bad"}],
                           [{"index": 0, "relevance_score": 0.5}] * 2):
                with self.subTest(result=result):
                    response = {"results": result}
                    self.assertIn("文件：a.txt", await kb.recall(None, "管理员"))
            status = 429
            self.assertIn("文件：a.txt", await kb.recall(None, "管理员"))

            status = 200
            kb.top_k = 2
            response = {"results": [{"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9}]}
            context = await kb.recall(None, "管理员")
            self.assertLess(context.index("b.txt"), context.index("a.txt"))
            response["results"][0]["index"] = 1
            context = await kb.recall(None, "管理员")
            self.assertLess(context.index("a.txt"), context.index("b.txt"))

            kb.reranker["enable"] = False
            count = len(requests)
            self.assertIn("文件：a.txt", await kb.recall(None, "管理员"))
            self.assertEqual(len(requests), count)

    async def test_timeout_and_lifecycle_stop(self):
        self.write("alpha", "a.txt", "管理员手册")
        memory = await asyncio.to_thread(self.offline, knowledge={
            "libraries": [self.alpha], "retrieval": {"timeout_seconds": 0.1},
            "sync": {"on_startup": True, "interval_seconds": 0.02},
        })
        kb = memory.knowledge
        self.assertIsNone(kb._task)
        memory.start()
        self.assertIsNotNone(kb._task)
        task = kb._task
        memory.start()
        self.assertIs(kb._task, task)
        for _ in range(100):
            if self.query(memory, "SELECT COUNT(*) FROM kb_chunks") == [(1,)]:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.query(memory, "SELECT COUNT(*) FROM kb_chunks"), [(1,)])
        self.write("alpha", "b.txt", "launch client")
        for _ in range(100):
            if self.query(memory, "SELECT COUNT(*) FROM kb_chunks") == [(2,)]:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.query(memory, "SELECT COUNT(*) FROM kb_chunks"), [(2,)])

        async def blocked_embed(texts, is_query=False):
            await asyncio.sleep(60)

        memory._embed.side_effect = blocked_embed
        self.assertEqual(await kb.recall(None, "管理员"), "")
        memory._embed.side_effect = self.embed
        kb.reranker = {"enable": True, "timeout_seconds": 0.02}
        async def blocked_post(*args, **kwargs):
            await asyncio.sleep(60)

        with patch.object(httpx.AsyncClient, "post", side_effect=blocked_post):
            self.assertIn("管理员手册", await kb.recall(None, "管理员"))
        await memory.aclose()
        self.assertTrue(task.cancelled())
        self.assertIsNone(memory._db)

    async def test_shutdown_cancels_inflight_sync_and_preserves_the_previous_document(self):
        path = self.write("alpha", "a.txt", "管理员原始文档")
        memory = self.offline(knowledge={"libraries": [self.alpha]})
        kb = memory.knowledge
        await kb.sync()
        path.write_text("管理员修改文档", encoding="utf-8")
        entered = asyncio.Event()

        async def pending_embedding(texts, is_query=False):
            entered.set()
            await asyncio.sleep(60)

        memory._embed.side_effect = pending_embedding
        memory._embed.reset_mock()
        kb.on_startup = True
        memory.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.wait_for(kb.sync(), timeout=1)
        self.assertEqual(memory._embed.await_count, 1)
        rows = await asyncio.wait_for(asyncio.to_thread(self.query, memory, "SELECT text FROM kb_chunks"), timeout=1)
        self.assertEqual(rows, [("管理员原始文档",)])
        await asyncio.wait_for(memory.aclose(), timeout=1)
        self.assertTrue(kb._task.cancelled())
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT text FROM kb_chunks").fetchall(), rows)

    async def test_async_shutdown_closes_database_off_event_loop(self):
        memory = self.offline()
        main_thread = threading.get_ident()
        thread_ids = []
        close = memory.close

        def observed_close():
            thread_ids.append(threading.get_ident())
            close()

        with patch.object(memory, "close", side_effect=observed_close):
            await memory.aclose()
        self.assertTrue(thread_ids)
        self.assertNotIn(main_thread, thread_ids)
        self.assertIsNone(memory._db)


if __name__ == "__main__":
    unittest.main()
