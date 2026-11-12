"""Drawing audit policy shared by SD, NAI and workflow entry points."""


def requires_nsfw_audit(draw_config, group_id):
    enabled = draw_config.get("禁止nsfw", False)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {"true", "yes", "on", "1"}
    if not enabled:
        return False
    allowed = {str(value) for value in (draw_config.get("allow_nsfw_groups") or [])}
    return str(group_id) not in allowed
