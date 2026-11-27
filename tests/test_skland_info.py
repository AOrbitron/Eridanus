"""独立检查森空岛信息入口、终末地网页签名和新旧统计字段。"""
import ast
import asyncio
from datetime import datetime
import hashlib
import hmac
import importlib.util
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import httpx
from PIL import Image as PILImage
from run.anime_game_service.service.skland.core.schemas.ark_models import assist_chars as assist_chars_module
from run.anime_game_service.service.skland.core.schemas.ark_models.buildings.base import Labor

PLUGIN = Path(__file__).resolve().parents[1] / "run/anime_game_service/service/skland"


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text())
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
    return namespace


spec = importlib.util.spec_from_file_location("_endfield_info_model", PLUGIN / "core/schemas/endfield_card.py")
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)
errors = load_functions(PLUGIN / "core/exception.py", {"RequestException", "UnauthorizedException", "LoginException"}, {})
api_ns = load_functions(PLUGIN / "core/api/request.py", {"SklandAPI"}, dict(
    errors, httpx=httpx, hmac=hmac, json=json, hashlib=hashlib, datetime=datetime, urlparse=urlparse,
    base_url="https://zonai.skland.com/api/v1", EndfieldCard=models.EndfieldCard,
))
API = api_ns["SklandAPI"]


def card_data():
    return dict(currentTs="1000", data=dict(
        dungeon=dict(current=120, total=360, maxTs="4600"), bp=dict(current=5, total=60),
        dailyMission=dict(current=60, total=100), weeklyMission=dict(current=4, total=10), signIn=False,
    ))


class ModelTests(unittest.TestCase):
    def test_legacy_fields_and_recovery(self):
        card = models.EndfieldCard.model_validate(card_data())
        self.assertEqual(card.recovery, "1小时0分钟后回满")
        self.assertIn(("体力", "120 / 360"), card.counters)
        self.assertIn(("今日签到", "未签到"), card.counters)

    def test_new_items_override_without_duplicate_and_preserve_new_counter(self):
        data = card_data()
        data["data"]["items"] = [
            dict(id="REALTIME_MODULE_BP_SYSTEM", name="通行证等级", count=dict(current=6, total=60)),
            dict(id="new_count", name="活动进度", count=dict(current=2, total=5)),
            dict(id="new_image", name="轮换活动", image=dict(url="https://example.com/event.png")),
        ]
        card = models.EndfieldCard.model_validate(data)
        self.assertEqual([value for title, value in card.counters if title == "通行证等级"], ["6 / 60"])
        self.assertIn(("活动进度", "2 / 5"), card.counters)
        self.assertEqual(card.data.items[2].image["url"], "https://example.com/event.png")

    def test_unavailable_fields_are_not_zero_or_unsigned(self):
        card = models.EndfieldCard.model_validate(dict(data={}))
        self.assertEqual(set(value for _, value in card.counters), {"未公开"})
        self.assertEqual(card.recovery, "恢复时间未公开")

    def test_full_stamina_and_invalid_timestamp(self):
        data = card_data()
        data["data"]["dungeon"]["current"] = 360
        self.assertEqual(models.EndfieldCard.model_validate(data).recovery, "体力已回满")
        data["data"]["dungeon"].update(current=100, maxTs="invalid")
        self.assertEqual(models.EndfieldCard.model_validate(data).recovery, "恢复时间未公开")

    def test_daily_update_time_uses_beijing_time_and_missing_is_unavailable(self):
        card = models.EndfieldCard.model_validate(card_data())
        self.assertEqual(card.updated_at, "1970-01-01 08:16")
        self.assertEqual(models.EndfieldCard.model_validate(dict(data={})).updated_at, "未公开")

    def test_ark_labor_with_zero_remaining_time_does_not_break_card(self):
        labor = Labor(maxValue=300, value=210, lastUpdateTime=int(datetime.now().timestamp()), remainSecs=0)
        self.assertEqual(labor.labor_now, 210)

    def test_assist_portrait_first_download_returns_usable_cached_path(self):
        with TemporaryDirectory() as temporary_dir:
            cache_dir = Path(temporary_dir)

            def save_image(_url, save_path):
                save_path.parent.mkdir(parents=True, exist_ok=True)
                PILImage.new("RGBA", (1, 1), (255, 255, 255, 255)).save(save_path)

            with patch.object(assist_chars_module, "CACHE_DIR", cache_dir), \
                    patch.object(assist_chars_module, "download_file", side_effect=save_image) as download:
                char = assist_chars_module.AssistChar(
                    charId="char_test", skinId="char_test", level=1, evolvePhase=0,
                    potentialRank=0, skillId="skill_test", mainSkillLvl=1,
                    specializeLevel=0,
                )

                first_path = char.portrait
                self.assertIsInstance(first_path, str)
                self.assertTrue(Path(first_path).is_file())
                with PILImage.open(first_path) as image:
                    self.assertEqual(image.size, (1, 1))
                self.assertEqual(char.portrait, first_path)
                download.assert_called_once()


