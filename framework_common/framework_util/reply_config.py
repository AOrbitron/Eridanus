"""Resolve the active reply configuration for shared plugin features.

core_reply has a different schema from ai_llm. Do not map one onto the other or
require legacy credentials when the new reply engine is enabled.
"""


def core_reply_enabled(config):
    core = getattr(config, "core_reply", None)
    return bool(core and core.config.get("enable", False))


def active_reply_config(config):
    if core_reply_enabled(config):
        return config.core_reply.config
    legacy = getattr(config, "ai_llm", None)
    return legacy.config if legacy else {}


def active_llm_config(config):
    return active_reply_config(config).get("llm", {})


async def auxiliary_reply(prompt, config, **legacy_kwargs):
    """Generate text without recording a user chat or invoking chat triggers."""
    if core_reply_enabled(config):
        from run.core_reply.service.llm_client import LLMClient

        client = LLMClient(config)
        try:
            return await client.chat([{"role": "user", "content": prompt}])
        finally:
            await client.aclose()
    from run.ai_llm.service.aiReplyCore import aiReplyCore

    user_id = legacy_kwargs.pop("user_id", 0)
    return await aiReplyCore([{"text": prompt}], user_id, config, **legacy_kwargs)


async def legacy_reply(*args, **kwargs):
    """Load legacy dependencies only when an explicit legacy branch runs."""
    from run.ai_llm.service.aiReplyCore import aiReplyCore

    return await aiReplyCore(*args, **kwargs)
