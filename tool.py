# -*- coding: utf-8 -*-
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from developTools.utils.logger import get_logger
from framework_common.utils.install_and_import import install_and_import, get_pypi_source

logger = get_logger()

parent_dir = os.path.dirname(os.getcwd())


def get_git_path(base_dir: str = None) -> str:
    """获取 git 可执行文件的路径，优先检查部署环境中的 MinGit，确保未设置环境变量的系统也能正常调用"""
    repo_dir = os.path.abspath(base_dir) if base_dir else os.path.dirname(os.path.abspath(__file__))
    p_dir = os.path.dirname(repo_dir)

    # 1. 检查一键整合包常见结构：上级目录中的 environments/MinGit/cmd/git.exe
    candidate_parent = os.path.join(p_dir, "environments", "MinGit", "cmd", "git.exe")
    if os.path.exists(candidate_parent):
        return candidate_parent

    # 2. 检查当前目录下 environments/MinGit/cmd/git.exe
    candidate_local = os.path.join(repo_dir, "environments", "MinGit", "cmd", "git.exe")
    if os.path.exists(candidate_local):
        return candidate_local

    # 3. 检查当前工作目录的父目录（兼容不同启动工作路径）
    cwd_parent = os.path.dirname(os.getcwd())
    candidate_cwd_parent = os.path.join(cwd_parent, "environments", "MinGit", "cmd", "git.exe")
    if os.path.exists(candidate_cwd_parent):
        return candidate_cwd_parent

    # 4. 检查系统环境变量中是否有 git
    which_git = shutil.which("git")
    if which_git:
        return which_git

    return "git"


git_path = get_git_path()

custom_python_path = os.path.join(parent_dir, "environments", "Python311", "python.exe")
python_path = sys.executable

try:
    from pip._internal.cli.main import main as pip_main
except ImportError:
    pip_main = None

pypi_source = get_pypi_source()
if pip_main is not None and pypi_source:
    try:
        pip_main(['config', 'set', 'global.index-url', pypi_source])
    except Exception:
        pass

SOURCES = [
    "https://github.com/avilliai/Eridanus.git",
    "https://gitcode.com/faasf/Eridanus.git",
    "https://github.akams.cn/https://github.com/avilliai/Eridanus.git",
    "https://mirror.ghproxy.com/https://github.com/avilliai/Eridanus",
    "https://ghfast.top/https://github.com/avilliai/Eridanus.git",
    "https://gh.llkk.cc/https://github.com/avilliai/Eridanus.git"
]

YAML_BACKUP_DIR = os.path.join("temp", "yaml_backup")

try:
    from ruamel.yaml import YAML
except Exception:
    if pip_main is not None:
        try:
            pip_main(['install', 'ruamel.yaml'])
        except Exception:
            pass
    from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def setup_git_proxy_if_interactive():
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        proxy = ym.common_config.basic_config.get("proxy", {}).get("http_proxy")
        if proxy:
            logger.warning(f"检测到设置了代理 {proxy}，是否要为 git 配置代理？输入 y 确认，输入 n 清除代理，回车不做修改。gitcode 源不需要代理。")
            set_proxy = input("在此输入：").strip().lower()
            if set_proxy == "y":
                subprocess.run([git_path, "config", "--global", "http.proxy", proxy], check=True)
                subprocess.run([git_path, "config", "--global", "https.proxy", proxy], check=True)
                logger.info("Git 代理配置成功。")
            elif set_proxy == "n":
                subprocess.run([git_path, "config", "--global", "--unset", "http.proxy"], stderr=subprocess.DEVNULL)
                subprocess.run([git_path, "config", "--global", "--unset", "https.proxy"], stderr=subprocess.DEVNULL)
                logger.info("Git 全局代理已清除。")
    except Exception as e:
        logger.debug(f"Git 代理交互配置跳过或异常: {e}")


def merge_dicts(old, new, path=""):
    """Keep the new schema; matching YAML types use the user's old value."""
    from framework_common.framework_util.config_migrations import merge_config_values
    return merge_config_values(new, old)


def conflict_file_dealter(file_old, file_new):
    with open(file_old, 'r', encoding="utf-8") as file:
        old_data = yaml.load(file)
    with open(file_new, 'r', encoding="utf-8") as file:
        new_data = yaml.load(file)
    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        raise ValueError("Config merge requires YAML mappings in both files")
    merge_dicts(old_data, new_data)
    from pathlib import Path
    from framework_common.framework_util.config_migrations import _atomic_save
    _atomic_save(Path(file_new), new_data)


def print_result_banner(status: str, detail: str = ""):
    line = "=" * 66
    if status == "UP_TO_DATE":
        msg = [
            line,
            "【当前已经是最新版本！】(Already Up-To-Date)",
            line,
            "您的代码库已与远程仓库完全同步，无需额外更新。",
            "所有配置文件与资源文件完好，您可以正常启动 Bot！",
            line
        ]
        for m in msg:
            logger.info(m)
    elif status == "SUCCESS":
        msg = [
            line,
            "【恭喜！代码已成功更新至最新版本！】(Update Success)",
            line,
            "本次更新已顺利完成，冲突资源与配置已安全处理与合并。",
            "若更新了核心框架模块，请重启 Bot 使其生效！",
            line
        ]
        for m in msg:
            logger.info(m)
    else:
        msg = [
            line,
            "【注意：未能完全更新至最新版本】(Update Incomplete)",
            line,
            "更新过程中可能遇到了未自动解决的冲突或网络波动。",
            f"原因/详情: {detail}" if detail else "请检查网络连接、Git 代理或查看上方的详细日志。",
            "我们已尽力保障您的 yaml 配置文件安全，没有丢失。",
            line
        ]
        for m in msg:
            logger.error(m)


