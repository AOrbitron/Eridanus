# -*- coding: utf-8 -*-
"""Greedy-packed, multi-scope retrieval supporting:
1. Group multi-speaker concise recognition
2. Universal user nickname & alias dynamic resolution (identifying who everyone is talking about)
3. Speaker profile/background knowledge unconditional injection (like memory slots)
4. Zero-truncation greedy item-by-item prompt packing
"""
import asyncio
import hashlib
import json
import re
import time
from typing import List, Dict, Optional, Tuple, Any, Set

import numpy as np

from framework_common.utils.system_logger import get_logger

logger = get_logger(__name__)

RAG_PREFIX = "\n\n【长期记忆检索 (RAG Memory)】："

ALIAS_PATTERNS = [
    re.compile(r'(?:外号|别名|绰号|自称|别称|简称|又叫|也叫|人称|被称作|被称为|被叫作|大家都叫[我TA他她]?)[：:\s是为叫]*[“"\'‘]([^’”"\'\s,，。；;\n\r]{1,16})[’”"\'’]'),
    re.compile(r'(?:外号|别名|绰号|自称|别称|简称|又叫|也叫|人称|大家都叫[我TA他她]?)[：:\s是为叫]+([^’”"\'\s,，。；;\n\r]{1,16})'),
    re.compile(r'[“"\'‘]([^’”"\'\s,，。；;\n\r]{1,16})[’”"\'’]\s*(?:这一特定称号|这一外号|这一称号|这个外号|这个别名|这一别称)'),
]

EXCLUDE_ALIAS_WORDS = {'用户', '群友', '机器人', 'Bot', 'bot', '管理员', '主人', '自己', '某人', '大家'}


def extract_aliases_from_text(text: str) -> List[str]:
    """从文本中抽取可能的用户外号、别名与称谓。"""
    if not text:
        return []
    found = set()
    for p in ALIAS_PATTERNS:
        for m in p.finditer(text):
            val = m.group(1).strip()
            val = re.sub(r'^[，。、“”"\'‘]+|[，。、“”"\'’]+$', '', val).strip()
            if val and 2 <= len(val) <= 12 and val not in EXCLUDE_ALIAS_WORDS:
                found.add(val)
    return list(found)


