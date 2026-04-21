"""Browser-parser engine adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.parsers.browser_parser.client import BrowserParserRunnerClient
from app.parsers.browser_parser.mapper import to_shopify_discovery_result


@dataclass(slots=True)
class BrowserParserEngine:
    """Run browser-parser and map output into shared discovery model."""

    parser_type: str = "browser_parser"

    def discover(
        self,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
        export_concurrency: int | None = None,
    ):
        if on_progress:
            on_progress()
        payload = BrowserParserRunnerClient.run(
            base_url=base_url,
            deadline_monotonic=deadline_monotonic,
            export_concurrency=export_concurrency,
        )
        if on_progress:
            on_progress()
        return to_shopify_discovery_result(payload)
