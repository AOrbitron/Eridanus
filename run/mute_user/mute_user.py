from developTools.event.events import GroupMessageEvent


DEFAULT_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 30 * 24 * 60


async def mute_group_user(
    bot,
    event,
    config,
    target_user_id: int,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
):
    """Mute a user in the current group for the requested number of minutes."""
    if not isinstance(event, GroupMessageEvent) or not getattr(event, "group_id", None):
        return "禁言功能只能在群聊中使用。"

    sender = getattr(event, "sender", None)
    sender_role = getattr(sender, "role", "member")
    master_id = int(config.common_config.basic_config["master"]["id"])
    operator_id = int(event.user_id)
    if sender_role not in {"owner", "admin"} and operator_id != master_id:
        return "操作失败：只有群主、群管理员或 bot 主人可以禁言用户。"

    try:
        target_user_id = int(target_user_id)
        duration_minutes = int(duration_minutes)
    except (TypeError, ValueError):
        return "操作失败：用户 ID 和禁言时长必须是整数。"

    if target_user_id <= 0:
        return "操作失败：用户 ID 无效。"
    if not 1 <= duration_minutes <= MAX_DURATION_MINUTES:
        return "操作失败：禁言时长必须在 1 到 43200 分钟之间。"
    if target_user_id == int(bot.id):
        return "操作失败：不能禁言 bot 自身。"

    duration_seconds = duration_minutes * 60
    try:
        await bot.mute(event.group_id, target_user_id, duration_seconds)
    except Exception as exc:
        bot.logger.error(
            f"禁言用户失败: group={event.group_id}, user={target_user_id}, "
            f"duration={duration_seconds}s, error={exc}"
        )
        return "禁言失败，请确认 bot 具有群管理员权限且目标用户可被管理。"

    return f"已禁言用户 {target_user_id}，时长 {duration_minutes} 分钟。"
