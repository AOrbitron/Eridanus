# -*- coding: utf-8 -*-
"""Episodic memory buffering, Mem0 atomic fact extraction, and background consolidation."""
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from typing import List, Dict, Optional, Tuple, Any

import httpx
import numpy as np

from framework_common.utils.system_logger import get_logger

logger = get_logger(__name__)

FACT_EXTRACT_SYSTEM_PROMPT = """你是一个高效、客观的长期记忆提取与状态机分析专家（参考 Mem0 架构）。
你的任务是从给定的最新对话片段中，提取出需要长期记住的关键原子事实（Facts），并判断每个事实的操作类型（ADD / UPDATE / DELETE）。

请提取三类实体的客观事实：
1. user: 用户的长期个人背景、稳定作息习惯、重要喜好/雷区、当前重大现实事件/人生节点、重要人际关系等。
2. group: 本群特有的社群定位、群专属黑话/梗文化、共同话题、重大集体事件。
3. bot: Bot自身经历的真实独立事件、明确认同的个性/习惯设定、收到的关键契约或重大生活足迹。

操作类型判断规则：
- ADD: 首次获知的新事实、新偏好或新经历。
- UPDATE: 某个之前已知的事实发生了明确变化或更正（例如用户更新了所在地、改变了作息、或者计划有了新进展）。
- DELETE: 之前的事实被明确撤销、否定或彻底失效。

输出格式要求：
严格返回一个标准的 JSON 数组，数组中每个对象包含以下字段：
- "action": "ADD" | "UPDATE" | "DELETE"
- "target_type": "user" | "bot" | "group"
- "target_id": 实体的唯一标识（用户的QQ号/ID，群号，若是Bot自身则固定为 "global"）
- "target_name": 实体名称（用户昵称、群名称，或Bot名字）
- "category": 事实分类，如 "profile"（档案）, "preference"（喜好偏好）, "habit"（习惯作息）, "plan"（近期计划）, "milestone"（重大事件/经历）, "relationship"（人际契约）
- "content": 精炼准确的客观事实陈述（必须简明扼要，建议20-60字，禁止废话，不要第一人称口语），如 "用户在莫斯科留学读政治学，正处于毕业设计高压期。"

若对话片段完全为闲聊吹水、无任何值得长期沉淀的事实价值，请返回空数组 []。直接输出 JSON，不要 Markdown 包装或解释。"""