def run_git_command(args: list) -> tuple:
    full_cmd = [git_path] + args
    try:
        p = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        out_str = stdout.decode('utf-8', errors='ignore')
        err_str = stderr.decode('utf-8', errors='ignore')
        return p.returncode, out_str, err_str
    except Exception as e:
        return -1, "", str(e)


def is_git_up_to_date(stdout: str, stderr: str) -> bool:
    combined = (stdout + "\n" + stderr).lower()
    return "already up to date" in combined or "已经是最新" in combined or "已经是最新版本" in combined


def is_git_pull_success(returncode: int, stdout: str, stderr: str) -> bool:
    if is_git_up_to_date(stdout, stderr):
        return True
    combined = (stdout + "\n" + stderr).lower()
    if returncode == 0:
        if "conflict" not in combined and "error:" not in combined and "fatal:" not in combined:
            return True
    if "updating " in combined and "files changed" in combined and "error:" not in combined and "fatal:" not in combined:
        return True
    return False


def parse_git_conflicts(output: str) -> list:
    files = set()
    lines = output.splitlines()
    in_overwrite_block = False

    for line in lines:
        stripped = line.strip()

        m = re.search(r'error:\s*Your local changes to the following files would be overwritten by merge:\s*', stripped, re.IGNORECASE)
        if m or "下列文件的本地更改将被合并覆盖" in stripped or "would be overwritten by merge" in stripped:
            in_overwrite_block = True
            continue

        if in_overwrite_block:
            if stripped.startswith("Please commit your changes") or stripped.startswith("Aborting") or stripped.startswith("请在合并前提交") or stripped.startswith("终止"):
                in_overwrite_block = False
                continue
            if stripped and not stripped.startswith("error:") and not stripped.startswith("fatal:"):
                files.add(stripped.replace("\\", "/"))
                continue

        m = re.search(r'error:\s*The following untracked working tree files would be overwritten by merge:\s*', stripped, re.IGNORECASE)
        if m or "下列未跟踪的工作区文件将被合并覆盖" in stripped:
            in_overwrite_block = True
            continue

        m = re.search(r'CONFLICT\s*\(.*?\):\s*Merge conflict in\s+(.*)', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'conflict in\s+(.*)', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'CONFLICT\s*\(modify/delete\):\s*(.*?)\s+deleted in', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'error:\s*unable to unlink\s+[\'"]?(.*?)[\'"]?:\s*', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

    clean_files = []
    for f in files:
        f_clean = f.strip().strip("'\"")
        if f_clean and not f_clean.startswith("fatal:") and not f_clean.startswith("error:"):
            clean_files.append(f_clean)
    return clean_files


def clean_and_backup_file(file_path: str, backed_up_yamls: dict) -> bool:
    if not os.path.exists(file_path):
        return True

    normalized = file_path.replace("\\", "/")
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".yaml", ".yml"]:
        try:
            os.makedirs(YAML_BACKUP_DIR, exist_ok=True)
            safe_name = normalized.replace("/", "__")
            backup_path = os.path.join(YAML_BACKUP_DIR, safe_name)
            shutil.copy2(file_path, backup_path)
            backed_up_yamls[normalized] = backup_path
            logger.info(f"已安全备份本地配置文件: {file_path} -> {backup_path}")
            os.remove(file_path)
            return True
        except Exception as e:
            logger.error(f"备份或移除本地 yaml 文件失败: {file_path}, error: {e}")
            return False
    else:
        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path, ignore_errors=True)
            else:
                os.remove(file_path)
            logger.warning(f"为排除拉取冲突，已自动清理冲突资源文件: {file_path}")
            return True
        except Exception as e:
            logger.error(f"清理冲突资源文件失败: {file_path}, error: {e}")
            return False


def restore_or_merge_yamls(backed_up_yamls: dict, pull_succeeded: bool):
    if not backed_up_yamls:
        return

    logger.info("开始处理暂存备份的配置文件...")
    for orig_rel_path, backup_path in list(backed_up_yamls.items()):
        if not os.path.exists(backup_path):
            continue

        if pull_succeeded:
            if os.path.exists(orig_rel_path):
                logger.info(f"正在智能合并配置更新: {orig_rel_path}")
                try:
                    conflict_file_dealter(backup_path, orig_rel_path)
                    logger.info(f"配置文件合并成功: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"合并配置文件失败 {orig_rel_path}: {e}，保留新模板和备份 {backup_path}，请检查后重试；不会用旧配置覆盖新结构")
            else:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(orig_rel_path)), exist_ok=True)
                    shutil.copy2(backup_path, orig_rel_path)
                    logger.info(f"远程无新同名配置，已完整还原原配置文件: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"还原原配置文件失败: {orig_rel_path}, error: {e}")
        else:
            if not os.path.exists(orig_rel_path):
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(orig_rel_path)), exist_ok=True)
                    shutil.copy2(backup_path, orig_rel_path)
                    logger.warning(f"更新未成功，已安全恢复原配置文件: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"恢复原配置文件失败: {orig_rel_path}, error: {e}")


def run_coroutine_sync(coro_fn):
    """
    在同步环境中安全地同步等待一个异步协程执行完毕并返回结果。
    如果当前线程没有运行中的事件循环，则直接使用 asyncio.run()。
    如果当前线程已有运行中的事件循环（例如 tool.py 的 async def main），
    则提交到单独的工作线程中通过 asyncio.run() 独立运行并阻塞等待返回，
    避免 'asyncio.run() cannot be called from a running event loop' 异常。
    """
    import concurrent.futures

    def _invoke():
        coro = coro_fn() if callable(coro_fn) else coro_fn
        return asyncio.run(coro)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_invoke)
            return future.result()
    else:
        return _invoke()