class APITests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        client_type = httpx.AsyncClient
        def create(**kwargs):
            kwargs.pop("proxy", None)  # 代理参数单独断言，离线请求始终进入 MockTransport。
            return client_type(transport=httpx.MockTransport(handler), **kwargs)
        return patch.object(httpx, "AsyncClient", side_effect=create)

    async def test_web_signature_and_explicit_role_id(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v1/game/endfield/statistic")
            self.assertEqual(request.headers["sk-game-role"], "3_12345_1")
            timestamp = request.headers["timestamp"]
            signed = dict(platform="3", timestamp=timestamp, dId="", vName="1.0.0")
            raw = request.url.path + timestamp + json.dumps(signed, separators=(",", ":"))
            digest = hmac.new(b"sign-token", raw.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(request.headers["sign"], hashlib.md5(digest.encode()).hexdigest())
            self.assertEqual(request.headers["vname"], "1.0.0")
            return httpx.Response(200, json=dict(code=0, data=card_data()))
        with self.client(handler) as factory:
            result = await API.endfield_card(SimpleNamespace(cred="cred", token="sign-token"), "12345", "1", proxy="http://configured-proxy:1234")
        self.assertEqual(result.data.bp.current, 5)
        self.assertEqual(factory.call_args.kwargs["proxy"], "http://configured-proxy:1234")

    async def test_http_401_is_refreshable(self):
        with self.client(lambda request: httpx.Response(401, json=dict(code=10000))):
            with self.assertRaises(errors["UnauthorizedException"]):
                await API.endfield_card(SimpleNamespace(cred="cred", token="old"), "12345")

    async def test_expired_cred_requires_login_refresh(self):
        with self.client(lambda request: httpx.Response(401, json=dict(code=10002))):
            with self.assertRaises(errors["LoginException"]):
                await API.endfield_card(SimpleNamespace(cred="cred", token="old"), "12345")

    async def test_empty_or_failed_statistics_are_not_rendered_as_zero(self):
        for value in (dict(code=0, data=None), dict(code=0, data=dict(data={})), dict(code=50000)):
            with self.client(lambda request: httpx.Response(200, json=value)):
                with self.assertRaises(errors["RequestException"]):
                    await API.endfield_card(SimpleNamespace(cred="cred", token="old"), "12345")


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.role = dict(uid="account-id", roleid="12345", serverid="1", nickname="测试管理员", level=60)
        self.account = dict(skland=dict(user_info=dict(cred="cred", cred_token="old", access_token="account"), character_info=dict(endfield=self.role)))
        self.db = SimpleNamespace(read_user=AsyncMock(side_effect=lambda uid: json.loads(json.dumps(self.account))))
        self.bot = SimpleNamespace(send=AsyncMock())
        login = SimpleNamespace(refresh_token=AsyncMock(return_value="new"))
        self.ns = dict(errors, logger=logging.getLogger("test.info"), db=self.db, SklandLoginAPI=login)
        load_functions(PLUGIN / "core/utils.py", {"refresh_cred_token_if_needed", "refresh_access_token_if_needed"}, self.ns)
        self.ns.update(
            SklandAPI=SimpleNamespace(endfield_card=AsyncMock(return_value=models.EndfieldCard.model_validate(card_data())), ark_card=AsyncMock()),
            CRED=SimpleNamespace, get_background_image=AsyncMock(return_value="bg.png"),
            render_endfield_card=AsyncMock(return_value="card.png"), render_ark_card=AsyncMock(),
            At=lambda **kw: kw, Image=lambda **kw: kw,
        )
        load_functions(PLUGIN / "skland.py", {"skland_info", "endfield_info"}, self.ns)

    async def test_endfield_role_id_and_refreshed_credentials_reach_api(self):
        card = models.EndfieldCard.model_validate(card_data())
        self.ns["SklandAPI"].endfield_card.side_effect = [errors["UnauthorizedException"](), card]
        result = await self.ns["endfield_info"]("1667962668", self.bot, object(), proxy="http://proxy:1234")
        self.assertEqual(result, "card.png")
        calls = self.ns["SklandAPI"].endfield_card.await_args_list
        self.assertEqual([call.args[0].token for call in calls], ["old", "new"])
        self.assertEqual(calls[1].args[1:], ("12345", "1"))
        self.assertEqual(calls[1].kwargs["proxy"], "http://proxy:1234")
        self.ns["SklandAPI"].ark_card.assert_not_awaited()

    async def test_missing_game_role_has_clear_hint(self):
        self.account["skland"]["character_info"]["endfield"] = {}
        await self.ns["endfield_info"]("1667962668", self.bot, object())
        self.ns["SklandAPI"].endfield_card.assert_not_awaited()
        self.assertIn("未找到终末地角色", str(self.bot.send.await_args))


class RenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_activity_and_all_counters_reach_drawing(self):
        drawing = AsyncMock(return_value="card.png")
        ns = load_functions(PLUGIN / "core/render.py", {"render_endfield_card"}, dict(manshuo_draw=drawing, card_img_dir=Path("icons")))
        data = card_data()
        data["data"]["items"] = [dict(id="activity", name="轮换活动", image=dict(url="https://example.com/activity.png"))]
        await ns["render_endfield_card"](models.EndfieldCard.model_validate(data), dict(nickname="管理员", roleid="12345", level=60), "bg.png")
        config = drawing.await_args.args[0]
        self.assertEqual(config[0]["img_path_save"], "data/pictures/cache")
        self.assertIsNone(config[0]["img_name_save"])
        content = json.dumps(config, ensure_ascii=False)
        daily_header = next(item for item in config if isinstance(item, dict)
                            and item.get("type") == "text" and "每日信息" in str(item.get("content")))
        # 通用 text 绘图只消费 content[0]，数据时间必须位于同一段内容中。
        self.assertEqual(len(daily_header["content"]), 1)
        self.assertIn("更新于", daily_header["content"][0])
        for text in ("120 / 360", "60 / 100", "4 / 10", "5 / 60", "未签到", "轮换活动", "https://example.com/activity.png", "UID:12345", "每日信息", "1970-01-01 08:16"):
            self.assertIn(text, content)

    async def test_ark_status_panel_uses_three_columns(self):
        def obj(**values):
            return SimpleNamespace(**values)

        reward = obj(current=1, total=2)
        building = obj(
            furniture=obj(total=0),
            labor=obj(labor_now=1, maxValue=2),
            rested_chars=0, dorm_chars=0, trading_stock=0, trading_stock_limit=0,
            manufacture_stoke=obj(current=0, total=0), tiredChars=[],
            meeting=obj(clue=obj(board=[])), hire=obj(refreshCount=1),
            training=obj(training_state="空闲"),
        )
        props = obj(
            status=obj(avatar=obj(url="avatar.png"), name="博士", level=1, uid="1",
                       register_time="2020-01-01", mainStageProgress="1-1",
                       ap=obj(ap_now=1, max=2)),
            chars=[], skins=[], building=building, medal=obj(total=0), assistChars=[],
            recruit_finished=0, recruit=[], recruit_complete_time=None, campaign=obj(reward=reward),
            routine=obj(daily=reward, weekly=reward),
            tower=obj(reward=obj(higherItem=reward, lowerItem=reward)), trainee_char="无",
        )
        drawing = AsyncMock(return_value="card.png")
        namespace = load_functions(
            PLUGIN / "core/render.py", {"render_ark_card"},
            dict(datetime=datetime, career_dir=Path("career"), Building_Dir=Path("building"),
                 card_img_dir=Path("cards"), manshuo_draw=drawing),
        )

        await namespace["render_ark_card"](props, "background.png")

        draw_items = drawing.await_args.args[0]
        status_panel = next(item for item in draw_items if isinstance(item, dict)
                            and item.get("type") == "img" and "理智\n1 / 2" in item.get("content", []))
        self.assertEqual(status_panel["number_per_row"], 3)
        self.assertEqual(len(status_panel["content"]), 9)


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handlers = {}
        self.at, self.text = object(), object()
        self.ark, self.endfield = AsyncMock(), AsyncMock()
        self.guide = AsyncMock()
        def on(event_type):
            def register(function):
                self.handlers[function.__name__] = function
                return function
            return register
        self.bot = SimpleNamespace(on=on, send=AsyncMock(return_value=dict(data=dict(message_id=99))), recall=AsyncMock())
        self.ns = dict(GroupMessageEvent=object, At=self.at, Text=self.text, skland_info=self.ark,
                       endfield_info=self.endfield, handle_skland_guide_command=self.guide)
        load_functions(PLUGIN.parents[1] / "skland.py", {"main"}, self.ns)
        self.ns["main"](self.bot, SimpleNamespace(common_config=SimpleNamespace(basic_config=dict(proxy=dict(http_proxy=None)))))

    def event(self, text):
        return SimpleNamespace(pure_text=text, sender=SimpleNamespace(user_id=1667962668), message_chain=SimpleNamespace(has=lambda kind: False))

    async def test_all_new_ark_aliases_and_old_aliases_removed(self):
        handler = self.handlers["ark_info_order"]
        for text in ("我的明日方舟", "我的方舟", "我的方舟z", "明日方舟信息"):
            await handler(self.event(text))
        self.assertEqual(self.ark.await_count, 4)
        for text in ("我的森空岛", "森空岛信息", "森空岛info", "sklandinfo", "终末地信息"):
            await handler(self.event(text))
        self.assertEqual(self.ark.await_count, 4)
        self.endfield.assert_not_awaited()

    async def test_endfield_mention_and_progress_recalled_on_failure(self):
        event = self.event("终末地信息")
        event.message_chain = SimpleNamespace(has=lambda kind: True, get=lambda kind: [SimpleNamespace(qq="200")] if kind is self.at else [SimpleNamespace(text="终末地信息")])
        self.endfield.side_effect = RuntimeError("test failure")
        with self.assertRaises(RuntimeError):
            await self.handlers["endfield_info_order"](event)
        self.endfield.assert_awaited_once_with("200", self.bot, event, proxy=None)
        self.bot.recall.assert_awaited_once_with(99)

    async def test_supported_aliases_reuse_endfield_info(self):
        aliases = ("终末地信息", "我的终末地", "终末地便笺")
        for text in aliases:
            await self.handlers["endfield_info_order"](self.event(text))
        self.assertEqual(self.endfield.await_count, len(aliases))
        for text in ("终末地每日", "终末地每日信息", "终末地日常", "终末地实时便笺", "终末地当前状态"):
            await self.handlers["endfield_info_order"](self.event(text))
        self.assertEqual(self.endfield.await_count, len(aliases))
        self.ark.assert_not_awaited()

    async def test_guide_event_is_wired_to_public_handler(self):
        for text in ("明日方舟干员图鉴能天使", "方舟干员攻略能天使", "明日方舟模组图鉴能天使",
                     "方舟模组攻略能天使", "终末地武器图鉴落草", "终末地武器攻略落草 不知归"):
            with self.subTest(text=text):
                self.guide.reset_mock()
                event = self.event(text)
                await self.handlers["skland_guide_order"](event)
                self.guide.assert_awaited_once_with(event.pure_text, "1667962668", self.bot, event, proxy=None)


if __name__ == "__main__":
    unittest.main()
