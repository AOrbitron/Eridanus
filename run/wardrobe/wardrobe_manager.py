# -*- coding: utf-8 -*-
"""
Wardrobe Manager (衣橱管理系统)
管理 Bot 服饰配置、当前着装及各条动态独立的 SD 提示词组装。
支持 WebUI (run/wardrobe/config.yaml) 与 Function Calling 协同换装。
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List


try:
    from ruamel.yaml import YAML
    _has_ruamel = True
except ImportError:
    _has_ruamel = False

try:
    import yaml
except ImportError:
    yaml = None

try:
    from framework_common.framework_util.yamlLoader import YAMLManager
    _has_yaml_manager = True
except ImportError:
    _has_yaml_manager = False
    YAMLManager = None

logger = logging.getLogger("Wardrobe")

YAML_CONFIG_PATH = os.path.join("run", "wardrobe", "config.yaml")
OUTFITS_KEY = "outfits_v7"  # Stable configuration key; adding presets does not change it.
RECENT_QZONE_OUTFIT_LIMIT = 3
RETIRED_DAILY_FIELDS = ("today_default_outfit", "today_default_tags", "today_default_no_hat", "last_daily_date")

DEFAULT_CHARACTER_ANCHOR = (
    "1girl, teenager, solo, grey hair, gradient hair, multicolored hair, blue hair, "
    "light purple-light blue mixed eyes, (Side swept hair:1.6), ahoge, bangs, middle long hair, (round face:1.2)"
)

DEFAULT_ART_ANCHOR = (
    "(Rella:1.2), (chen bin:1.3), virtual youtuber, (starshadowmagician:1.2), "
    "masterpiece, extremely detailed, lineart, (hand-drawn:1.3), (sketch:1.2), "
    "Picasso style, Van Gogh's almond blossoms, <lora:DeniaV1-Nuclear1811-IL:0.5>"
)

DEFAULT_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, "
    "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, nsfw"
)



def _read_catalog(doc):
    import copy
    return copy.deepcopy(dict(doc.get(OUTFITS_KEY, {})))


class WardrobeManager:
    _instance: Optional['WardrobeManager'] = None
    _lock = threading.Lock()

    def __init__(self, yaml_path: str = YAML_CONFIG_PATH):
        self.yaml_path = yaml_path
        self._rw_lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._yaml_rt = None
        self._commented_map = None
        self._yaml_manager = None
        self._registered_reload_cb = False
        if _has_ruamel:
            self._yaml_rt = YAML()
            self._yaml_rt.preserve_quotes = True
            self._yaml_rt.indent(mapping=2, sequence=4, offset=2)
        self.load_config()
        self._setup_yaml_manager_listener()

    def _setup_yaml_manager_listener(self) -> None:
        """若存在 YAMLManager，注册重载回调以支持 WebUI 或外部文件修改后的热重载"""
        if not _has_yaml_manager or YAMLManager is None:
            return
        try:
            ym = YAMLManager.get_instance()
            if ym and not self._registered_reload_cb:
                def on_yaml_reload(plugin_name: Optional[str]):
                    if plugin_name == "wardrobe":
                        logger.info("[Wardrobe] 检测到 wardrobe/config.yaml 被外部修改，正在同步热重载...")
                        self.load_config()
                        from run.wardrobe import refresh_function_declarations
                        refresh_function_declarations("wardrobe")
                ym.register_reload_callback(on_yaml_reload)
                self._registered_reload_cb = True
                self._yaml_manager = ym
        except Exception as e:
            logger.debug(f"[Wardrobe] 注册 YAMLManager 监听失败 (可能尚未完全初始化): {e}")

    @classmethod
    def get_instance(cls, yaml_path: str = YAML_CONFIG_PATH) -> 'WardrobeManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = WardrobeManager(yaml_path)
            return cls._instance

    def load_config(self) -> None:
        with self._rw_lock:
            loaded = False
            # 1. 优先使用统一 YAMLManager 实例管理 (支持热重载与 ruamel.yaml 无损注释)
            if self.yaml_path == YAML_CONFIG_PATH and _has_yaml_manager and YAMLManager is not None:
                try:
                    ym = YAMLManager.get_instance()
                    if ym is not None and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                        doc = ym.wardrobe.config
                        if isinstance(doc, dict):
                            self._yaml_manager = ym
                            self._commented_map = doc
                            self._data = dict(doc)
                            if OUTFITS_KEY in self._data:
                                self._data[OUTFITS_KEY] = dict(self._data[OUTFITS_KEY])
                            loaded = True
                            #logger.info("[Wardrobe] 成功接入统一 YAMLManager 管理 wardrobe/config")
                except Exception as e:
                    logger.debug(f"[Wardrobe] 从 YAMLManager 载入失败或未初始化，尝试直接读取: {e}")

            # 2. 独立/回退：使用 ruamel.yaml 直接读取 YAML 配置，严格保留所有注释与排版格式
            if not loaded and self._yaml_rt and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        doc = self._yaml_rt.load(f)
                    if isinstance(doc, dict):
                        self._commented_map = doc
                        self._data = dict(doc)
                        if OUTFITS_KEY in self._data:
                            self._data[OUTFITS_KEY] = dict(self._data[OUTFITS_KEY])
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] ruamel.yaml 加载 YAML 失败: {e}")

            # 2. 回退使用 PyYAML 读取
            if not loaded and yaml and os.path.exists(self.yaml_path):
                try:
                    with open(self.yaml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        self._data = data
                        loaded = True
                except Exception as e:
                    logger.warning(f"[Wardrobe] PyYAML 加载 YAML 失败: {e}")

            if loaded:
                self._data[OUTFITS_KEY] = _read_catalog(self._data)
                for field in RETIRED_DAILY_FIELDS:
                    self._data.pop(field, None)
            if loaded:
                self._data["character_anchor"] = self._data.get("character_anchor", DEFAULT_CHARACTER_ANCHOR)


            # 3. 若均不存在或损坏，初始化默认结构并持久化至 YAML
            if not loaded:
                self._data = self._build_default_data()
                self._save_to_disk()

    def _sync_to_commented_map(self) -> None:
        """将 self._data 的更新同步至 self._commented_map，完整保留原有 YAML 注释"""
        if self._commented_map is None:
            return
        for legacy_key in RETIRED_DAILY_FIELDS:
            if legacy_key in self._commented_map:
                self._commented_map.pop(legacy_key, None)
        for k, v in self._data.items():
            if k == OUTFITS_KEY and isinstance(v, dict):
                if OUTFITS_KEY not in self._commented_map:
                    self._commented_map[OUTFITS_KEY] = {}
                for ok, ov in v.items():
                    if ok not in self._commented_map[OUTFITS_KEY]:
                        self._commented_map[OUTFITS_KEY][ok] = dict(ov)
                    else:
                        if isinstance(ov, dict):
                            for fk, fv in ov.items():
                                self._commented_map[OUTFITS_KEY][ok][fk] = fv
            else:
                self._commented_map[k] = v



    def _save_to_disk(self) -> None:
        """将配置持久化至磁盘，优先通过统一 YAMLManager 保存，保留全部注释与排版"""
        self._sync_to_commented_map()

        # 1. 若当前受 YAMLManager 管理，优先使用 YAMLManager.save_yaml
        if self.yaml_path == YAML_CONFIG_PATH and self._yaml_manager is not None:
            try:
                if hasattr(self._yaml_manager, "data") and "wardrobe" in self._yaml_manager.data:
                    if self._commented_map is not None:
                        self._yaml_manager.data["wardrobe"]["config"] = self._commented_map
                    self._yaml_manager.save_yaml("config", "wardrobe")
                    return
            except Exception as e:
                logger.warning(f"[Wardrobe] 通过 YAMLManager 保存配置失败，回退至独立写盘: {e}")

        # 2. 回退写入 YAML 权威配置文件（使用 ruamel.yaml 保留全部注释与键序，.tmp 原子替换防崩溃）
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.yaml_path)), exist_ok=True)
            tmp_yaml = f"{self.yaml_path}.tmp"
            if self._yaml_rt:
                target_obj = self._commented_map if self._commented_map is not None else self._data
                with open(tmp_yaml, "w", encoding="utf-8") as f:
                    self._yaml_rt.dump(target_obj, f)
                os.replace(tmp_yaml, self.yaml_path)
            elif yaml:
                with open(tmp_yaml, "w", encoding="utf-8") as f:
                    yaml.dump(self._data, f, allow_unicode=True, sort_keys=False)
                os.replace(tmp_yaml, self.yaml_path)
        except Exception as e:
            logger.error(f"[Wardrobe] 保存 YAML 配置失败: {e}")

    def save_config(self) -> None:
        with self._rw_lock:
            self._save_to_disk()

    def is_enabled(self) -> bool:
        with self._rw_lock:
            return bool(self._data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        with self._rw_lock:
            self._data["enabled"] = bool(enabled)
            self._save_to_disk()

    def get_character_anchor(self) -> str:
        with self._rw_lock:
            return self._data.get("character_anchor", DEFAULT_CHARACTER_ANCHOR)

    def get_art_anchor(self) -> str:
        with self._rw_lock:
            return self._data.get("art_anchor", DEFAULT_ART_ANCHOR)

    def get_negative_prompt(self) -> str:
        with self._rw_lock:
            return self._data.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)

    def get_outfits(self) -> Dict[str, Any]:
        with self._rw_lock:
            return dict(self._data.get(OUTFITS_KEY, {}))

    def get_outfit(self, name: str) -> Optional[Dict[str, Any]]:
        with self._rw_lock:
            return self._data.get(OUTFITS_KEY, {}).get(name)

    def get_current_outfit(self) -> Dict[str, Any]:
        with self._rw_lock:
            if not self._data.get("enabled", True):
                name = self._data.get("default_outfit", "常服1")
                outfit = self._data.get(OUTFITS_KEY, {}).get(name, {})
                tags = outfit.get("clothing_tags", "")
                return {
                    "name": name,
                    "clothing_tags": tags,
                    "category": outfit.get("category", "daily"),
                    "no_hat": outfit.get("no_hat", False),
                    "description": outfit.get("description", "")
                }
            name = self._data.get("current_outfit", "常服1")
            outfit = self._data.get(OUTFITS_KEY, {}).get(name, {})
            tags = self._data.get("current_outfit_tags") or outfit.get("clothing_tags", "")
            no_hat = self._data.get("current_outfit_no_hat")
            if no_hat is None:
                no_hat = outfit.get("no_hat", False)
            return {
                "name": name,
                "clothing_tags": tags,
                "category": outfit.get("category", "daily"),
                "no_hat": no_hat,
                "description": outfit.get("description", "")
            }


    def set_current_outfit(self, outfit_name: str, custom_tags: Optional[str] = None, no_hat: Optional[bool] = None) -> bool:
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return False
            outfit = self._data.get(OUTFITS_KEY, {}).get(outfit_name)
            if not outfit and not custom_tags:
                return False
            self._data["current_outfit"] = outfit_name
            if custom_tags is not None:
                self._data["current_outfit_tags"] = custom_tags
            elif outfit:
                self._data["current_outfit_tags"] = outfit.get("clothing_tags", "")
            if no_hat is not None:
                self._data["current_outfit_no_hat"] = no_hat
            elif outfit:
                self._data["current_outfit_no_hat"] = outfit.get("no_hat", False)
            else:
                self._data.pop("current_outfit_no_hat", None)
            self._save_to_disk()
            logger.info(f"[Wardrobe] 当前穿着已切换至: {outfit_name}")
            return True


    def match_outfit(self, query: str):
        """Resolve the exact catalog key already selected by the LLM/tool caller."""
        if not query:
            return None
        return next((key for key in self.get_outfits() if key.casefold() == query.strip().casefold()), None)


    def get_qzone_candidates(self, post_text="", theme_desc="", season_name=""):
        """Expose every usable outfit; semantic selection belongs to the LLM."""
        return {key: obj for key, obj in self.get_outfits().items() if obj.get("clothing_tags")}

    def resolve_qzone_outfit(self, key, post_text="", theme_desc=""):
        """Keep the model's exact key; never replace it by category or usage count."""
        obj = self.get_outfits()[key]
        return {"name": key, "clothing_tags": obj.get("clothing_tags", ""),
                "no_hat": obj.get("no_hat", False), "matched_by": "llm_key"}

    def get_recent_qzone_outfits(self):
        """Return successful pictured posts, oldest first, across task types."""
        with self._rw_lock:
            recent = self._data.get("qzone_outfit_history", [])
            if isinstance(recent, list) and recent:
                return [key for key in recent[-RECENT_QZONE_OUTFIT_LIMIT:] if isinstance(key, str)]
            # Older configs have counts but no chronological history. Seed only
            # the last published outfit; counts cannot reconstruct older order.
            current = self._data.get("current_outfit")
            counts = self._data.get("qzone_outfit_usage", {})
            return [current] if isinstance(current, str) and counts.get(current, 0) > 0 else []

    def record_qzone_outfit_usage(self, key):
        """Called only after a post containing its image has been published."""
        with self._rw_lock:
            if key not in self._data.get(OUTFITS_KEY, {}):
                return
            counts = self._data.setdefault("qzone_outfit_usage", {})
            counts[key] = counts.get(key, 0) + 1
            recent = self._data.get("qzone_outfit_history", [])
            recent = recent if isinstance(recent, list) else []
            self._data["qzone_outfit_history"] = (recent + [key])[-RECENT_QZONE_OUTFIT_LIMIT:]
            self._save_to_disk()

    def pick_base_outfit_for_theme(self, theme_desc="", post_text="", is_first_today=False, season_name=""):
        """Compatibility accessor; never infer clothing from theme or post text."""
        return self.get_current_outfit()

    def update_from_qzone_tags(self, outfit_name: str, clothing_tags: str, no_hat: Optional[bool] = None) -> None:
        """记录该条动态的最终穿搭；后续动态独立交给 LLM 选择。"""
        with self._rw_lock:
            if not self._data.get("enabled", True):
                return
            if not isinstance(clothing_tags, str) or not clothing_tags.strip():
                return
            self._data["current_outfit"] = outfit_name
            self._data["current_outfit_tags"] = clothing_tags
            if no_hat is not None:
                self._data["current_outfit_no_hat"] = no_hat
            logger.info(f"[Wardrobe] Qzone 动态更新当前着装: [{outfit_name}] -> {clothing_tags[:60]}... (no_hat={no_hat})")
            self._save_to_disk()


    def on_post_change_check(self, task_name, post_content="", theme_desc="", selection=None):
        """Apply an explicit LLM selection only; post text cannot trigger a change."""
        if not self.is_enabled() or not selection:
            return None
        self.update_from_qzone_tags(selection["name"], selection["clothing_tags"],
                                    no_hat=selection.get("no_hat", False))
        return selection["name"]

    def get_visual_prompt_section(self) -> str:
        """
        动态生成注入 System Prompt 的视觉与绘图触发规则段落。
        结构严格对应 yucca.txt 原版格式：
        [基础形象设定] + [画风与模型设定] + [当前服装设定] + [绘图原则] + [换装协同规则]
        """
        char_anchor = self.get_character_anchor()
        art_anchor = self.get_art_anchor()

        if not self.is_enabled():
            default_name = self._data.get("default_outfit", "常服1")
            outfit = self._data.get(OUTFITS_KEY, {}).get(default_name, {})
            clothing_tags = outfit.get("clothing_tags", "")
            clothing_header = f"3. 默认服装设定（衣橱未启用，默认穿着: {default_name}）："
        else:
            cur = self.get_current_outfit()
            cur_name = cur.get("name", "常服1")
            clothing_tags = cur.get("clothing_tags", "")
            clothing_header = f"3. 当前服装设定（衣橱当前穿着: {cur_name}）："

        section = f"""# ️ 视觉与绘图触发规则
当你觉得在聊天中合适时，你会时不时发送一张自拍或当前状态的照片给对方。
照片的 Prompt 组合方式：【基础特征】+【画风模型】+【当前的情绪表情】+【当前的服装/场景】+【自拍视角/日常视角】。

Prompt 公式：
[基础形象设定] + [当前情绪/表情] + [当前动作/场景] + [视角与画风]

1. 基础形象设定：
{char_anchor}

2. 画风与模型设定：
{art_anchor}

{clothing_header}
{clothing_tags}

在所有情况下，场景、动作、服饰和表情都不是固定的。在保持角色基本形象锚点的前提下，尽可能通过多样化的形象展示让用户保持新鲜感。

⚠️ 绘图原则与换装规则：
- 构图要有变化（不要全是正面大头照，可以尝试不同视角）。
- 穿搭以当前完整套装为准；睡衣不混入外出毛衣、围巾或靴子；裙装不叠加无关长裤。
- 保留手绘风格 lineart, (hand-drawn:1.3), (sketch:1.2)。
- 调用绘图必须严格遵守函数调用规则，不要直接把提示词丢到正文。
- 【重点·换装联动】：当用户明确要求换装、换衣服、穿上特定服饰，或者在请求自拍/合照时指定了新服装，你在调用绘图工具（call_text2img）生成图片的同时，必须同时调用 call_change_outfit 工具更新衣橱穿着！这样你之后的日常状态和后续照片就会一直保持这套新穿搭。"""
        return section


