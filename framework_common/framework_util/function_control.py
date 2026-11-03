"""
function_control.py —— core_reply 函数调用 / skill 开关的「单一数据源」。

被 Web 后端（列出 / 保存）与 core_reply（发给 LLM 前过滤）共用。仅在导入期依赖标准库，
导入零副作用，因此放在 framework_common 里，两侧都能干净引用，也不会牵入 run.core_reply 的包导入链。

开关状态存在 run/core_reply/function_control.json：
    {"disabled": ["func_name", ...], "disabled_skills": ["skill_name", ...]}
- "disabled"        —— 被禁用的函数（tool）名。
- "disabled_skills" —— 被禁用的 skill 包名（对应 SKILL.md frontmatter 的 name）。
- 缺省（文件不存在 / 列表为空）= 全部启用，保持向后兼容。
- 刻意用 .json 而非 .yaml：避开 YAMLManager 对 run/ 下 yaml 的文件监听，
  这样每次切换开关都【不会】触发整插件热重载。
"""

import os
import re
import json
import importlib.util
import threading

# 以本文件位置反推项目根：framework_common/framework_util/function_control.py -> 上三级
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_DIR = os.path.join(_ROOT, "run")
CONTROL_FILE = os.path.join(RUN_DIR, "core_reply", "function_control.json")

_lock = threading.Lock()
_cache = {"mtime": None, "disabled": frozenset(), "disabled_skills": frozenset()}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


# --------------------------------------------------------------------------- #
# 读写：control 文件（disabled 函数 + disabled_skills）
# --------------------------------------------------------------------------- #

def _load_control():
    """读取整个 control 文件为 (disabled, disabled_skills) 两个 frozenset（按 mtime 缓存）。

    文件缺失 / 损坏均视为「全部启用」，返回两个空集。
    """
    try:
        mtime = os.path.getmtime(CONTROL_FILE)
    except OSError:
        with _lock:
            _cache["mtime"] = None
            _cache["disabled"] = frozenset()
            _cache["disabled_skills"] = frozenset()
        return frozenset(), frozenset()

    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["disabled"], _cache["disabled_skills"]

    disabled = frozenset()
    disabled_skills = frozenset()
    try:
        with open(CONTROL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            disabled = _clean_set(data.get("disabled", []))
            disabled_skills = _clean_set(data.get("disabled_skills", []))
    except Exception:
        disabled = frozenset()
        disabled_skills = frozenset()

    with _lock:
        _cache["mtime"] = mtime
        _cache["disabled"] = disabled
        _cache["disabled_skills"] = disabled_skills
    return disabled, disabled_skills


def _save_control(disabled, disabled_skills):
    """写入整个 control 文件（去重、排序，保证父目录存在，原子替换），并刷新缓存。"""
    payload = {
        "disabled": sorted(_clean_set(disabled)),
        "disabled_skills": sorted(_clean_set(disabled_skills)),
    }
    os.makedirs(os.path.dirname(CONTROL_FILE), exist_ok=True)
    tmp = CONTROL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONTROL_FILE)
    # 立即刷新缓存，避免依赖 mtime 精度
    try:
        with _lock:
            _cache["mtime"] = os.path.getmtime(CONTROL_FILE)
            _cache["disabled"] = frozenset(payload["disabled"])
            _cache["disabled_skills"] = frozenset(payload["disabled_skills"])
    except OSError:
        pass


def _clean_set(names) -> frozenset:
    return frozenset(str(n).strip() for n in (names or []) if isinstance(n, str) and str(n).strip())


# --------------------------------------------------------------------------- #
# 公共 API：函数开关
# --------------------------------------------------------------------------- #

def load_disabled() -> set:
    """读取被禁用的函数名集合。文件缺失 / 损坏均返回空集。"""
    disabled, _ = _load_control()
    return set(disabled)


def save_disabled(names) -> None:
    """写入被禁用的函数名列表，保留原有的 disabled_skills 不动。"""
    _, disabled_skills = _load_control()
    _save_control(names, disabled_skills)


# --------------------------------------------------------------------------- #
# 公共 API：skill 开关
# --------------------------------------------------------------------------- #

def load_disabled_skills() -> set:
    """读取被禁用的 skill 名集合。文件缺失 / 损坏均返回空集。"""
    _, disabled_skills = _load_control()
    return set(disabled_skills)