class EpisodeArchive:
    """负责会话缓冲、片段分块与 Mem0 原子事实状态机管理"""

    def _init_archive(self, config):
        self._archive_cfg = self.cfg.get("archive", {})
        self._buffers: Dict[str, List[Dict[str, Any]]] = {}
        self._buffer_lock = threading.Lock()
        self._last_archive_time: Dict[str, float] = {}
        self._flushing_scopes = set()

        # 加载轻量 LLM (trigger_llm) 配置供 Mem0 抽取事实使用
        ccfg = getattr(config.mai_reply, "config", {})
        trig_cfg = ccfg.get("trigger_llm", {}) or {}
        self._trig_model = str(trig_cfg.get("model", "")).strip() or "qwen3.8-flash"
        self._trig_base_url = str(trig_cfg.get("base_url", "")).strip().rstrip("/") or "http://api.apollodorus.xyz/v1"
        raw_key = trig_cfg.get("api_key")
        raw_keys = trig_cfg.get("api_keys", [])
        keys = []
        if raw_key and str(raw_key).strip():
            keys.append(str(raw_key).strip())
        if isinstance(raw_keys, list):
            keys.extend([str(k).strip() for k in raw_keys if k and str(k).strip()])
        elif isinstance(raw_keys, str) and raw_keys.strip():
            keys.append(raw_keys.strip())

        # 若 trigger_llm 未单独配置 key，回退到主回复模型 openai.api_keys
        if not keys:
            llm_openai = ccfg.get("llm", {}).get("openai", {})
            main_keys = llm_openai.get("api_keys", [])
            if isinstance(main_keys, list):
                keys.extend([str(k).strip() for k in main_keys if k and str(k).strip()])
            elif isinstance(main_keys, str) and main_keys.strip():
                keys.append(main_keys.strip())

        self._trig_keys = keys

    def _event(self, speaker_name: str, speaker_id: str, text: str, is_bot: bool, ts: float, message_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "name": str(speaker_name),
            "id": str(speaker_id),
            "text": str(text).strip(),
            "is_bot": bool(is_bot),
            "ts": float(ts),
            "message_id": str(message_id) if message_id else None,
        }

    async def record_turn(
        self,
        group_id: Optional[str],
        user_id: Any,
        user_name: str,
        user_text: str,
        bot_reply: str,
        bot_name: Optional[str] = None,
        message_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        ts: Optional[float] = None,
        **kwargs,
    ):
        if not self.allowed(group_id):
            return
        now = ts if ts is not None else (timestamp if timestamp is not None else time.time())
        scope = self.scope_for(group_id, user_id)
        bot_label = bot_name or "Bot"
        events = [
            self._event(user_name, str(user_id), user_text, is_bot=False, ts=now, message_id=message_id),
            self._event(bot_label, "bot", bot_reply, is_bot=True, ts=now + 0.1),
        ]
        self._append_events(scope, events, is_group=(group_id is not None), group_id=group_id, user_id=user_id)

    async def observe(
        self,
        group_id: Optional[str],
        user_id: Any,
        user_name: str,
        user_text: str,
        message_id: Optional[str] = None,
        role: str = "user",
        timestamp: Optional[float] = None,
        ts: Optional[float] = None,
        **kwargs,
    ):
        if not self.allowed(group_id):
            return
        gcfg = self.cfg.get("group", {})
        if group_id is not None and not gcfg.get("observe_untriggered", True):
            return
        now = ts if ts is not None else (timestamp if timestamp is not None else time.time())
        scope = self.scope_for(group_id, user_id)
        is_bot = (role == "assistant")
        speaker_id = "bot" if is_bot else str(user_id)
        events = [self._event(user_name, speaker_id, user_text, is_bot=is_bot, ts=now, message_id=message_id)]
        self._append_events(scope, events, is_group=(group_id is not None), group_id=group_id, user_id=user_id)

    def _append_events(self, scope: str, events: List[Dict[str, Any]], is_group: bool, group_id: Optional[str], user_id: Any):
        with self._buffer_lock:
            if scope not in self._last_archive_time:
                self._last_archive_time[scope] = time.time()
            buf = self._buffers.setdefault(scope, [])
            buf.extend(events)
            max_buf = int(self._archive_cfg.get("max_buffer_messages", 200))
            if len(buf) > max_buf:
                del buf[:-max_buf]

            due = self._archive_due(scope, buf, is_group)

        if due:
            asyncio.create_task(self._flush_archive(scope, is_group, group_id, user_id))

    def _archive_due(self, scope: str, buf: List[Dict[str, Any]], is_group: bool) -> bool:
        if not buf:
            return False
        if scope in self._flushing_scopes:
            return False
        if is_group:
            trigger_msgs = int(self._archive_cfg.get("group_messages", 10))
            user_count = sum(1 for e in buf if not e["is_bot"])
            if user_count >= trigger_msgs:
                return True
        else:
            trigger_turns = int(self._archive_cfg.get("private_turns", 3))
            bot_count = sum(1 for e in buf if e["is_bot"])
            if bot_count >= trigger_turns:
                return True

        # 超时补归档
        idle_seconds = float(self._archive_cfg.get("idle_seconds", 600.0))
        if idle_seconds > 0 and len(buf) >= 2:
            last_time = self._last_archive_time.get(scope, 0.0)
            if time.time() - last_time > idle_seconds:
                return True
        return False

    async def _flush_archive(self, scope: str, is_group: bool, group_id: Optional[str], user_id: Any):
        with self._buffer_lock:
            if scope in self._flushing_scopes:
                return
            buf = list(self._buffers.get(scope, []))
            if not buf:
                return
            self._flushing_scopes.add(scope)
            self._buffers[scope] = []
            self._last_archive_time[scope] = time.time()

        try:
            now = time.time()
            # 1. 保存对话片段 (fact_type='episode')
            chunk_lines = []
            for e in buf:
                chunk_lines.append(f"{e['name']}: {e['text']}")
            episode_text = "\n".join(chunk_lines).strip()

            if episode_text:
                def save_episode(db):
                    # 检查是否与当前 scope 最新一条 episode 完全相同，避免短时间刷屏重复入库
                    last_ep = db.execute("""
                        SELECT text FROM memories
                        WHERE scope=? AND fact_type='episode' AND namespace=?
                        ORDER BY id DESC LIMIT 1
                    """, (scope, self._namespace)).fetchone()
                    if last_ep and (last_ep[0] or "").strip() == episode_text:
                        return
                    db.execute("""
                        INSERT INTO memories (
                            scope, text, created, ended, user_id, message_id, namespace,
                            fact_type, category, target_id, target_name, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'episode', 'conversation', ?, ?, ?)
                    """, (
                        scope, episode_text, buf[0]["ts"], buf[-1]["ts"],
                        str(user_id) if user_id else None,
                        buf[-1].get("message_id"),
                        self._namespace,
                        str(group_id) if is_group else str(user_id),
                        f"群{group_id}" if is_group else "私聊",
                        now
                    ))

                try:
                    self._run_db(save_episode)
                except Exception as exc:
                    self._warn("[MaiReply RAG] 保存历史片段失败: %s", exc)

            # 2. 异步调用 trigger_llm 执行 Mem0 原子事实抽取与状态机更新
            try:
                await self._extract_and_apply_mem0(scope, buf, is_group, group_id, user_id)
            except Exception as exc:
                self._warn("[MaiReply RAG] Mem0 抽取事实失败 (%s): %s", type(exc).__name__, exc)
        finally:
            with self._buffer_lock:
                self._flushing_scopes.discard(scope)

    async def _extract_and_apply_mem0(self, scope: str, buf: List[Dict[str, Any]], is_group: bool, group_id: Optional[str], user_id: Any):
        facts = await self._extract_facts_llm(buf, is_group, group_id, user_id)
        if not facts:
            return

        now = time.time()
        def apply_all(db):
            for fact in facts:
                # 确定该事实归属的存储范围
                target_type = str(fact.get("target_type", "user")).lower()
                target_id = str(fact.get("target_id", "")).strip()
                if target_type == "user":
                    fact_scope = f"user:{target_id}" if target_id else (f"user:{user_id}" if user_id else scope)
                elif target_type == "bot":
                    fact_scope = "agent:global"
                elif target_type == "group":
                    fact_scope = f"group:{target_id}" if target_id else (f"group:{group_id}" if group_id else scope)
                else:
                    fact_scope = scope

                self._apply_mem0_fact(db, fact, fact_scope, now)

        self._run_db(apply_all)

    async def _extract_facts_llm(self, buf: List[Dict[str, Any]], is_group: bool, group_id: Optional[str], user_id: Any) -> List[Dict[str, Any]]:
        # 组装对话上下文
        dialog_lines = []
        for e in buf:
            dialog_lines.append(f"[{e['name']} (ID:{e['id']})]: {e['text']}")
        conv_text = "\n".join(dialog_lines)

        user_prompt = f"""当前对话场景：{'群聊 (群号:' + str(group_id) + ')' if is_group else '私聊 (用户ID:' + str(user_id) + ')'}
对话内容：
{conv_text}

请提取原子事实（JSON 格式）："""

        headers = {"Content-Type": "application/json"}
        if self._trig_keys:
            headers["Authorization"] = f"Bearer {self._trig_keys[0]}"

        url = f"{self._trig_base_url}/chat/completions"
        payload = {
            "model": self._trig_model,
            "messages": [
                {"role": "system", "content": FACT_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 800
        }

        async with httpx.AsyncClient(timeout=25.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                self._warn(f"[MaiReply RAG] trigger_llm 请求失败 HTTP {resp.status_code}: {resp.text[:200]}")
                return []
            content = resp.json()["choices"][0]["message"]["content"].strip()

        # 解析 JSON
        clean_json = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()
        try:
            facts = json.loads(clean_json)
            if isinstance(facts, list):
                return facts
        except Exception:
            # 尝试正则提取 JSON array
            m = re.search(r"\[.*\]", clean_json, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return []

    def _apply_mem0_fact(self, db, fact: Dict[str, Any], fact_scope: str, now: float):
        action = str(fact.get("action", "ADD")).upper().strip()
        content = str(fact.get("content", "")).strip()
        if not content:
            return

        target_id = str(fact.get("target_id", "")).strip()
        target_name = str(fact.get("target_name", "")).strip()
        category = str(fact.get("category", "general")).strip()
        target_type = str(fact.get("target_type", "user")).strip()

        # 1. 严格内容去重：检查该 scope 与 target 下是否已有完全相同文本的活跃事实
        # 若已有完全一致的有效事实，仅刷新 updated_at，保留已有 vector 不重置，彻底防止重复调用 Embedding
        exact_row = db.execute("""
            SELECT id, text FROM memories
            WHERE scope=? AND target_id=? AND text=? AND fact_type='fact' AND ended IS NULL
            LIMIT 1
        """, (fact_scope, target_id, content)).fetchone()

        if exact_row:
            db.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, exact_row[0]))
            self._log("[MaiReply RAG] Mem0 事实无变化，保留已有向量不重算 scope=%s target=%s: %s", fact_scope, target_name, content)
            return

        if action == "ADD":
            row = db.execute("""
                SELECT id, text FROM memories
                WHERE scope=? AND target_id=? AND category=? AND fact_type='fact' AND ended IS NULL
                ORDER BY id DESC LIMIT 1
            """, (fact_scope, target_id, category)).fetchone()

            if row:
                old_text = (row[1] or "").strip()
                if old_text == content:
                    db.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, row[0]))
                    self._log("[MaiReply RAG] Mem0 事实无变化，保留已有向量 scope=%s target=%s: %s", fact_scope, target_name, content)
                else:
                    # 内容确实变化，更新文本并重置 vector=NULL 重新索引
                    db.execute("""
                        UPDATE memories SET text=?, updated_at=?, vector=NULL
                        WHERE id=?
                    """, (content, now, row[0]))
                    self._log("[MaiReply RAG] Mem0 更新事实 scope=%s target=%s: %s", fact_scope, target_name, content)
            else:
                db.execute("""
                    INSERT INTO memories (
                        scope, text, created, ended, user_id, namespace,
                        fact_type, category, target_id, target_name, updated_at
                    ) VALUES (?, ?, ?, NULL, ?, ?, 'fact', ?, ?, ?, ?)
                """, (fact_scope, content, now, target_id, self._namespace, category, target_id, target_name, now))
                self._log("[MaiReply RAG] Mem0 新增事实 scope=%s target=%s: %s", fact_scope, target_name, content)

        elif action == "UPDATE":
            row = db.execute("""
                SELECT id, text FROM memories
                WHERE scope=? AND target_id=? AND fact_type='fact' AND ended IS NULL
                ORDER BY id DESC LIMIT 1
            """, (fact_scope, target_id)).fetchone()

            if row:
                old_text = (row[1] or "").strip()
                if old_text == content:
                    db.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, row[0]))
                    self._log("[MaiReply RAG] Mem0 事实无变化，保留已有向量 scope=%s target=%s: %s", fact_scope, target_name, content)
                else:
                    db.execute("""
                        UPDATE memories SET text=?, updated_at=?, vector=NULL
                        WHERE id=?
                    """, (content, now, row[0]))
                    self._log("[MaiReply RAG] Mem0 更新事实 scope=%s target=%s: %s", fact_scope, target_name, content)
            else:
                db.execute("""
                    INSERT INTO memories (
                        scope, text, created, ended, user_id, namespace,
                        fact_type, category, target_id, target_name, updated_at
                    ) VALUES (?, ?, ?, NULL, ?, ?, 'fact', ?, ?, ?, ?)
                """, (fact_scope, content, now, target_id, self._namespace, category, target_id, target_name, now))
                self._log("[MaiReply RAG] Mem0 新增事实 scope=%s target=%s: %s", fact_scope, target_name, content)

        elif action == "DELETE":
            db.execute("""
                UPDATE memories SET ended=?
                WHERE scope=? AND target_id=? AND fact_type='fact' AND ended IS NULL
            """, (now, fact_scope, target_id))
            self._log("[MaiReply RAG] Mem0 失效事实 scope=%s target=%s", fact_scope, target_name)

    def _pending(self, db, limit: int = 16):
        return db.execute("""
            SELECT id, text, scope, fact_type FROM memories
            WHERE vector IS NULL AND namespace=?
            ORDER BY id ASC LIMIT ?
        """, (self._namespace, limit)).fetchall()

    def _embedding_text(self, text: str, fact_type: str = "episode") -> str:
        if fact_type == "fact":
            return f"事实记忆: {text}"
        return text

    def _recent_events(self, db, scope: str, limit: int = 6):
        return db.execute("""
            SELECT text, created FROM memories
            WHERE scope=? AND namespace=?
            ORDER BY COALESCE(ended, created) DESC, id DESC LIMIT ?
        """, (scope, self._namespace, limit)).fetchall()