class EpisodeRetrieval:
    """负责跨会话多作用域隔离召回、群聊多成员感知、用户外号识别与背景事实注入"""

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
        query_text = (query or "").strip()

        # -------------------------------------------------------------
        # 1. 作用域解析与群聊多发言人（Multi-Speaker）感知
        # -------------------------------------------------------------
        other_members: Dict[str, str] = {}  # other_uid -> name

        if not is_group:
            # 私聊环境：自身私聊范围 + 该用户档案 + Bot全局自我记忆
            target_scopes = [current_scope, f"user:{user_id_str}", "agent:global"]
        else:
            # 群聊环境：
            # (1) 解析近期群聊滑动窗口中的在场其他活跃群友
            if isinstance(recent_context, list):
                for item in reversed(recent_context):
                    if isinstance(item, dict):
                        uid = str(item.get("user_id") or "").strip()
                        name = str(item.get("sender") or "").strip()
                        if uid and uid != user_id_str and uid != "bot" and name != "Bot":
                            if uid not in other_members:
                                other_members[uid] = name

            # (2) 从当前 query 中提取被 @ 或被提及的群成员
            at_matches = re.findall(r"(?:qq=|[at@])(\d{5,12})", query_text)
            for at_uid in at_matches:
                if at_uid != user_id_str:
                    other_members.setdefault(at_uid, f"群友{at_uid}")

            # (3) 补充拉取本群沉淀过事实的知名活跃群成员
            def fetch_known_members(db):
                return db.execute("""
                    SELECT DISTINCT target_id, target_name FROM memories
                    WHERE scope=? AND fact_type='fact' AND target_id IS NOT NULL AND target_id != ?
                    LIMIT 6
                """, (current_scope, user_id_str)).fetchall()

            try:
                db_members = self._run_db(fetch_known_members)
                for mid, mname in db_members:
                    if mid and str(mid) != user_id_str:
                        other_members.setdefault(str(mid), mname or f"群友{mid}")
            except Exception:
                pass

        # -------------------------------------------------------------
        # 1.2 通用外号与别名知识库解析（识别“大家说的是谁”）
        # 核心保证：从长期事实与 memory_slots 中动态提取已知外号，并建立 alias -> user_id 映射
        # -------------------------------------------------------------
        known_alias_map: Dict[str, Dict[str, Any]] = {}  # alias_lower -> {alias, user_id, user_name, text}
        resolved_entities_in_query: List[Dict[str, Any]] = []

        def fetch_alias_candidate_facts(db):
            if is_group:
                return db.execute("""
                    SELECT target_id, target_name, text, category FROM memories
                    WHERE (scope = ? OR scope LIKE 'user:%' OR (target_id IS NOT NULL AND target_id != ''))
                      AND fact_type = 'fact'
                      AND ended IS NULL
                      AND (
                        category IN ('profile', 'identity', 'alias', 'nickname')
                        OR text LIKE '%外号%' OR text LIKE '%别名%' OR text LIKE '%称呼%' OR text LIKE '%自称%'
                      )
                    ORDER BY created DESC LIMIT 50
                """, (current_scope,)).fetchall()
            else:
                return db.execute("""
                    SELECT target_id, target_name, text, category FROM memories
                    WHERE (scope = ? OR scope = ? OR target_id = ?)
                      AND fact_type = 'fact'
                      AND ended IS NULL
                    ORDER BY created DESC LIMIT 20
                """, (current_scope, f"user:{user_id_str}", user_id_str)).fetchall()

        try:
            cand_rows = self._run_db(fetch_alias_candidate_facts)
            for t_id, t_name, t_text, t_cat in cand_rows:
                u_id = str(t_id or "").strip()
                if not u_id and t_cat == 'profile':
                    u_id = user_id_str
                u_name = t_name or other_members.get(u_id, "") or (f"用户{u_id}" if u_id else "")
                aliases = extract_aliases_from_text(t_text)
                for a in aliases:
                    a_key = a.lower()
                    if a_key not in known_alias_map and u_id:
                        known_alias_map[a_key] = {
                            "alias": a,
                            "user_id": u_id,
                            "user_name": u_name,
                            "fact_text": t_text.strip(),
                        }
        except Exception as exc:
            self._warn(f"[MaiReply RAG] 提取外号知识库失败: {exc}")

        # 检查提问 query 或上下文是否包含已知外号（“知道大家说的是谁”）
        matched_user_ids = set()
        for a_key, a_info in known_alias_map.items():
            alias_word = a_info["alias"]
            if alias_word in query_text or (len(alias_word) >= 2 and a_key in query_text.lower()):
                m_uid = a_info["user_id"]
                if m_uid not in matched_user_ids:
                    matched_user_ids.add(m_uid)
                    resolved_entities_in_query.append(a_info)
                    if m_uid != user_id_str:
                        other_members.setdefault(m_uid, a_info["user_name"] or f"群友{m_uid}")

        # 组装群聊检索目标作用域
        if is_group:
            target_scopes = [current_scope, f"user:{user_id_str}", "agent:global"]
            for o_uid in list(other_members.keys())[:5]:
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
        # 1.5 无条件背景事实召回 (Background Identity, Alias & Profile Facts)
        # 核心保证：即使 query 没有命中任何关键词，用户的外号/昵称、基础档案也像 memory_slots 一样无条件作为背景知识注入！
        # -------------------------------------------------------------
        current_speaker_facts = []
        other_members_best: Dict[str, Tuple[float, str, str]] = {}  # uid -> (sim, display_name, concise_fact)
        group_facts = []
        bot_facts = []
        episodes = []
        seen_texts = set()

        if user_id_str:
            def fetch_user_background_facts(db):
                return db.execute("""
                    SELECT id, scope, text, created, ended, user_id, fact_type, category, target_id, target_name
                    FROM memories
                    WHERE (scope = ? OR (target_id = ? AND target_id != ''))
                      AND namespace = ?
                      AND fact_type = 'fact'
                      AND ended IS NULL
                    ORDER BY 
                      CASE 
                        WHEN category IN ('profile', 'identity', 'alias', 'nickname') THEN 0 
                        WHEN category IN ('preference', 'relationship') THEN 1
                        ELSE 2 
                      END,
                      created DESC
                    LIMIT 8
                """, (f"user:{user_id_str}", user_id_str, self._namespace)).fetchall()

            try:
                bg_rows = self._run_db(fetch_user_background_facts)
                for r in bg_rows:
                    t = r[2].strip()
                    t_name = r[9] or user_id_str
                    if t and t not in seen_texts:
                        seen_texts.add(t)
                        current_speaker_facts.append((1.0, t_name, t))
            except Exception as exc:
                self._warn(f"[MaiReply RAG] 读取用户背景事实失败: {exc}")

            # 若 memories 暂无该用户的事实记录，尝试从持久化 memory_slots 桥接基础档案（如外号/常住地）
            if not current_speaker_facts:
                try:
                    def fetch_slot_profile(db):
                        return db.execute("""
                            SELECT slot_id, category, content FROM memory_slots
                            WHERE owner_type='user' AND owner_id=? AND slot_id IN (1, 6) AND content != ''
                            ORDER BY slot_id ASC
                        """, (user_id_str,)).fetchall()

                    slot_rows = []
                    try:
                        slot_rows = self._run_db(fetch_slot_profile)
                    except Exception:
                        pass

                    if not slot_rows:
                        import os, sqlite3
                        imp_path = "data/dataBase/impression_store.db"
                        if os.path.exists(imp_path):
                            with sqlite3.connect(imp_path) as idb:
                                slot_rows = idb.execute("""
                                    SELECT slot_id, category, content FROM memory_slots
                                    WHERE owner_type='user' AND owner_id=? AND slot_id IN (1, 6) AND content != ''
                                    ORDER BY slot_id ASC
                                """, (user_id_str,)).fetchall()

                    for s_id, s_cat, s_content in slot_rows:
                        s_text = s_content.strip()
                        if s_text and s_text not in seen_texts:
                            seen_texts.add(s_text)
                            current_speaker_facts.append((0.95, user_id_str, f"[{s_cat}] {s_text}"))
                except Exception:
                    pass

        # 群聊环境下，拉取其他在场/被提及/外号命中的群成员基础档案与外号
        if is_group and other_members:
            for o_uid in list(other_members.keys())[:5]:
                def fetch_other_bg(db, uid=o_uid):
                    return db.execute("""
                        SELECT target_id, target_name, text FROM memories
                        WHERE (scope = ? OR (target_id = ? AND target_id != ''))
                          AND namespace = ?
                          AND fact_type = 'fact'
                          AND ended IS NULL
                        ORDER BY 
                          CASE WHEN category IN ('profile', 'identity', 'alias', 'nickname') THEN 0 ELSE 1 END,
                          created DESC
                        LIMIT 1
                    """, (f"user:{uid}", uid, self._namespace)).fetchall()
                try:
                    o_rows = self._run_db(fetch_other_bg)
                    for _, t_name, t_text in o_rows:
                        t_text = t_text.strip()
                        if t_text and o_uid not in other_members_best and t_text not in seen_texts:
                            seen_texts.add(t_text)
                            display_name = other_members.get(o_uid, t_name or f"群友{o_uid}")
                            other_members_best[o_uid] = (0.85, display_name, t_text)
                except Exception:
                    pass

        # -------------------------------------------------------------
        # 2. 生成 Query Embedding (动态语义检索)
        # -------------------------------------------------------------
        q_vec = None
        if query_text:
            cache_ttl = float(cfg.get("query_cache_seconds", 300.0))
            max_cache_size = int(cfg.get("query_cache_size", 256))

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

        # -------------------------------------------------------------
        # 3. 从数据库读取语义候选记忆
        # -------------------------------------------------------------
        top_candidates = []
        if q_vec is not None:
            placeholders = ",".join("?" for _ in unique_scopes)
            query_sql = f"""
                SELECT id, scope, text, vector, created, ended, user_id, fact_type, category, target_id, target_name
                FROM memories
                WHERE scope IN ({placeholders}) AND namespace=? AND vector IS NOT NULL AND ended IS NULL
                ORDER BY COALESCE(ended, created) DESC LIMIT 200
            """
            params = list(unique_scopes) + [self._namespace]
            rows = self._run_db(lambda db: db.execute(query_sql, params).fetchall())

            if rows:
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

                scored.sort(key=lambda x: x[0], reverse=True)
                top_candidates = scored[:top_k]

        # -------------------------------------------------------------
        # 4. 结构化分类与实体归并
        # -------------------------------------------------------------
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
                # 当前互动发言者
                if scope == f"user:{user_id_str}" or (target_id and target_id == user_id_str):
                    current_speaker_facts.append((sim, target_name, text))
                # 群内其他成员（每人保留相似度最高的1句精炼认知，节省Token）
                elif scope.startswith("user:") or (target_id and target_id in other_members):
                    mid = target_id if (target_id and target_id in other_members) else scope.replace("user:", "")
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
        # 5. 贪心逐项打包算法 (Item-by-Item Greedy Packing)
        # 核心保证：只添加完整条目，超预算则整条舍弃，绝不切断句子！
        # -------------------------------------------------------------
        sections = []

        # 5.0 群成员外号与称呼映射（明确大家说的是谁）
        if resolved_entities_in_query:
            lines = []
            header = "【已知群成员外号与称谓映射（明确“大家说的是谁”）】：\n"
            cur_len = len(header)
            for item_info in resolved_entities_in_query:
                alias = item_info["alias"]
                u_id = item_info["user_id"]
                u_name = item_info["user_name"] or f"群友{u_id}"
                line_str = f"- 外号/称呼【{alias}】对应用户：【{u_name}】(ID: {u_id})\n"
                if cur_len + len(line_str) <= max_prompt_chars:
                    lines.append(line_str)
                    cur_len += len(line_str)
                else:
                    break
            if lines:
                sections.append(header + "".join(lines).strip())

        # 5.1 当前互动发言者事实（包含无条件背景外号/档案及相关检索事实）
        if current_speaker_facts:
            lines = []
            header = "【关于当前对话用户 (发言者) 的事实记忆与背景认知】：\n"
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

        # 5.2 群内在场/被提及其他群友的简短认知（1人1句精炼速览，极低Token占用）
        if other_members_best:
            lines = []
            header = "【群内其他在场/被提及群友的认知与外号】：\n"
            cur_len = len(header)
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

        # 5.3 本群共同认知与话题
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

        # 5.4 Bot自身全局真实经验与近期状态足迹
        if bot_facts:
            lines = []
            header = "【你自身真实世界经历与自我记忆】：\n"
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

        # 5.5 历史对话片段（近期对话原型）
        if episodes:
            lines = []
            header = "【相关历史对话片段（参考）】：\n"
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
        self._log(f"[MaiReply RAG] 成功召回长记忆: scope={current_scope} 在场群友={len(other_members_best)}人 注入总字数={len(result)}")
        return result