def is_ai_configured() -> bool:
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        if not hasattr(ym, "core_reply"):
            return False
        cfg = ym.core_reply.config
        if not cfg or not cfg.get("enable", True):
            return False
        llm = cfg.get("llm", {})
        provider = llm.get("provider", "openai")
        provider_cfg = llm.get(provider, {})
        keys = provider_cfg.get("api_keys", [])
        if isinstance(keys, str):
            keys = [keys]
        if not keys:
            return False
        first_key = str(keys[0]).strip()
        if not first_key or first_key in ["xxx", "YOUR_GEMINI_API_KEY", "YOUR_OPENAI_API_KEY"]:
            return False
        return True
    except Exception:
        return False


def ai_solve_git_update(source_url: str, initial_stdout: str, initial_stderr: str) -> tuple:
    backed_up_yamls = {}
    success = False
    default_repo_url = source_url
    def clean_conflicts(file_paths: list = None, **kwargs) -> str:
        if not file_paths:
            return "错误: 未提供要清理的文件列表"
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        cleaned = []
        for fp in file_paths:
            if isinstance(fp, str):
                fp = fp.strip().strip("'").strip('"')
            if fp and clean_and_backup_file(fp, backed_up_yamls):
                cleaned.append(fp)
        logger.info(f"AI 执行 clean_conflicts，已处理文件: {cleaned}")
        return f"已成功处理并备份/清理冲突文件: {cleaned}"

    def git_pull(source_url: str = "", **kwargs) -> str:
        nonlocal success
        target_url = source_url or default_repo_url
        logger.info(f"AI 正在执行 git_pull: {target_url}")
        code, out, err = run_git_command(["pull", target_url])
        if is_git_pull_success(code, out, err):
            success = True
            logger.info("AI 执行 git_pull 成功！")
            return f"Pull 成功！已拉取最新代码。\nSTDOUT: {out}\nSTDERR: {err}"
        else:
            logger.warning(f"AI 执行 git_pull 未成功: {err or out}")
            return f"Pull 仍有错误或未完成。\nReturncode: {code}\nSTDOUT: {out}\nSTDERR: {err}"

    def git_status(**kwargs) -> str:
        logger.info("AI 正在执行 git_status")
        code, out, err = run_git_command(["status"])
        return f"Git Status:\n{out}\n{err}"

    def git_abort_merge(**kwargs) -> str:
        logger.info("AI 正在执行 git_abort_merge")
        code, out, err = run_git_command(["merge", "--abort"])
        return f"Git merge --abort 执行完成: {out} {err}"

    def git_checkout_file(file_paths: list = None, **kwargs) -> str:
        if not file_paths:
            return "错误: 未提供要还原的文件列表"
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        logger.info(f"AI 正在执行 git_checkout_file: {file_paths}")
        code, out, err = run_git_command(["checkout", "--"] + file_paths)
        return f"Checkout 结果:\nSTDOUT: {out}\nSTDERR: {err}"

    tools_map = {
        "clean_conflicts": {
            "func": clean_conflicts,
            "declaration": {
                "name": "clean_conflicts",
                "description": "清理导致 Git 冲突的文件或目录。对于 yaml/yml 配置文件会自动备份以便后续合并配置，对于其他资源或代码文件会直接移除以允许 pull。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要清理的冲突文件或目录相对路径列表，例如 ['run/character_detection/config.yaml']"
                        }
                    },
                    "required": ["file_paths"]
                }
            }
        },
        "git_pull": {
            "func": git_pull,
            "declaration": {
                "name": "git_pull",
                "description": "执行 git pull 操作从远程仓库拉取最新代码。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_url": {
                            "type": "string",
                            "description": "Git 远程仓库地址（可选，留空则使用当前配置的仓库源）"
                        }
                    },
                    "required": []
                }
            }
        },
        "git_status": {
            "func": git_status,
            "declaration": {
                "name": "git_status",
                "description": "查看当前的 git status 输出，确认当前工作区状态与冲突文件。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        "git_abort_merge": {
            "func": git_abort_merge,
            "declaration": {
                "name": "git_abort_merge",
                "description": "如果处于未完成的冲突 merge 状态，执行 git merge --abort 回滚合并状态。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        "git_checkout_file": {
            "func": git_checkout_file,
            "declaration": {
                "name": "git_checkout_file",
                "description": "放弃某些本地未提交文件的更改，将其还原为 HEAD 版本。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要放弃修改并还原的文件路径列表"
                        }
                    },
                    "required": ["file_paths"]
                }
            }
        }
    }

    system_prompt = (
        "你是一个专业的 Git 诊断与自动化更新解决助手。当前用户正在更新开源项目，但遇到了 Git 冲突或错误。\n"
        "请记住：用户是技术小白，你需要全自动调用工具解决问题，直至成功 pull 到最新代码。\n"
        "规则：\n"
        "1. 仔细阅读报错信息中冲突的文件列表。\n"
        "2. 遇到 yaml, yml 配置文件冲突，必须调用 clean_conflicts（系统会自动安全备份，并在成功拉取后自动智能合并用户配置，绝不丢失配置）。\n"
        "3. 遇到 gif, png, jpg, txt, py 等非 yaml 资源或代码冲突，调用 clean_conflicts 直接清理它们以排除阻碍。\n"
        "4. 在清理完冲突文件后，必须调用 git_pull 重新尝试拉取代码。\n"
        "5. 如果 pull 成功或已经是最新代码 (already up to date)，向用户简要汇报拉取结果，无需再调用工具。\n"
        "6. 不要陷入死循环，目标是确保代码成功拉取完毕。"
    )

    initial_log = f"Git pull 输出日志：\nSTDOUT:\n{initial_stdout}\nSTDERR:\n{initial_stderr}\n当前更新源 URL: {source_url}"
    messages = [{"role": "user", "content": initial_log}]

    async def on_intermediate_text(text: str):
        if text and text.strip():
            logger.info(f"AI 提示: {text.strip()}")

    async def _run_ai():
        from framework_common.framework_util.yamlLoader import YAMLManager
        from run.core_reply.service.llm_client import LLMClient
        ym = YAMLManager.get_instance()
        client = LLMClient(ym)
        try:
            return await client.chat(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools_map,
                on_intermediate_text=on_intermediate_text
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    logger.info("AI 正在分析并执行自动修复与拉取方案...")
    detail = ""
    try:
        reply = run_coroutine_sync(_run_ai)
        detail = reply or ""
        if detail:
            logger.info(f"AI 总结: {detail}")
    except Exception as e:
        logger.error(f"AI 诊断请求异常: {e}")
        detail = str(e)

    if not success and backed_up_yamls:
        # AI 处理若清理了文件但未及时调用 git_pull，补做一次 pull 校验
        code, out, err = run_git_command(["pull", default_repo_url])
        if is_git_pull_success(code, out, err):
            success = True
            logger.info("补充执行 git_pull 成功！")

    restore_or_merge_yamls(backed_up_yamls, pull_succeeded=success)
    return success, detail


def heuristic_solve_git_update(source_url: str, initial_stdout: str, initial_stderr: str) -> tuple:
    backed_up_yamls = {}
    last_stdout = initial_stdout
    last_stderr = initial_stderr

    for round_idx in range(4):
        logger.info(f"正在使用启发式规则排查更新冲突（第 {round_idx + 1} 轮）...")
        conflict_files = parse_git_conflicts(last_stdout + "\n" + last_stderr)
        if not conflict_files:
            code, status_out, status_err = run_git_command(["status", "--porcelain"])
            for line in status_out.splitlines():
                if line.startswith("UU ") or line.startswith("AA "):
                    conflict_files.append(line[3:].strip())

        if not conflict_files:
            logger.info("未识别出具体冲突文件，尝试直接重新拉取...")
            code, out, err = run_git_command(["pull", source_url])
            last_stdout, last_stderr = out, err
            if is_git_pull_success(code, out, err):
                restore_or_merge_yamls(backed_up_yamls, pull_succeeded=True)
                return True, "拉取成功"
            break

        logger.warning(f"检测到以下引起冲突的文件/目录: {conflict_files}")
        for cf in conflict_files:
            clean_and_backup_file(cf, backed_up_yamls)

        code, out, err = run_git_command(["pull", source_url])
        last_stdout, last_stderr = out, err
        if is_git_pull_success(code, out, err):
            logger.info("清理冲突后重新拉取成功！")
            restore_or_merge_yamls(backed_up_yamls, pull_succeeded=True)
            return True, "拉取成功"

    code, out, err = run_git_command(["pull", source_url])
    final_success = is_git_pull_success(code, out, err)
    restore_or_merge_yamls(backed_up_yamls, pull_succeeded=final_success)
    detail = (out + "\n" + err).strip()
    return final_success, detail


def execute_smart_update(source_idx: int = 0, non_interactive: bool = False) -> tuple:
    if source_idx < 0 or source_idx >= len(SOURCES):
        source_idx = 0
    source_url = SOURCES[source_idx]

    logger.info(f"开始从源 [{source_idx}] {source_url} 拉取更新...")
    code, stdout, stderr = run_git_command(["pull", source_url])

    logger.info(stdout)
    if stderr:
        logger.warning(stderr)

    if is_git_up_to_date(stdout, stderr):
        print_result_banner("UP_TO_DATE")
        return "UP_TO_DATE", "当前已经是最新版本，无需更新。"

    if is_git_pull_success(code, stdout, stderr):
        print_result_banner("SUCCESS")
        return "SUCCESS", "更新成功，已拉取到最新代码。"

    logger.warning("首轮 git pull 未直接成功，正在启动智能冲突处理机制...")

    if is_ai_configured():
        logger.info("检测到 MaiReply 已配置可用 AI 大模型，优先交由 AI 自主分析与解决 Git 冲突...")
        try:
            ai_success, detail = ai_solve_git_update(source_url, stdout, stderr)
            if ai_success:
                print_result_banner("SUCCESS")
                return "SUCCESS", "AI 成功协助解决更新冲突并拉取到最新版本。"
            else:
                logger.warning(f"AI 处理未完全成功 ({detail})，将自动回退到规则启发式处理...")
        except Exception as e:
            logger.error(f"AI 处理过程发生异常: {e}，回退到规则启发式处理...")

    heur_success, detail = heuristic_solve_git_update(source_url, stdout, stderr)
    if heur_success:
        print_result_banner("SUCCESS")
        return "SUCCESS", "通过冲突文件自动清理与配置合并，已成功更新至最新代码。"
    else:
        print_result_banner("FAILED", detail)
        return "FAILED", f"未能自动解决冲突更新失败: {detail}"


def restart_bot_process():
    logger.info("准备重启 Bot 进程以使新代码生效...")
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    target_bat = os.path.join(workspace_dir, "启动脚本.bat")
    cur_pid = os.getpid()
    pids_to_kill = []

    try:
        import psutil
        cur_proc = psutil.Process(cur_pid)
        for child in cur_proc.children(recursive=True):
            if child.pid not in pids_to_kill:
                pids_to_kill.append(child.pid)
        pids_to_kill.append(cur_pid)

        for ancestor in cur_proc.parents():
            anc_name = (ancestor.name() or "").lower()
            if anc_name in ("python.exe", "pythonw.exe", "py.exe"):
                if ancestor.pid not in pids_to_kill:
                    pids_to_kill.append(ancestor.pid)
                continue
            if anc_name in ("cmd.exe", "powershell.exe", "pwsh.exe"):
                try:
                    cmdline_str = " ".join(ancestor.cmdline())
                    if "启动脚本2" in cmdline_str:
                        alt_bat = os.path.join(workspace_dir, "启动脚本2(循环重启).bat")
                        if os.path.exists(alt_bat):
                            target_bat = alt_bat
                except Exception:
                    pass
                if ancestor.pid not in pids_to_kill:
                    pids_to_kill.append(ancestor.pid)
            break
    except Exception as e:
        logger.warning(f"收集进程树信息时出现异常: {e}")
        if cur_pid not in pids_to_kill:
            pids_to_kill.append(cur_pid)
        ppid = os.getppid()
        if ppid and ppid not in pids_to_kill:
            pids_to_kill.append(ppid)

    restarter_code = (
        "import sys, os, time, subprocess, socket\n"
        "workspace_dir = sys.argv[1]\n"
        "target_bat = sys.argv[2]\n"
        "pids_to_kill = [int(p) for p in sys.argv[3:] if p.isdigit()]\n"
        "time.sleep(0.8)\n"
        "for pid in pids_to_kill:\n"
        "    try:\n"
        "        subprocess.run(['taskkill', '/F', '/PID', str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "    except Exception:\n"
        "        pass\n"
        "for _ in range(25):\n"
        "    try:\n"
        "        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:\n"
        "            s.settimeout(0.3)\n"
        "            if s.connect_ex(('127.0.0.1', 5007)) != 0:\n"
        "                break\n"
        "    except Exception:\n"
        "        break\n"
        "    time.sleep(0.4)\n"
        "CREATE_NEW_CONSOLE = 0x00000010\n"
        "if os.path.exists(target_bat):\n"
        "    subprocess.Popen(['cmd.exe', '/c', target_bat], cwd=workspace_dir, creationflags=CREATE_NEW_CONSOLE, close_fds=True)\n"
        "else:\n"
        "    subprocess.Popen([sys.executable, 'main.py'], cwd=workspace_dir, creationflags=CREATE_NEW_CONSOLE, close_fds=True)\n"
    )

    try:
        CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        cmd = [sys.executable, "-c", restarter_code, workspace_dir, target_bat] + [str(p) for p in pids_to_kill]
        subprocess.Popen(cmd, cwd=workspace_dir, creationflags=flags, close_fds=True)
    except Exception as e:
        logger.error(f"拉起独立重启守护进程异常: {e}")

    time.sleep(0.3)
    os._exit(0)


async def admin_update_system(bot, event, config):
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        master_id = ym.common_config.basic_config.get("master", {}).get("id")
    except Exception:
        master_id = None

    sender_id = getattr(event, "user_id", None)
    if master_id and sender_id and int(sender_id) != int(master_id):
        await bot.send(event, "抱歉，系统更新功能仅限 Bot 管理员执行！")
        return

    source_idx = 0
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        source_idx = int(ym.common_config.basic_config.get("git_update_source", 0))
    except Exception:
        source_idx = 0

    await bot.send(event, f"收到更新指令！已启动后台智能更新流程（使用源序号: {source_idx}）...\n完成后将通过私信向您汇报结果并自动重启。")

    async def _bg_update_task():
        try:
            status, detail = await asyncio.to_thread(execute_smart_update, source_idx, True)
            if status in ["UP_TO_DATE", "SUCCESS"]:
                report_msg = (
                    f"【系统更新报告】\n"
                    f"状态: {'已经是最新版本' if status == 'UP_TO_DATE' else '更新成功'}\n"
                    f"详情: {detail}\n"
                    f"Bot 将在 3 秒后自动重启以载入新模块..."
                )
            else:
                report_msg = (
                    f"【系统更新报告】\n"
                    f"状态: 更新失败\n"
                    f"详情: {detail}\n"
                    f"配置文件已安全保护，请根据日志排查。"
                )

            if master_id:
                try:
                    await bot.send_friend_message(int(master_id), report_msg)
                except Exception as e:
                    logger.error(f"向管理员发送更新报告私信失败: {e}")
                    try:
                        await bot.send(event, report_msg)
                    except Exception:
                        pass

            if status in ["UP_TO_DATE", "SUCCESS"]:
                await asyncio.sleep(2)
                restart_bot_process()
        except Exception as e:
            logger.error(f"后台更新任务异常: {e}")
            if master_id:
                try:
                    await bot.send_friend_message(int(master_id), f"系统更新发生严重异常: {e}")
                except Exception:
                    pass

    asyncio.create_task(_bg_update_task())


def updaat(f=False, source=None, yamls: dict = None):
    sources = SOURCES
    if source is None:
        for i in sources:
            logger.info(f"{sources.index(i)}. {i}")
        logger.info("拉取bot代码\n--------------------")
        logger.warning("0为git源,1为gitcode源，其他镜像源可能存在版本滞后现象。如拉取失败可自行为environments/MinGit/cmd/git.exe配置代理(windows)。")
        source = input("选择更新源(输入数字 )：").strip()

    try:
        source_idx = int(source)
    except Exception:
        logger.error("无效输入，重新执行")
        return updaat(f, None, yamls)

    if source_idx < 0 or source_idx >= len(sources):
        logger.error("无效输入，重新执行")
        return updaat(f, None, yamls)

    execute_smart_update(source_idx=source_idx, non_interactive=False)

def fuck_requirements():
    from ruamel.yaml import YAML

    yaml = YAML(typ='safe')
    with open('data/system/requirements.yaml', 'r', encoding='utf-8') as f:
        local_config = yaml.load(f)
    update_requirements = local_config.get("update")
    for i in update_requirements:
        try:
            logger.info(f"开始更新依赖{i}...")
            pip_main(['install', '--upgrade', i])
        except Exception as e:
            logger.error(f"更新依赖{i}失败：{e}")
    for i in local_config.get("restrict"):
        try:
            logger.info(f"开始安装依赖{i}...")
            pip_main(['install', i])
        except Exception as e:
            logger.error(f"安装依赖{i}失败：{e}")


def parse_requirements(file_path):
    """
    解析 requirements.txt 文件，返回包名和版本需求信息。
    """
    requirements = {}
    requirement_pattern = re.compile(r'([a-zA-Z0-9_.-]+)([<>=!~].*)?')
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):  # 跳过空行和注释
                continue
            match = requirement_pattern.match(line)
            if match:
                pkg = match.group(1).lower()  # 包名
                spec = match.group(2)  # 版本约束
                requirements[pkg] = spec.strip() if spec else None
            else:
                print(f"无法解析行：'{line}'，请检查格式是否正确。")
    return requirements


