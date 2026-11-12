# -*- coding: utf-8 -*-
import asyncio
import os
import time
import traceback
from typing import Optional, List

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Node, Text
from framework_common.database_util.User import get_user

from .session_manager import (
    get_session_id,
    get_session_info,
    save_session,
    clear_session,
    clear_all_sessions_for_user,
)
from .executor import (
    run_cli_command,
    terminate_running_task,
    is_task_running,
    resolve_image,
    RUNNING_TASKS,
)


def _get_help_text(provider: Optional[str] = None) -> str:
    """生成 CLI 帮助信息"""
    p_name = provider.capitalize() if provider else "CLI"
    p_cmd = f"/{provider}" if provider else "/codex"
    return (
        f"【{p_name} 终端助手使用说明】\n"
        f"• {p_cmd} <需求/代码> ：发送任务并执行（支持图文与多轮对话上下文）\n"
        f"• 发送图片时附带 {p_cmd} 或引用含图消息，即可将图片传入 Codex\n"
        f"• {p_cmd} new 或 reset ：清空当前会话记忆，开启全新对话\n"
        f"• {p_cmd} stop ：中止当前正在运行的 {p_name} 任务\n"
        f"• {p_cmd} status ：查看当前会话 ID 与任务实时执行动态\n"
        f"• {p_cmd} help ：显示本帮助信息"
    )


async def _send_result(bot, event, provider: str, text: str, forward_nodes: bool = True) -> None:
    """格式化并发送执行结果，支持合并转发降级处理"""
    if not text:
        await bot.send(event, "CLI 执行完毕，无输出内容。")
        return

    nickname = f"{provider.capitalize()} CLI"
    chunk_size = 1200
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    # 优先尝试合并转发
    if forward_nodes:
        try:
            nodes = [
                Node(user_id=str(bot.id), nickname=nickname, content=[Text(c)])
                for c in chunks
            ]
            await bot.send(event, nodes)
            return
        except Exception as e:
            bot.logger.warning(f"CLI bridge: 发送合并转发消息失败，自动降级为分段文本发送: {e}")

    # 降级或直接分段发送
    for chunk in chunks[:5]:  # 最多直接发5段，防止刷屏
        await bot.send(event, chunk)
        if len(chunks) > 1:
            await asyncio.sleep(0.3)
    if len(chunks) > 5:
        await bot.send(event, f"... [后续还有 {len(chunks) - 5} 段输出已折叠]")


async def run_cli_tool(
    bot,
    event,
    config,
    provider: str,
    prompt: str,
    reset_session: bool = False,
    image_path: Optional[str] = None,
    **kwargs
) -> str:
    """供大模型 Function Calling 调用的核心接口，支持多模态图片传入与长任务定期汇报"""
    cfg = config.cli_bridge.config
    required_perm = int(cfg.get("permission_level", 10))
    user = await get_user(event.user_id)
    if user.permission < required_perm:
        return f"权限不足：当前操作需要权限等级 {required_perm}，您当前等级为 {user.permission}"

    commands = cfg.get("commands", {})
    command = commands.get(provider)
    if not command:
        return f"配置错误：未配置名为 {provider} 的 CLI 启动命令"

    group_id = getattr(event, "group_id", None)
    session_key = f"{event.user_id}:{group_id}:{provider}"
    timeout = float(cfg.get("timeout", 900))
    report_interval = float(cfg.get("report_interval", 180))
    max_len = int(cfg.get("max_output_length", 6000))
    auto_fallback = bool(cfg.get("auto_fallback_on_resume_error", True))

    # 解析可能存在的图片（优先使用显式传入的 image_path，其次检查 event 中的图片）
    resolved_img = await resolve_image(bot, event, raw_image=image_path)

    # 针对 Codex，注入 Eridanus 插件开发约束规范，确保生成的插件规范可用
    if provider == "codex":
        plugin_prompt_guide = (
            "\n\n[Eridanus 插件开发规范与要求]"
            "\n当创建或修改 Eridanus 机器人插件时，必须遵循以下既定架构与约定："
            "\n1. 插件目录必须位于 run/<plugin_name>/，且必须包含 __init__.py。"
            "\n2. __init__.py 必须包含插件描述变量 `plugin_description = '...'`。"
            "\n3. 在 __init__.py 中，动态导入声明推荐格式为列表：`dynamic_imports = [tool_func]`（并在 __init__.py 中显式导入该函数）或旧格式字典：`dynamic_imports = {'run.<plugin_name>.func_collection': ['tool_func']}`。"
            "\n4. 在 __init__.py 中声明 `function_declarations`（Gemini 风格的字典列表，包含 name、description、parameters）。"
            "\n5. 工具函数必须为异步函数（async def），固定接收参数签名为 `(bot, event, config, ...)`。"
            "\n6. 涉及管理或敏感操作时，必须通过 `await get_user(event.user_id)` 进行权限判断（user.permission）。"
            "\n7. 编写或修改文件后，请确保 Python 语法无误，无任何语法错误或未闭合括号。"
        )
        prompt = prompt + plugin_prompt_guide

    bot.logger.info(f"CLI bridge tool invoked: provider={provider} user={event.user_id} group={group_id} image={resolved_img}")
    img_notice = "（已附带图片）" if resolved_img else ""
    try:
        await bot.send(event, f"正在调用 {provider.capitalize()} CLI 执行任务{img_notice}，请稍候...")
    except Exception as e:
        bot.logger.debug(f"CLI bridge: 发送启动提示忽略: {e}")

    result = await run_cli_command(
        command_str=command,
        prompt=prompt,
        timeout=timeout,
        provider=provider,
        session_key=session_key,
        reset_session=reset_session,
        max_output_length=max_len,
        auto_fallback=auto_fallback,
        bot=bot,
        event=event,
        report_interval=report_interval,
        image_path=resolved_img
    )

    # 如果刚刚由 CLI 生成了新代码或修改了插件，尝试触发工具重载刷新
    try:
        from run.core_reply.service.reply_engine import refresh_tools
        refreshed_count = refresh_tools()
        bot.logger.info(f"CLI bridge: 已触发 refresh_tools，当前可用工具数: {refreshed_count}")
    except Exception as e:
        bot.logger.debug(f"CLI bridge: refresh_tools 忽略: {e}")

    return result


