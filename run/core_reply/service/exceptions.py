"""Exceptions and response validation for core_reply."""

DEFAULT_REJECTED_RESPONSE_MODELS = ("ministral-3-3b",)
DEFAULT_REJECTED_RESPONSE_KEYWORDS = ()


class LLMResponseError(RuntimeError):
    """The upstream response cannot be used as a successful AI reply."""


class RejectedResponseModelError(LLMResponseError):
    """The upstream returned a model that must be treated as a failure."""


class RejectedResponseContentError(LLMResponseError):
    """The upstream returned content that must be treated as a failure."""


def normalize_rejected_list(value, default=(), *, strip_items=False):
    """Normalize a configured string or sequence into a tuple of non-empty strings."""
    if value is None:
        return tuple(default)
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return tuple(default)

    normalized = []
    for item in items:
        if item is None:
            continue
        text = str(item)
        if strip_items:
            text = text.strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def validate_response_model(response, rejected_models=None):
    """Check the model field of the actual upstream response body."""
    if not isinstance(response, dict):
        return
    models = DEFAULT_REJECTED_RESPONSE_MODELS if rejected_models is None else normalize_rejected_list(rejected_models, strip_items=True)
    if not models:
        return
    model = response.get("model") or response.get("modelVersion")
    if isinstance(model, str) and model in models:
        raise RejectedResponseModelError(f"Upstream returned rejected model: {model}")


def validate_response_content(content, rejected_keywords=None):
    """Check whether response text contains any rejected keyword."""
    if not isinstance(content, str) or not content:
        return
    keywords = DEFAULT_REJECTED_RESPONSE_KEYWORDS if rejected_keywords is None else normalize_rejected_list(rejected_keywords, strip_items=False)
    for keyword in keywords:
        if keyword in content:
            raise RejectedResponseContentError(f"Upstream returned rejected keyword: {keyword!r}")