def get_installed_packages():
    """
    使用 pip 获取已安装的包和版本信息。
    """

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'freeze'],  # 避免找不到 pip
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    installed_packages = {}
    logger.info(f"获取已安装包中...")
    logger.info(f"{result.stdout}")
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if '==' in line:
                pkg, version = line.split('==')
                installed_packages[pkg.strip()] = version.strip()
    else:
        print(f"获取已安装包失败：{result.stderr}")
    return installed_packages


def check_requirements(requirements_file):
    """
    检查 requirements.txt 中的依赖是否已安装。
    """
    if not os.path.exists(requirements_file):
        print(f"文件 {requirements_file} 不存在！")
        return

    requirements = parse_requirements(requirements_file)

    installed_packages = get_installed_packages()

    normalize_package_name = lambda name:name.lower().replace('_', '-')
    installed_packages = {normalize_package_name(k): v for k, v in installed_packages.items()}
    requirements = {normalize_package_name(k): v for k, v in requirements.items()}

    missing = []
    mismatched = []

    for pkg, required_version in requirements.items():
        if pkg not in installed_packages:
            missing.append(pkg)
        elif required_version and installed_packages[pkg] != required_version:
            mismatched.append((pkg, required_version, installed_packages[pkg]))

    if missing:
        print("缺失的包：")
        for pkg in missing:
            print(f"  - {pkg}")
            if "<" in pkg or ">" in pkg or "=" in pkg:
                pip_main(['install', pkg])
            else:
                pip_main(['install', '--upgrade', pkg])
    if mismatched:
        print("\n版本不匹配的包(一般不用管这个)：")
        for pkg, required_version, installed_version in mismatched:
            print(f"  - {pkg}: 需要 {required_version}, 已安装 {installed_version}")

    if not missing and not mismatched:
        print("所有依赖都已正确安装！")


