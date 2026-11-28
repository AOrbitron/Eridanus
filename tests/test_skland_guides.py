"""图鉴与基质移植的离线检查，不加载账号数据库或调用游戏接口。"""
import ast
import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

PLUGIN = Path(__file__).resolve().parents[1] / "run/anime_game_service/service/skland"
PACKAGE = "_skland_guides_tests"
package = ModuleType(PACKAGE)
package.__path__ = [str(PLUGIN)]
sys.modules[PACKAGE] = package
commands = ModuleType(f"{PACKAGE}.command")
commands.__path__ = [str(PLUGIN / "command")]
sys.modules[commands.__name__] = commands
card_stub = ModuleType(f"{commands.__name__}.card")
for node in ast.parse((PLUGIN / "command/card.py").read_text()).body:
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "GAME_ALIASES" for target in node.targets):
        card_stub.GAME_ALIASES = ast.literal_eval(node.value)
sys.modules[card_stub.__name__] = card_stub
guide = importlib.import_module(f"{PACKAGE}.command.guide")
resource = importlib.import_module(f"{PACKAGE}.utils.guide_resource")
wiki = importlib.import_module(f"{PACKAGE}.utils.arknights_wiki")
image = importlib.import_module(f"{PACKAGE}.utils.guide_image")
draw_wiki = importlib.import_module(f"{PACKAGE}.utils.draw_wiki")
gem = importlib.import_module(f"{PACKAGE}.utils.draw_gem")
data_models = importlib.import_module(f"{PACKAGE}.utils.endfield_gamedata.weapon_gem_info")


def ark_tables():
    return {
        "character_table": {"char_test": dict(name="测试干员", appellation="Test Operator", rarity="TIER_6",
            profession="SNIPER", position="RANGED", subProfessionId="marksman", description="治疗{value}点",
            trait=dict(candidates=[dict(blackboard=[dict(key="value", value=70)])]),
            phases=[dict(maxLevel=90, attributesKeyFrames=[dict(data=dict(atk=540, maxHp=1000, **{"def": 160}))])],
            skills=[dict(skillId="skchr_test")], talents=[], potentialRanks=[], favorKeyFrames=[])} ,
        "skill_table": {"skchr_test": dict(levels=[dict(name="测试技能", skillType="AUTO", duration=4,
            spData=dict(spType="INCREASE_WITH_TIME", initSp=1, spCost=4),
            description="攻击力{atk:0%}，持续{duration}秒", blackboard=[dict(key="atk", value=1.1)])])},
        "uniequip_table": dict(subProfDict=dict(marksman=dict(subProfessionName="速射手")),
            charEquip=dict(char_test=["uniequip_test"]), equipDict=dict(uniequip_test=dict(uniEquipName="测试模组"))),
        "battle_equip_table": {"uniequip_test": dict(phases=[dict(equipLevel=i,
            attributeBlackboard=[dict(key="atk", value=10*i)], parts=[dict(target="TALENT_DATA_ONLY",
                addOrOverrideTalentDataBundle=dict(candidates=[dict(requiredPotentialRank=0,
                    upgradeDescription="加成{atk:0%}", blackboard=[dict(key="atk", value=0.1*i)])]))]) for i in range(1,4)])},
    }


