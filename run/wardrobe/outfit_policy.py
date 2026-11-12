"""Validate the LLM response schema without interpreting or rewriting its tags."""


def validate_outfit_prompt(payload, *, require_native_hint=False):
    """Check field types only; clothing and scenes belong to the LLM."""
    if not isinstance(payload, dict):
        raise ValueError("LLM outfit prompt must be a JSON object")
    for field in ("clothing_tags", "native_hint_tags", "scene_tags"):
        if not isinstance(payload.get(field), str):
            raise ValueError(f"LLM outfit prompt requires string field {field}")
    if not payload["clothing_tags"].strip():
        raise ValueError("LLM clothing_tags must not be empty")
    if require_native_hint and not payload["native_hint_tags"].strip():
        raise ValueError("LLM native_hint_tags must not be empty")
    if type(payload.get("no_hat")) is not bool:
        raise ValueError("LLM no_hat must be a boolean")
