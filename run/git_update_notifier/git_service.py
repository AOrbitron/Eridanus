import asyncio
import json
import re
from developTools.utils.logger import get_logger
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = get_logger("GitUpdateNotifier")


def get_git_executable(repo_root: Optional[Path] = None) -> str:
    """获取 git 可执行文件的路径，优先复用 tool.py 的解析结果或检索 environments/MinGit"""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent
    else:
        repo_root = Path(repo_root)

    # 1. 优先尝试从 tool.py 导入获取
    try:
        from tool import get_git_path, git_path
        if callable(get_git_path):
            res = get_git_path(str(repo_root))
        else:
            res = git_path
        if res and res != "git" and os.path.exists(res):
            return res
        if res and shutil.which(res):
            return res
    except Exception as e:
        logger.debug(f"[GitService] 从 tool.py 获取 git 路径异常: {e}")

    # 2. 检查父目录 environments/MinGit/cmd/git.exe（一键整合包标准结构）
    candidate_parent = repo_root.parent / "environments" / "MinGit" / "cmd" / "git.exe"
    if candidate_parent.exists():
        return str(candidate_parent)

    # 3. 检查仓库根目录下 environments/MinGit/cmd/git.exe
    candidate_local = repo_root / "environments" / "MinGit" / "cmd" / "git.exe"
    if candidate_local.exists():
        return str(candidate_local)

    # 4. 检查当前工作目录的父目录
    cwd_parent = Path(os.getcwd()).parent / "environments" / "MinGit" / "cmd" / "git.exe"
    if cwd_parent.exists():
        return str(cwd_parent)

    # 5. 检查系统环境变量中的 git
    which_git = shutil.which("git")
    if which_git:
        return which_git

    return "git"


