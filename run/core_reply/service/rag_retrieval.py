# -*- coding: utf-8 -*-
"""Greedy-packed, multi-scope retrieval supporting group multi-speaker concise recognition and zero truncation."""
import asyncio
import hashlib
import json
import re
import time
from typing import List, Dict, Optional, Tuple, Any

import numpy as np

from framework_common.utils.system_logger import get_logger

logger = get_logger(__name__)

RAG_PREFIX = "\n\n【长期记忆检索 (RAG Memory)】"


class EpisodeRetrieval:
    """负责跨会话多作用域隔离召回、群聊多成员感知与防截断贪心组装"""

    def _init_retrieval(self):
        self._query_cache: Dict[str, Tuple[float, np.ndarray]] = {}

    async def _recall(
        self,
        group_id: Optional[str],
        user_id: Any,
        query: str,
        recent_context=None,
        now: Optional[float] = None,
    ) -> str:
        now = time.time() if now is None else now
        is_group = group_id is not None
        current_scope = self.scope_for(group_id, user_id)
        user_id_str = str(user_id) if user_id is not None else ""

        # -------------------------------------------------------------
        # 1. 作用域解析与群聊多发言人（Multi-Speaker）感知
        # -------------------------------------------------------------
        other_members: Dict[str, str] = {}  # other_uid -> name

        if not is_group:
            # 私聊环境：自身私聊范围 + 该用户档案 + Bot全局自我记忆
            target_scopes = [current_scope, f"user:{user_id_str}", "agent:global"]
        else:
            # 群聊环境：
            # (1) 解析近期群聊滑动窗口中的在场其他活跃群友（按发言时间从新到旧优先）
            if isinstance(recent_context, list):
                for item in reversed(recent_context):
                    if isinstance(item, dict):
                        uid = str(item.get("user_id") or "").strip()
                        name = str(item.get("sender") or "").strip()
                        if uid and uid != user_id_str and uid != "bot" and name != "Bot":
                            if uid not in other_members:
                                other_members[uid] = name

            # (2) 从当前 query 中提取被 @ 或被提及的群成员（如 [CQ:at,qq=123456] 或 @123456）
            at_matches = re.findall(r"(?:qq=|[at@])(\d{5,12})", query)
            for at_uid in at_matches:
                if at_uid != user_id_str:
                    other_members.setdefault(at_uid, f"群友{at_uid}")

            # (3) 补充拉取本群沉淀过事实的知名活跃群成员（保留前4位活跃在场者，节省Token）
            def fetch_known_members(db):
                return db.execute("""
                    SELECT DISTINCT target_id, target_name FROM memories
                    WHERE scope=? AND fact_type='fact' AND target_id IS NOT NULL AND target_id != ?
                    LIMIT 4
                """, (current_scope, user_id_str)).fetchall()

            try:
                db_members = self._run_db(fetch_known_members)
                for mid, mname in db_members:
                    if mid and str(mid) != user_id_str:
                        other_members.setdefault(str(mid), mname or f"群友{mid}")
            except Exception:
                pass

            # 组装群聊检索目标作用域：
            # - 本群话题与共同记忆：group:{group_id}
            # - 当前正在互动的说话者：user:{current_speaker}
            # - 群内在场/被提及的其他群成员：user:{other_member_id}（限制最多4位最关键在场者，节省上下文）
            # - Bot全局自我经历：agent:global
            # 【最高安全边界】：绝对禁止查询 private:*，防止私聊泄密！
            target_scopes = [current_scope, f"user:{user_id_str}", "agent:global"]
            for o_uid in list(other_members.keys())[:4]:
                target_scopes.append(f"user:{o_uid}")

        # 去重且保持顺序
        unique_scopes = []
        for s in target_scopes:
            if s and s not in unique_scopes:
                unique_scopes.append(s)

        cfg = self.cfg.get("retrieval", {})
        timeout = float(cfg.get("timeout_seconds", 15.0))
        top_k = max(1, int(cfg.get("top_k", 10)))
        min_sim = float(cfg.get("min_similarity", 0.30))
        max_prompt_chars = int(cfg.get("max_prompt_chars", 1200))

        # -------------------------------------------------------------
        # 2. 生成 Query Embedding
        # -------------------------------------------------------------
        query_text = query.strip()
        if not query_text:
            return ""

        cache_ttl = float(cfg.get("query_cache_seconds", 300.0))
        max_cache_size = int(cfg.get("query_cache_size", 256))
        q_vec = None

        cached = self._query_cache.get(query_text)
        if cached and (now - cached[0]) < cache_ttl:
            q_vec = cached[1]

        if q_vec is None:
            try:
                vectors = await asyncio.wait_for(self._embed([query_text], is_query=True), timeout=timeout)
                q_vec = vectors[0]
                if len(self._query_cache) >= max_cache_size:
                    oldest_k = min(self._query_cache.keys(), key=lambda k: self._query_cache[k][0])
                    self._query_cache.pop(oldest_k, None)
                self._query_cache[query_text] = (now, q_vec)
            except Exception as exc:
                self._warn(f"[MaiReply RAG] 生成 Query Embedding 超时或失败: {exc}")
                return ""

        # -------------------------------------------------------------
        # 3. 从数据库读取候选记忆（包含群内多人及本群记忆）
        # -------------------------------------------------------------
        placeholders = ",".join("?" for _ in unique_scopes)
        query_sql = f"""
            SELECT id, scope, text, vector, created, ended, user_id, fact_type, category, target_id, target_name
            FROM memories
            WHERE scope IN ({placeholders}) AND namespace=? AND vector IS NOT NULL AND ended IS NULL
            ORDER BY COALESCE(ended, created) DESC LIMIT 200
        """
        params = list(unique_scopes) + [self._namespace]
        rows = self._run_db(lambda db: db.execute(query_sql, params).fetchall())

        if not rows:
            return ""

        # -------------------------------------------------------------
        # 4. 计算余弦相似度并打分筛选
        # -------------------------------------------------------------
        scored = []
        for row in rows:
            v_blob = row[3]
            if not v_blob:
                continue
            try:
                mem_vec = np.frombuffer(v_blob, dtype=np.float32)
                sim = float(np.dot(q_vec, mem_vec))
                if sim >= min_sim:
                    scored.append((sim, row))
            except Exception:
                continue

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        top_candidates = scored[:top_k]

        # -------------------------------------------------------------
        # 5. 结构化分类与实体归并（Mem0 单人单条精炼认知压缩）
        # -------------------------------------------------------------
        current_speaker_facts = []
        other_members_best: Dict[str, Tuple[float, str, str]] = {}  # uid -> (sim, display_name, concise_fact)
        group_facts = []
        bot_facts = []
        episodes = []

        seen_texts = set()
        for sim, r in top_candidates:
            scope = r[1]
            text = r[2].strip()
            fact_type = r[7] or "episode"
            target_id = str(r[9] or "").strip()
            target_name = r[10] or other_members.get(target_id, "") or target_id

            if text in seen_texts:
                continue
            seen_texts.add(text)

            if fact_type == "fact":
                # 当前互动发言者：保留最相关的 1-3 条事实
                if scope == f"user:{user_id_str}" or (target_id and target_id == user_id_str):
                    current_speaker_facts.append((sim, target_name, text))
                # 群内在场其他成员：按照 Mem0 精炼认知原则，每人只保留相关度最高的 1 句精炼认知（大幅节省 Token）
                elif scope.startswith("user:") or (target_id and target_id in other_members):
                    mid = target_id or scope.replace("user:", "")
                    display_name = other_members.get(mid, target_name or f"群友{mid}")
                    if mid not in other_members_best or sim > other_members_best[mid][0]:
                        other_members_best[mid] = (sim, display_name, text)
                elif scope.startswith("group:"):
                    group_facts.append((sim, target_name, text))
                elif scope == "agent:global":
                    bot_facts.append((sim, text))
                else:
                    current_speaker_facts.append((sim, target_name, text))
            else:
                episodes.append((sim, text))

        # -------------------------------------------------------------
        # 6. 贪心逐项打包算法 (Item-by-Item Greedy Packing)
        # 核心保证：只添加完整条目，超预算则整条舍弃，绝不切断句子！
        # -------------------------------------------------------------
        sections = []

        # 6.1 当前互动发言者事实（重点认知）
        if current_speaker_facts:
            lines = []
            header = "【关于当前对话用户 (发言者) 的事实记忆】：\n"
            cur_len = len(header)
            for _, name, t in current_speaker_facts:
                item = f"- {t}\n"
                if cur_len + len(item) <= max_prompt_chars:
                    lines.append(item)
                    cur_len += len(item)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        # 6.2 群内在场/被提及其他群友的简短认知（1人1句精炼速览，极低Token占用）
        if other_members_best:
            lines = []
            header = "【群内在场/被提及其他群友的简短认知（你在群里也认识他们）】：\n"
            cur_len = len(header)
            # 按相似度排序取前 3-4 位
            sorted_others = sorted(other_members_best.values(), key=lambda x: x[0], reverse=True)
            for _, mname, t in sorted_others[:4]:
                item = f"- {mname}：{t}\n"
                if cur_len + len(item) <= max_prompt_chars:
                    lines.append(item)
                    cur_len += len(item)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        # 6.3 本群共同话题与文化
        if group_facts:
            lines = []
            header = "【本群共同认知与话题】：\n"
            cur_len = len(header)
            for _, name, t in group_facts:
                item = f"- {t}\n"
                if cur_len + len(item) <= max_prompt_chars:
                    lines.append(item)
                    cur_len += len(item)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        # 6.4 Bot自身全局独立生活与状态记忆
        if bot_facts:
            lines = []
            header = "【你的真实世界经历与自我记忆】：\n"
            cur_len = len(header)
            for _, t in bot_facts:
                item = f"- {t}\n"
                if cur_len + len(item) <= max_prompt_chars:
                    lines.append(item)
                    cur_len += len(item)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        # 6.5 历史对话往事（完整对话引文）
        if episodes:
            lines = []
            header = "【相关历史往事（引文）】：\n"
            cur_len = len(header)
            for _, t in episodes:
                compact = " ".join(t.splitlines())
                item = f'"{compact}"\n'
                if cur_len + len(item) <= max_prompt_chars:
                    lines.append(item)
                    cur_len += len(item)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        if not sections:
            return ""

        result = RAG_PREFIX + "\n" + "\n\n".join(sections) + "\n"
        self._log(f"[MaiReply RAG] 成功召回长期记忆 scope={current_scope} 在场群友={len(other_members_best)}人 最终字数={len(result)}")
        return result
