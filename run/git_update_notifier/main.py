import asyncio
from developTools.utils.logger import get_logger
from typing import Optional, Dict, Any

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text
from framework_common.framework_util.any_event import AnyEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from run.git_update_notifier.git_service import GitService

logger = get_logger("GitUpdateNotifier")

_bg_task: Optional[asyncio.Task] = None
_loop_started = False
_lock = asyncio.Lock()


def _get_plugin_config(config) -> Dict[str, Any]:
    try:
        if hasattr(config, "git_update_notifier") and hasattr(config.git_update_notifier, "config"):
            return config.git_update_notifier.config
    except Exception:
        pass
    return {
        "enable": True,
        "check_interval": 1800,
        "initial_delay": 20,
        "remote": "origin",
        "branch": "auto",
        "use_core_reply": True,
        "notify_master": True,
        "master_id": None,
        "max_commit_log_count": 15,
        "fetch_timeout": 45,
        "notify_up_to_date_on_manual": True,
    }


def _get_master_id(config, plugin_cfg: Dict[str, Any]) -> Optional[int]:
    cfg_master = plugin_cfg.get("master_id")
    if cfg_master:
        try:
            return int(cfg_master)
        except (ValueError, TypeError):
            pass

    try:
        master_id = config.common_config.basic_config["master"]["id"]
        return int(master_id)
    except Exception:
        pass

    return None


async def send_to_master(bot: ExtendBot, master_id: int, message: str):
    try:
        await bot.send_friend_message(master_id, message)
    except Exception as e:
        logger.error(f"[GitNotifier] 向 master ({master_id}) 发送通知失败: {e}")


async def report_update_via_core_reply(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]) -> bool:
    try:
        mai_cfg = getattr(config, "core_reply", None)
        if not mai_cfg:
            logger.info("[GitNotifier] core_reply 插件未找到，回退到普通文本播报")
            return False

        mai_dict = getattr(mai_cfg, "config", {})
        if not isinstance(mai_dict, dict) or not mai_dict.get("enable", False):
            logger.info("[GitNotifier] core_reply 未启用，回退到普通文本播报")
            return False

        from run.core_reply.service.reply_engine import ReplyEngine

        engine = ReplyEngine(config)
        event = AnyEvent()
        event.user_id = int(master_id)

        prompt = (
            f"【系统重要通知：远程 Git 仓库检测到新更新/新功能发布】\n"
            f"目标分支：{update_info['branch']}\n"
            f"远程仓库领先当前版本共 {update_info['ahead_count']} 个提交 (commit)\n"
            f"最新提交哈希：{update_info['remote_commit'][:8]}\n\n"
            f"以下是新提交的详细记录：\n"
            f"{update_info['commit_details']}\n\n"
            f"文件变动总体统计：\n{update_info['diff_stat']}\n\n"
            f"【你的任务 - 专属更新汇报】\n"
            f"请以你的性格与口吻，向你的管理员（Master）汇报这次更新的亮点：\n"
            f"1. 兴奋或关切地告知 Master 仓库有了最新更新（领先了 {update_info['ahead_count']} 个提交）；\n"
            f"2. 详细梳理并说明这些提交都干了什么（重点说明新增了什么功能、优化或修复了哪些问题，让管理员一目了然）；\n"
            f"   - 如果包含多个 commit，请条理清晰地列出主要更新内容；\n"
            f"3. 贴心提醒管理员：现在只需要直接在聊天中对你下达更新命令（例如直接对你说“更新系统”或“帮我更新代码”），"
            f"你就会自动完成代码拉取、冲突处理与自动重启；当然也可以运行根目录下的【更新脚本.bat】进行更新。"
            f"（注意：本次仅为检测汇报通知，请只发送汇报文字，不要在本次汇报中直接调用 update_system 工具）。"
        )

        logger.info(f"[GitNotifier] 正在调用 core_reply 向管理员 master ({master_id}) 生成更新播报 (包含 {update_info['ahead_count']} 个提交)...")
        await engine.handle(bot, event, prompt)
        return True

    except Exception as e:
        logger.error(f"[GitNotifier] 调用 core_reply 生成播报失败: {e}", exc_info=True)
        return False


async def report_update_fallback(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]):
    structured_msg = (
        f"📢 【Git 仓库更新提醒】\n"
        f"检测到远程仓库 [{update_info['branch']}] 分支有 {update_info['ahead_count']} 个新提交！\n\n"
        f"【更新提交详情】\n{update_info['commit_details']}\n\n"
        f"【修改文件统计】\n{update_info['diff_stat']}\n\n"
        f"💡 提醒：你可以直接在聊天中对我下达更新命令（如对我说「更新系统」）让我自动更新并重启，或者运行根目录下的【更新脚本.bat】进行一键更新~"
    )
    await send_to_master(bot, master_id, structured_msg)