def get_wardrobe_manager() -> WardrobeManager:
    return WardrobeManager.get_instance()


async def call_change_outfit(bot=None, event=None, config=None, outfit_name: str = "", custom_description: str = "") -> dict:
    """
    Function Calling 工具：切换或更换当前穿着的服装/衣橱搭配。
    当用户要求换装、换衣服、穿上特定服饰，或希望你生成特定着装自拍时调用。
    """
    wm = get_wardrobe_manager()
    if not wm.is_enabled():
        return {
            "status": "disabled",
            "message": "衣橱功能当前处于关闭状态，保持使用默认设置的穿着。",
            "current_outfit": wm.get_current_outfit()
        }

    if not outfit_name and not custom_description:
        cur = wm.get_current_outfit()
        return {
            "status": "info",
            "message": f"当前穿着是：【{cur.get('name')}】。描述：{cur.get('clothing_tags')}",
            "current_outfit": cur
        }

    # 智能模糊匹配已有服饰
    matched_name = wm.match_outfit(outfit_name) if outfit_name else None

    if matched_name:
        outfit_info = wm.get_outfit(matched_name) or {}
        tags = outfit_info.get("clothing_tags", "")
        if custom_description:
            tags = f"{tags}, {custom_description.strip()}"
        wm.set_current_outfit(matched_name, tags)
        logger.info(f"[Wardrobe Tool] 已切换着装至已知款式: {matched_name}")
        return {
            "status": "success",
            "message": f"已成功换上【{matched_name}】！",
            "outfit_name": matched_name,
            "clothing_tags": tags
        }
    else:
        # 用户指定了自定义全新服饰
        target_name = outfit_name.strip() if outfit_name else "定制新装"
        custom_tags = custom_description.strip() if custom_description else target_name
        wm.set_current_outfit(target_name, custom_tags)
        logger.info(f"[Wardrobe Tool] 已切换着装至自定义新装: {target_name} -> {custom_tags}")
        return {
            "status": "success",
            "message": f"已换上特别搭配的【{target_name}】！",
            "outfit_name": target_name,
            "clothing_tags": custom_tags
        }


