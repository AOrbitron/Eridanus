"""Real SQLite and scheduler execution; HTTP, bot and LLM are offline fixtures."""
import asyncio
import datetime
import inspect
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import traceback
from contextlib import closing
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiosqlite
from test_core_reply_mentions_profile import ROOT, definitions, module
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Image, Text


def weather_scope():
    return definitions('run/basic_plugin/basic_plugin.py', {'call_weather_query'},
                       dict(get_user=AsyncMock(return_value=NS(city='上海')),
                            weather_query=AsyncMock(return_value='晴，20°C')))


def config():
    return NS(common_config=NS(basic_config={'proxy': {'http_proxy': None}}),
              basic_plugin=NS(config={'心知天气': {'api_key': ''}}),
              core_reply=NS(config={'enable': False}))


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_location_uses_user_id_without_sender(self):
        scope = weather_scope()
        result = await scope['call_weather_query'](None, NS(user_id=7), config())
        self.assertEqual(result, {'result': '晴，20°C'})
        scope['get_user'].assert_awaited_once_with(7)
        self.assertEqual(scope['weather_query'].await_args.args[-1], '上海')

    async def test_explicit_city_or_location_does_not_require_user_lookup(self):
        for params in ({'city': '北京'}, {'location': '深圳'}, {'location': '北京', 'city': '上海'}):
            scope = weather_scope()
            await scope['call_weather_query'](None, NS(user_id=7), config(), **params)
            scope['get_user'].assert_not_awaited()
            self.assertEqual(scope['weather_query'].await_args.args[-1], params.get('location') or params['city'])

    async def test_empty_and_none_location_use_saved_city(self):
        for location in (None, '', '  ', '无'):
            scope = weather_scope()
            await scope['call_weather_query'](None, NS(user_id=7), config(), location=location)
            self.assertEqual(scope['weather_query'].await_args.args[-1], '上海')

    async def test_unset_city_never_calls_weather_api(self):
        for city in (None, '', '无', '未设置', 'none'):
            scope = weather_scope()
            scope['get_user'].return_value = NS(city=city)
            result = await scope['call_weather_query'](None, NS(user_id=7), config())
            self.assertIn('修改城市', result['result'])
            scope['weather_query'].assert_not_awaited()

    async def test_weather_schema_permits_no_city(self):
        declarations = module('run/basic_plugin/__init__.py').function_declarations
        schema = next(d for d in declarations if d['name'] == 'call_weather_query')['parameters']
        self.assertEqual(schema.get('required', []), [])
        self.assertEqual(set(schema['properties']), {'location'})


class ScheduleDeclarationTests(unittest.TestCase):
    def test_tool_contract_is_generic_not_weather_specific(self):
        declarations = module('run/scheduled_tasks/__init__.py').function_declarations
        declaration = next(d for d in declarations if d['name'] == 'call_create_schedule_task')
        properties = declaration['parameters']['properties']
        self.assertEqual(properties['action_type']['enum'], ['message', 'tool'])
        self.assertEqual(properties['tool_name']['type'], 'string')
        self.assertEqual(properties['tool_params']['type'], 'object')
        descriptions = [declaration['description']] + [
            properties[name]['description'] for name in ('action_type', 'tool_name', 'tool_params')]
        for description in descriptions:
            for specific in ('天气', 'call_weather_query', 'location', 'call_asmr'):
                self.assertNotIn(specific, description)
        self.assertIn('已注册', properties['action_type']['description'])
        self.assertIn('参数声明', properties['tool_params']['description'])
        self.assertIn('注入', properties['tool_params']['description'])


class UserCityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / 'users.db')
        self.scope = definitions('framework_common/database_util/User.py',
                                {'User', 'ensure_db_initialized', 'initialize_db', 'add_user', 'get_user', 'update_user'},
                                dict(aiosqlite=aiosqlite, datetime=datetime, os=os, json=json,
                                     traceback=traceback, logger=Mock(), dbpath=self.db, _db_initialized=False,
                                     redis_cache_manager=NS(is_connected=lambda: False, delete=Mock())))

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_auto_registration_defaults_to_none(self):
        user = await self.scope['get_user'](7)
        self.assertEqual(user.city, '无')

    async def test_explicit_registration_defaults_to_none(self):
        await self.scope['add_user'](7, '小明', '群名')
        self.assertEqual((await self.scope['get_user'](7)).city, '无')

    async def test_sql_default_and_explicit_city(self):
        await self.scope['initialize_db']()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO users(user_id) VALUES(7)')
            db.commit()
            self.assertEqual(db.execute('SELECT city FROM users WHERE user_id=7').fetchone()[0], '无')
        await self.scope['add_user'](8, '小红', '群名', city='通辽')
        self.assertEqual((await self.scope['get_user'](8)).city, '通辽')

    async def test_old_schema_and_existing_values_survive_initialization(self):
        # Historical SQL is a committed fixture, never a developer's output directory.
        create_sql = (Path(__file__).parent / 'fixtures' / 'legacy_users.sql').read_text(encoding='utf-8')
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(create_sql)
            db.execute("ALTER TABLE users ADD COLUMN future_plugin_field TEXT DEFAULT 'keep'")
            db.execute("INSERT INTO users(user_id,nickname,city,permission,user_portrait) VALUES(7,'旧用户','通辽',9,'旧画像')")
            db.commit()
            before_schema = db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
            before_row = db.execute('SELECT * FROM users').fetchone()
        await self.scope['initialize_db']()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0], before_schema)
            self.assertEqual(db.execute('SELECT * FROM users').fetchone(), before_row)
        await self.scope['add_user'](8, '新用户', '')
        self.assertEqual((await self.scope['get_user'](8)).city, '无')
        await self.scope['update_user'](7, city='北京')
        self.assertEqual((await self.scope['get_user'](7)).city, '北京')


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mod = module('framework_common/schedule_service/scheduler_engine.py')
        self.mod.get_user = AsyncMock(return_value=NS(nickname='小明', card='群名', city='上海'))
        self.bot = NS(id=9, send_friend_message=AsyncMock(), send_group_message=AsyncMock())
        self.scheduler = self.mod.DynamicScheduler(self.bot, config(), str(Path(self.temp.name) / 'tasks.db'))
        self.scheduler._custom_tools = {}
        # Resolution sees the registry at execution time, not a snapshot at creation.
        self.registry = {}
        self.scheduler._find_callable_tool = lambda name: self.registry.get(name)
        self.weather = weather_scope()
        self.registry['call_weather_query'] = self.weather['call_weather_query']
        from framework_common.schedule_service.timezone_helper import TimezoneHelper
        self.create_scope = definitions('run/scheduled_tasks/schedule_tool.py', {'call_create_schedule_task'},
                                        dict(asyncio=asyncio, json=json, datetime=datetime, Optional=__import__('typing').Optional,
                                             Union=__import__('typing').Union, Dict=dict, Any=object, List=list,
                                             get_user=AsyncMock(return_value=NS(city='上海')), logger=Mock(),
                                             get_scheduler=lambda **kw: self.scheduler, TimezoneHelper=TimezoneHelper))
        self.create = self.create_scope['call_create_schedule_task']

    async def test_creation_calculates_time_and_resolves_timezone_off_loop(self):
        from framework_common.schedule_service.timezone_helper import TimezoneHelper
        main_thread = threading.get_ident()
        calculate_threads = []
        resolve_threads = []
        calculate = self.scheduler.calculate_initial_next_run
        resolve = TimezoneHelper.resolve_timezone

        def observed_calculate(*args, **kwargs):
            calculate_threads.append(threading.get_ident())
            return calculate(*args, **kwargs)

        def observed_resolve(*args, **kwargs):
            resolve_threads.append(threading.get_ident())
            return resolve(*args, **kwargs)

        with patch.object(self.scheduler, 'calculate_initial_next_run', side_effect=observed_calculate), patch.object(
            TimezoneHelper, 'resolve_timezone', side_effect=observed_resolve
        ):
            result = await self.create(description='线程验证', time_str='09:00', recur_type='daily',
                                       bot=None, event=NS(user_id=7), config=config())
        self.assertIn('已成功', result)
        self.assertTrue(calculate_threads)
        self.assertTrue(resolve_threads)
        self.assertNotIn(main_thread, calculate_threads + resolve_threads)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def create_task(self, **kwargs):
        params = dict(description='每日天气', time_str='08:00', recur_type='daily', action_type='tool',
                      tool_name='call_weather_query', tool_params={}, bot=self.bot,
                      event=NS(user_id=7), config=config())
        params.update(kwargs)
        return await self.create(**params)

    async def task(self, **kwargs):
        await self.create_task(**kwargs)
        return (await self.scheduler.list_active_tasks())[-1]

    async def test_create_persist_reload_execute_weather_daily(self):
        result = await self.create_task()
        self.assertIn('已成功', result)
        task = (await self.scheduler.list_active_tasks())[0]
        self.assertEqual(task.recur_type, 'daily')
        self.assertEqual(task.get_payload_dict(), {'tool_name': 'call_weather_query', 'tool_params': {}})
        # Restart reads the persisted task and still discovers its tool.
        restart = self.mod.DynamicScheduler(self.bot, config(), self.scheduler.db_path)
        restart._find_callable_tool = self.scheduler._find_callable_tool
        loaded = (await restart.list_active_tasks())[0]
        self.weather['get_user'].return_value.city = '北京'  # city changed after task creation
        await restart.execute_task(loaded)
        self.assertEqual(self.weather['weather_query'].await_args.args[-1], '北京')
        self.assertEqual(self.bot.send_friend_message.await_args.args[0], 7)
        self.assertIn('晴', self.bot.send_friend_message.await_args.args[1][0].text)

    async def test_tick_updates_next_day_and_sends_once(self):
        task = await self.task()
        with closing(sqlite3.connect(self.scheduler.db_path)) as db:
            db.execute('UPDATE dynamic_tasks SET next_run_timestamp=?', (time.time() - 1,))
            db.commit()
        original = self.scheduler.execute_task
        jobs = []
        async def observe(t):
            await original(t)
            jobs.append(t.task_id)
        self.scheduler.execute_task = observe
        await self.scheduler.tick()
        for _ in range(100):
            if jobs:
                break
            await asyncio.sleep(.01)
        self.assertEqual(jobs, [task.task_id])
        self.assertEqual(self.bot.send_friend_message.await_count, 1)
        loaded = (await self.scheduler.list_active_tasks())[0]
        self.assertGreater(loaded.next_run_timestamp, time.time())
        self.assertTrue(loaded.last_run_at)
        await self.scheduler.tick()
        self.assertEqual(self.bot.send_friend_message.await_count, 1)

    async def test_old_payload_executes_without_database_rewrite(self):
        task = await self.task()
        legacy = {'func_name': 'call_weather_query', 'parameters': {'city': '北京'}}
        with closing(sqlite3.connect(self.scheduler.db_path)) as db:
            db.execute('UPDATE dynamic_tasks SET action_payload=? WHERE task_id=?', (json.dumps(legacy), task.task_id))
            db.execute("ALTER TABLE dynamic_tasks ADD COLUMN future_column TEXT DEFAULT 'preserve'")
            db.commit()
            schema_before = db.execute("SELECT sql FROM sqlite_master WHERE name='dynamic_tasks'").fetchone()[0]
        restarted = self.mod.DynamicScheduler(self.bot, config(), self.scheduler.db_path)
        restarted._find_callable_tool = self.scheduler._find_callable_tool
        loaded = (await restarted.list_active_tasks())[0]
        await restarted.execute_task(loaded)
        self.assertEqual(self.weather['weather_query'].await_args.args[-1], '北京')
        with closing(sqlite3.connect(self.scheduler.db_path)) as db:
            self.assertEqual(json.loads(db.execute('SELECT action_payload FROM dynamic_tasks').fetchone()[0]), legacy)
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='dynamic_tasks'").fetchone()[0], schema_before)

    async def test_future_registered_sync_tool_with_full_event(self):
        task = await self.task(tool_name='future_tool', tool_params={'value': 3, 'obsolete_argument': True})
        # New function registered after task creation needs no scheduler changes.
        def future_tool(value, event, bot, config, user_id):
            self.assertIsInstance(event, PrivateMessageEvent)
            self.assertEqual(event.sender.user_id, 7)
            self.assertEqual(user_id, 7)
            self.assertIs(bot, self.bot)
            self.assertNotEqual(threading.current_thread(), threading.main_thread())
            return {'new_value': value * 2}
        self.registry['future_tool'] = future_tool
        await self.scheduler.execute_task(task)
        self.assertEqual(json.loads(self.bot.send_friend_message.await_args.args[1][0].text), {'new_value': 6})

    async def test_group_event_uses_creator_city_and_group_destination(self):
        task = await self.task(event=NS(user_id=7, group_id=42))
        await self.scheduler.execute_task(task)
        self.weather['get_user'].assert_awaited_with(7)
        self.bot.send_friend_message.assert_not_awaited()
        self.assertEqual(self.bot.send_group_message.await_args.args[0], 42)
        e = await self.scheduler._build_task_event(task)
        self.assertIsInstance(e, GroupMessageEvent)
        self.assertEqual((e.user_id, e.group_id, e.sender.user_id), (7, 42, 7))

    async def test_return_variants_and_no_return(self):
        task = await self.task()
        for value in ('text', {'result': 'envelope'}, {'key': 1}, 0, Image(file='fixture.png'),
                      [Text('chain')], [{'type': 'text', 'data': {'text': 'raw'}}], [{'a': 1}]):
            self.bot.send_friend_message.reset_mock()
            await self.scheduler._send_tool_result(task, value)
            self.bot.send_friend_message.assert_awaited_once()
        for value in (None, '', [], {'result': None}):
            self.bot.send_friend_message.reset_mock()
            await self.scheduler._send_tool_result(task, value)
            self.bot.send_friend_message.assert_not_awaited()

    async def test_awaitable_callable_and_positional_only(self):
        task = await self.task()
        e = await self.scheduler._build_task_event(task)
        def positional(value, /, event):
            return value + event.user_id
        self.assertEqual(await self.scheduler._invoke_tool(positional, {'value': 2}, e), 9)
        class FutureCallable:
            async def __call__(self, event, **kwargs):
                return event.user_id, kwargs['bot']
        value = await self.scheduler._invoke_tool(FutureCallable(), {}, e)
        self.assertEqual(value, (7, self.bot))

    async def test_context_cannot_be_spoofed_by_saved_params(self):
        task = await self.task()
        e = await self.scheduler._build_task_event(task)
        async def probe(bot, event, config):
            return bot, event, config
        result = await self.scheduler._invoke_tool(probe, {'bot': 'bad', 'event': 'bad', 'config': 'bad'}, e)
        self.assertEqual(result, (self.bot, e, self.scheduler.config))

    async def test_distinct_tools_and_creators_not_deduplicated(self):
        await self.create_task(event=NS(user_id=7, group_id=42))
        await self.create_task(event=NS(user_id=7, group_id=42), tool_name='future_tool')
        await self.create_task(event=NS(user_id=8, group_id=42))
        self.assertEqual(len(await self.scheduler.list_active_tasks()), 3)
        await self.create_task(event=NS(user_id=7, group_id=42))
        self.assertEqual(len(await self.scheduler.list_active_tasks()), 3)

    async def test_concurrent_identical_creations_reuse_one_task(self):
        await asyncio.gather(*(self.create_task() for _ in range(4)))
        self.assertEqual(len(await self.scheduler.list_active_tasks()), 1)

    async def test_new_registered_plugin_discovered_without_scheduler_name_map(self):
        from types import ModuleType
        fake = ModuleType('framework_common.framework_util.func_map_loader')
        tools = {}
        fake.build_tool_map = lambda: tools
        del self.scheduler._find_callable_tool
        task = await self.task(tool_name='brand_new_plugin')
        async def future_plugin(event):
            return {'result': f'future:{event.user_id}'}
        tools['brand_new_plugin'] = future_plugin
        import sys
        with patch.dict(sys.modules, {'framework_common.framework_util.func_map_loader': fake}):
            await self.scheduler.execute_task(task)
        self.assertEqual(self.bot.send_friend_message.await_args.args[1][0].text, 'future:7')

    async def test_bad_parameters_do_not_persist(self):
        for params in ('broken', '[]', [], 0, False):
            result = await self.create_task(tool_params=params)
            self.assertIn('失败', result)
        self.assertIn('失败', await self.create_task(tool_name=''))
        self.assertEqual(await self.scheduler.list_active_tasks(), [])

    async def test_missing_tool_reports_failure_and_clears_running_state(self):
        task = await self.task(tool_name='not_installed')
        await self.scheduler.execute_task(task)
        self.assertIn('执行失败', self.bot.send_friend_message.await_args.args[1][0].text)
        self.assertNotIn(task.task_id, self.scheduler._running_tasks)

    async def test_legacy_parameters_json_string_and_empty_canonical_params(self):
        name, params = self.scheduler._tool_call_from_payload({'func_name': 'new', 'parameters': '{"x": 1}'})
        self.assertEqual((name, params), ('new', {'x': 1}))
        self.assertEqual(self.scheduler._tool_call_from_payload(
            {'tool_name': 'new', 'tool_params': {}, 'parameters': {'stale': 1}}), ('new', {}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
