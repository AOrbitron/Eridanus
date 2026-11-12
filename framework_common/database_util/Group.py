"""
群组消息管理器 - 数据库持久化版本
支持 SQLite 持久化存储 + 内存缓存

优化说明：
- add_to_group 写路径完全无锁：用 queue.SimpleQueue 替代 threading.Lock
- 后台线程复用同一个持久化 event loop，不再反复 new_event_loop()
- deque LRU 的 O(n) remove 改为 set 标记，不在热路径上遍历
- 缓存失效改为懒惰式：读取时校验版本号，不在写路径上遍历删除
- 批量写入改为 asyncio.sleep 驱动，减少 CPU 空转
"""
import json
import asyncio
import os
import queue
import time
import threading
from collections import defaultdict, deque
from threading import RLock
import aiosqlite
from developTools.utils.logger import get_logger

logger = get_logger()

DB_PATH = "data/dataBase/group_messages.db"

_db_initialized: bool = False


async def ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        await initialize_db()
        _db_initialized = True


async def initialize_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute("PRAGMA cache_size=10000;")
            await db.execute("PRAGMA temp_store=MEMORY;")
            await db.execute("PRAGMA busy_timeout=5000;")

            await db.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                user_id INTEGER,
                user_name TEXT,
                message TEXT,
                timestamp TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_group_id ON group_messages(group_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_group_created ON group_messages(group_id, created_at);")

            await db.commit()

    except Exception as e:
        logger.error(f"群消息数据库初始化失败: {e}")
        os.remove(DB_PATH)
        raise


class GroupMessageManager:
    """群组消息管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self.MAX_MESSAGES = 100
        self.MAX_GROUPS = 1000
        self.MAX_CACHE_ITEMS = 500

        self.BATCH_SIZE = 50          # 每次 flush 最多取多少条
        self.FLUSH_INTERVAL = 0.5     # flush 间隔（秒）

        # 内存缓存（读多写少，保留 RLock 保护读操作的一致性）
        self._rlock = RLock()
        self._messages_cache: dict[int, deque] = defaultdict(lambda: deque(maxlen=self.MAX_MESSAGES))
        self._group_order_set: set[int] = set()   # 仅用于判断是否已知群组

        # 预处理缓存：key -> (version, result)
        # version 与 _group_write_version[group_id] 比对，脏了就丢弃
        self._processed_cache: dict[tuple, tuple] = {}          # key -> (version, result)
        self._group_write_version: dict[int, int] = defaultdict(int)  # group_id -> write count

        # ---- 无锁写队列（核心优化） ----
        # SimpleQueue 在 CPython 里基于 collections.deque + threading.Lock 实现，
        # 但 put() 极轻量（GIL 保护 + 单次 append），远比 RLock 竞争代价低。
        # 关键：主协程/线程只调用 put_nowait，永不阻塞。
        self._pending_queue: queue.SimpleQueue = queue.SimpleQueue()

        self._running = True
        self._initialized = True

        self._start_background_tasks()

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def set_max_messages(self, max_messages: int):
        with self._rlock:
            self.MAX_MESSAGES = max_messages
            old_messages = dict(self._messages_cache)
            self._messages_cache = defaultdict(lambda: deque(maxlen=self.MAX_MESSAGES))
            for group_id, msgs in old_messages.items():
                new_deque = deque(maxlen=self.MAX_MESSAGES)
                new_deque.extend(msgs)
                self._messages_cache[group_id] = new_deque
            logger.info(f"群消息保留数量已更新为 {max_messages}")

    # ------------------------------------------------------------------
    # 后台线程（持久化 event loop，避免反复创建）
    # ------------------------------------------------------------------

    def _start_background_tasks(self):
        def background_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._background_loop())
            loop.close()

        self._worker_thread = threading.Thread(target=background_worker, daemon=True, name="gmm-bg")
        self._worker_thread.start()

    async def _background_loop(self):
        """持久化运行的后台协程，定期 flush 写队列"""
        await ensure_db_initialized()
        while self._running:
            try:
                await self._flush_pending_messages()
            except Exception as e:
                logger.error(f"后台 flush 错误: {e}")
            await asyncio.sleep(self.FLUSH_INTERVAL)
        # 退出前最后一次 flush
        try:
            await self._flush_pending_messages()
        except Exception:
            pass

    async def _flush_pending_messages(self):
        """从无锁队列批量取出并写入数据库"""
        if self._pending_queue.empty():
            return

        batch = []
        try:
            for _ in range(self.BATCH_SIZE):
                batch.append(self._pending_queue.get_nowait())
        except queue.Empty:
            pass

        if not batch:
            return

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.executemany(
                    """INSERT INTO group_messages (group_id, user_id, user_name, message, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    batch
                )
                await db.commit()
                logger.debug(f"批量写入 {len(batch)} 条消息到数据库")
        except Exception as e:
            logger.error(f"写入数据库失败: {e}")
            # 写回队列，保证不丢消息
            for row in batch:
                self._pending_queue.put_nowait(row)

    # ------------------------------------------------------------------
    # 核心写路径（极度轻量，不阻塞事件循环）
    # ------------------------------------------------------------------

    def add_to_group_fast(self, group_id: int, message):
        """
        无锁快速写入。

        内存缓存写入：deque.append 在 CPython 中由 GIL 保护，天然线程安全，
        无需额外锁。对于异步调用方（同一线程），更不存在竞争。

        数据库写入：put_nowait 到 SimpleQueue，后台线程批量消费。
        """
        # deque.append 是原子操作（CPython GIL），不需要锁
        self._messages_cache[group_id].append(message)

        # 版本号递增，使相关缓存在下次读取时失效（懒惰失效）
        # 用 int 加法，不需要锁（GIL 保护）
        self._group_write_version[group_id] = self._group_write_version[group_id] + 1

        # 仅做存在性记录，set.add 是 GIL 保护的原子操作
        self._group_order_set.add(group_id)

        # 入队到持久化队列（put_nowait 不阻塞）
        user_id = message.get('user_id', 0)
        user_name = message.get('user_name', '未知用户')
        msg_content = json.dumps(message.get('message', []), ensure_ascii=False)
        timestamp = message.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
        self._pending_queue.put_nowait((group_id, user_id, user_name, msg_content, timestamp))

    def add_to_group_sync(self, group_id: int, message):
        """同步添加消息（接口保持兼容）"""
        self.add_to_group_fast(group_id, message)

    async def add_to_group(self, group_id: int, message, delete_after: int = 50):
        """添加消息到群组（接口保持兼容）"""
        self.add_to_group_fast(group_id, message)
        logger.debug(f"消息已添加到群组 {group_id}")

    # ------------------------------------------------------------------
    # 读路径
    # ------------------------------------------------------------------

    async def get_group_messages(self, group_id: int, limit: int = 50):
        """获取群组消息（优先从内存，不足时从数据库补充）"""
        messages = list(self._messages_cache.get(group_id, []))

        if len(messages) < limit:
            try:
                await ensure_db_initialized()
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        """SELECT user_id, user_name, message, timestamp
                           FROM group_messages
                           WHERE group_id = ?
                           ORDER BY created_at DESC
                           LIMIT ?""",
                        (group_id, limit)
                    ) as cursor:
                        rows = await cursor.fetchall()

                        db_messages = []
                        for row in rows:
                            try:
                                msg_content = json.loads(row[2]) if row[2] else []
                                db_messages.append({
                                    'user_id': row[0],
                                    'user_name': row[1],
                                    'message': msg_content,
                                    'timestamp': row[3]
                                })
                            except Exception:
                                continue

                        if db_messages and len(messages) == 0:
                            cache_deque = self._messages_cache[group_id]
                            for msg in reversed(db_messages):
                                cache_deque.append(msg)
                            self._group_order_set.add(group_id)
                            logger.debug(f"从数据库加载 {len(db_messages)} 条消息到群 {group_id} 的内存缓存")

                        if db_messages:
                            messages = list(reversed(db_messages))[:limit]
            except Exception as e:
                logger.error(f"从数据库读取消息失败: {e}")

        messages = list(reversed(messages))[:limit]
        return messages

    async def get_group_messages_raw(self, group_id: int, limit: int = 50):
        return await self.get_group_messages(group_id, limit)

    # ------------------------------------------------------------------
    # 消息预处理
    # ------------------------------------------------------------------

    def _build_context_info(self, messages):
        context_info = {
            'participants': set(),
            'message_count': len(messages),
            'activities': []
        }
        for msg in messages[:10]:
            user_name = msg.get('user_name', '未知用户')
            user_id = msg.get('user_id', '')
            if len(context_info['participants']) < 10:
                context_info['participants'].add(f"{user_name}(ID:{user_id})")
            for msg_part in msg.get("message", []):
                if isinstance(msg_part, dict) and msg_part.get('type') == 'text':
                    text = msg_part.get('text', '').strip()
                    if '?' in text or '？' in text:
                        context_info['activities'].append('提问')
                        break
        return context_info

    async def _process_single_message(self, raw_message, index, context_info, standard, bot, event, include_images=True):
        user_name = raw_message.get('user_name', '未知用户')
        user_id = raw_message.get('user_id', '')
        timestamp = raw_message.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))

        position_desc = "最新" if index == 0 else f"第{index + 1}条"
        context_prompt = (
            f"【群聊上下文-{position_desc}消息】"
            f"发送者：{user_name}(ID:{user_id}) | "
            f"时间：{timestamp}"
        )

        message_copy = json.loads(json.dumps(raw_message))
        message_copy["message"] = [
            {"type": "text", "text": "艾特你了"} if (
                isinstance(item, dict) and
                item.get('type') == 'text' and
                not item.get('text', '').strip()
            ) else item
            for item in message_copy["message"]
        ]

        if not include_images:
            filtered_message = []
            for item in message_copy["message"]:
                if isinstance(item, dict) and ("image" in item or "mface" in item):
                    filtered_message.append({"text": "[图片]"})
                else:
                    filtered_message.append(item)
            message_copy["message"] = filtered_message

        message_copy["message"].insert(0, {"text": f"{context_prompt}。"})

        if standard == "gemini":
            from run.ai_llm.service.aiReplyHandler.gemini import gemini_prompt_elements_construct
            return await gemini_prompt_elements_construct(message_copy["message"], bot=bot, event=event)
        elif standard == "new_openai":
            from run.ai_llm.service.aiReplyHandler.openai import prompt_elements_construct, prompt_elements_construct_old_version
            return await prompt_elements_construct(message_copy["message"], bot=bot, event=event)
        else:
            from run.ai_llm.service.aiReplyHandler.openai import prompt_elements_construct, prompt_elements_construct_old_version
            return await prompt_elements_construct_old_version(message_copy["message"], bot=bot, event=event)

    def _format_final_result(self, processed_list, context_info, standard):
        participants_list = list(context_info['participants'])
        activities = list(set(context_info['activities'])) if context_info['activities'] else ['正常聊天']

        group_summary = (
            "================== 群聊上下文 开始 ==================\n"
            f"【群聊概况】参与人数：{len(participants_list)}人 | "
            f"消息总数：{context_info['message_count']}条 | "
            f"主要参与者：{', '.join(participants_list[:3])} | "
            f"活动类型：{', '.join(activities[:2])}"
        )
        context_end = "================== 群聊上下文 结束 =================="

        if standard == "gemini":
            all_parts = []
            for entry in processed_list:
                if entry.get('role') == 'user':
                    all_parts.extend(entry.get('parts', []))
            all_parts.insert(0, {"text": f"{group_summary}"})
            all_parts.append({"text": f"{context_end}\n以上是群聊历史消息上下文，仅作为背景信息使用，请专注于下次的提问信息，无需回答历史消息中的问题"})
            return [
                {"role": "user", "parts": all_parts},
                {"role": "model", "parts": [{"text": "好的，我已了解群聊上下文，会根据之后的用户消息进行回复。"}]}
            ]
        else:
            all_parts = []
            for entry in processed_list:
                if entry.get('role') == 'user' and isinstance(entry.get('content'), list):
                    all_parts.extend(entry['content'])
            if all_parts:
                all_parts.insert(0, {"type": "text", "text": f"{group_summary}"})
                all_parts.append({"type": "text", "text": f"{context_end}\n以上是群聊历史消息上下文，仅作为背景信息使用，请专注于下次的提问信息，无需回答历史消息中的问题"})
                return [
                    {"role": "user", "content": all_parts},
                    {"role": "assistant", "content": "好的，我已了解群聊上下文，会根据之后的用户消息进行回复。"}
                ]
            else:
                return [
                    {"role": "user", "content": f"{group_summary}\n{context_end}\n以上是群聊历史消息上下文，仅作为背景信息使用，请专注于下次的提问信息，无需回答历史消息中的问题"},
                    {"role": "assistant", "content": "好的，我已了解群聊上下文，会根据之后的用户消息进行回复。"}
                ]

    async def _preprocess_group_messages(self, group_id: int, standard: str = "gemini",
                                         data_length: int = 20, bot=None, event=None, include_images=True):
        try:
            messages = await self.get_group_messages(group_id, data_length)
            if not messages:
                logger.debug(f"群组 {group_id} 消息为空")
                return []

            actual_length = min(data_length, len(messages))
            messages = messages[-actual_length:] if len(messages) > actual_length else messages
            messages = list(reversed(messages))

            context_info = self._build_context_info(messages)
            processed_list = []
            for i, raw_message in enumerate(messages):
                try:
                    processed_msg = await self._process_single_message(
                        raw_message, i, context_info, standard, bot, event, include_images
                    )
                    if processed_msg:
                        processed_list.append(processed_msg)
                except Exception as e:
                    logger.error(f"处理单条消息失败: {e}")
                    continue

            return self._format_final_result(processed_list, context_info, standard)
        except Exception as e:
            logger.error(f"预处理失败: {e}")
            return []

    async def get_last_20_and_convert_to_prompt(self, group_id: int, data_length=20,
                                                prompt_standard="gemini", bot=None, event=None, include_images=True):
        """
        获取转换后的 prompt（懒惰版本缓存）。

        不再在写路径上删除缓存项，改为读取时检查版本号。
        写入次数变化 => 缓存过期 => 重新计算并存储新版本。
        """
        cache_key = (group_id, prompt_standard, data_length, include_images)
        current_version = self._group_write_version[group_id]

        cached = self._processed_cache.get(cache_key)
        if cached is not None:
            cached_version, result = cached
            if cached_version == current_version:
                return result

        result = await self._preprocess_group_messages(group_id, prompt_standard, data_length, bot, event, include_images)

        if result:
            # 简单 LRU：超出上限时随机驱逐一个旧项（O(1) amortized）
            if len(self._processed_cache) >= self.MAX_CACHE_ITEMS:
                evict_key = next(iter(self._processed_cache))
                del self._processed_cache[evict_key]
            self._processed_cache[cache_key] = (current_version, result)

        return result

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def clear_group_messages(self, group_id: int):
        """清除群组消息（内存 + 数据库）"""
        cache_deque = self._messages_cache.get(group_id)
        if cache_deque is not None:
            cache_deque.clear()
        self._group_order_set.discard(group_id)
        self._group_write_version[group_id] = self._group_write_version[group_id] + 1

        # 清除预处理缓存中该群的条目
        expired = [k for k in self._processed_cache if k[0] == group_id]
        for k in expired:
            del self._processed_cache[k]

        try:
            await ensure_db_initialized()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM group_messages WHERE group_id = ?", (group_id,))
                await db.commit()
        except Exception as e:
            logger.error(f"清除数据库消息失败: {e}")

        logger.info(f"已清除 group_id={group_id} 的所有消息")

    async def clear_all_group_cache(self):
        """清除所有数据（内存 + 数据库）"""
        self._messages_cache.clear()
        self._group_order_set.clear()
        self._processed_cache.clear()
        self._group_write_version.clear()

        try:
            await ensure_db_initialized()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM group_messages")
                await db.commit()
        except Exception as e:
            logger.error(f"清除数据库失败: {e}")

        logger.info("所有群组数据已清除")
        return True

    async def cleanup_old_messages(self):
        """清理数据库中超出限制的旧消息"""
        try:
            await ensure_db_initialized()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT DISTINCT group_id FROM group_messages") as cursor:
                    groups = await cursor.fetchall()
                for (group_id,) in groups:
                    await db.execute("""
                        DELETE FROM group_messages
                        WHERE group_id = ? AND id NOT IN (
                            SELECT id FROM group_messages
                            WHERE group_id = ?
                            ORDER BY created_at DESC
                            LIMIT ?
                        )
                    """, (group_id, group_id, self.MAX_MESSAGES))
                await db.commit()
                logger.debug("已清理超出限制的旧消息")
        except Exception as e:
            logger.error(f"清理旧消息失败: {e}")

    # ------------------------------------------------------------------
    # 统计 & 关闭
    # ------------------------------------------------------------------

    def get_cache_stats(self):
        total_messages = sum(len(msgs) for msgs in self._messages_cache.values())
        return {
            "total_groups": len(self._messages_cache),
            "total_messages_in_cache": total_messages,
            "cached_prompts": len(self._processed_cache),
            "pending_writes": self._pending_queue.qsize(),
            "max_messages_per_group": self.MAX_MESSAGES
        }

    def shutdown(self):
        self._running = False
        if hasattr(self, '_worker_thread'):
            self._worker_thread.join(timeout=5.0)


# ======================= 全局单例实例 =======================
_manager = None


def get_manager():
    global _manager
    if _manager is None:
        _manager = GroupMessageManager()
    return _manager


# ======================= 外部接口函数（保持兼容） =======================

async def add_to_group(group_id: int, message, delete_after: int = 50):
    manager = get_manager()
    await manager.add_to_group(group_id, message, delete_after)


async def get_group_messages(group_id: int, limit: int = 50):
    manager = get_manager()
    return await manager.get_group_messages(group_id, limit)


async def get_last_20_and_convert_to_prompt(group_id: int, data_length=20, prompt_standard="gemini",
                                            bot=None, event=None, include_images=True):
    manager = get_manager()
    return await manager.get_last_20_and_convert_to_prompt(group_id, data_length, prompt_standard, bot, event, include_images)


async def clear_group_messages(group_id: int):
    manager = get_manager()
    await manager.clear_group_messages(group_id)


async def clear_all_group_cache():
    manager = get_manager()
    return await manager.clear_all_group_cache()


def get_cache_stats():
    manager = get_manager()
    return manager.get_cache_stats()