def build_change_outfit_declaration(yaml_path: str = YAML_CONFIG_PATH, custom_outfits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    根据 config.yaml 动态构建 call_change_outfit 的 Function Calling 声明。
    完整罗列全部服饰名称（按分类整理），使 bot 具备完全的自主挑选能力。
    """
    outfits = custom_outfits
    if outfits is None and yaml_path == YAML_CONFIG_PATH and _has_yaml_manager and YAMLManager is not None:
        try:
            ym = YAMLManager.get_instance()
            if ym and hasattr(ym, "wardrobe") and hasattr(ym.wardrobe, "config"):
                doc = ym.wardrobe.config
                if isinstance(doc, dict):
                    outfits = _read_catalog(doc)
        except Exception as e:
            logger.debug(f"[Wardrobe] 从 YAMLManager 读取服饰列表失败: {e}")

    if outfits is None:
        try:
            if _has_ruamel and os.path.exists(yaml_path):
                ryaml = YAML()
                ryaml.preserve_quotes = True
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = ryaml.load(f)
                    if isinstance(doc, dict):
                        outfits = _read_catalog(doc)
            elif yaml and os.path.exists(yaml_path):
                with open(yaml_path, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
                    if isinstance(doc, dict):
                        outfits = _read_catalog(doc)
        except Exception as e:
            logger.warning(f"[Wardrobe] 从 {yaml_path} 读取服饰列表失败: {e}")



    count = len(outfits)

    cat_order = [
        ("daily", "日常私服"),
        ("seasonal", "四季时令"),
        ("sleepwear", "居家睡衣"),
        ("special", "特色装扮"),
        ("sport", "运动活力"),
        ("festival", "节日庆典"),
    ]
    cat_map: Dict[str, List[str]] = {}
    for name, data in outfits.items():
        c = data.get("category", "other") if isinstance(data, dict) else "other"
        cat_map.setdefault(c, []).append(f"{name}" if isinstance(data, dict) else name)

    catalog_lines = []
    for c_key, c_label in cat_order:
        names = cat_map.pop(c_key, [])
        if names:
            catalog_lines.append("、".join(names))
    if cat_map:
        other_names = []
        for v in cat_map.values():
            other_names.extend(v)
        if other_names:
            catalog_lines.append(f"【其他款式 ({len(other_names)}套)】: " + "、".join(other_names))

    all_outfits_formatted = "\n".join(catalog_lines)

    tool_description = (
        f"切换或更换当前穿着的服装/衣橱搭配。当用户在聊天中要求换装、换衣服、穿上特定服饰，"
    )

    outfit_param_desc = (
        f"要更换的目标服装名称。请优先从以下完整收录的全部 {count} 套衣橱服饰中自主挑选最契合当前语境、活动或用户需求的款式名称：\n"
        f"{all_outfits_formatted}\n"
        f"（也支持输入任意自定义或模糊服装风格描述）。"
    )

    return {
        "name": "call_change_outfit",
        "description": tool_description,
        "parameters": {
            "type": "object",
            "properties": {
                "outfit_name": {
                    "type": "string",
                    "description": outfit_param_desc
                },
                "custom_description": {
                    "type": "string",
                    "description": "特定服饰细节、配色或额外的自定义 SD Prompt 关键词（可选，留空则使用对应服装的标准衣橱配置）"
                }
            },
            "required": ["outfit_name"]
        }
    }


def get_function_declarations(yaml_path: str = YAML_CONFIG_PATH) -> list:
    """获取动态生成的 Function Declarations 声明列表"""
    return [build_change_outfit_declaration(yaml_path=yaml_path)]