class ParserTests(unittest.TestCase):
    def test_prefix_suffix_and_game_aliases(self):
        for game in ("明日方舟", "方舟"):
            for category, kind in (("干员", "operator"), ("模组", "module")):
                for action in ("图鉴", "攻略"):
                    for text in (f"{game}{category}{action}能天使", f"{game}能天使{category}{action}",
                                 f"{game} {category} {action}：能天使"):
                        with self.subTest(text=text):
                            self.assertEqual(guide.parse_guide_command(text), ("arknights", kind, "能天使"))
        for action in ("图鉴", "攻略"):
            for text in (f"终末地武器{action}落草 不知归", f"终末地落草 不知归武器{action}",
                         f"终末地 武器 {action}：落草 不知归"):
                with self.subTest(text=text):
                    self.assertEqual(guide.parse_guide_command(text), ("endfield", "gem", "落草 不知归"))
        for text, expected in [
            ("明日方舟 干员图鉴：能天使", ("arknights", "operator", "能天使")),
            ("ARK 能天使模组攻略", ("arknights", "module", "能天使")),
            ("明日方舟：终末地 落草 不知归武器图鉴", ("endfield", "gem", "落草 不知归")),
            ("方舟干员攻略", ("arknights", "operator", "")),
            ("终末地武器图鉴", ("endfield", "gem", "")),
            ("Endfield 资源更新", ("endfield", "update", "")),
        ]:
            self.assertEqual(guide.parse_guide_command(text), expected, text)

    def test_unrelated_games_or_wrong_game_feature_ignored(self):
        for text in ("原神干员图鉴能天使", "明日方舟武器攻略落草", "方舟武器图鉴落草",
                     "终末地模组图鉴能天使", "终末地干员攻略能天使", "森空岛签到", "终末地抽卡记录",
                     "终末地武器基质落草", "终末地武器基质副本落草", "终末地武器刷什么基质落草",
                     "明日方舟角色图鉴能天使"):
            self.assertIsNone(guide.parse_guide_command(text), text)


class WikiTests(unittest.TestCase):
    def test_game_percent_formats_negative_and_case_insensitive_keys(self):
        self.assertEqual(wiki.format_description("<@x>{ATK:0%}</> / {-atk:0.0%} / {atk:0.00}",
                         [dict(key="atk", value=1.1)]), "110% / -110.0% / 1.10")

    def test_operator_raw_enums_trait_and_duration_substitution(self):
        tables = ark_tables()
        cid, _ = wiki.find_operator(tables, "Test Operator")
        sections = dict(wiki.operator_sections(tables, cid))
        body = "\n".join(sections.values())
        for expected in ("★★★★★★", "治疗70点", "防御 160", "自动回复 / 自动触发", "攻击力110%，持续4秒"):
            self.assertIn(expected, body)
        self.assertNotIn("未公开", body)

    def test_duplicate_names_require_explicit_id(self):
        tables = ark_tables()
        tables["character_table"]["char_other"] = copy.deepcopy(tables["character_table"]["char_test"])
        with self.assertRaisesRegex(resource.GuideError, "同名"):
            wiki.find_operator(tables, "测试干员")
        self.assertEqual(wiki.find_operator(tables, "char_other")[0], "char_other")

    def test_modules_keep_all_levels_and_data_only_descriptions(self):
        sections = wiki.module_sections(ark_tables(), "char_test")
        self.assertEqual(len(sections), 3)
        for index, (title, body) in enumerate(sections, 1):
            self.assertIn(f"等级 {index}", title)
            self.assertIn(f"攻击 +{index*10}", body)
            self.assertIn(f"加成{index*10}%", body)

    def test_no_module_has_clear_message(self):
        tables = ark_tables()
        tables["uniequip_table"]["charEquip"] = {}
        self.assertEqual(wiki.module_sections(tables, "char_test"), [("模组图鉴", "该干员暂无可查询模组")])


class ResourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_update_preserves_entire_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(resource, "ROOT", Path(folder)):
            resource._save_tables("arknights", ark_tables())
            before = resource.resource_path("arknights").read_bytes()
            def handler(request):
                name = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
                return httpx.Response(200, json={} if name == "battle_equip_table" else ark_tables()[name])
            client_type = httpx.AsyncClient
            with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler))):
                with self.assertRaises(resource.GuideError):
                    await resource.ensure_guide_resources("arknights", force=True)
            self.assertEqual(resource.resource_path("arknights").read_bytes(), before)
            self.assertFalse(list(Path(folder).rglob("*.tmp")))

    async def test_first_queries_share_download_and_later_queries_reuse_only_game_tables(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(resource, "ROOT", Path(folder)), patch.object(resource, "_LOCKS", {}):
            requested = []
            def handler(request):
                name = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
                requested.append(name)
                return httpx.Response(200, json=ark_tables()[name])
            client_type = httpx.AsyncClient
            with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler))):
                values = await asyncio.gather(*(resource.ensure_guide_resources("arknights") for _ in range(3)))
                self.assertEqual(len(requested), 4)
                self.assertEqual(values[0], ark_tables())
                self.assertEqual(await resource.ensure_guide_resources("arknights"), values[0])
                self.assertEqual(len(requested), 4)


