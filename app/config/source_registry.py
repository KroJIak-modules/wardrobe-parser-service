"""Load and query parser sources from external config file."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import ValidationError


_service_root = Path(__file__).resolve().parents[2]


class SourceEntry(BaseModel):
    """One source entry from sources file."""

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=1024)
    parser_type: Literal["shopify", "custom"]
    enabled: bool = True
    notes: str | None = None


def _resolve_sources_file_path() -> Path:
    raw = settings.parser_sources_file.strip()
    if not raw:
        raise ValidationError("PARSER_SOURCES_FILE не задан")

    path = Path(raw)
    if path.is_absolute():
        return path
    return (_service_root / path).resolve()


@lru_cache(maxsize=1)
def load_sources() -> list[SourceEntry]:
    """Load all sources from configured JSON file."""
    path = _resolve_sources_file_path()
    if not path.exists():
        raise ValidationError(f"Файл источников не найден: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Некорректный JSON в файле источников: {exc}") from exc

    if isinstance(payload, dict):
        raw_sources = payload.get("sources")
    else:
        raw_sources = payload

    if not isinstance(raw_sources, list):
        raise ValidationError("Файл источников должен содержать список 'sources'")

    sources: list[SourceEntry] = []
    for raw_item in raw_sources:
        if not isinstance(raw_item, dict):
            continue
        sources.append(SourceEntry.model_validate(raw_item))
    return sources


def get_source_by_key(source_key: str) -> SourceEntry:
    """Find one source by key or raise ValidationError."""
    key = source_key.strip()
    if not key:
        raise ValidationError("source_key не может быть пустым")

    for source in load_sources():
        if source.key == key:
            return source
    raise ValidationError(f"Источник с key='{key}' не найден в sources файле")


def list_sources(*, parser_type: Literal["shopify", "custom"] | None = None) -> list[SourceEntry]:
    """List sources optionally filtered by parser_type."""
    items = load_sources()
    if parser_type is None:
        return items
    return [item for item in items if item.parser_type == parser_type]
