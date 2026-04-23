"""Shopify parser engine adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.config import settings
from app.parsers.engines.contracts import ParserType
from app.parsers.shopify.fallback import discover_with_browser_fallback
from app.parsers.shopify.parser import ShopifyParser


@dataclass(slots=True)
class ShopifyParserEngine:
    """Shopify engine with internal browser-fallback policy."""

    parser_type: ParserType = "shopify"

    def discover(
        self,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
        on_detail_progress: Callable[[dict], None] | None = None,
    ):
        primary_result = ShopifyParser.discover(
            base_url,
            max_products=settings.parser_default_max_products,
            sample_products=settings.parser_default_sample_products,
            timeout_sec=settings.parser_default_timeout_sec,
            fetch_all_products=True,
            response_products_limit=settings.parser_default_max_products,
            error_details_limit=settings.parser_default_error_details_limit,
            parallel_workers=settings.parser_default_parallel_workers,
            max_retries=settings.parser_default_max_retries,
            retry_backoff_sec=settings.parser_default_retry_backoff_sec,
            second_pass_enabled=settings.parser_default_second_pass_enabled,
            second_pass_timeout_sec=settings.parser_default_second_pass_timeout_sec,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
            on_detail_progress=on_detail_progress,
        )
        return discover_with_browser_fallback(
            primary_result=primary_result,
            base_url=base_url,
            on_progress=on_progress,
            on_detail_progress=on_detail_progress,
        )
