"""Shared parser engine contracts."""

from __future__ import annotations

from typing import Callable, Literal, Protocol

ParserType = Literal["shopify", "crawlee"]


class ParserEngine(Protocol):
    """Minimal parser engine contract used by sync services."""

    parser_type: ParserType

    def discover(
        self,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
        on_detail_progress: Callable[[dict], None] | None = None,
    ):
        """Run source discovery and return result with previews/counters."""