async def perform_update_check(
    bot: ExtendBot,
    config,
    git_service: GitService,
    is_manual: bool = False,
    force_notify: bool = False,
) -> Dict[str, Any]:
    plugin_cfg = _get_plugin_config(config)
    remote = plugin_cfg.get("remote", "origin")
    branch = plugin_cfg.get("branch", "auto")
    max_commits = int(plugin_cfg.get("max_commit_log_count", 15))
    fetch_timeout = int(plugin_cfg.get("fetch_timeout", 45))
    use_mai = plugin_cfg.get("use_core_reply", True)
    notify_master = plugin_cfg.get("notify_master", True)

    master_id = _get_master_id(config, plugin_cfg)

    logger.info(f"[GitNotifier] 正在检查远程 Git 仓库 (remote={remote}, branch={branch})...")
    update_info = await git_service.check_updates(
        remote=remote,
        branch=branch,
        max_commits=max_commits,
        fetch_timeout=fetch_timeout,
    )

    if not update_info["success"]:
        logger.error(f"[GitNotifier] 检查更新失败: {update_info['error']}")
        return update_info

    if not update_info["is_ahead"]:
        logger.info(f"[GitNotifier] 当前已是最新版本，本地与远程一致 (最新提交: {update_info['local_commit'][:8]})")
        return update_info

    ahead_count = update_info["ahead_count"]
    remote_commit = update_info["remote_commit"]
    logger.info(
        f"[GitNotifier] 发现远程仓库领先 {ahead_count} 个提交 (最新远程 commit: {remote_commit[:8]})"
    )

    if not force_notify and git_service.is_notified(remote_commit):
        logger.info(f"[GitNotifier] 远程 commit {remote_commit[:8]} 已在之前通知过管理员，跳过重复提醒")
        return update_info

    if notify_master and master_id:
        reported = False
        if use_mai:
            reported = await report_update_via_core_reply(bot, config, master_id, update_info)

        if not reported:
            await report_update_fallback(bot, config, master_id, update_info)

        git_service.mark_notified(remote_commit, ahead_count, update_info["branch"])

    return update_info


async def git_monitor_loop(bot: ExtendBot, config, git_service: GitService):
    plugin_cfg = _get_plugin_config(config)
    initial_delay = float(plugin_cfg.get("initial_delay", 20))
    check_interval = float(plugin_cfg.get("check_interval", 1800))

    logger.info(f"[GitNotifier] 定时监控协程已启动，将在 {initial_delay} 秒后首次检查，之后每 {check_interval} 秒检查一次")
    await asyncio.sleep(initial_delay)

    while True:
        try:
            current_cfg = _get_plugin_config(config)
            if not current_cfg.get("enable", True):
                logger.info("[GitNotifier] 插件已被禁用，跳过检查")
                await asyncio.sleep(60)
                continue

            interval = float(current_cfg.get("check_interval", 1800))
            await perform_update_check(bot, config, git_service, is_manual=False)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[GitNotifier] 监控协程被取消退出")
            break
        except Exception as e:
            logger.error(f"[GitNotifier] 监控循环异常: {e}", exc_info=True)
            await asyncio.sleep(60)


def main(bot: ExtendBot, config):
    plugin_cfg = _get_plugin_config(config)
    if not plugin_cfg.get("enable", True):
        bot.logger.info("[GitNotifier] 插件未启用 (enable=false)")
        return

    git_service = GitService()

    global _bg_task, _loop_started

    def _start_background_loop():
        global _bg_task, _loop_started
        if _loop_started and _bg_task is not None and not _bg_task.done():
            return
        _loop_started = True
        _bg_task = asyncio.create_task(git_monitor_loop(bot, config, git_service))
        bot.logger.info("[GitNotifier] 定时检查远程仓库任务已投入运行")

    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(event: LifecycleMetaEvent):
        _start_background_loop()

    bot_loop = getattr(bot, "loop", None)
    if bot_loop and bot_loop.is_running():
        try:
            bot_loop.call_soon_threadsafe(_start_background_loop)
        except Exception:
            pass

    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def handle_git_commands(event: GroupMessageEvent | PrivateMessageEvent):
        text = (getattr(event, "pure_text", "") or "").strip()
        command_list = ["/git check", "/git status", "检查更新", "查看更新", "/check_update"]
        if text not in command_list:
            return

        current_cfg = _get_plugin_config(config)
        master_id = _get_master_id(config, current_cfg)

        if event.user_id != master_id:
            await bot.send(event, [Text("只有机器人的管理员（Master）才可以执行检查更新指令哦~")])
            return

        await bot.send(event, [Text("正在检查远程仓库更新状态，请稍候...")])

        try:
            update_info = await perform_update_check(
                bot, config, git_service, is_manual=True, force_notify=True
            )

            if not update_info["success"]:
                await bot.send(event, [Text(f"❌ 检查更新失败：\n{update_info['error']}")])
                return

            if not update_info["is_ahead"]:
                if current_cfg.get("notify_up_to_date_on_manual", True):
                    await bot.send(
                        event,
                        [Text(f"✅ 当前已是最新版本！\n分支：{update_info['branch']}\n最新提交：{update_info['local_commit'][:8]}\n暂无需要更新的内容。")]
                    )
            else:
                await bot.send(
                    event,
                    [Text(f"✨ 发现远程分支 {update_info['branch']} 领先 {update_info['ahead_count']} 个提交！已开始生成详细更新汇报通知 Master（您也可以直接对我下达「更新系统」指令让我自动完成更新）...")]
                )

        except Exception as e:
            bot.logger.error(f"[GitNotifier] 手动检查更新异常: {e}", exc_info=True)
            await bot.send(event, [Text(f"❌ 检查时发生错误: {e}")])