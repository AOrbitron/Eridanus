"""Import the release files in a fresh process, without the developer worktree."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseImportTests(unittest.TestCase):
    def run_child(self, source):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-I', '-c',
                 'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + ');\n' + source],
                cwd=directory, capture_output=True, text=True, encoding='utf-8',
                env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        return result.stdout

    def test_trigger_and_both_new_modules_import_without_worktree_fallback(self):
        output = self.run_child('''import importlib
from pathlib import Path
for name in ('message_identity', 'user_profile', 'trigger'):
    module = importlib.import_module('run.core_reply.service.' + name)
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.path[0]).resolve())
    print('IMPORT_OK', name)
''')
        self.assertIn('IMPORT_OK trigger', output)

    def test_complete_main_and_reply_engine_import(self):
        output = self.run_child('''from unittest.mock import patch
from framework_common.database_util.RedisCacheManager import RedisCacheManager
# Do not contact Redis or auto-start services during an import smoke test.
with patch.object(RedisCacheManager, '_init_connection', lambda self: None):
    import run.core_reply.main as entry
    from run.core_reply.service.reply_engine import ReplyEngine
    assert callable(entry.main)
    print('MAIN_IMPORT_OK', entry.__file__)
    print('ENGINE_IMPORT_OK', ReplyEngine.__module__)
''')
        self.assertIn('MAIN_IMPORT_OK', output)
        self.assertIn('ENGINE_IMPORT_OK', output)

    def test_registered_group_and_private_handlers_reach_reply_backend(self):
        output = self.run_child('''import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from framework_common.database_util.RedisCacheManager import RedisCacheManager
with patch.object(RedisCacheManager, '_init_connection', lambda self: None):
    import run.core_reply.main as entry
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import At, Text
from developTools.message.message_chain import MessageChain

async def exercise():
    handlers = {}
    def on(event_type):
        def register(callback):
            handlers[event_type] = callback
            return callback
        return register
    bot = NS(id=9, on=on, logger=Mock(), send=AsyncMock())
    cfg = NS(core_reply=NS(config={'enable': True, 'trigger': {'prefix': []},
             'trigger_llm': {'enable': False, 'whitelist_enabled': False}}),
             common_config=NS(basic_config={'bot': 'fixture-bot'}))
    context = Mock()
    async def reply(bot, event, text, **kwargs):
        await bot.send(event, 'fixture-reply:' + text)
    engine = NS(context=context, emotion=None, handle=AsyncMock(side_effect=reply),
                rag_memory=NS(allowed=lambda gid: False),
                impression_updater=NS(is_group_memory_enabled=lambda gid: False))
    checker = entry.TriggerChecker(cfg, context, None)
    try:
        with patch.object(entry, 'ReplyEngine', return_value=engine), \\
             patch.object(entry, 'TriggerChecker', return_value=checker), \\
             patch.object(entry, 'ProactiveService'), patch.object(entry, 'FollowUpService'):
            entry.main(bot, cfg)
            assert GroupMessageEvent in handlers and PrivateMessageEvent in handlers
            group = NS(group_id=42, user_id=7, pure_text='hello',
                       sender=NS(card='member', nickname='member'),
                       message_chain=MessageChain([At(qq=9), Text('hello')]))
            private = NS(user_id=7, pure_text='hello',
                         message_chain=MessageChain([Text('hello')]))
            await handlers[GroupMessageEvent](group)
            await handlers[PrivateMessageEvent](private)
            await asyncio.sleep(0)
            assert engine.handle.await_count == 2
            assert bot.send.await_count == 2
            print('GROUP_AND_PRIVATE_HANDLERS_OK: mocked reply backend sent two replies')
    finally:
        await checker.http_client.aclose()
asyncio.run(exercise())
''')
        self.assertIn('GROUP_AND_PRIVATE_HANDLERS_OK', output)

    def test_reply_injects_knowledge_independently_of_legacy_memory(self):
        output = self.run_child('''import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from framework_common.database_util.RedisCacheManager import RedisCacheManager
with patch.object(RedisCacheManager, '_init_connection', lambda self: None):
    from run.core_reply.service.reply_engine import ReplyEngine
    from run.core_reply.service.rag_memory import RAGMemory
    from run.core_reply.service.prompt_builder import PromptBuilder

async def exercise():
    engine = object.__new__(ReplyEngine)
    engine.cfg = NS(core_reply=NS(config={'skills': {'enable': False}, 'tts': {}, 'trigger_llm': {'api_key': ''}}))
    engine.emotion = NS(get_mood=lambda: '平静', get_score=lambda: 0)
    engine.prompt_builder = PromptBuilder(engine.cfg, engine.emotion)
    engine._get_user_name = AsyncMock(return_value='用户')
    engine._get_bot_name = AsyncMock(return_value='测试Bot')
    engine._get_group_name = AsyncMock(return_value='测试群')
    engine.is_master = Mock(return_value=False)
    engine.concurrency = NS(
        merge_or_process=AsyncMock(return_value='管理员怎么设置'),
        preempt_and_register=AsyncMock(return_value='管理员怎么设置'),
        acquire_global=AsyncMock(), unregister_task=AsyncMock(), release_global=Mock(),
    )
    engine.context = Mock(
        acquire_lock=AsyncMock(return_value=True), get_session_history=Mock(return_value=[]),
        get_group_user_session_context=Mock(return_value=[]), build_group_context_snippet=Mock(return_value=''),
        get_global_memory=Mock(return_value='旧版全局记忆'), get_user_memory=Mock(return_value='旧版用户记忆'),
        get_effective_user_memory_mode=Mock(return_value='slots'),
        get_effective_group_memory_mode=Mock(return_value='slots'),
        get_group_memory_slots=Mock(return_value='旧版群记忆'), get_recent_speaker_memories=Mock(return_value=[]),
    )
    engine.llm = NS(chat=AsyncMock(return_value='测试回复'))
    engine.processor = NS(process=lambda text: [text], send_with_delay=AsyncMock())
    engine.impression_updater = Mock(is_group_memory_enabled=Mock(return_value=False))
    engine.audit_system = Mock()
    memory = object.__new__(RAGMemory)
    memory.enable = True
    memory.cfg = {'group': {'whitelist_enabled': True, 'whitelist': [42]}}
    memory.recall = AsyncMock(return_value='\\n\\n【长期记忆】\\n已归档对话')
    memory.record_turn = AsyncMock()
    knowledge = '\\n\\n【知识库参考资料】\\n> 管理员手册含原文 {bot_name}'
    service = NS(recall=AsyncMock(return_value=knowledge))
    engine.rag_memory = memory

    for mode, group_id, enabled, allowed in (
        ('replace', None, True, True), ('augment', 42, True, True),
        ('replace', 99, True, False), ('augment', None, False, True),
    ):
        memory.cfg['integration_mode'] = mode
        memory.knowledge = service if enabled else None
        service.recall.reset_mock()
        memory.recall.reset_mock()
        memory.record_turn.reset_mock()
        await engine.handle(NS(logger=Mock()), NS(user_id=7, group_id=group_id), '管理员怎么设置', include_tools=False)
        prompt = engine.llm.chat.call_args.kwargs['system_prompt']
        assert ('已归档对话' in prompt) == allowed
        assert ('旧版用户记忆' in prompt) == (not allowed or mode == 'augment')
        assert ('旧版全局记忆' in prompt) == (not allowed or mode == 'augment')
        if group_id is not None and (mode == 'augment' or not allowed):
            assert '旧版群记忆' in prompt
        assert (knowledge in prompt) == (enabled and allowed)
        assert service.recall.await_count == int(enabled and allowed)
        assert memory.recall.await_count == int(allowed)
        assert memory.record_turn.await_count == int(allowed)
        if allowed:
            assert '管理员手册' not in repr(memory.record_turn.call_args)
    assert engine.llm.chat.await_count == 4
    print('KNOWLEDGE_REPLY_OK')

asyncio.run(exercise())
''')
        self.assertIn('KNOWLEDGE_REPLY_OK', output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
