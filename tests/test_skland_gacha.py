"""离线验证真实寻访协议、合并和指令，加载时不启动 Eridanus 插件。"""
import ast
import asyncio
import copy
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx


PLUGIN = Path(__file__).resolve().parents[1] / "run/anime_game_service/service/skland"
package = ModuleType("_skland_gacha_tests")
package.__path__ = [str(PLUGIN / "utils")]
sys.modules[package.__name__] = package


def load_tool(name):
    spec = importlib.util.spec_from_file_location(f"{package.__name__}.{name}", PLUGIN / "utils" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gacha = load_tool("gacha")
draw = load_tool("draw_gacha")


def command_module(db):
    tree = ast.parse((PLUGIN / "command/card.py").read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign))]
    nodes = [node for node in nodes if not isinstance(node, ast.Assign) or not any(isinstance(t, ast.Name) and t.id == "logger" for t in node.targets)]
    namespace = dict(asyncio=asyncio, re=__import__("re"), logger=logging.getLogger("test.skland"),
                     At=lambda **kw: kw, Image=lambda **kw: kw,
                     AsyncSQLiteDatabase=SimpleNamespace(get_instance=AsyncMock(return_value=db)),
                     GAME_NAMES=draw.GAME_NAMES, render_cards=AsyncMock(return_value=[]))
    namespace.update({name: getattr(gacha, name) for name in ["GachaError", "load_cache", "numeric", "record_counts", "refresh_records", "save_cache"]})
    code = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(code, str(PLUGIN / "command/card.py"), "exec"), namespace)
    return namespace


def row(seq, *, pool="special_1", rarity=4, free=False, kind="draw", **extra):
    return dict(seqId=str(seq), poolId=pool, poolName="测试卡池", gachaTs=str(1700000000000 + seq),
                rarity=rarity, charId="chr_0001_test", charName="测试角色", isFree=free, kind=kind, **extra)


def ark(pos, ts=1700000000000, **extra):
    return dict(poolId="pool_1", poolName="标准寻访", gachaTs=str(ts), pos=pos,
                rarity=5, charId="char_002_amiya", charName="测试干员", **extra)


def cache(game="endfield", records=(), key="char:E_CharacterGachaPoolType_Special", **extra):
    return dict(version=1, game=game, uid="12345", server_id="1", initialized=True,
                streams={key: dict(name="测试寻访", kind="char", complete=True, records=list(records))}, **extra)


class MergeTests(unittest.TestCase):
    def test_duplicate_streams_and_same_seq_different_pools(self):
        value = cache(records=[row(1), row(2)])
        value["streams"]["other"] = dict(kind="char", name="其他", records=[row(1), row(1, pool="other")])
        self.assertEqual(gacha.record_counts(value), (3, 0))

    def test_ark_ten_pull_identical_chars_keep_all_positions(self):
        records = [ark(i) for i in range(10)]
        merged = gacha.merge_records("arknights", "char", records, records)
        self.assertEqual(len(merged), 10)
        self.assertEqual([item["pos"] for item in merged], list(reversed(range(10))))

    def test_unknown_fields_survive_merge_and_update(self):
        merged = gacha.merge_records("endfield", "char", [row(1, poolVersion=None, opaque=7)], [row(1)])
        self.assertIsNone(merged[0]["poolVersion"])
        self.assertEqual(merged[0]["opaque"], 7)

    def test_gifts_and_free_six_do_not_advance_or_reset_paid_pity(self):
        value = cache(records=[row(1), row(2, rarity=6, free=True), row(3), row(4, kind="gift_book")])
        group = draw.summaries(value)[0]
        self.assertEqual(gacha.record_counts(value), (3, 1))
        self.assertEqual((group["total"], group["free"], group["six"], group["tail"]), (3, 1, 1, 2))

    def test_ark_zero_based_rarity(self):
        self.assertEqual(draw.rarity("arknights", ark(0)), 6)
        self.assertEqual(draw.rarity("endfield", row(0, rarity=6)), 6)

    def test_six_stars_display_newest_first(self):
        group = draw.summaries(cache(records=[row(2, rarity=6), row(1, rarity=6)]))[0]
        self.assertEqual([event["record"]["seqId"] for event in group["events"]], ["2", "1"])

    def test_weapon_pools_have_independent_counters(self):
        value = cache(records=[])
        value["streams"] = {"weapon:a": dict(name="武器", kind="weapon", records=[row(1, pool="a", rarity=6), row(2, pool="b")])}
        groups = draw.summaries(value)
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(item["tail"] for item in groups), [0, 1])

    def test_atomic_save_full_backup_and_older_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gacha, "ROOT", Path(directory)):
            value = cache(records=[row(1)])
            gacha.save_cache(value)
            value["streams"][next(iter(value["streams"]))]["records"].append(row(2))
            gacha.save_cache(value, full_refresh=True)
            self.assertEqual(gacha.record_counts(gacha.load_cache("endfield", "12345")), (2, 0))
            backup = json.loads(gacha.cache_path("endfield", "12345").with_suffix(".json.bak").read_text())
            self.assertEqual(gacha.record_counts(backup), (1, 0))
            self.assertFalse(list(Path(directory).rglob("*.tmp")))

    def test_corrupt_cache_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gacha, "ROOT", Path(directory)):
            path = gacha.cache_path("endfield", "12345")
            path.parent.mkdir(parents=True)
            path.write_text("bad json")
            with self.assertRaises(gacha.GachaError):
                gacha.load_cache("endfield", "12345")
            self.assertEqual(path.read_text(), "bad json")


class PageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = gacha.GachaAPI(None)

    async def test_incremental_stops_at_known_record(self):
        self.api.request = AsyncMock(return_value=dict(list=[row(5), row(4)], hasMore=True))
        old = dict(complete=True, records=[row(4), row(1)])
        result = await self.api.pages("endfield", "char", "unused", {}, old, False)
        self.assertEqual(len(result), 2)
        self.assertEqual(self.api.request.await_count, 1)
        merged = gacha.merge_records("endfield", "char", old["records"], result)
        self.assertEqual([item["seqId"] for item in merged], ["5", "4", "1"])

    async def test_full_refresh_ignores_overlap(self):
        self.api.request = AsyncMock(side_effect=[dict(list=[row(5), row(4)], hasMore=True), dict(list=[row(2)], hasMore=False)])
        result = await self.api.pages("endfield", "char", "unused", {}, dict(complete=True, records=[row(4)]), True)
        self.assertEqual(len(result), 3)
        self.assertEqual(self.api.request.await_args_list[1].kwargs["params"]["seq_id"], "4")

    async def test_gift_last_row_drives_cursor(self):
        self.api.request = AsyncMock(side_effect=[dict(list=[row(6), row(5, kind="gift_intel_book")], hasMore=True), dict(list=[row(4)], hasMore=False)])
        await self.api.pages("endfield", "char", "unused", {}, {}, False)
        self.assertEqual(self.api.request.await_args_list[1].kwargs["params"]["seq_id"], "5")

    async def test_ark_cursor_includes_zero_position(self):
        self.api.request = AsyncMock(side_effect=[dict(list=[ark(1), ark(0)], hasMore=True), dict(list=[ark(9, 1699999999999)], hasMore=False)])
        await self.api.pages("arknights", "char", "unused", {}, {}, False)
        params = self.api.request.await_args_list[1].kwargs["params"]
        self.assertEqual((params["gachaTs"], params["pos"]), ("1700000000000", "0"))

    async def test_incomplete_stream_does_not_stop_at_overlap(self):
        self.api.request = AsyncMock(side_effect=[dict(list=[row(4)], hasMore=True), dict(list=[row(1)], hasMore=False)])
        await self.api.pages("endfield", "char", "unused", {}, dict(records=[row(4)], complete=False), False)
        self.assertEqual(self.api.request.await_count, 2)

    async def test_repeated_cursor_is_error(self):
        self.api.request = AsyncMock(return_value=dict(list=[row(3)], hasMore=True))
        with self.assertRaises(gacha.GachaError):
            await self.api.pages("endfield", "char", "unused", {}, {}, False)

    async def test_has_more_empty_page_is_error(self):
        self.api.request = AsyncMock(return_value=dict(list=[], hasMore=True))
        with self.assertRaises(gacha.GachaError):
            await self.api.pages("endfield", "char", "unused", {}, {}, False)

    async def test_errors_never_include_token_or_url(self):
        def handler(request):
            raise httpx.ConnectError("secret-token-in-url", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(gacha.GachaError) as result:
                await gacha.GachaAPI(client).request("GET", "https://example.com?token=secret", "测试")
            self.assertNotIn("secret", str(result.exception))

    async def test_expired_http_authorization_prompts_relogin(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            with self.assertRaises(gacha.GachaError) as result:
                await gacha.GachaAPI(client).request("GET", "https://example.com?token=secret", "测试")
            self.assertIn("森空岛登录", str(result.exception))
            self.assertNotIn("secret", str(result.exception))


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_ark_session_and_timestamp_position_pagination(self):
        seen = []
        def handler(request):
            seen.append(request)
            path = request.url.path
            if path.endswith("grant"):
                return httpx.Response(200, json=dict(status=0, data=dict(token="oauth")))
            if path.endswith("binding_list"):
                return httpx.Response(200, json=dict(status=0, data=dict(list=[dict(appCode="arknights", bindingList=[dict(uid="12345", nickName="博士")])])), headers={})
            if path.endswith("u8_token_by_uid"):
                return httpx.Response(200, json=dict(status=0, data=dict(token="u8")))
            if path.endswith("role/login"):
                return httpx.Response(200, json=dict(code=0, data={}), headers={"Set-Cookie": "ak-user-center=session; Path=/"})
            self.assertIn("ak-user-center=session", request.headers.get("cookie", ""))
            self.assertEqual(request.headers.get("x-role-token"), "u8")
            if path.endswith("role/info"):
                return httpx.Response(200, json=dict(code=0, data=dict(uid="12345", name="测试博士")))
            if path.endswith("gacha/cate"):
                return httpx.Response(200, json=dict(code=0, data=[dict(id="normal", name="标准寻访")]))
            self.assertEqual(request.url.params["category"], "normal")
            if "pos" not in request.url.params:
                data = dict(list=[ark(1), ark(0)], hasMore=True)
            else:
                self.assertEqual(request.url.params["pos"], "0")
                self.assertEqual(request.url.params["gachaTs"], "1700000000000")
                data = dict(list=[ark(9, ts=1699999999999)], hasMore=False)
            return httpx.Response(200, json=dict(code=0, data=data))
        client_type = httpx.AsyncClient
        with patch.object(gacha.httpx, "AsyncClient", side_effect=lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw)):
            result, added, _, warnings = await gacha.refresh_records("arknights", dict(access_token="account"), dict(uid="12345"), cache("arknights", key="ark:normal"))
        self.assertEqual((added, warnings), (3, []))
        self.assertEqual(result["profile"]["nickname"], "测试博士")
        self.assertEqual(len([request for request in seen if request.url.path.endswith("gacha/history")]), 2)

    async def test_authorization_uses_account_uid_not_endfield_role_id(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path.endswith("grant"):
                return httpx.Response(200, json=dict(status=0, data=dict(token="oauth")))
            if request.url.path.endswith("binding_list"):
                return httpx.Response(200, json=dict(status=0, data=dict(list=[dict(appCode="endfield", bindingList=[dict(uid="99", roles=[dict(roleId="12345", serverId="1", nickName="测试管理员")])])])))
            self.assertEqual(json.loads(request.content)["uid"], "99")
            return httpx.Response(200, json=dict(status=0, data=dict(token="u8")))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            token, profile = await gacha.GachaAPI(client).authorize("endfield", dict(access_token="account"), dict(uid="99", roleid="12345", serverid="1"))
        self.assertEqual(token, "u8")
        self.assertEqual(profile["nickname"], "测试管理员")

    async def test_rerun_future_types_offline_weapon_and_partial_failure(self):
        value = cache(records=[row(1)])
        seen = []
        async def request(api, method, url, action, **kwargs):
            if url.endswith("char/meta"):
                return dict(tabs=[dict(poolType="E_CharacterGachaPoolType_Future", label="未来池")])
            return [dict(poolId="offline_pool", poolName="已下线武器", online=False)]
        async def pages(api, game, kind, url, params, old, full, headers):
            seen.append((url, dict(params), full))
            if params.get("pool_type", "").endswith("Special"):
                return [row(2), row(1)]
            if params.get("pool_type", "").endswith("Rerun"):
                raise gacha.GachaError("暂时不可用")
            return []
        with patch.object(gacha.GachaAPI, "authorize", new=AsyncMock(return_value=("token", {}))), patch.object(gacha.GachaAPI, "request", new=request), patch.object(gacha.GachaAPI, "pages", new=pages):
            result, added, gifts, warnings = await gacha.refresh_records("endfield", {}, {}, value, full_refresh=True)
        self.assertEqual((added, gifts), (1, 0))
        self.assertTrue(any(params.get("pool_id") == "offline_pool" for _, params, _ in seen))
        self.assertTrue(any(params.get("pool_type", "").endswith("Future") for _, params, _ in seen))
        self.assertTrue(all(full for _, _, full in seen))
        self.assertTrue(warnings)
        self.assertEqual(gacha.record_counts(value), (1, 0))
        self.assertEqual(gacha.record_counts(result), (2, 0))

    async def test_all_failure_preserves_input(self):
        value = cache(records=[row(1)])
        before = copy.deepcopy(value)
        with patch.object(gacha.GachaAPI, "authorize", new=AsyncMock(return_value=("token", {}))), patch.object(gacha.GachaAPI, "request", new=AsyncMock(return_value=[])), patch.object(gacha.GachaAPI, "pages", new=AsyncMock(side_effect=gacha.GachaError("失败"))):
            with self.assertRaises(gacha.GachaError):
                await gacha.refresh_records("endfield", {}, {}, value)
        self.assertEqual(value, before)

    async def test_weapon_discovery_failure_tries_cached_and_compatibility(self):
        value = cache()
        value["streams"]["weapon:old_pool"] = dict(name="旧武器池", kind="weapon", complete=True, records=[])
        async def request(api, method, url, action, **kwargs):
            if url.endswith("char/meta"):
                return dict(tabs=[])
            raise gacha.GachaError("列表暂时不可用")
        pages = AsyncMock(return_value=[])
        with patch.object(gacha.GachaAPI, "authorize", new=AsyncMock(return_value=("token", {}))), patch.object(gacha.GachaAPI, "request", new=request), patch.object(gacha.GachaAPI, "pages", new=pages):
            result, _, _, warnings = await gacha.refresh_records("endfield", {}, {}, value)
        self.assertIn("weapon:old_pool", result["streams"])
        self.assertIn("weapon:all", result["streams"])
        weapon_params = [call.args[3] for call in pages.await_args_list if call.args[1] == "weapon"]
        self.assertEqual([params.get("pool_id") for params in weapon_params], ["old_pool", None])
        self.assertTrue(warnings)

    async def test_successful_weapon_catalog_still_fetches_uncatalogued_history(self):
        archived = row(1, pool="expired_pool", rarity=6)
        shared = row(3, pool="current_pool", rarity=6)
        missing = row(2, pool="uncatalogued_pool")
        value = cache()
        value["streams"]["weapon:all"] = dict(name="武器", kind="weapon", complete=True, records=[archived])
        async def request(api, method, url, action, **kwargs):
            return dict(tabs=[]) if url.endswith("char/meta") else [dict(poolId="current_pool")]
        async def pages(api, game, kind, url, params, old, full, headers):
            if kind == "char":
                return []
            return [shared] if params.get("pool_id") else [shared, missing]
        with patch.object(gacha.GachaAPI, "authorize", new=AsyncMock(return_value=("token", {}))), patch.object(gacha.GachaAPI, "request", new=request), patch.object(gacha.GachaAPI, "pages", new=pages):
            result, added, _, warnings = await gacha.refresh_records("endfield", {}, {}, value, full_refresh=True)
        weapons = [record for kind, _, record in gacha.all_records(result) if kind == "weapon"]
        self.assertEqual({record["poolId"] for record in weapons}, {"expired_pool", "current_pool", "uncatalogued_pool"})
        self.assertEqual(len(weapons), 3)  # 汇总与逐池重复项只计一次，过期旧记录保留。
        self.assertEqual((added, warnings), (2, []))
        self.assertFalse(result["coverage"]["account_history_complete"])
        self.assertEqual(result["coverage"]["api_history_days"], 90)


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.role = dict(uid="99", roleid="12345", serverid="1", nickname="测试管理员")
        self.db = SimpleNamespace(read_user=AsyncMock(return_value=dict(skland=dict(user_info=dict(access_token="account"), character_info=dict(endfield=self.role)))))
        self.ns = command_module(self.db)
        self.bot = SimpleNamespace(send=AsyncMock(), recall=AsyncMock())
        self.sleep = patch("asyncio.sleep", new=AsyncMock())
        self.sleep.start()
        self.directory = tempfile.TemporaryDirectory()
        self.root = patch.object(gacha, "ROOT", Path(self.directory.name))
        self.root.start()

    async def asyncTearDown(self):
        self.sleep.stop()
        self.root.stop()
        self.directory.cleanup()

    async def call(self, text):
        return await self.ns["handle_skland_card_command"](text, "100", self.bot, object())

    def test_aliases_and_actions(self):
        parse = self.ns["parse_card_command"]
        self.assertEqual(parse("明日方舟：终末地全量更新抽卡记录"), ("endfield", "refresh", None, True))
        self.assertEqual(parse("ARK UID:12345 查看抽卡记录"), ("arknights", "show", "12345", False))
        self.assertIsNone(parse("原神抽卡记录"))
        self.assertIsNone(parse("终末地抽卡记录其他文本"))

    def test_requested_uid_uses_role_uid(self):
        with self.assertRaises(gacha.GachaError):
            self.ns["resolve_role"](dict(character_info=dict(endfield=self.role)), "endfield", "99")

    async def test_existing_cache_query_does_not_refresh(self):
        gacha.save_cache(cache(records=[row(1)]))
        self.ns["refresh_records"] = AsyncMock()
        await self.call("终末地抽卡记录")
        self.ns["refresh_records"].assert_not_awaited()
        self.ns["render_cards"].assert_awaited_once()

    async def test_empty_result_is_cached_and_not_repeatedly_fetched(self):
        value = cache(records=[])
        self.ns["refresh_records"] = AsyncMock(return_value=(value, 0, 0, []))
        await self.call("终末地抽卡记录")
        await self.call("终末地查看抽卡记录")
        self.assertEqual(self.ns["refresh_records"].await_count, 1)
        self.ns["render_cards"].assert_not_awaited()

    async def test_refresh_reports_added_and_does_not_render(self):
        gacha.save_cache(cache(records=[row(1)]))
        value = cache(records=[row(1), row(2)])
        self.ns["refresh_records"] = AsyncMock(return_value=(value, 1, 0, []))
        await self.call("终末地更新抽卡记录")
        self.assertIn("新增 1 抽，共保存 2 抽", str(self.bot.send.await_args))
        self.ns["render_cards"].assert_not_awaited()

    async def test_duplicate_update_does_not_issue_request(self):
        lock = asyncio.Lock()
        await lock.acquire()
        self.ns["_LOCKS"][("endfield", "12345", "1")] = lock
        self.ns["refresh_records"] = AsyncMock()
        try:
            await self.call("终末地更新抽卡记录")
        finally:
            lock.release()
        self.ns["refresh_records"].assert_not_awaited()


class DrawTests(unittest.TestCase):
    def test_long_history_adds_columns_in_one_image_for_both_games(self):
        from PIL import Image
        for game in ("arknights", "endfield"):
            records = [ark(i) for i in range(128)] if game == "arknights" else [row(i, rarity=6) for i in range(1, 129)]
            value = cache(game=game, records=records, profile=dict(nickname="测试管理员", level=10))
            with self.subTest(game=game), tempfile.TemporaryDirectory() as directory, \
                    patch.object(draw, "ROOT", Path(directory)), patch.object(draw, "OUTPUT_DIR", Path(directory)):
                rendered = []
                global_headers = []
                pool_headers = []
                def record_event(img, current_game, event, x, y):
                    record = event["record"]
                    rendered.append((str(record.get("seqId", record.get("pos"))), x, y))
                    img.putpixel((x, y), (255, 0, 0, 255))
                def record_global_header(img, _payload, _groups):
                    global_headers.append(True)
                    img.putpixel((1100, 10), (0, 255, 0, 255))
                def record_pool_header(_img, _payload, _group, _title, y, x_offset=0):
                    pool_headers.append((x_offset, y))
                with patch.object(draw, "_draw_event", side_effect=record_event), \
                        patch.object(draw, "_draw_header", side_effect=record_global_header), \
                        patch.object(draw, "_draw_pool_header", side_effect=record_pool_header):
                    paths = draw.draw_cards(value)
                self.assertEqual(len(paths), 1)
                self.assertEqual(len(rendered), 128)
                self.assertEqual(len(global_headers), 1)
                self.assertEqual({x // 1200 for x, _ in pool_headers}, {0, 1, 2, 3})
                self.assertTrue(all(y >= draw.HEADER_HEIGHT for x, y in pool_headers if x == 0))
                self.assertTrue(all(y < draw.HEADER_HEIGHT for x, y in pool_headers if x > 0))
                expected_ids = [str(i) for i in reversed(range(128) if game == "arknights" else range(1, 129))]
                self.assertEqual([item[0] for item in rendered], expected_ids)
                columns = {x // 1200 for _, x, _ in rendered}
                self.assertEqual(columns, {0, 1, 2, 3})
                with Image.open(paths[0]) as img:
                    self.assertEqual(img.width, 4800)
                    self.assertLess(img.height, 3000)
                    self.assertEqual(img.getpixel((1100, 10)), (0, 255, 0))
                    for col in range(1, 4):
                        self.assertNotEqual(img.getpixel((col * 1200 + 1100, 10)), (0, 255, 0))
                    for _, x, y in rendered:
                        self.assertEqual(img.getpixel((x, y)), (255, 0, 0))

    def test_pool_header_moves_with_its_column(self):
        from PIL import Image, ImageChops
        value = cache(records=[row(1, rarity=6)])
        group = draw._display_groups(value)[0]
        image = Image.new("RGBA", (2400, 300))
        with patch.object(draw, "_open_icon", return_value=None):
            draw._draw_pool_header(image, value, group, group["name"], 0, 0)
            draw._draw_pool_header(image, value, group, group["name"], 0, 1200)
        left, right = image.crop((0, 0, 1200, 300)), image.crop((1200, 0, 2400, 300))
        self.assertIsNotNone(left.getbbox())
        self.assertIsNone(ImageChops.difference(left, right).convert("RGB").getbbox())

    def test_repeated_query_creates_new_image_directly_in_output_directory(self):
        value = cache(records=[row(1, rarity=6)])
        with tempfile.TemporaryDirectory() as directory, patch.object(draw, "OUTPUT_DIR", Path(directory)):
            first = draw.draw_cards(value)
            second = draw.draw_cards(value)
            self.assertNotEqual(first, second)
            self.assertTrue(all(path.parent == Path(directory) and path.is_file() for path in first + second))


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handlers = {}
        self.at, self.text = object(), object()
        self.command = AsyncMock()
        tree = ast.parse((PLUGIN.parents[1] / "skland.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
        ns = dict(GroupMessageEvent=object, At=self.at, Text=self.text, handle_skland_card_command=self.command)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "skland.py", "exec"), ns)
        def on(event_type):
            def register(function):
                handlers[function.__name__] = function
                return function
            return register
        self.bot = SimpleNamespace(on=on)
        config = SimpleNamespace(common_config=SimpleNamespace(basic_config=dict(proxy=dict(http_proxy="http://configured-proxy:1234"))))
        ns["main"](self.bot, config)
        self.handler = handlers["skland_card_order"]

    async def test_sender_query_passes_configured_proxy(self):
        event = SimpleNamespace(pure_text="明日方舟抽卡记录", sender=SimpleNamespace(user_id=100), message_chain=SimpleNamespace(has=lambda kind: False))
        await self.handler(event)
        self.command.assert_awaited_once_with("明日方舟抽卡记录", "100", self.bot, event, proxy="http://configured-proxy:1234")

    async def test_mention_refresh_uses_mentioned_account(self):
        def get(kind):
            return [SimpleNamespace(qq="200")] if kind is self.at else [SimpleNamespace(text="终末地全量更新抽卡记录")]
        event = SimpleNamespace(pure_text="终末地全量更新抽卡记录", sender=SimpleNamespace(user_id=100), message_chain=SimpleNamespace(has=lambda kind: True, get=get))
        await self.handler(event)
        self.command.assert_awaited_once_with("终末地全量更新抽卡记录", "200", self.bot, event, proxy="http://configured-proxy:1234")

    async def test_other_messages_are_ignored(self):
        event = SimpleNamespace(pure_text="明日方舟签到", sender=SimpleNamespace(user_id=100), message_chain=SimpleNamespace(has=lambda kind: False))
        await self.handler(event)
        self.command.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