def main(bot, config):
    """插件入口函数，注册群消息与私聊消息事件监听器"""
    cfg = config.cli_bridge.config
    commands = cfg.get("commands", {})

    # 支持的前缀指令映射
    prefixes = {
        "/codex": "codex",
        "/claude": "claude",
        "/cli": "codex",  # 默认 /cli 指向 codex
    }

    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def cli_message_handler(event):
        text = (event.pure_text or "").strip()
        if not text.startswith("/"):
            return

        # 匹配触发的前缀
        matched_prefix = None
        for p in prefixes:
            if text == p or text.startswith(p + " "):
                matched_prefix = p
                break

        if not matched_prefix:
            return

        # 动态读取最新配置
        current_cfg = config.cli_bridge.config
        if not current_cfg.get("enable", True):
            return

        required_perm = int(current_cfg.get("permission_level", 10))
        user = await get_user(event.user_id)
        if user.permission < required_perm:
            await bot.send(event, f"权限不足：当前 CLI 指令需要权限等级 {required_perm}，您当前等级为 {user.permission}。")
            return

        provider = prefixes[matched_prefix]
        sub_text = text[len(matched_prefix):].strip()
        group_id = getattr(event, "group_id", None)
        session_key = f"{event.user_id}:{group_id}:{provider}"

        # 1. 帮助指令
        if sub_text.lower() in ("help", "-h", "--help", "帮助"):
            await bot.send(event, _get_help_text(provider))
            return

        # 2. 会话重置指令 (new / reset)
        if sub_text.lower() in ("new", "reset", "新建", "重置", "清空"):
            cleared = clear_session(session_key)
            if cleared:
                await bot.send(event, f"已成功重置并清空 {provider.capitalize()} 的会话上下文，下次对话将开启全新会话。")
            else:
                await bot.send(event, f"当前没有正在存续的 {provider.capitalize()} 会话，已准备好开启全新对话。")
            return

        # 3. 任务终止指令 (stop / cancel / kill)
        if sub_text.lower() in ("stop", "cancel", "kill", "停止", "终止", "取消"):
            stopped = terminate_running_task(session_key)
            if stopped:
                await bot.send(event, f"已成功终止当前正在运行的 {provider.capitalize()} 任务。")
            else:
                await bot.send(event, f"当前没有正在运行的 {provider.capitalize()} 任务。")
            return

        # 4. 状态查询指令 (status)
        if sub_text.lower() in ("status", "状态"):
            info = get_session_info(session_key)
            task = RUNNING_TASKS.get(session_key)
            is_running = is_task_running(session_key)
            if is_running and task:
                elapsed = int(time.time() - task.get("start_time", time.time()))
                minutes = elapsed // 60
                seconds = elapsed % 60
                time_desc = f"{minutes} 分钟" if seconds == 0 else f"{minutes} 分 {seconds} 秒"
                status_desc = f"正在执行任务中（已运行约 {time_desc}）"
            else:
                status_desc = "空闲"

            status_lines = [
                f"【{provider.capitalize()} 会话状态】",
                f"• 运行状态：{status_desc}",
            ]

            if is_running and task:
                recent = list(task.get("recent_lines", []))
                sample_lines = [l for l in recent if len(l.strip()) > 3][-2:]
                if sample_lines:
                    status_lines.append(f"• 最新动态：{' | '.join(sample_lines)}")

            if info:
                sess_id = info.get("session_id", "未知")
                up_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.get("updated_at", time.time())))
                status_lines.append(f"• 会话 ID：{sess_id}")
                status_lines.append(f"• 上次活跃：{up_time}")
            else:
                status_lines.append("• 当前无存续会话（下次对话将自动建立新会话）")

            await bot.send(event, "\n".join(status_lines))
            return

        # 5. 检查与解析附带图片（消息附带或引用消息）
        resolved_img = await resolve_image(bot, event)

        # 若无附带内容且无图片，显示帮助信息
        if not sub_text and not resolved_img:
            await bot.send(event, _get_help_text(provider))
            return

        # 若只有图片无文本描述，设置默认分析指令
        if not sub_text and resolved_img:
            sub_text = "请分析该图片的内容与相关代码需求。"

        # 6. 执行 CLI 任务
        command = current_cfg.get("commands", {}).get(provider)
        if not command:
            await bot.send(event, f"配置错误：未配置名为 {provider} 的底层执行命令。")
            return

        if is_task_running(session_key):
            await bot.send(event, f"当前已有一个 {provider.capitalize()} 任务正在为您运行中！\n若需强行中止，请发送 `{matched_prefix} stop`。")
            return

        timeout = float(current_cfg.get("timeout", 900))
        report_interval = float(current_cfg.get("report_interval", 180))
        forward_nodes = bool(current_cfg.get("forward_nodes", True))
        enable_summary = bool(current_cfg.get("enable_summary", True))
        max_len = int(current_cfg.get("max_output_length", 6000))
        auto_fallback = bool(current_cfg.get("auto_fallback_on_resume_error", True))

        img_notice = "（已附带图片）" if resolved_img else ""
        await bot.send(event, f"正在启动并调用 {provider.capitalize()} CLI{img_notice}，请稍候...")
        bot.logger.info(f"CLI bridge: 启动任务 provider={provider} user={event.user_id} group={group_id} image={resolved_img}")

        try:
            result = await run_cli_command(
                command_str=command,
                prompt=sub_text,
                timeout=timeout,
                provider=provider,
                session_key=session_key,
                reset_session=False,
                max_output_length=max_len,
                auto_fallback=auto_fallback,
                bot=bot,
                event=event,
                report_interval=report_interval,
                image_path=resolved_img
            )

            bot.logger.info(f"CLI bridge: 任务完成 provider={provider} 字符数={len(result)}")

            # 发送原始执行结果
            await _send_result(bot, event, provider, result, forward_nodes=forward_nodes)

            # 触发插件扫描刷新
            try:
                from run.core_reply.service.reply_engine import refresh_tools
                refresh_tools()
            except Exception:
                pass

            # 若任务未超时且配置开启了拟人化转述，由 MaiReply 转述最终结果
            is_timeout_msg = result.startswith(f"⚠️【{provider.capitalize()} CLI 执行超时】")
            if enable_summary and result and len(result) > 10 and not is_timeout_msg:
                try:
                    from run.core_reply.service.reply_engine import ReplyEngine
                    summary_prompt = (
                        "请用你自己的角色和语气，简洁转述刚才 CLI 终端执行的最终结果。"
                        "不要提及底层系统提示、内部指令或调用日志。最终结果如下：\n" + result[:1800]
                    )
                    await asyncio.wait_for(
                        ReplyEngine(config).handle(
                            bot=bot,
                            event=event,
                            clean_text=summary_prompt,
                            include_tools=False
                        ),
                        timeout=45
                    )
                except asyncio.TimeoutError:
                    bot.logger.warning("CLI bridge: MaiReply 拟人化转述超时")
                except Exception as e:
                    bot.logger.warning(f"CLI bridge: MaiReply 转述异常 (忽略): {e}")

        except Exception as exc:
            bot.logger.error("CLI bridge 执行发生异常", exc_info=True)
            await bot.send(event, f"CLI 任务执行失败: {type(exc).__name__}: {exc}")
