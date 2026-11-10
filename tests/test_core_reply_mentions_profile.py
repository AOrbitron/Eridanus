"""Offline regressions: mention identity and active-engine personal information."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(os.environ.get('CORE_REPLY_TEST_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from developTools.message.message_components import At, Text, Image, Reply, Mface
from developTools.message.message_chain import MessageChain


def module(rel):
    spec = importlib.util.spec_from_file_location('fixture_' + Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def definitions(rel, names, scope):
    tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    exec(compile(tree, rel, 'exec'), scope)
    return scope


def event(*parts, gid=42, uid=7):
    return NS(group_id=gid, user_id=uid, sender=NS(user_id=uid, card='群名片', nickname='昵称'),
              pure_text='你好', message_chain=MessageChain(list(parts)))


class MentionTests(unittest.IsolatedAsyncioTestCase):
    def identity(self):
        return module('run/core_reply/service/message_identity.py')

    async def test_group_card_before_nickname(self):
        identity = self.identity()
        bot = NS(id=9, get_group_member_info=AsyncMock(return_value={'data': {'card': '小明', 'nickname': '本名'}}))
        result = await identity.resolve_message_text(event(Text('请问'), At(qq=8), Text('你好')), bot, '机器人')
        self.assertIn('@小明', result)
        self.assertIn('QQ: 8', result)
        self.assertIn('非机器人', result)
        self.assertTrue(result.startswith('请问'))
        self.assertTrue(result.endswith('你好'))

    async def test_nickname_fallback_and_flat_response(self):
        identity = self.identity()
        bot = NS(id=9, get_group_member_info=AsyncMock(return_value={'card': '', 'nickname': '小红'}))
        result = await identity.resolve_message_text(event(At(qq=8)), bot, '机器人')
        self.assertIn('@小红', result)

    async def test_all_and_bot_need_no_lookup(self):
        identity = self.identity()
        bot = NS(id=9, get_group_member_info=AsyncMock())
        result = await identity.resolve_message_text(event(At(qq=0), At(qq=9)), bot, '机器人')
        self.assertIn('全体成员', result)
        self.assertIn('@机器人', result)
        self.assertIn('机器人自身', result)
        bot.get_group_member_info.assert_not_awaited()

    async def test_lookup_failure_uses_component_name_not_sender(self):
        identity = self.identity()
        bot = NS(id=9, get_group_member_info=AsyncMock(side_effect=RuntimeError('offline')))
        result = await identity.resolve_message_text(event(At(qq=8, name='组件昵称')), bot, '机器人')
        self.assertIn('@组件昵称', result)
        self.assertNotIn('群名片', result)

    async def test_unknown_target_still_identified_as_non_bot(self):
        identity = self.identity()
        result = await identity.resolve_message_text(event(At(qq=8)), NS(id=9), '机器人')
        self.assertIn('QQ: 8', result)
        self.assertIn('非机器人', result)

    async def test_repeated_mentions_resolve_once(self):
        identity = self.identity()
        bot = NS(id=9, get_group_member_info=AsyncMock(return_value={'data': {'card': '成员'}}))
        result = await identity.resolve_message_text(event(At(qq=8), Text('和'), At(qq=8)), bot, '机器人')
        self.assertEqual(result.count('QQ: 8'), 2)
        self.assertEqual(bot.get_group_member_info.await_count, 1)

    async def test_sender_event_user_fallback(self):
        identity = self.identity()
        e = NS(user_id=7, user=NS(card='用户群名', nickname='用户名'))
        self.assertEqual(identity.sender_display_name(e), '用户群名')

    async def test_fake_sentinel_and_group_prefix_do_not_at_bot(self):
        scope = definitions('run/core_reply/service/trigger.py', {'TriggerChecker'},
                            dict(At=At, Text=Text, Optional=__import__('typing').Optional,
                                 Tuple=__import__('typing').Tuple, Dict=__import__('typing').Dict,
                                 List=list, Any=object))
        checker = scope['TriggerChecker']
        self.assertFalse(checker._has_at(event(At(qq=8), gid=111110123), 9))
        self.assertFalse(checker._has_at(event(At(qq=1000000)), 9))
        self.assertFalse(checker._has_at(event(At(qq=0)), 9))
        self.assertTrue(checker._has_at(event(At(qq=8), At(qq=9)), 9))
        self.assertTrue(checker._has_at(event(At(qq=1000000)), 1000000))

    async def test_trigger_keeps_resolved_chain_instead_of_rebuilding_numbers(self):
        mod = module('run/core_reply/service/trigger.py')
        checker = mod.TriggerChecker.__new__(mod.TriggerChecker)
        checker.window_enabled = False
        checker._is_reply_to_bot = lambda *args: False
        checker._evaluate_window_batch = AsyncMock(return_value={0: False})
        chain_text = '[@小明，QQ: 8，非机器人]你好'
        should, clean = await checker.check(event(At(qq=8), Text('你好')), 9, '机器人',
                                            '你好', message_text=chain_text)
        self.assertFalse(should)
        self.assertEqual(clean, chain_text)
        batch = checker._evaluate_window_batch.await_args.args[1]
        self.assertEqual(batch[0]['clean_text'], chain_text)
        self.assertEqual(batch[0]['sender_name'], '群名片')

    async def test_multimodal_text_reuses_the_same_resolved_mentions(self):
        identity = self.identity()
        scope = definitions('run/core_reply/main.py', {'extract_message_content'},
                            dict(Text=Text, At=At, Reply=Reply, Image=Image, Mface=Mface,
                                 resolve_message_text=identity.resolve_message_text))
        resolved = '[@小明，QQ: 8，非机器人]你好'
        text, content = await scope['extract_message_content'](
            event(At(qq=8), Text('你好')), NS(id=9), message_text=resolved)
        self.assertEqual(text, resolved)
        self.assertEqual(content, resolved)

    async def test_main_observer_and_trigger_receive_the_same_resolved_chain(self):
        identity = self.identity()
        tree = ast.parse((ROOT / 'run/core_reply/main.py').read_text(encoding='utf-8'))
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handle_group')
        handler.decorator_list = []
        context = NS(push_group_window=Mock())
        engine = NS(context=context, rag_memory=NS(allowed=lambda gid: False),
                    impression_updater=NS(is_group_memory_enabled=lambda gid: False), handle=AsyncMock())
        bot = NS(id=9, logger=Mock(), get_group_member_info=AsyncMock(return_value={'data': {'card': '小明'}}))
        trigger = NS(_has_at=lambda *args: False, check=AsyncMock(return_value=(False, 'not used')))
        cfg = NS(core_reply=NS(config={'trigger': {'prefix': []},
                 'trigger_llm': {'enable': True, 'whitelist_enabled': False}}),
                 common_config=NS(basic_config={'bot': '机器人'}))
        extract = definitions('run/core_reply/main.py', {'extract_message_content'},
                              dict(Text=Text, At=At, Reply=Reply, Image=Image, Mface=Mface,
                                   resolve_message_text=identity.resolve_message_text))['extract_message_content']
        from developTools.event.events import GroupMessageEvent
        scope = dict(bot=bot, config=cfg, engine=engine, trigger=trigger, asyncio=asyncio,
                     GroupMessageEvent=GroupMessageEvent, handle_clear_command=AsyncMock(return_value=False),
                     prefix_check=lambda *args: False, resolve_message_text=identity.resolve_message_text,
                     sender_display_name=identity.sender_display_name, extract_message_content=extract)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'main-handler', 'exec'), scope)
        await scope['handle_group'](event(At(qq=8), Text('你好')))
        text = trigger.check.await_args.kwargs['message_text']
        self.assertIn('@小明', text)
        self.assertIn('非机器人', text)
        self.assertEqual(context.push_group_window.call_args.args, (42, '群名片', text))
        engine.handle.assert_not_awaited()
        bot.get_group_member_info.assert_awaited_once()


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    def profile(self):
        return module('run/core_reply/service/user_profile.py')

    async def test_modes_only_read_enabled_backends(self):
        mod = self.profile()
        for slots in (False, True):
            for impression in (False, True):
                for rag in (False, True):
                    ctx = NS(enable_memory_slots=slots, enable_impression=impression,
                             get_user_memory=Mock(return_value='槽位数据'), get_impression=Mock(return_value='印象数据'))
                    mem = NS(allowed=Mock(return_value=rag), query_user_facts=AsyncMock(return_value='事实数据'))
                    result = await mod.query_user_profile(NS(context=ctx, rag_memory=mem), 42, 7)
                    self.assertEqual(ctx.get_user_memory.call_count, int(slots))
                    self.assertEqual(ctx.get_impression.call_count, int(impression))
                    self.assertEqual(mem.query_user_facts.await_count, int(rag))
                    for enabled, value in ((slots, '槽位数据'), (impression, '印象数据'), (rag, '事实数据')):
                        self.assertEqual(value in '\n'.join(result), enabled)

    async def test_no_memory_shows_disabled_or_empty(self):
        mod = self.profile()
        ctx = NS(enable_memory_slots=True, enable_impression=False, get_user_memory=Mock(return_value=''))
        mem = NS(allowed=Mock(return_value=False))
        result = '\n'.join(await mod.query_user_profile(NS(context=ctx, rag_memory=mem), 42, 7))
        self.assertIn('暂无', result)
        self.assertIn('未启用', result)

    async def test_one_backend_failure_keeps_other_results(self):
        mod = self.profile()
        ctx = NS(enable_memory_slots=True, enable_impression=True,
                 get_user_memory=Mock(side_effect=RuntimeError('broken')),
                 get_impression=Mock(return_value='仍有印象'))
        mem = NS(allowed=Mock(return_value=False))
        result = '\n'.join(await mod.query_user_profile(NS(context=ctx, rag_memory=mem), 42, 7))
        self.assertIn('查询失败', result)
        self.assertIn('仍有印象', result)

    async def test_info_card_switches_away_from_legacy(self):
        draws = []
        async def draw(items):
            draws.extend(items)
            return 'fixture.png'
        cfg = NS(system_plugin=NS(config={'user_data': {'是否启用个人信息查询': True}}), core_reply=NS(config={'enable': True}))
        data = NS(signed_days=[], user_id=7, nickname='昵称', card='名片', sex='x', age=1, city='城',
                  registration_date='today', permission=1, ai_token_record=123,
                  portrait_update_time='legacy-time', user_portrait='旧版画像不应出现')
        engine = NS(context=NS(enable_memory_slots=True, enable_impression=False,
                              get_user_memory=Mock(return_value='新版槽位')), rag_memory=NS(allowed=Mock(return_value=False)))
        from types import ModuleType
        fake = ModuleType('run.core_reply.service.reply_engine')
        fake.ReplyEngine = Mock(return_value=engine)
        scope = dict(get_user=AsyncMock(return_value=data), datetime=__import__('datetime').datetime,
                     manshuo_draw=draw, Image=Image)
        definitions('run/system_plugin/func_collection.py', {'call_user_data_query'}, scope)
        with patch.dict(sys.modules, {'run.core_reply.service.reply_engine': fake}):
            await scope['call_user_data_query'](NS(send=AsyncMock(), logger=Mock()), event(Text('我的信息')), cfg)
        rendered = str(draws)
        self.assertIn('新版槽位', rendered)
        self.assertNotIn('旧版画像不应出现', rendered)
        self.assertNotIn('ai对话token', rendered)

    async def test_user_facts_are_scoped_owned_and_active(self):
        import typing
        scope = definitions('run/core_reply/service/rag_memory.py', {'RAGMemory'},
                            dict(EpisodeArchive=type('Archive', (), {}), EpisodeRetrieval=type('Retrieval', (), {}),
                                 **vars(typing), asyncio=asyncio, np=NS(ndarray=object)))
        cls = scope['RAGMemory']
        db = sqlite3.connect(':memory:', check_same_thread=False)
        db.execute('CREATE TABLE memories(scope TEXT, namespace TEXT, target_id TEXT, fact_type TEXT, ended REAL, created REAL, text TEXT)')
        rows = [('group:42', 'current', '7', 'fact', None, 1, '本群本人'),
                ('user:7', 'current', '7', 'fact', None, 2, '本人全局'),
                ('group:99', 'current', '7', 'fact', None, 3, '其他群'),
                ('group:42', 'old', '7', 'fact', None, 4, '旧命名空间'),
                ('group:42', 'current', '8', 'fact', None, 5, '其他人'),
                ('group:42', 'current', None, 'fact', None, 6, '无归属'),
                ('group:42', 'current', '7', 'fact', 7, 7, '已失效'),
                ('group:42', 'current', '7', 'message', None, 8, '聊天日志')]
        db.executemany('INSERT INTO memories VALUES(?,?,?,?,?,?,?)', rows)
        obj = cls.__new__(cls)
        obj.allowed = lambda gid: True
        obj._namespace = 'current'
        obj._db = db
        obj._run_db = lambda fn: fn(db)
        result = await obj.query_user_facts(42, 7)
        self.assertIn('本群本人', result)
        self.assertIn('本人全局', result)
        for text in [r[-1] for r in rows[2:]]:
            self.assertNotIn(text, result)
        result = await obj.query_user_facts(None, 7)
        self.assertIn('本人全局', result)
        self.assertNotIn('本群本人', result)
        db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?)', ('private:7', 'current', '7', 'fact', None, 9, '私聊本人'))
        self.assertIn('私聊本人', await obj.query_user_facts(None, 7))
        self.assertNotIn('私聊本人', await obj.query_user_facts(42, 7))
        db.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