def extract_cuda_version(nvcc_output):
    """
    从nvcc --version命令的输出中提取CUDA版本，并转换为用于构建PyTorch URL的形式。
    :param nvcc_output: str, nvcc --version命令的输出字符串。
    :return: str, 转换后的CUDA版本号，如'cu121'。
    """
    match = re.search(r'release (\d+\.\d+)', nvcc_output)
    if match:
        cuda_version = match.group(1)  # 获取主版本和次版本号
        major, minor = cuda_version.split('.')
        return f'cu{major}{minor}'
    else:
        return None


def ai_req():
    try:
        nvcc_output = subprocess.check_output(["nvcc", "--version"], stderr=subprocess.STDOUT).decode()
        cuda_torch_suffix = extract_cuda_version(nvcc_output)
        if cuda_torch_suffix:
            logger.info(f"检测到CUDA版本：{cuda_torch_suffix[2:]}，正在安装支持CUDA的PyTorch...")
        else:
            logger.warning("未能检测到CUDA版本，假设系统中未安装CUDA。")
    except Exception:
        logger.error('CUDA')
        logger.warning("未能检测到CUDA版本或nvcc未安装，假设系统中未安装CUDA。")
        cuda_torch_suffix = None

    try:
        pip_main(['install', 'opencv-python-headless'])
        if cuda_torch_suffix:
            # 如果检测到了支持的CUDA版本，则安装带有CUDA支持的PyTorch包
            pip_main(['install', 'torch', 'torchvision', 'torchaudio',
                      f'--index-url=https://download.pytorch.org/whl/{cuda_torch_suffix}'])
        else:
            # 如果没有检测到CUDA或不支持的CUDA版本，则安装CPU-only版本的PyTorch包
            logger.info("未检测到CUDA或CUDA版本不受支持，正在安装仅CPU版本的PyTorch...")
            pip_main(['install', 'opencv-python-headless', 'torch', 'torchvision', 'torchaudio'])
    except subprocess.CalledProcessError as e:
        logger.error(f"安装PyTorch时出错：{e}")
        sys.exit(1)

    logger.info("ai相关库安装成功完成")
    return
