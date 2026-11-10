# -*- coding: utf-8 -*-
"""
schedule_tool.py
定时任务 Function Calling 工具集：
- 供 LLM 自主安排、取消、查询定时任务
- 严格区分群聊（群内任务）与私聊（个人任务），防止跨域泄露或误取消
- 支持序号索引取消、关键词模糊匹配、或全部取消（"全部"/"all"）
- 支持多循环类型（一次性、每天、每周特定天、工作日、周末）
- 支持预输入嵌套 Function（例如睡前发送 ASMR）以及自然语言 Prompt
- 自动根据用户城市及所在时区与 Bot 默认时区（东八区）进行差异化换算
"""

import json
from developTools.utils.logger import get_logger
import datetime
from typing import Optional, Union, Dict, Any, List

from framework_common.database_util.User import get_user
from framework_common.schedule_service import get_scheduler, TimezoneHelper

logger = get_logger("ScheduleTool")


async def call_create_schedule_task(
    description: str,
    time_str: str,
    recur_type: str = "once",
    weekdays: str = "",
    action_type: str = "message",
    prompt_or_message: str = "",
    tool_name: str = "",
    tool_params: Union[dict, str, None] = None,
    city: str = "",
    bot=None,
    event=None,
    config=None,
) -> str:
    """创建/安排一个定时任务"""
    try:
        user_id = getattr(event, "user_id", None)
        group_id = getattr(event, "group_id", None)
        is_group = bool(group_id)

        target_type = "group" if is_group else "private"
        target_id = int(group_id) if is_group else (int(user_id) if user_id else 0)
        creator_id = int(user_id) if user_id else 0

        user_city = (city or "").strip()
        if not user_city and user_id:
            try:
                user_info = await get_user(int(user_id))
                if user_info and user_info.city:
                    user_city = user_info.city.strip()
            except Exception as e:
                logger.warning(f"[ScheduleTool] 获取用户城市失败: {e}")

        parsed_tool_params: Dict[str, Any] = {}
        if tool_params:
            if isinstance(tool_params, dict):
                parsed_tool_params = tool_params
            elif isinstance(tool_params, str):
                try:
                    parsed_tool_params = json.loads(tool_params)
                except Exception:
                    parsed_tool_params = {}

        action_payload: Dict[str, Any] = {}
        if action_type in ("tool", "function_call"):
            action_type = "function_call"
            action_payload = {
                "func_name": tool_name.strip(),
                "parameters": parsed_tool_params,
            }
        else:
            action_type = "message"
            action_payload = {
                "prompt": (prompt_or_message or description).strip()
            }

        scheduler = get_scheduler(bot=bot, config=config)

        # 防抖与去重机制（Debounce / Deduplication）：
        # LLM 在同一轮对话中如果连续调用或因思考延迟重复调用创建工具，
        # 容易针对同一事件创建两个几乎同时触发的任务。
        # 1. 意图/描述高度相似且触发时间差 <= 180 秒，视为重复任务直接复用；
        # 2. 相同循环周期且触发时间差 <= 30 秒，视为重复任务。
        active_tasks = await scheduler.list_active_tasks(target_id=target_id, target_type=target_type)
        candidate_next_ts = scheduler.calculate_initial_next_run(time_str, recur_type, None, user_city)
        clean_desc = description.strip().lower()
        clean_prompt = (prompt_or_message or '').strip().lower()
        for existing_task in active_tasks:
            ext_desc = existing_task.description.strip().lower()
            ext_payload = existing_task.get_payload_dict()
            ext_prompt = (ext_payload.get('prompt') or ext_payload.get('message') or '').strip().lower()
            
            desc_similar = (
                clean_desc == ext_desc
                or (clean_prompt and (clean_prompt == ext_prompt or clean_prompt in ext_desc or ext_desc in clean_prompt))
                or (clean_desc in ext_desc or ext_desc in clean_desc)
            )
            time_diff = abs(existing_task.next_run_timestamp - candidate_next_ts)
            
            # 发现高度重合的近期任务，直接复用以避免并发双重触发
            if (desc_similar and time_diff <= 180) or (existing_task.recur_type == recur_type and time_diff <= 30):
                logger.info(f"[ScheduleTool] 检测到重复或重叠定时任务 [{existing_task.task_id}] ({existing_task.description})，自动复用防抖")
                task = existing_task
                break
        else:
            task = await scheduler.add_task(
                creator_id=creator_id,
                target_type=target_type,
                target_id=target_id,
                task_type="function_call" if action_type == "function_call" else "reminder",
                time_str=time_str,
                recur_type=recur_type,
                weekdays=weekdays,
                city=user_city,
                action_type=action_type,
                action_payload=action_payload,
                description=description,
            )

        next_dt = datetime.datetime.fromtimestamp(task.next_run_timestamp)
        _, tz_name, _ = TimezoneHelper.resolve_timezone(user_city)

        recur_map = {
            "once": "单次任务",
            "daily": "每天循环",
            "weekly": f"每周循环 ({task.weekdays or '指定星期'})",
            "workday": "工作日循环 (周一至周五)",
            "weekend": "周末循环 (周六和周日)",
            "yearly": "每年循环 (生日/纪念日)",
        }
        recur_desc = recur_map.get(recur_type, recur_type)

        scope_desc = f"本群（群号 {target_id}）" if is_group else "私聊专属"
        tz_note = f"（根据所在城市 [{user_city}] / {tz_name} 时区智能换算）" if user_city else ""

        lines = [
            "已成功为您安排定时任务！",
            f"任务范围：{scope_desc}",
            f"任务内容：{task.description}",
            f"循环模式：{recur_desc}",
            f"设定时间：{task.time_str}{tz_note}",
            f"下次触发时间：{next_dt.strftime('%Y-%m-%d %H:%M:%S')} (东八区时间)"
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[ScheduleTool] 创建定时任务异常: {e}", exc_info=True)
        return f"创建定时任务失败：{e}"


async def call_cancel_schedule_task(
    task_id_or_keyword: str,
    bot=None,
    event=None,
    config=None,
) -> str:
    """取消定时任务。支持序号、关键词、或全部取消。系统后台任务受权限保护，不会被误取消。"""
    try:
        user_id = getattr(event, "user_id", None)
        group_id = getattr(event, "group_id", None)
        is_group = bool(group_id)

        target_id = int(group_id) if is_group else (int(user_id) if user_id else 0)
        target_type = "group" if is_group else "private"
        creator_id = int(user_id) if user_id else 0

        is_master = False
        try:
            if config and hasattr(config, "common_config"):
                master_id = int(config.common_config.basic_config.get("master", {}).get("id", 0) or 0)
                if user_id and int(user_id) == master_id:
                    is_master = True
        except Exception:
            pass

        scheduler = get_scheduler(bot=bot, config=config)
        kw = (task_id_or_keyword or "").strip()
        is_all_kw = kw.lower() in ["all", "全部", "所有", "清空", "取消全部", "全部取消", "全部闹钟", "所有任务"]

        digit_idx = None
        cn_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        clean_num_str = kw.replace("第", "").replace("个", "").replace("项", "").strip()
        if clean_num_str.isdigit():
            digit_idx = int(clean_num_str)
        elif clean_num_str in cn_num:
            digit_idx = cn_num[clean_num_str]

        if digit_idx is not None and digit_idx > 0:
            current_tasks = await scheduler.list_active_tasks(
                target_id=target_id,
                target_type=target_type
            )
            if not current_tasks and is_group and creator_id:
                current_tasks = await scheduler.list_active_tasks(
                    target_id=target_id,
                    target_type=target_type,
                    creator_id=creator_id
                )
            # 非 Master 过滤掉系统守护任务
            if not is_master:
                current_tasks = [t for t in current_tasks if not scheduler.is_system_task(t)]

            if 1 <= digit_idx <= len(current_tasks):
                target_task = current_tasks[digit_idx - 1]
                if scheduler.is_system_task(target_task) and not is_master:
                    return "系统后台守护任务受权限保护，仅 Master 可以管理。"
                cancelled = await scheduler.cancel_tasks(
                    task_id_or_keyword=target_task.task_id,
                    target_id=target_id,
                    target_type=target_type
                )
                if cancelled:
                    return f"已成功取消第 {digit_idx} 项任务：「{target_task.description}」，之后不会再触发。"

        # 非 Master 尝试取消系统守护任务时的拦截
        if not is_master and any(k in kw.lower() for k in ["qzone", "空间", "巡检", "保活"]):
            return "系统后台守护任务受权限保护，仅 Master 可以管理。"

        cancelled = await scheduler.cancel_tasks(
            task_id_or_keyword=kw,
            target_id=target_id,
            target_type=target_type
        )

        if not cancelled and is_group and creator_id:
            cancelled = await scheduler.cancel_tasks(
                task_id_or_keyword=kw,
                target_id=target_id,
                target_type=target_type,
                creator_id=creator_id
            )

        if cancelled:
            names = [f"「{t.description}」" for t in cancelled]
            system_note = "（系统守护巡检任务已受保护保留）" if (is_all_kw and is_master) else ""
            return f"已成功取消以下 {len(cancelled)} 个定时任务：{', '.join(names)}。{system_note}"
        else:
            context_hint = "当前群聊" if is_group else "您的私聊"
            return f"在{context_hint}中没有找到与「{task_id_or_keyword}」相关的有效定时任务。您可以让我先“查一下定时任务”看看列表再指定取消。"
    except Exception as e:
        logger.error(f"[ScheduleTool] 取消定时任务异常: {e}", exc_info=True)
        return f"取消定时任务失败：{e}"


async def call_list_schedule_tasks(
    bot=None,
    event=None,
    config=None,
) -> str:
    """查询当前环境生效中的定时任务列表。Master 私聊下会清晰区分个人日程与系统后台守护任务；普通用户仅能查看自己的任务。"""
    try:
        user_id = getattr(event, "user_id", None)
        group_id = getattr(event, "group_id", None)
        is_group = bool(group_id)

        target_id = int(group_id) if is_group else (int(user_id) if user_id else 0)
        target_type = "group" if is_group else "private"

        is_master = False
        try:
            if config and hasattr(config, "common_config"):
                master_id = int(config.common_config.basic_config.get("master", {}).get("id", 0) or 0)
                if user_id and int(user_id) == master_id:
                    is_master = True
        except Exception:
            pass

        scheduler = get_scheduler(bot=bot, config=config)
        tasks = await scheduler.list_active_tasks(target_id=target_id, target_type=target_type)

        scope_title = f"本群（群号 {target_id}）生效中的定时任务" if is_group else "您当前生效中的私聊定时任务"

        recur_map = {
            "once": "单次任务",
            "daily": "每天",
            "weekly": "每周",
            "workday": "工作日",
            "weekend": "周末",
            "yearly": "每年",
            "interval": "固定间隔",
        }

        def _format_task_entry(idx: int, t) -> str:
            next_dt = datetime.datetime.fromtimestamp(t.next_run_timestamp)
            payload_info = ""
            if t.action_type in ("tool", "function_call"):
                p_dict = t.get_payload_dict()
                t_name = p_dict.get("tool_name") or p_dict.get("func_name") or ""
                payload_info = f" [调用函数: {t_name}]" if t_name else ""

            tz_tag = f" ({t.target_city})" if t.target_city else ""
            recur_str = recur_map.get(t.recur_type, t.recur_type)
            if t.recur_type == "weekly" and t.weekdays:
                recur_str = f"每周 (周{t.weekdays})"

            return (
                f"{idx}. 「{t.description}」\n"
                f"   设定时间: {t.time_str}{tz_tag} | 频次: {recur_str}\n"
                f"   下次触发: {next_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"   任务类型: {t.action_type}{payload_info}"
            )

        # 区分 Master 私聊视图与普通用户/群聊视图
        if is_master and not is_group:
            user_tasks = [t for t in tasks if not scheduler.is_system_task(t)]
            sys_tasks = [t for t in tasks if scheduler.is_system_task(t)]

            if not user_tasks and not sys_tasks:
                return f"{scope_title}：\n当前没有任何生效中的定时任务哦。随时可以让我帮您设置一个~"

            sections = [f"Master 专属定时任务看板（共 {len(tasks)} 项）："]
            if user_tasks:
                sections.append(f"\n📌 【个人日程与提醒任务】（共 {len(user_tasks)} 项）：")
                for idx, t in enumerate(user_tasks, start=1):
                    sections.append(_format_task_entry(idx, t))
            else:
                sections.append("\n📌 【个人日程与提醒任务】：暂无（您可以随时吩咐我‘提醒我喝水’、‘每年生日祝我快乐’等）")

            if sys_tasks:
                sections.append(f"\n🛡️ 【系统后台守护任务】（仅 Master 可见，共 {len(sys_tasks)} 项）：")
                for idx, t in enumerate(sys_tasks, start=1):
                    sections.append(_format_task_entry(idx, t))
                sections.append("   ※ 提示：系统后台守护任务已受安全保护，执行“全部取消”时不会被误删。")

            sections.append("\n提示：您可以说“取消第1个”或“取消叫起床”来关闭对应的个人任务。")
            return "\n".join(sections)

        # 普通用户或群聊：自动过滤系统后台守护任务，保证隐私与安全隔离
        visible_tasks = [t for t in tasks if not scheduler.is_system_task(t)]
        if not visible_tasks:
            return f"{scope_title}：\n当前没有任何生效中的定时任务哦。随时可以让我帮您设置一个~"

        lines = [f"{scope_title}（共 {len(visible_tasks)} 项）："]
        for idx, t in enumerate(visible_tasks, start=1):
            lines.append(_format_task_entry(idx, t))
        lines.append("\n提示：您可以说“取消第1个”或“取消叫起床”来关闭对应的任务。")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[ScheduleTool] 查询定时任务列表异常: {e}", exc_info=True)
        return f"查询定时任务失败：{e}"
