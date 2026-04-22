"""Crawlee parser engine adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.parsers.crawlee.client import CrawleeRunnerClient
from app.parsers.crawlee.mapper import to_shopify_discovery_result


@dataclass(slots=True)
class CrawleeParserEngine:
    """Parser engine implementation backed by Node.js Crawlee runner."""

    parser_type: str = "crawlee"

    def discover(
        self,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
        on_detail_progress: Callable[[dict], None] | None = None,
    ):
        _ = on_detail_progress
        if on_progress:
            on_progress()
        payload = CrawleeRunnerClient.run(
            base_url=base_url,
            deadline_monotonic=deadline_monotonic,
        )
        if on_progress:
            on_progress()
        return to_shopify_discovery_result(payload)