def export_yaml(base_dir="run"):
    if not os.path.exists("old_yamls"):
        os.mkdir("old_yamls")
    """
    导出yaml文件到old_yamls文件夹
    """

    yaml_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yaml"):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, base_dir)
                yaml_files.append(relative_path)
    def copy_to_old_yamls(yaml_files, target_dir="old_yamls"):
        for rel_path in yaml_files:
            src_path = os.path.join(base_dir, rel_path)
            dst_path = os.path.join(target_dir, rel_path)

            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            print(f"Copied: {src_path} -> {dst_path}")

    copy_to_old_yamls(yaml_files)
    logger.info("导出yaml文件到old_yamls文件夹完成")
    logger.info("请将old_yamls文件夹复制到新的Eridanus目录下，放在run目录旁边。路径应当为：Eridanus/old_yamls")
    logger.info("在新目录下运行Eridanus/tool.py或更新脚本，选择导入旧配置即可。")
    return yaml_files
def import_yaml(base_dir="run"):
    yaml_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yaml"):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, base_dir)
                yaml_files.append(relative_path)
    failed_files = []
    for files in yaml_files:
        if os.path.exists(os.path.join(base_dir, files)):
            logger.warning(f"开始处理冲突文件{files}...")
            try:
                conflict_file_dealter(os.path.join("old_yamls", files), os.path.join(base_dir, files))
            except Exception as e:
                logger.error(f"处理冲突文件{files}失败：{e}")
                continue
        else:
            logger.warning(f"文件{files}在新配置中不存在，跳过")
            continue
    if failed_files:
        logger.warning(f"以下文件处理失败：{failed_files}，建议手动处理")