class GemTests(unittest.TestCase):
    def recommendations(self, *, both=True):
        point = data_models.WeaponGemEnergyPointData(point_id="point", point_name="重度能量淤积点·测试",
            primary_term_ids=["p1", "p2", "p3", "p4"], guaranteed_secondary_term_ids=["s1", "s2"],
            guaranteed_skill_term_ids=["skill"] if both else [], world_level=7)
        return [data_models.WeaponGemRecommendationData(weapon=data_models.WeaponDetailData(id=f"wpn_{i}", name=f"武器{i}"),
            perfect_gem=data_models.WeaponGemPresetData(gem_id=f"gem{i}"), recommended_primary_term_ids=[f"p{i}"],
            recommended_secondary_term_ids=[f"s{i}"], recommended_skill_term_ids=["skill"],
            recommended_energy_points=[point], best_energy_point=point) for i in (1,2)]

    def test_full_plan_obeys_three_primary_and_one_extra_lock(self):
        data = self.recommendations()
        plans = gem._select_display_plans(gem._select_multi_point_plans(data), data)
        self.assertTrue(plans)
        self.assertLessEqual(len(plans[0].locked_primary_ids), 3)
        self.assertEqual(plans[0].locked_lock_term_id, "skill")
        self.assertEqual(set(plans[0].lock_covered_weapon_names), {"武器1", "武器2"})
        self.assertTrue(gem._is_full_input_plan(plans[0], data))

    def test_incompatible_fourth_terms_do_not_claim_full_coverage(self):
        data = self.recommendations(both=False)
        plans = gem._select_multi_point_plans(data)
        self.assertTrue(plans)
        self.assertFalse(any(gem._is_full_input_plan(plan, data) for plan in plans))

    def test_multi_query_deduplicates_and_keeps_unknown_names(self):
        a, b = self.recommendations()
        with patch.object(data_models.WeaponGemInfoTable, "get_by_weapon_name", side_effect=lambda name: {"武器1":a, "武器2":b}.get(name)):
            result, missing = guide.query_gems("武器1，武器1 武器2 未知")
            self.assertEqual([item.weapon.id for item in result], ["wpn_1", "wpn_2"])
            self.assertEqual(missing, ["未知"])
            with self.assertRaises(resource.GuideError):
                guide.query_gems("不存在")


class DrawingTests(unittest.TestCase):
    def test_long_wiki_paginated_without_dropping_final_text_and_redrawn_every_time(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(image, "OUTPUT_DIR", Path(folder)), patch.object(draw_wiki, "load_icon", return_value=None):
            sections = [("长图", "\n".join(f"第{i}行" for i in range(200)))]
            original = draw_wiki.ImageDraw.ImageDraw.text
            texts = []
            def track(draw, xy, text, *args, **kwargs):
                texts.append(text)
                return original(draw, xy, text, *args, **kwargs)
            with patch.object(draw_wiki.ImageDraw.ImageDraw, "text", track):
                first = draw_wiki.render_wiki("char_test", "测试", "干员图鉴", sections)
            second = draw_wiki.render_wiki("char_test", "测试", "干员图鉴", sections)
            self.assertGreater(len(first), 1)
            self.assertFalse(set(first) & set(second))
            self.assertIn("第199行", texts)
            for path in first + second:
                self.assertEqual(Path(path).parent, Path(folder))
                with Image.open(path) as im:
                    self.assertLessEqual(im.height, draw_wiki.MAX_HEIGHT)
                    self.assertEqual(im.width, 1120)


if __name__ == "__main__":
    unittest.main()
