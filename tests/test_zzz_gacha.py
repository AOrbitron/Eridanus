"""独立验证双接口抽卡合并，避免导入插件触发应用启动。"""

import ast
import asyncio
import copy
from datetime import datetime
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "run/anime_game_service/service/mihuyo_club"
spec = importlib.util.spec_from_file_location("zzz_gacha", PLUGIN / "utils/zzz_gacha.py")
gacha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gacha)
POOL = "独家频段"
EPOCH = 1700000000


def card_namespace(extra_names=()):
    """加载实际函数但跳过带应用启动副作用的包初始化。"""
    names = {
        "GachaRequestError", "_record_id", "_sort_records", "_summary", "_gacha_summaries",
        "_cache_path", "_load_cache_sync", "_write_cache_sync", "refresh_zzz_gacha_records",
    } | set(extra_names)
    tree = ast.parse((PLUGIN / "command/card.py").read_text())
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names]
    ns = dict(asyncio=asyncio, datetime=datetime, json=json, Path=Path, shutil=shutil, uuid4=uuid4,
              httpx=httpx, logger=logging.getLogger("test.zzz_gacha"),
              merge_pool_summary=gacha.merge_pool_summary,
              has_statistics_overlap=gacha.has_statistics_overlap,
              POOL_CONFIG=tuple((name, "", str(ids[0])) for name, ids in gacha.POOL_TYPES.items()))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id in {"NORMAL_ZZZ_S_ITEMS", "POOL_CONFIG"}:
                ns[target.id] = ast.literal_eval(node.value)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(PLUGIN / "command/card.py"), "exec"), ns)
    return ns


def snapshot(positions=(30, 60, 110), total=120, same_time=False):
    stats = []
    for name, (_, type_name) in gacha.POOL_TYPES.items():
        stats.append(dict(gacha_type=type_name, total_count=str(total if name == POOL else 0),
                          s_count=str(len(positions) if name == POOL else 0), up_count="0",
                          next_s_cur_times=total - positions[-1] if name == POOL and positions else total if name == POOL else 0,
                          has_data_vers=["1.0"]))
    events = []
    previous = 0
    for position in positions:
        events.append(dict(item_id="1011", name="测试代理人", rarity="S", is_up=True,
                           sort=str(position), count=str(position - previous),
                           record_time=str(EPOCH + (0 if same_time else position))))
        previous = position
    return dict(index=dict(type_stats=stats), pools={POOL: dict(current=[], history=[dict(cur_records=events)])})


