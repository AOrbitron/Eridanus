"""Offline media fixtures; exercise the registered plugin handlers, not live QQ."""
import asyncio
import io
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image

from run.giftoolbox import giftoolbox as plugin
from run.giftoolbox.service import core


def image_bytes(color='red', size=(12, 12)):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format='PNG')
    return out.getvalue()


def animation():
    out = io.BytesIO()
    frames = [Image.new('RGB', (12, 12), color) for color in ('red', 'green', 'blue')]
    frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:], duration=[100, 200, 300], loop=0)
    return out.getvalue()


class CoreTests(unittest.TestCase):
    def test_command_lists_and_aliases_survive_project_updates(self):
        from ruamel.yaml import YAML
        from framework_common.framework_util.config_migrations import merge_config_values
        template = YAML().load((Path(__file__).resolve().parents[1] / 'run/giftoolbox/config.yaml').read_text(encoding='utf-8'))
        custom = {'action': 'reverse', 'name': '自定义倒放', 'triggers': ['倒带喵']}
        previous = {'commands': [custom]}
        self.assertIsInstance(template['commands'], list)
        merged = merge_config_values(template, previous)
        self.assertEqual(list(plugin._commands(merged).values()), [custom])

    def test_help_and_handlers_share_list_legacy_and_enable_semantics(self):
        from run.giftoolbox.service.help_image import help_items
        active = {'action': 'reverse', 'enable': 'yes'}
        inactive = {'action': 'reverse', 'enable': '关闭'}
        for commands in ([active, inactive], {'active': active, 'inactive': inactive}):
            cfg = {'commands': commands}
            self.assertEqual(help_items(cfg), [active])
            self.assertEqual([item for item in plugin._commands(cfg).values() if plugin._enabled(item)], [active])

    def test_reverse_and_speed_preserve_frame_count_and_timing(self):
        output, info = core.reverse(animation())
        self.assertEqual(info['n'], 3)
        with Image.open(io.BytesIO(output)) as image:
            self.assertEqual(image.n_frames, 3)
            self.assertEqual(image.info['duration'], 300)
        _, info = core.speed_change(animation(), 'factor', 2)
        self.assertEqual(info['kept'], 3)
        self.assertAlmostEqual(info['dst_fps'], 10)

    def test_apng_contains_every_frame_and_duration(self):
        output, _ = core.reverse(animation(), 'APNG')
        with Image.open(io.BytesIO(output)) as image:
            self.assertEqual(image.n_frames, 3)
            self.assertFalse(image.info.get('default_image', False))
            self.assertAlmostEqual(image.info['duration'], 300)

    def test_all_static_operations(self):
        data = image_bytes()
        self.assertEqual(len(core.crop_grid(data, 2, 2)), 4)
        self.assertEqual(len(core.decompose(animation(), 2)), 2)
        self.assertTrue(core.lineart(data).startswith(b'\xff\xd8'))
        self.assertEqual(core.age(data, 1)[1]['frames'], 1)
        output, info = core.concat([data, image_bytes('blue')])
        self.assertEqual(info['frames'], 2)
        self.assertTrue(output.startswith(b'GIF'))

    def test_resource_limits_and_invalid_grid(self):
        with patch.object(core, 'MAX_PIXELS', 100):
            with self.assertRaises(core.ToolError):
                core.lineart(image_bytes())
        for rows, cols, margins in ((0, 2, {}), (20, 20, {}), (2, 2, {'left': -1})):
            with self.assertRaises(core.ToolError):
                core.crop_grid(image_bytes(), rows, cols, margins)

    def test_video_uses_existing_ffmpeg_and_has_timeout(self):
        with patch.object(core.subprocess, 'run', side_effect=FileNotFoundError) as run:
            with self.assertRaisesRegex(core.ToolError, 'FFmpeg'):
                core.video_to_gif('video.mp4')
            self.assertEqual(run.call_args.args[0][0], 'ffmpeg')
            self.assertEqual(run.call_args.kwargs['timeout'], 45)
        with patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 45)):
            with self.assertRaisesRegex(core.ToolError, '超时'):
                core.video_to_gif('video.mp4')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'existing project FFmpeg is not installed')
    def test_real_ffmpeg_converts_tiny_video(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.mp4'
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'testsrc=size=32x32:rate=5', '-t', '1', '-pix_fmt', 'yuv420p', str(path)],
                           check=True, capture_output=True, timeout=15)
            output, info = core.video_to_gif(str(path), fps=5, scale=1)
            self.assertEqual(info['frames'], 5)
            with Image.open(io.BytesIO(output)) as image:
                self.assertEqual(image.n_frames, 5)


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for name, value in {'CACHE_DIR': str(self.directory), 'INDEX_FILE': str(self.directory / '.sent_index.json'),
                            '_SENT_INDEX': {}, '_last_cleanup': 0}.items():
            self.enterContext(patch.object(plugin, name, value))

    async def test_local_read_does_not_block_event_loop(self):
        path = self.directory / 'input.png'
        path.write_bytes(image_bytes())
        original = open
        main_thread = threading.get_ident()
        thread_ids = []

        def slow_open(*args, **kwargs):
            thread_ids.append(threading.get_ident())
            time.sleep(0.06)
            return original(*args, **kwargs)

        with patch('builtins.open', side_effect=slow_open):
            self.assertEqual(await plugin._download(str(path)), image_bytes())
        self.assertTrue(thread_ids)
        self.assertNotIn(main_thread, thread_ids)

    async def test_bounded_local_base64_and_http_downloads(self):
        path = self.directory / 'large.bin'
        path.write_bytes(b'x' * 20)
        with patch.object(plugin, 'MAX_MEDIA_BYTES', 10):
            for source in (str(path), 'base64://' + 'eA==' * 30):
                with self.assertRaises(plugin.core.ToolError):
                    await plugin._download(source)
            original_client = httpx.AsyncClient
            transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 20))
            with patch.object(plugin.httpx, 'AsyncClient', side_effect=lambda **kw: original_client(transport=transport, **kw)):
                with self.assertRaisesRegex(core.ToolError, '过大'):
                    await plugin._download('https://media.example/image')

    async def test_cancellation_drains_worker_before_cleanup(self):
        entered, finished = threading.Event(), threading.Event()

        def work():
            entered.set()
            time.sleep(0.08)
            finished.set()

        task = asyncio.create_task(plugin._run_in_worker(work))
        await asyncio.to_thread(entered.wait)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finished.is_set())

    async def test_concurrent_cache_updates_remain_parseable(self):
        await asyncio.gather(*(asyncio.to_thread(plugin._remember_sent, {'message_id': i}, ['fixture.png']) for i in range(50)))
        data = json.loads((self.directory / '.sent_index.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data), 50)

    def bot(self, action='decompose', **settings):
        handlers = {}
        bot = NS(logger=Mock(), send=AsyncMock(return_value={'message_id': 99}))
        bot.on = lambda event_type: lambda handler: handlers.setdefault(event_type, handler)
        cfg = {'commands': {'command': {'action': action, 'triggers': ['测试'], 'reply': '', 'frame_label': '第{n}帧'}}, **settings}
        plugin.main(bot, NS(giftoolbox=NS(config=cfg)))
        return bot, handlers[plugin.GroupMessageEvent]

    async def test_registered_handler_batches_never_exceed_one_node(self):
        bot, handler = self.bot(forward_max_nodes=1)
        with patch.object(plugin, '_collect_media', AsyncMock(return_value=['fixture'])), patch.object(
            plugin, '_download', AsyncMock(return_value=animation())
        ):
            await handler(NS(message_chain=[plugin.Text('测试')]))
        batches = [call.args[1] for call in bot.send.await_args_list
                   if call.args[1] and isinstance(call.args[1][0], plugin.Node)]
        self.assertEqual(len(batches), 3)
        self.assertTrue(all(len(batch) == 1 for batch in batches))

    async def test_busy_handler_rejects_unbounded_work(self):
        bot, handler = self.bot(action='reverse')
        gate = asyncio.Event()
        entered = 0

        async def collect(*args, **kwargs):
            nonlocal entered
            entered += 1
            await gate.wait()
            return []

        event = NS(message_chain=[plugin.Text('测试')])
        with patch.object(plugin, '_collect_media', side_effect=collect):
            first = asyncio.create_task(handler(event))
            second = asyncio.create_task(handler(event))
            for _ in range(100):
                if entered == 2:
                    break
                await asyncio.sleep(0.01)
            await handler(event)
            self.assertEqual(entered, 2)
            self.assertTrue(any('稍后重试' in str(call.args[1]) for call in bot.send.await_args_list))
            gate.set()
            await asyncio.gather(first, second)


if __name__ == '__main__':
    unittest.main()
