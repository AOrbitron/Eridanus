"""Exceptions raised by the core reply LLM client."""


class LLMResponseError(RuntimeError):
    """The upstream response cannot be used as a successful AI reply."""


class RejectedResponseModelError(LLMResponseError):
    """The upstream returned a model that must be treated as a failure."""