async def youtube_cookie_and_login_helper():
    cookie_dir = os.path.join("data", "cookies")
    target_cookie_path = os.path.join(cookie_dir, "youtube_cookies.txt")
    os.makedirs(cookie_dir, exist_ok=True)

    while True:
        try:
            from run.streaming_media.service.youtube.youtube_tools import find_youtube_cookie_file, test_youtube_connection
            current_cookie = find_youtube_cookie_file()
        except Exception:
            current_cookie = target_cookie_path if os.path.exists(target_cookie_path) else None
            test_youtube_connection = None

        status_msg = f"已生效 ({current_cookie})" if current_cookie else "未配置 (当前尝试移动端免登录策略)"

        print("\n" + "=" * 62)
        print("           YouTube 登录与 Cookie 配置向导")
        print("=" * 62)
        print(f"当前 Cookie 状态: {status_msg}")
        print("""
说明：YouTube 近期反爬严格，直接下载常提示：
      "Sign in to confirm you're not a bot"
配置 Cookie 可以彻底解决人机验证和风控拦截问题。

请选择操作：
  [1]. 导入本地已导出的 cookies.txt 文件 (推荐，最稳定)
  [2]. 在终端直接粘贴 cookies.txt 内容并保存
  [3]. 尝试自动从本机浏览器(Edge/Chrome/Firefox)提取 Cookie
  [4]. 测试当前 YouTube 连接与 Cookie 有效性
  [5]. 查看获取 YouTube cookies.txt 的详细图文步骤
  [6]. 旧版 pytubefix 网页设备码 OAuth 授权登录
  [0]. 返回主菜单
""")
        sub_choice = input("请输入选项序号 [0-6]：").strip()

        if sub_choice == "1":
            print("\n--- 导入本地 cookies.txt 文件 ---")
            print("提示：可以将文件直接拖入终端，或直接按回车检查当前目录的 cookies.txt")
            file_path = input("请输入 cookies.txt 的路径: ").strip().strip('"').strip("'")
            if not file_path:
                if os.path.exists("cookies.txt"):
                    file_path = "cookies.txt"
                elif os.path.exists(os.path.join("data", "cookies.txt")):
                    file_path = os.path.join("data", "cookies.txt")

            if file_path and os.path.isfile(file_path):
                try:
                    shutil.copyfile(file_path, target_cookie_path)
                    logger.info(f"✅ Cookie 文件已成功保存至: {target_cookie_path}")
                    print("\n正在验证 YouTube 连接...")
                    if test_youtube_connection:
                        ok, res = test_youtube_connection()
                        if ok:
                            logger.info(f"🎉 验证成功！视频测试解析正常: 《{res.get('title')}》")
                        else:
                            logger.warning(f"⚠️ 解析测试出现警告/失败: {res}")
                except Exception as e:
                    logger.error(f"复制 Cookie 文件失败: {e}")
            else:
                logger.error(f"未找到指定的有效文件: {file_path}")

        elif sub_choice == "2":
            print("\n--- 粘贴 cookies.txt 文本内容 ---")
            print("请复制 cookies.txt 的文本内容并在此粘贴。")
            print("输入完成后，在新的一行输入 'EOF' 或连续按两次回车完成保存：")
            lines_input = []
            while True:
                try:
                    line = input()
                    if line.strip() == "EOF":
                        break
                    if not line and lines_input and not lines_input[-1]:
                        lines_input.pop()
                        break
                    lines_input.append(line)
                except EOFError:
                    break

            content = "\n".join(lines_input).strip()
            if content:
                try:
                    with open(target_cookie_path, "w", encoding="utf-8") as f:
                        f.write(content + "\n")
                    logger.info(f"✅ Cookie 内容已写入: {target_cookie_path}")
                    print("\n正在验证 YouTube 连接...")
                    if test_youtube_connection:
                        ok, res = test_youtube_connection()
                        if ok:
                            logger.info(f"🎉 验证成功！视频测试解析正常: 《{res.get('title')}》")
                        else:
                            logger.warning(f"⚠️ 解析测试出现警告/失败: {res}")
                except Exception as e:
                    logger.error(f"保存 Cookie 失败: {e}")
            else:
                logger.warning("未输入任何内容，取消保存。")

        elif sub_choice == "3":
            print("\n--- 从本机浏览器提取 Cookie ---")
            print("⚠️ 注意事项：")
            print("1. Windows 下 Chromium 内核(Edge/Chrome)对 Cookie 数据库加有独占文件锁。")
            print("2. 提取前请务必【完全关闭】目标浏览器（包括后台所有进程）！")
            print("3. 部分新版 Chrome 启用了 AppBound 加密，若提取失败请优先使用选项 [1] 导入文件。")
            print("\n支持的浏览器: [1] edge  [2] chrome  [3] firefox  [4] brave  [5] vivaldi")
            b_choice = input("请选择浏览器序号 (默认 1 Edge): ").strip()
            b_map = {"1": "edge", "2": "chrome", "3": "firefox", "4": "brave", "5": "vivaldi", "": "edge"}
            browser_name = b_map.get(b_choice, "edge")

            print(f"正在尝试从 {browser_name} 提取 YouTube Cookie...")
            try:
                from yt_dlp.cookies import extract_cookies_from_browser
                jar = extract_cookies_from_browser(browser_name)
                jar.save(target_cookie_path, ignore_discard=True, ignore_expires=True)
                logger.info(f"✅ 成功从 {browser_name} 提取并保存 Cookie 到: {target_cookie_path}")
                print("\n正在验证 YouTube 连接...")
                if test_youtube_connection:
                    ok, res = test_youtube_connection()
                    if ok:
                        logger.info(f"🎉 验证成功！视频测试解析正常: 《{res.get('title')}》")
                    else:
                        logger.warning(f"⚠️ 解析测试出现警告/失败: {res}")
            except Exception as e:
                logger.error(f"提取浏览器 Cookie 失败: {e}")
                logger.warning("提示：如果提示数据库被占用或找不到文件，建议完全退出浏览器后重试，或使用选项 [1] 手动导入 cookies.txt。")

        elif sub_choice == "4":
            print("\n--- 测试当前 YouTube 连接与 Cookie 状态 ---")
            print("正在连接 YouTube 并尝试解析测试视频...")
            if test_youtube_connection:
                ok, res = test_youtube_connection()
                if ok:
                    print("\n" + "-" * 45)
                    print("✅ 状态：测试成功！YouTube 可以正常解析。")
                    print(f"📌 标题: {res.get('title')}")
                    print(f"👤 作者: {res.get('uploader')}")
                    print(f"⏱️ 时长: {res.get('duration')} 秒")
                    print(f"🍪 凭据: {res.get('cookie_used')}")
                    print("-" * 45)
                else:
                    print("\n" + "-" * 45)
                    print("❌ 状态：解析失败！")
                    print(f"错误信息: {res}")
                    print("建议：请检查代理设置，或通过选项 [1] 导入登录后的 cookies.txt。")
                    print("-" * 45)
            else:
                logger.error("无法导入 test_youtube_connection 函数")

        elif sub_choice == "5":
            print("\n" + "=" * 62)
            print("            如何获取 YouTube cookies.txt 教程")
            print("=" * 62)
            print("""
步骤 1: 安装浏览器扩展
  - 推荐使用开源安全的扩展: "Get cookies.txt LOCALLY"
  - Edge 扩展商店: 搜索 "Get cookies.txt LOCALLY"
  - Chrome 扩展商店: 搜索 "Get cookies.txt LOCALLY"
  - GitHub 开源地址: https://github.com/kairi003/Get-Cookie-UX

步骤 2: 登录并导出
  1. 打开浏览器并访问 https://www.youtube.com
  2. 登录你的 Google / YouTube 账号，确保可以正常播放视频。
  3. 点击浏览器扩展栏中的 "Get cookies.txt LOCALLY" 图标。
  4. 确认域名包含 youtube.com，点击 "Export" 导出保存为 cookies.txt。

步骤 3: 导入到本项目
  - 方式 A: 直接将导出的 cookies.txt 放入本项目根目录或 data/cookies/youtube_cookies.txt
  - 方式 B: 返回当前向导菜单，选择 [1] 并输入文件路径即可自动完成导入与测试。
""")
            input("按回车键继续...")

        elif sub_choice == "6":
            logger.info("旧版 pytubefix 设备码 OAuth 登录")
            logger.warning(
                """
                \n
                youtube登录需要手动操作，请按照以下步骤进行：
                0.等待链接出现
                1.打开链接
                2.输入input code 后面的代码
                3.继续使用你的google账号登录
                4.完成后，在这个页面按回车(等待结束后自动退出)
                """
            )
            try:
                from framework_common.framework_util.yamlLoader import YAMLManager
                yamlmanager = YAMLManager.get_instance()
                proxy = yamlmanager.common_config.basic_config.get("proxy", {}).get("http_proxy")
                pyproxies = {"http": proxy, "https": proxy} if proxy else None

                from pytubefix import YouTube
                from pytubefix.helpers import reset_cache
                reset_cache()

                yt = YouTube(url="https://www.youtube.com/watch?v=PZnXXFrjSjg", client='IOS', proxies=pyproxies, use_oauth=True, allow_oauth_cache=True)
                ys = yt.streams.get_audio_only()
                logger.info("pytubefix 登录流程完成！")
            except Exception as e:
                logger.error(f"pytubefix 登录失败: {e}")

        elif sub_choice == "0":
            break
        else:
            print("无效输入，请重新输入。")


