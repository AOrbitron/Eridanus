"""Adapted from BeyondUID 95ba169 (GPL-3.0-or-later). See ../GUIDE_SOURCES.md."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, model_validator

from ..guide_resource import read_tables

DEFAULT_I18N_TABLE_FILENAME = "I18nTextTable_CN.json"


@lru_cache(maxsize=1)
def _load_i18n_table(
    filename: str = DEFAULT_I18N_TABLE_FILENAME,
) -> dict[str, str]:
    data = read_tables("endfield").get(filename.removesuffix(".json"), {})

    if not isinstance(data, dict):
        return {}

    return {str(key): value for key, value in data.items() if isinstance(value, str)}


def clear_i18n_text_cache() -> None:
    _load_i18n_table.cache_clear()


def get_i18n_text_by_hash(text_hash: int | str | None) -> str:
    if text_hash in (None, "", 0, "0"):
        return ""
    return _load_i18n_table().get(str(text_hash), "")


def get_i18n_text(value: Any) -> str:
    if isinstance(value, I18nText):
        text = (value.text or "").strip()
        return text or get_i18n_text_by_hash(value.id)

    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return get_i18n_text_by_hash(value.get("id"))

    if isinstance(value, str):
        return value.strip()

    return ""


class I18nText(BaseModel):
    id: int
    text: str | None

    @model_validator(mode="after")
    def _fill_text_from_hash(self) -> "I18nText":
        if self.text and self.text.strip():
            self.text = self.text.strip()
        else:
            self.text = get_i18n_text_by_hash(self.id)
        return self

    @property
    def value(self) -> str:
        return get_i18n_text(self)

    def __str__(self) -> str:
        return self.value
