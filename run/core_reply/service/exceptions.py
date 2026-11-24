"""Exceptions and response validation for core_reply."""


class LLMResponseError(RuntimeError):
    """The upstream response cannot be used as a successful AI reply."""


class RejectedResponseModelError(LLMResponseError):
    """The upstream returned a model that must be treated as a failure."""


def validate_response_model(response):
    """Check the model field of the actual upstream response body."""
    if response.get("model") == "ministral-3-3b":
        raise RejectedResponseModelError("Upstream returned rejected model: ministral-3-3b")