class GitService:
    def __init__(
        self,
        repo_root: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        git_path: Optional[str] = None,
    ):
        if repo_root is None:
            self.repo_root = Path(__file__).resolve().parent.parent.parent
        else:
            self.repo_root = Path(repo_root)

        if data_dir is None:
            self.data_dir = Path(__file__).resolve().parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "git_update_state.json"

        self.git_path = git_path or get_git_executable(self.repo_root)
        logger.info(f"[GitService] 初始化完成，使用 Git 路径: {self.git_path}")

    def is_git_available(self) -> bool:
        """检查当前指定的 Git 可执行文件是否真实可用"""
        if self.git_path != "git":
            return os.path.exists(self.git_path)
        return shutil.which("git") is not None

    def _run_git_sync(self, args: list[str], timeout: int = 30) -> Tuple[int, str, str]:
        try:
            res = subprocess.run(
                [self.git_path] + args,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"Git 命令超时（{timeout}秒）: {self.git_path} {' '.join(args)}"
        except FileNotFoundError:
            return -1, "", (
                f"未找到 Git 可执行程序（尝试路径: {self.git_path}）。"
                f"用户部署环境中未将 Git 加入系统环境变量，且未在 environments/MinGit/cmd/git.exe 检测到内置 MinGit。"
                f"请确保安装了 Git 或将 MinGit 解压部署至 environments 目录。"
            )
        except Exception as e:
            return -1, "", str(e)

    async def run_git(self, args: list[str], timeout: int = 30) -> Tuple[int, str, str]:
        return await asyncio.to_thread(self._run_git_sync, args, timeout)

    async def get_current_branch(self) -> str:
        code, out, _ = await self.run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code == 0 and out:
            return out
        return "master"

    async def get_local_commit(self) -> str:
        code, out, _ = await self.run_git(["rev-parse", "HEAD"])
        if code == 0 and out:
            return out
        return ""

    async def fetch_remote(self, remote: str = "origin", branch: str = "master", timeout: int = 45) -> Tuple[bool, str]:
        """仅查询远端分支 SHA，保留接口名；不下载 Git 对象，不扩大范围重试。"""
        if branch == "auto":
            branch = await self.get_current_branch()
        ref = f"refs/heads/{branch}"
        code, out, err = await self.run_git(
            ["ls-remote", "--exit-code", "--refs", "--", remote, ref], timeout=timeout
        )
        if code != 0:
            return False, err or f"远端不存在分支 {branch}"
        for line in out.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1] == ref:
                if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fields[0]):
                    return True, fields[0]
        return False, f"无法读取远端分支 {branch} 的 commit"

    async def _compare_github(self, remote, base, head, max_commits, timeout):
        """只读取 GitHub 提交差异元数据，不获取 blob 或 pack。"""
        import httpx
        from urllib.parse import urlparse, quote

        code, url, _ = await self.run_git(["remote", "get-url", remote])
        if code != 0:
            url = remote
        if url.startswith("git@github.com:"):
            url = "https://github.com/" + url.split(":", 1)[1]
        parsed = urlparse(url)
        if parsed.hostname != "github.com":
            raise ValueError("远端 commit 不同，但该源不支持 GitHub 提交差异接口；已跳过对象下载")
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("无法解析 GitHub 仓库地址")
        owner, repo = (quote(part, safe="") for part in parts)
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{head}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                endpoint, params={"per_page": max(1, min(max_commits, 100))},
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            data = response.json()
        count = int(data["ahead_by"])
        commits = data.get("commits", [])[:max(0, max_commits)]
        summaries, details = [], []
        for item in commits:
            sha = item["sha"][:8]
            commit = item["commit"]
            message = commit["message"]
            author = commit.get("author") or {}
            summaries.append(f"* [{sha}] {message.splitlines()[0]} ({author.get('name', '')})")
            details.append(f"[Commit {sha}]\n{message}\nAuthor: {author.get('name', '')} ({author.get('date', '')})")
        files = data.get("files", [])
        stats = "\n".join(
            f"{item['filename']} | +{item.get('additions', 0)} -{item.get('deletions', 0)} ({item.get('status', '')})"
            for item in files
        )
        if len(files) >= 300:
            stats += "\n（文件列表可能受 GitHub 300 项上限截断）"
        if count > len(commits):
            details.append(f"（共 {count} 个新提交，仅展示其中 {len(commits)} 个）")
        return count, "\n".join(summaries), "\n\n".join(details), stats

    async def check_updates(
        self,
        remote: str = "origin",
        branch: str = "auto",
        max_commits: int = 20,
        fetch_timeout: int = 45,
    ) -> Dict[str, Any]:
        target_branch = branch
        if target_branch == "auto" or not target_branch:
            target_branch = await self.get_current_branch()

        if not self.is_git_available():
            err_msg = (
                f"未检测到可用的 Git 程序（当前指定路径: {self.git_path}）。"
                f"当前部署环境中未设置 Git 环境变量，且未在 environments/MinGit/cmd/git.exe 找到内置 MinGit。"
            )
            logger.error(f"[GitService] {err_msg}")
            return {
                "success": False,
                "error": err_msg,
                "is_ahead": False,
                "ahead_count": 0,
                "local_commit": "",
                "remote_commit": "",
                "branch": target_branch,
                "remote": remote,
            }

        local_commit = await self.get_local_commit()

        fetch_ok, fetch_msg = await self.fetch_remote(remote=remote, branch=target_branch, timeout=fetch_timeout)
        if not fetch_ok:
            return {
                "success": False,
                "error": f"查询远程分支失败: {fetch_msg}",
                "is_ahead": False,
                "ahead_count": 0,
                "local_commit": local_commit,
                "remote_commit": "",
                "branch": target_branch,
                "remote": remote,
            }

        remote_commit = fetch_msg
        remote_ref = remote_commit
        # 固定本次查询的 SHA，不能读取过期的 origin/* 或 FETCH_HEAD。
        code_object, _, _ = await self.run_git(["cat-file", "-e", f"{remote_commit}^{{commit}}"])
        if code_object != 0:
            try:
                ahead_count, commit_list, commit_details, diff_stat = await self._compare_github(
                    remote, local_commit, remote_commit, max_commits, fetch_timeout
                )
            except Exception as exc:
                return {
                    "success": False, "error": f"提交差异查询失败（未下载仓库对象）: {exc}",
                    "is_ahead": False, "ahead_count": 0, "local_commit": local_commit,
                    "remote_commit": remote_commit, "branch": target_branch, "remote": remote,
                }
            return {
                "success": True, "error": "", "is_ahead": ahead_count > 0,
                "ahead_count": ahead_count, "local_commit": local_commit,
                "remote_commit": remote_commit, "branch": target_branch, "remote": remote,
                "commit_list": commit_list, "commit_details": commit_details, "diff_stat": diff_stat,
            }

        code_count, count_str, _ = await self.run_git(["rev-list", "--count", f"HEAD..{remote_ref}"])
        ahead_count = int(count_str) if (code_count == 0 and count_str.isdigit()) else 0

        is_ahead = ahead_count > 0

        commit_list = ""
        commit_details = ""
        diff_stat = ""

        if is_ahead:
            # 1. 提交摘要简要列表
            _, commit_list, _ = await self.run_git([
                "log",
                f"HEAD..{remote_ref}",
                "--pretty=format:* [%h] %s (%an, %cd)",
                "--date=format:%Y-%m-%d %H:%M",
                f"-n{max_commits}",
            ])

            # 2. 详细包含每个 commit 的变动内容、提交人与说明
            _, raw_log, _ = await self.run_git([
                "log",
                f"HEAD..{remote_ref}",
                "--name-status",
                "--pretty=format:===COMMIT_SPLIT===%n[Commit %h]%nTitle: %s%nAuthor: %an (%cd)%nBody: %b%nFiles:",
                "--date=format:%Y-%m-%d %H:%M",
                f"-n{max_commits}",
            ])

            parts = [p.strip() for p in raw_log.split("===COMMIT_SPLIT===") if p.strip()]
            commit_details = "\n\n".join(parts)

            # 3. 统计变动文件
            _, diff_stat, _ = await self.run_git([
                "diff",
                "--stat",
                f"HEAD..{remote_ref}",
            ])

        return {
            "success": True,
            "error": "",
            "is_ahead": is_ahead,
            "ahead_count": ahead_count,
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "branch": target_branch,
            "remote": remote,
            "commit_list": commit_list,
            "commit_details": commit_details,
            "diff_stat": diff_stat,
        }

    def load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取状态文件 {self.state_file} 失败: {e}")
            return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存状态文件 {self.state_file} 失败: {e}")

    def is_notified(self, remote_commit: str) -> bool:
        if not remote_commit:
            return False
        state = self.load_state()
        return state.get("last_notified_commit") == remote_commit

    def mark_notified(self, remote_commit: str, ahead_count: int, branch: str) -> None:
        import datetime
        state = self.load_state()
        state["last_notified_commit"] = remote_commit
        state["last_notified_ahead_count"] = ahead_count
        state["last_notified_branch"] = branch
        state["last_notified_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_state(state)
