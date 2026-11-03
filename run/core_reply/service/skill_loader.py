"""
skill_loader.py
动态加载官方 LLM Skill 风格的 skill 包。

支持的目录结构：
skills/
  skill-name/
    SKILL.md

SKILL.md 需要包含 YAML frontmatter，至少有 name 和 description。
"""

import asyncio
import json
import os
import re
import subprocess
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from ruamel.yaml import YAML
except Exception:  # pragma: no cover - 依赖异常时走极简解析
    YAML = None

from framework_common.utils.system_logger import get_logger
from framework_common.framework_util.function_control import load_disabled_skills

logger = get_logger(__name__)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    mtime: float


class SkillLoader:
    def __init__(self, config):
        cfg = config.core_reply.config.get("skills", {})
        self.enabled: bool = bool(cfg.get("enable", True))
        self.skills_dir: Path = Path(cfg.get("skills_dir", "skills"))
        self.include_catalog: bool = bool(cfg.get("include_catalog", True))
        self.auto_trigger: bool = bool(cfg.get("auto_trigger", True))
        self.llm_select: bool = bool(cfg.get("llm_select", True))
        self.always_load: List[str] = list(cfg.get("always_load", []) or [])
        self.max_loaded_skills: int = int(cfg.get("max_loaded_skills", 3))
        self.max_skill_chars: int = int(cfg.get("max_skill_chars", 6000))
        self.max_file_chars: int = int(cfg.get("max_file_chars", 12000))
        self.reload_interval: float = float(cfg.get("reload_interval_seconds", 10))
        self.enable_skill_tools: bool = bool(cfg.get("enable_skill_tools", True))
        self.allow_script_execution: bool = bool(cfg.get("allow_script_execution", False))
        self.script_timeout_seconds: float = float(cfg.get("script_timeout_seconds", 20))
        self.allowed_script_extensions = set(cfg.get("allowed_script_extensions", [".py"]) or [])

        self._skills: Dict[str, Skill] = {}
        self._last_scan: float = 0.0

    def build_prompt_section(self, user_text: str) -> str:
        if not self.enabled:
            return ""

        self._scan_if_needed()
        if not self._skills:
            return ""

        selected = self._select_skills(user_text)
        catalog = self._build_catalog(selected)
        loaded = self._build_loaded_skills(selected, "本轮已预加载的 skill 说明（按需遵循）：")

        if not catalog and not loaded:
            return ""

        section = "\n\n【可动态使用的 Skills】\n"
        if self.llm_select and self.enable_skill_tools:
            section += (
                "你会先看到 skill 元数据目录。不要因为目录存在就强行使用 skill；"
                "只有当当前问题明显需要某个 skill 时，才通过函数调用 load_skill 读取完整说明。"
                "如果 skill 正文要求读取 references/ 或执行 scripts/ 下的脚本，"
                "优先使用 read_skill_file 或 run_skill_script，不要臆造文件内容。\n"
            )
        if catalog:
            section += catalog
        if loaded:
            section += loaded
        return section.rstrip()

    def build_loaded_section_by_names(self, names: List[str]) -> str:
        if not self.enabled:
            return ""
        self._scan_if_needed()
        selected = []
        wanted = {name.strip() for name in names if name and name.strip()}
        for skill in self._visible_skills().values():
            if skill.name in wanted:
                selected.append(skill)
        return self._build_loaded_skills(selected, "按模型请求加载的 skill 说明：")

    def get_tool_map(self) -> Dict[str, Dict]:
        if not self.enabled or not self.enable_skill_tools:
            return {}

        script_status = "当前配置已启用脚本执行" if self.allow_script_execution else "当前配置未启用脚本执行"
        return {
            "load_skill": {
                "func": self.load_skill,
                "declaration": {
                    "name": "load_skill",
                    "description": "读取一个官方 LLM Skill 风格技能包的完整 SKILL.md 说明。仅当当前问题需要该 skill 时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "要加载的 skill 名称，对应 SKILL.md frontmatter 中的 name。"}
                        },
                        "required": ["name"],
                    },
                },
            },
            "read_skill_file": {
                "func": self.read_skill_file,
                "declaration": {
                    "name": "read_skill_file",
                    "description": "读取某个 skill 包目录内的资源文件，例如 references/*.md。路径必须是 skill 目录内的相对路径。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "skill 名称。"},
                            "relative_path": {"type": "string", "description": "相对 skill 根目录的文件路径。"},
                        },
                        "required": ["skill_name", "relative_path"],
                    },
                },
            },
            "run_skill_script": {
                "func": self.run_skill_script,
                "declaration": {
                    "name": "run_skill_script",
                    "description": (
                        f"执行某个 skill 包 scripts/ 目录下的脚本。{script_status}；"
                        "仅支持白名单扩展名，且不会通过 shell 执行。"
                        "如果当前 skill 正文要求运行脚本，应调用本工具并等待工具结果，不要自行声称系统不允许。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "skill 名称。"},
                            "script_path": {"type": "string", "description": "相对 skill 根目录的脚本路径，通常位于 scripts/ 下。"},
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "传给脚本的字符串参数列表。",
                            },
                        },
                        "required": ["skill_name", "script_path"],
                    },
                },
            },
        }

    def _scan_if_needed(self) -> None:
        now = time.monotonic()
        if now - self._last_scan < self.reload_interval:
            return
        self._last_scan = now
        self._scan()

    def _visible_skills(self) -> Dict[str, Skill]:
        """扫描到的 skill 中，剔除在「功能管理」里被禁用的那些。

        禁用列表由 function_control.load_disabled_skills 提供（上游 mtime 缓存），
        因此在界面上切换开关后，下一条对话即生效，无需热重载。
        """
        try:
            disabled = load_disabled_skills()
        except Exception:
            disabled = set()
        if not disabled:
            return self._skills
        return {k: v for k, v in self._skills.items() if v.name not in disabled}

    def _scan(self) -> None:
        if not self.skills_dir.exists():
            return

        found: Dict[str, Skill] = {}
        for skill_file in self.skills_dir.glob("*/SKILL.md"):
            try:
                mtime = skill_file.stat().st_mtime
                cached = self._skills.get(str(skill_file))
                if cached and cached.mtime == mtime:
                    found[str(skill_file)] = cached
                    continue

                parsed = self._parse_skill(skill_file, mtime)
                if parsed:
                    found[str(skill_file)] = parsed
            except Exception as exc:
                logger.warning(f"[MaiReply] 加载 Skill 失败: {skill_file} | {exc}")

        self._skills = found

    def _parse_skill(self, skill_file: Path, mtime: float) -> Optional[Skill]:
        text = skill_file.read_text(encoding="utf-8-sig")
        match = _FRONTMATTER_RE.match(text)
        if not match:
            logger.warning(f"[MaiReply] Skill 缺少 YAML frontmatter: {skill_file}")
            return None

        meta_text, body = match.group(1), match.group(2).strip()
        meta = self._load_yaml(meta_text)
        name = str(meta.get("name", "")).strip()
        description = str(meta.get("description", "")).strip()
        if not name or not description:
            logger.warning(f"[MaiReply] Skill 缺少 name/description: {skill_file}")
            return None

        return Skill(
            name=name,
            description=description,
            body=body,
            path=skill_file.parent,
            mtime=mtime,
        )

    @staticmethod
    def _load_yaml(meta_text: str) -> dict:
        if YAML is not None:
            yaml = YAML(typ="safe")
            data = yaml.load(meta_text) or {}
            return data if isinstance(data, dict) else {}

        data = {}
        for line in meta_text.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip("\"'")
        return data

    def _select_skills(self, user_text: str) -> List[Skill]:
        selected: List[Tuple[int, Skill]] = []
        lowered = (user_text or "").lower()

        for skill in self._visible_skills().values():
            score = 0
            if skill.name in self.always_load:
                score += 1000
            if f"${skill.name}".lower() in lowered or skill.name.lower() in lowered:
                score += 100

            if self.auto_trigger and lowered:
                score += self._match_score(lowered, skill)

            if score > 0:
                selected.append((score, skill))

        selected.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in selected[: self.max_loaded_skills]]

    @staticmethod
    def _match_score(text: str, skill: Skill) -> int:
        score = 0
        haystack = f"{skill.name} {skill.description}".lower()

        # 英文/数字/短横线词，适合官方 skill description。
        for token in set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", haystack)):
            if token in text:
                score += 3

        # 中文连续词，做一个保守的子串匹配。
        for token in set(re.findall(r"[\u4e00-\u9fff]{2,}", haystack)):
            if token in text:
                score += 4

        return score

    def _build_catalog(self, selected: List[Skill]) -> str:
        if not self.include_catalog:
            return ""

        selected_names = {skill.name for skill in selected}
        lines = []
        for skill in sorted(self._visible_skills().values(), key=lambda item: item.name):
            marker = "已加载" if skill.name in selected_names else "可触发"
            lines.append(f"- {skill.name}（{marker}）：{skill.description}")
        return "当前可用 skill 包：\n" + "\n".join(lines) + "\n"

    def _build_loaded_skills(self, selected: List[Skill], title: str) -> str:
        if not selected:
            return ""

        blocks = [f"\n{title}"]
        for skill in selected:
            body = skill.body[: self.max_skill_chars].rstrip()
            if len(skill.body) > self.max_skill_chars:
                body += "\n\n（该 skill 内容过长，已按配置截断）"
            blocks.append(
                f"\n---\nSkill: {skill.name}\nPath: {skill.path.as_posix()}\nDescription: {skill.description}\n\n{body}"
            )
        return "\n".join(blocks)

    def _get_skill_by_name(self, name: str) -> Optional[Skill]:
        self._scan_if_needed()
        normalized = (name or "").strip()
        for skill in self._visible_skills().values():
            if skill.name == normalized:
                return skill
        return None

    async def load_skill(self, name: str) -> str:
        skill = self._get_skill_by_name(name)
        if not skill:
            return json.dumps({"error": f"未找到 skill: {name}"}, ensure_ascii=False)
        return self._build_loaded_skills([skill], "已通过 load_skill 加载：")

    async def read_skill_file(self, skill_name: str, relative_path: str) -> str:
        skill = self._get_skill_by_name(skill_name)
        if not skill:
            return json.dumps({"error": f"未找到 skill: {skill_name}"}, ensure_ascii=False)

        target = self._resolve_inside_skill(skill, relative_path)
        if target is None or not target.is_file():
            return json.dumps({"error": "文件不存在或路径越界"}, ensure_ascii=False)

        text = target.read_text(encoding="utf-8-sig", errors="replace")
        truncated = len(text) > self.max_file_chars
        text = text[: self.max_file_chars]
        if truncated:
            text += "\n\n（文件内容过长，已按配置截断）"
        return text

    async def run_skill_script(self, skill_name: str, script_path: str, args: Optional[List[str]] = None) -> str:
        try:
            if not self.allow_script_execution:
                return json.dumps({"error": "配置 skills.allow_script_execution=false，脚本执行已关闭"}, ensure_ascii=False)

            args = self._normalize_script_args(args)
            skill = self._get_skill_by_name(skill_name)
            if not skill:
                return json.dumps({"error": f"未找到 skill: {skill_name}"}, ensure_ascii=False)

            target = self._resolve_inside_skill(skill, script_path)
            if target is None or not target.is_file():
                return json.dumps({"error": "脚本不存在或路径越界"}, ensure_ascii=False)
            if "scripts" not in target.relative_to(skill.path.resolve()).parts:
                return json.dumps({"error": "只允许执行 skill 包 scripts/ 目录下的脚本"}, ensure_ascii=False)
            if target.suffix.lower() not in self.allowed_script_extensions:
                return json.dumps({"error": f"脚本扩展名不在白名单: {target.suffix}"}, ensure_ascii=False)

            cmd = self._script_command(target, args)
            logger.info(
                f"[MaiReply][Skill] 执行 skill 脚本: skill={skill.name}, script={target}, args={args}"
            )
            completed = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(skill.path.resolve()),
                capture_output=True,
                text=False,
                timeout=self.script_timeout_seconds,
            )
            stdout = completed.stdout or b""
            stderr = completed.stderr or b""
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            logger.warning(
                f"[MaiReply][Skill] skill 脚本执行超时: skill={skill.name}, script={target}"
            )
            return json.dumps({"error": "脚本执行超时"}, ensure_ascii=False)
        except Exception as exc:
            logger.error(
                f"[MaiReply][Skill] skill 脚本执行异常: skill={skill_name}, "
                f"script={script_path}, args={args!r}, error={exc!r}",
                exc_info=True,
            )
            return json.dumps(
                {
                    "error": "skill 脚本执行异常",
                    "exception": repr(exc),
                    "traceback": traceback.format_exc()[-4000:],
                },
                ensure_ascii=False,
            )

        stdout_text = stdout.decode("utf-8", errors="replace")[: self.max_file_chars]
        stderr_text = stderr.decode("utf-8", errors="replace")[: self.max_file_chars]
        logger.info(
            f"[MaiReply][Skill] skill 脚本执行完成: skill={skill.name}, "
            f"script={target.name}, returncode={returncode}, stdout={stdout_text!r}, stderr={stderr_text!r}"
        )

        return json.dumps(
            {
                "returncode": returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _resolve_inside_skill(skill: Skill, relative_path: str) -> Optional[Path]:
        try:
            root = skill.path.resolve()
            target = (root / relative_path).resolve()
            if root == target or root in target.parents:
                return target
        except Exception:
            return None
        return None

    @staticmethod
    def _script_command(target: Path, args: List[str]) -> List[str]:
        if target.suffix.lower() == ".py":
            return [os.sys.executable, str(target), *[str(arg) for arg in args]]
        return [str(target), *[str(arg) for arg in args]]

    @staticmethod
    def _normalize_script_args(args) -> List[str]:
        if args is None:
            return []
        if isinstance(args, list):
            return [str(arg) for arg in args]
        if isinstance(args, tuple):
            return [str(arg) for arg in args]
        return [str(args)]