async def main():
    setup_git_proxy_if_interactive()
    logger.info("""请输入要执行的指令：
        [1].YouTube登录与Cookie配置(解决人机验证/下载失败)
        [2].更新bot代码(常用)
        [3].playwright工具安装
        [4].开发者工具
        [5].若只的检测相关ai库(如奶龙检测)
        [6].B站 or 抖音 or 小红书 登录。不登也不影响你用
        [7].导出配置文件
        [8].导入配置文件
        [9].更新jmcomic库(当代理正常但jm功能不可用时请自助更新)
        [10].退出""")
    user_input = input("请输入指令序号：").strip()
    if user_input == "1":
        await youtube_cookie_and_login_helper()
    elif user_input == "2":
        updaat()
    elif user_input == "3":
        logger.info("playwright工具安装(b站动态爬取需要)")
        os.system(f"\"{python_path}\" -m playwright install chromium")
    elif user_input == "4":
        logger.info("""请输入开发者工具序号：
#
        2 没想好呢""")
        input("请输入开发者工具序号：")
    elif user_input == "5":
        logger.info("安装奶龙相关ai库依赖中")
        ai_req()
    elif user_input == "6":
        install_and_import("PyExecJS")
        install_and_import("PyGObject", "gi")

        from run.streaming_media.service.Link_parsing.core.login_core import login_core_select
        await login_core_select()
    elif user_input == "7":
        logger.info("导出配置文件")
        export_yaml()
        logger.info("配置文件导出完成")
        logger.warning("请将old_yamls文件夹复制到新的Eridanus目录下。如有必要，请自行覆盖新的data文件夹")
    elif user_input == "8":
        logger.info("导入配置文件")
        import_yaml()
        logger.info("配置文件导入完成")
    elif user_input == "9":
        if pip_main is not None:
            pip_main(['install', '--upgrade', 'jmcomic'])
    elif user_input == "10":
        logger.info("退出")

if __name__ == '__main__':
    asyncio.run(main())
