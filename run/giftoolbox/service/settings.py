"""Shared, hot-reload-safe command settings for handlers and help rendering."""


def command_items(cfg):
    commands = cfg.get("commands") or []
    # Lists survive the project's schema merge unchanged, including user aliases.
    # Keep accepting the initial PR's mapping shape for existing installations.
    if isinstance(commands, dict):
        commands = commands.values()
    elif not isinstance(commands, list):
        return []
    return [item for item in commands if isinstance(item, dict)]


def enabled(item):
    value = item.get("enable", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "off", "no", "关", "关闭", "禁用")
    return bool(value)
