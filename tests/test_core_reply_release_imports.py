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


if __name__ == '__main__':
    unittest.main(verbosity=2)