def save_disabled_skills(names) -> None:
    """写入被禁用的 skill 名列表，保留原有的 disabled（函数开关）不动。"""
    disabled, _ = _load_control()
    _save_control(disabled, names)


# --------------------------------------------------------------------------- #
# 列举：供「功能管理」界面使用
# --------------------------------------------------------------------------- #

def _load_plugin_init(init_file):
    """隔离加载一个 __init__.py 并返回 module（失败返回 None）。

    与 web/server_new.py:get_plugin_description 同款做法：不写入 sys.modules，
    只为读取其中的 plugin_description / function_declarations 这两个纯数据变量。
    """
    try:
        spec = importlib.util.spec_from_file_location("eridanus_func_probe", init_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def list_all_functions():
    """遍历 run/* 各插件，列出其 function_declarations 声明的函数及启用状态。

    返回 [{"plugin": <目录名>, "description": <plugin_description>,
           "functions": [{"name", "description", "enabled"}]}]。
    以 function_declarations 为准 —— 这正是会发给大模型、消耗 token 的那批声明。
    """
    disabled = load_disabled()
    plugins = []
    if not os.path.isdir(RUN_DIR):
        return plugins

    for name in sorted(os.listdir(RUN_DIR)):
        plugin_dir = os.path.join(RUN_DIR, name)
        init_file = os.path.join(plugin_dir, "__init__.py")
        if not os.path.isdir(plugin_dir) or not os.path.exists(init_file):
            continue

        module = _load_plugin_init(init_file)
        if module is None:
            continue

        declarations = getattr(module, "function_declarations", None)
        if not isinstance(declarations, list) or not declarations:
            continue
        description = getattr(module, "plugin_description", None) or name

        functions = []
        seen = set()
        for decl in declarations:
            if not isinstance(decl, dict):
                continue
            fname = decl.get("name")
            if not isinstance(fname, str) or not fname or fname in seen:
                continue
            seen.add(fname)
            functions.append({
                "name": fname,
                "description": decl.get("description", "") or "",
                "enabled": fname not in disabled,
            })

        if functions:
            plugins.append({
                "plugin": name,
                "description": description,
                "functions": functions,
            })

    return plugins


def _resolve_skills_dir():
    """定位 skills 目录。默认 <root>/skills；尽力从 core_reply 配置读取 skills.skills_dir。

    与 skill_loader.SkillLoader 的解析保持一致：skills_dir 为相对路径时相对项目根。
    """
    skills_dir = "skills"
    cfg_path = os.path.join(RUN_DIR, "core_reply", "config.yaml")
    try:
        from ruamel.yaml import YAML
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = YAML(typ="safe").load(f) or {}
        val = (((data.get("skills") or {}) if isinstance(data, dict) else {}) or {}).get("skills_dir")
        if isinstance(val, str) and val.strip():
            skills_dir = val.strip()
    except Exception:
        pass

    if not os.path.isabs(skills_dir):
        skills_dir = os.path.join(_ROOT, skills_dir)
    return skills_dir


def _parse_skill_meta(skill_file):
    """从 SKILL.md 读取 frontmatter 中的 name / description（stdlib，容错解析）。"""
    try:
        with open(skill_file, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except Exception:
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None

    name = ""
    description = ""
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        if key == "name":
            name = value
        elif key == "description":
            description = value

    if not name or not description:
        return None
    return {"name": name, "description": description}


def list_all_skills():
    """扫描 skills 目录，列出各 skill 包及启用状态。

    返回 [{"name", "description", "enabled"}]，enabled = name 不在 disabled_skills 中。
    这正是会注入系统提示词、消耗 token 的那批 skill 元数据。
    """
    disabled = load_disabled_skills()
    skills = []
    skills_dir = _resolve_skills_dir()
    if not os.path.isdir(skills_dir):
        return skills

    seen = set()
    for name in sorted(os.listdir(skills_dir)):
        skill_md = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        meta = _parse_skill_meta(skill_md)
        if not meta or meta["name"] in seen:
            continue
        seen.add(meta["name"])
        skills.append({
            "name": meta["name"],
            "description": meta["description"],
            "enabled": meta["name"] not in disabled,
        })

    return skills