def raw_records(start=90, end=120, s_positions=(110,), same_time=False):
    return [dict(id=str(position), item_id="1011", name="测试代理人", item_type="角色",
                 rank_type="4" if position in s_positions else "2",
                 time=datetime.fromtimestamp(EPOCH + (0 if same_time else position), gacha.CN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"))
            for position in range(end, start - 1, -1)]


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.ns = card_namespace()

    def merge(self, stats, records=()):
        return self.ns["_gacha_summaries"](dict(data={POOL: list(records)}, statistics=stats))[POOL]

    def test_statistics_only_complete_history(self):
        result = self.merge(snapshot())
        self.assertEqual((result["total"], result["pity"], result["average"]), (120, 10, 36.67))
        self.assertEqual([item["_position"] for item in result["s_items"]], [110, 60, 30])

    def test_overlap_is_not_counted_twice(self):
        result = self.merge(snapshot(), raw_records())
        self.assertEqual((result["total"], result["pity"], len(result["s_items"])), (120, 10, 3))
        self.assertEqual(result["s_items"][0]["_pull_count"], 50)
        self.assertEqual(result["warnings"], [])

    def test_legacy_tail_extends_official_statistics(self):
        result = self.merge(snapshot(), raw_records(end=130, s_positions=(110, 125)))
        self.assertEqual((result["total"], result["pity"], len(result["s_items"])), (130, 5, 4))
        self.assertEqual(result["s_items"][0]["_pull_count"], 15)

    def test_same_second_same_character_keeps_each_pull(self):
        result = self.merge(snapshot((70, 71), 72, True), raw_records(65, 72, (70, 71), True))
        self.assertEqual(len(result["s_items"]), 2)
        self.assertEqual([item["_pull_count"] for item in result["s_items"]], [1, 70])

    def test_current_history_overlap_is_deduplicated(self):
        stats = snapshot()
        stats["pools"][POOL]["current"] = copy.deepcopy(stats["pools"][POOL]["history"])
        gacha.validate_statistics(stats)
        self.assertEqual(len(self.merge(stats)["s_items"]), 3)

    def test_unaligned_local_s_is_retained_with_unknown_count(self):
        result = self.merge(snapshot(), raw_records(125, 130, (125,)))
        self.assertEqual(len(result["s_items"]), 4)
        self.assertTrue(result["s_items"][0]["_count_incomplete"])
        self.assertIsNone(result["average"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["pity"], 5)

    def test_no_statistics_uses_legacy(self):
        result = self.merge({}, raw_records())
        self.assertEqual((result["total"], result["pity"], len(result["s_items"])), (31, 10, 1))

    def test_incomplete_history_rejected(self):
        stats = snapshot()
        stats["pools"][POOL]["history"][0]["cur_records"].pop(0)
        with self.assertRaises(gacha.GachaStatisticsError):
            gacha.validate_statistics(stats)

    def test_inconsistent_total_rejected(self):
        stats = snapshot()
        stats["index"]["type_stats"][1]["total_count"] = "121"
        with self.assertRaises(gacha.GachaStatisticsError):
            gacha.validate_statistics(stats)

    def test_duplicate_position_conflict_rejected(self):
        stats = snapshot()
        duplicate = copy.deepcopy(stats["pools"][POOL]["history"])
        duplicate[0]["cur_records"][0]["item_id"] = "2022"
        stats["pools"][POOL]["current"] = duplicate
        with self.assertRaises(gacha.GachaStatisticsError):
            gacha.validate_statistics(stats)

    def test_permanent_pool_weapon_keeps_type_and_is_not_up(self):
        stats = snapshot()
        event = stats["pools"][POOL]["history"][0]["cur_records"][0]
        stats["index"]["type_stats"][2].update(total_count="1", s_count="1", next_s_cur_times="0")
        stats["pools"]["常驻频段"] = {"current": [], "history": [dict(cur_records=[
            dict(event, sort="1", count="1", item_type="ItemType_Weapon")
        ])]}
        merged = self.ns["_gacha_summaries"](dict(statistics=stats))["常驻频段"]
        self.assertFalse(merged["s_items"][0]["_is_up"])
        self.assertEqual(merged["s_items"][0]["item_type"], "音擎")
        self.assertIsNone(merged["average_up"])


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_chunking_and_current_deduplication(self):
        stats = snapshot()
        stats["index"]["type_stats"][1]["has_data_vers"] = [str(i) for i in range(10)]
        requests = []

        def handle(request):
            requests.append(request)
            if request.url.path.endswith("/index"):
                data = stats["index"]
            else:
                data = {"list": stats["pools"][POOL]["history"]}
            return httpx.Response(200, json=dict(retcode=0, data=data))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            actual = await gacha.fetch_gacha_statistics(client, "123", "prod_gf_cn", {}, {}, 5)
        history = [r for r in requests if r.url.path.endswith("/hist_pool_stat")]
        self.assertEqual([len(r.url.params["vers"].split(",")) for r in history], [8, 2])
        self.assertEqual(len(requests), 4)
        self.assertTrue(actual["updated_at"])

    async def test_api_error_rejected(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=dict(retcode=-100, data=None)))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(gacha.GachaStatisticsError):
                await gacha.fetch_gacha_statistics(client, "123", "prod_gf_cn", {}, {}, 5)


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ns = card_namespace()
        self.ns.update(PLAYER_ROOT=Path(self.directory.name), _proxy_options=lambda proxy: {},
                       _request_timeout=lambda: 1, _region_for_uid=lambda uid: "prod_gf_cn",
                       _account_cookies=lambda account: {}, plugin_env=SimpleNamespace(device_config=SimpleNamespace(USER_AGENT_MOBILE="test")))
        self.new_api = AsyncMock(return_value=snapshot())
        self.old_api = AsyncMock(return_value=({POOL: raw_records()}, 31, []))
        self.ns.update(fetch_gacha_statistics=self.new_api, _fetch_and_merge=self.old_api,
                       _get_authkey=AsyncMock(return_value="test-key"))
        self.path = self.ns["_cache_path"]("123")

    def save(self, stats=True, legacy_time=True):
        payload = dict(uid="123", data={POOL: raw_records()}, untouched="preserved")
        if stats:
            payload["statistics"] = snapshot()
        if legacy_time:
            payload["legacy_data_time"] = "previous"
        self.ns["_write_cache_sync"]("123", payload, False)
        return payload

    async def refresh(self, full=False, statistics_only=False):
        return await self.ns["refresh_zzz_gacha_records"](
            object(), "123", full_refresh=full, statistics_only=statistics_only
        )

    async def test_first_automatic_fetch_only_requests_statistics(self):
        added, total, warnings = await self.refresh(statistics_only=True)
        self.assertEqual((added, total, warnings), (120, 120, []))
        payload = json.loads(self.path.read_text())
        self.assertIn("statistics", payload)
        self.assertNotIn("legacy_data_time", payload)
        self.assertEqual(payload["data"], {})
        self.old_api.assert_not_awaited()
        self.ns["_get_authkey"].assert_not_awaited()

    async def test_normal_refresh_only_calls_legacy_and_reports_zero_changes(self):
        self.save()
        added, total, _ = await self.refresh()
        self.assertEqual((added, total), (0, 120))
        self.new_api.assert_not_awaited()
        self.old_api.assert_awaited_once()
        self.assertEqual(json.loads(self.path.read_text())["untouched"], "preserved")

    async def test_statistics_only_cache_uses_incremental_legacy_with_overlap(self):
        payload = dict(uid="123", data={}, statistics=snapshot())
        self.ns["_write_cache_sync"]("123", payload, False)
        await self.refresh()
        self.new_api.assert_not_awaited()
        self.old_api.assert_awaited_once()
        self.assertFalse(self.old_api.call_args.args[-1])
        self.assertEqual(self.old_api.call_args.kwargs["statistics"], payload["statistics"])

    async def test_first_manual_normal_update_only_uses_legacy(self):
        added, total, warnings = await self.refresh()
        self.assertEqual((added, total, warnings), (31, 31, []))
        self.new_api.assert_not_awaited()
        self.old_api.assert_awaited_once()

    async def test_full_refresh_calls_both_and_keeps_backup(self):
        self.save()
        await self.refresh(True)
        self.new_api.assert_awaited_once()
        self.old_api.assert_awaited_once()
        self.assertTrue(self.old_api.call_args.args[-1])
        self.assertTrue(list((self.path.parent / "backup").glob("*.json")))

    async def test_existing_legacy_cache_normal_update_only_uses_legacy(self):
        self.save(stats=False, legacy_time=False)
        await self.refresh()
        self.new_api.assert_not_awaited()
        self.old_api.assert_awaited_once()
        self.assertFalse(self.old_api.call_args.args[-1])

    async def test_full_new_failure_still_updates_legacy_and_keeps_statistics(self):
        payload = self.save()
        self.new_api.side_effect = httpx.ConnectError("offline")
        self.old_api.return_value = ({POOL: raw_records(end=130, s_positions=(110, 125))}, 10, [])
        added, total, warnings = await self.refresh(full=True)
        self.assertEqual((added, total), (10, 130))
        self.assertTrue(warnings)
        self.assertEqual(json.loads(self.path.read_text())["statistics"], payload["statistics"])
        self.assertTrue(self.old_api.call_args.args[-1])

    async def test_automatic_new_failure_never_calls_legacy(self):
        self.new_api.side_effect = httpx.ConnectError("offline")
        with self.assertRaises(self.ns["GachaRequestError"]):
            await self.refresh(statistics_only=True)
        self.old_api.assert_not_awaited()
        self.assertFalse(self.path.exists())

    async def test_normal_legacy_failure_does_not_call_new_or_write_cache(self):
        self.save()
        before = self.path.read_bytes()
        self.old_api.side_effect = self.ns["GachaRequestError"]("offline")
        with self.assertRaises(self.ns["GachaRequestError"]):
            await self.refresh()
        self.new_api.assert_not_awaited()
        self.assertEqual(self.path.read_bytes(), before)

    async def test_old_failure_still_saves_new_statistics(self):
        self.old_api.side_effect = self.ns["GachaRequestError"]("offline")
        _, total, warnings = await self.refresh(True)
        self.assertEqual(total, 120)
        self.assertTrue(warnings)
        self.assertIn("statistics", json.loads(self.path.read_text()))
        self.assertNotIn("legacy_data_time", json.loads(self.path.read_text()))

    async def test_both_fail_cache_unchanged(self):
        self.save()
        before = self.path.read_bytes()
        self.new_api.side_effect = httpx.ConnectError("offline")
        self.old_api.side_effect = self.ns["GachaRequestError"]("offline")
        with self.assertRaises(self.ns["GachaRequestError"]):
            await self.refresh(True)
        self.assertEqual(self.path.read_bytes(), before)


class PagingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = card_namespace({"_fetch_and_merge"})
        self.ns.update(POOL_CONFIG=((POOL, "2001", "2"),), OPTIONAL_POOLS=set(),
                       MAX_PAGES_PER_POOL=999, PAGE_INTERVAL=0)
        self.rows = raw_records(1, 130, (30, 60, 110, 125))

        async def get_page(client, uid, authkey, gacha_type, base_type, page, end_id):
            return self.rows[(page - 1) * 20:page * 20]

        self.pages = AsyncMock(side_effect=get_page)
        self.ns["_get_gacha_page"] = self.pages

    async def fetch(self, existing=None, statistics=None, full=False):
        data, _, warnings = await self.ns["_fetch_and_merge"](
            None, "123", "test-key", existing or {}, full, statistics=statistics
        )
        self.assertFalse(warnings)
        return data

    async def test_statistics_only_history_stops_at_first_matching_s_page(self):
        data = await self.fetch(statistics=snapshot())
        self.assertEqual(self.pages.await_count, 2)
        self.assertEqual(len(data[POOL]), 40)
        summary = self.ns["_gacha_summaries"](dict(data=data, statistics=snapshot()))[POOL]
        self.assertEqual((summary["total"], summary["pity"], len(summary["s_items"])), (130, 5, 4))
        self.assertFalse(summary["warnings"])

    async def test_existing_legacy_id_stops_first_page(self):
        data = await self.fetch(existing={POOL: raw_records(100, 120)}, statistics=snapshot())
        self.assertEqual(self.pages.await_count, 1)
        self.assertEqual(len(data[POOL]), 31)

    async def test_full_refresh_ignores_both_overlap_markers(self):
        data = await self.fetch(existing={POOL: raw_records()}, statistics=snapshot(), full=True)
        self.assertEqual(self.pages.await_count, 8)
        self.assertEqual(len(data[POOL]), 130)

    async def test_without_overlap_reads_all_available_history(self):
        data = await self.fetch(statistics=snapshot((), 120))
        self.assertEqual(self.pages.await_count, 8)
        self.assertEqual(len(data[POOL]), 130)

    async def test_non_s_item_with_same_identity_does_not_stop_pagination(self):
        for item in self.rows:
            if item["id"] == "110":
                item["rank_type"] = "2"
        await self.fetch(statistics=snapshot())
        self.assertEqual(self.pages.await_count, 4)


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_legacy_cache_draws_without_automatic_update(self):
        with tempfile.TemporaryDirectory() as directory:
            ns = card_namespace({"_handle_action"})
            path = Path(directory) / "card.png"
            path.write_bytes(b"test")
            ns.update(PLAYER_ROOT=Path(directory), _UID_LOCKS={}, _send_text=AsyncMock(),
                      _render_gacha_card=AsyncMock(return_value=path),
                      At=lambda **kwargs: kwargs, Image=lambda **kwargs: kwargs)
            ns["refresh_zzz_gacha_records"] = AsyncMock(side_effect=ns["GachaRequestError"]("offline"))
            payload = dict(data={POOL: raw_records()})
            ns["_write_cache_sync"]("123", payload, False)
            before = ns["_cache_path"]("123").read_bytes()
            bot = SimpleNamespace(send=AsyncMock())
            await ns["_handle_action"]("show", "123", object(), "123", bot, object(), None, False)
            ns["refresh_zzz_gacha_records"].assert_not_awaited()
            ns["_render_gacha_card"].assert_awaited_once()
            bot.send.assert_awaited_once()
            self.assertEqual(ns["_cache_path"]("123").read_bytes(), before)
            self.assertFalse(path.exists())

    async def test_empty_cache_automatically_requests_only_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            ns = card_namespace({"_handle_action"})
            path = Path(directory) / "card.png"
            path.write_bytes(b"test")
            ns.update(PLAYER_ROOT=Path(directory), _UID_LOCKS={}, _send_text=AsyncMock(),
                      _render_gacha_card=AsyncMock(return_value=path),
                      At=lambda **kwargs: kwargs, Image=lambda **kwargs: kwargs)

            async def update(*args, **kwargs):
                self.assertTrue(kwargs["statistics_only"])
                self.assertFalse(kwargs["full_refresh"])
                ns["_write_cache_sync"]("123", dict(data={}, statistics=snapshot()), False)
                return 120, 120, []

            ns["refresh_zzz_gacha_records"] = AsyncMock(side_effect=update)
            bot = SimpleNamespace(send=AsyncMock())
            await ns["_handle_action"]("show", "123", object(), "123", bot, object(), None, False)
            ns["refresh_zzz_gacha_records"].assert_awaited_once()
            ns["_render_gacha_card"].assert_awaited_once()
            self.assertFalse(ns["_send_text"].call_args_list[0].kwargs.get("recall"))


if __name__ == "__main__":
    unittest.main()
