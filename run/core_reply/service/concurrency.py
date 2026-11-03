"""
concurrency.py
并发控制器 —— 全局并发信号量 + 消息合并窗口 + 会话任务抢占
防止同一会话同时处理多条消息导致的回复混乱

抢占逻辑（"真人换频道"模式）：
  新消息到来时，若该会话有正在处理的 Task，直接 cancel() 它。
  同时将"上一条未完成的消息 + 新消息"合并，作为新请求的输入，
  模拟真人看到新消息后重新思考的状态。
"""

import asyncio
import time
from typing import Dict, Optional, Tuple

from framework_common.database_util.RedisCacheManager import create_custom_cache_manager


class ConcurrencyController:

    def __init__(self, config):
        self.cfg = config
        ccfg = config.core_reply.config.get("concurrency", {})
        max_concurrent: int = int(ccfg.get("max_concurrent", 20))
        self.merge_window_ms: int = int(ccfg.get("message_merge_window_ms", 1200))
        self.lock_timeout: int = int(ccfg.get("lock_timeout", 30))

        # 全局并发信号量
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # 消息合并窗口：session_key -> {"text": str, "event": asyncio.Event}
        self._pending: Dict[str, dict] = {}
        self._pending_lock = asyncio.Lock()

        # 会话任务抢占：session_key -> (Task, 正在处理的原始消息文本)
        # Task 是当前正在处理该会话的 asyncio.Task
        # 文本用于新消息到来时拼接"旧问题+新消息"
        self._active_tasks: Dict[str, Tuple[asyncio.Task, str]] = {}
        self._task_lock = asyncio.Lock()

    async def acquire_global(self) -> None:
        """获取全局并发槽（阻塞等待）"""
        await self._semaphore.acquire()

    def release_global(self) -> None:
        """释放全局并发槽"""
        self._semaphore.release()

    async def merge_or_process(self, session_key: str, text: str) -> Optional[str]:
        if self.merge_window_ms <= 0:
            return text

        window_sec = self.merge_window_ms / 1000.0
        event = asyncio.Event()

        async with self._pending_lock:
            if session_key in self._pending:
                # 【关键修复 1】：把直接覆盖改为追加合并！
                old_text = self._pending[session_key]["text"]
                merged_text = f"{old_text}\n{text}" if old_text else text

                self._pending[session_key]["event"].set()
                new_event = asyncio.Event()
                # 存入合并后的文本
                self._pending[session_key] = {"text": merged_text, "event": new_event}
                local_event = new_event
            else:
                self._pending[session_key] = {"text": text, "event": event}
                local_event = event

        try:
            await asyncio.wait_for(local_event.wait(), timeout=window_sec)
            return None
        except asyncio.TimeoutError:
            async with self._pending_lock:
                pending = self._pending.get(session_key)
                if pending and pending.get("event") is local_event:
                    final_text = pending["text"]
                    del self._pending[session_key]
                    return final_text
                return None

    # ------------------------------------------------------------------ 任务抢占

    async def preempt_and_register(
        self, session_key: str, new_text: str, new_task: asyncio.Task
    ) -> str:
        """
        核心抢占方法。调用时机：新消息通过合并窗口、准备真正开始处理之前。

        行为：
        1. 若该会话有正在运行的旧 Task → cancel() 它（旧任务被取消后其结果会被丢弃）
        2. 将旧消息文本与新消息文本合并（旧问题\n新消息），让 bot 知道上下文
        3. 注册新 Task 为当前活跃任务

        返回：合并后的最终文本（调用方用这个文本去构建 prompt）
        """
        async with self._task_lock:
            merged_text = new_text
            if session_key in self._active_tasks:
                old_task, old_text = self._active_tasks[session_key]
                if not old_task.done():
                    old_task.cancel()
                    # 合并：把旧问题带进来，让 bot 知道之前在说什么
                    if old_text and old_text != new_text:
                        merged_text = f"{old_text}\n{new_text}"
            self._active_tasks[session_key] = (new_task, merged_text)

            return merged_text

    async def unregister_task(self, session_key: str, task: asyncio.Task) -> None:
        """任务结束时注销（只注销自己，防止覆盖后来注册的新任务）"""
        async with self._task_lock:
            entry = self._active_tasks.get(session_key)
            if entry and entry[0] is task:
                del self._active_tasks[session_key]

    def has_active_task(self, session_key: str) -> bool:
        """判断某个会话当前是否有正在处理的任务"""
        entry = self._active_tasks.get(session_key)
        return entry is not None and not entry[0].done()