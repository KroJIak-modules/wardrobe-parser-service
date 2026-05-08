from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SourceContext:
    source_id: int
    source_key: str
    source_url: str
    adapter_key: str
    source_config: dict


@dataclass(frozen=True)
class StrategyContext:
    source: SourceContext
    dry_run: bool = False


class Strategy(Protocol):
    name: str

    def run(self, context: StrategyContext) -> list[dict]:
        """Return raw product records for this strategy."""


class SiteAdapter(Protocol):
    adapter_key: str
    allowed_strategies: Sequence[str]

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        """Return visible catalog urls for baseline coverage."""

    def normalize_product(self, raw_product: dict) -> dict:
        """Normalize raw record into unified source product shape."""

    def validate_product(self, normalized_product: dict) -> tuple[bool, list[str]]:
        """Return validation result and machine-readable reasons."""
