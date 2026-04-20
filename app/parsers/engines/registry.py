"""Parser engine registry for parser_type-based dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.parsers.crawlee.engine import CrawleeParserEngine
from app.parsers.shopify.parser import ShopifyParser
from app.parsers.shopify.fallback import discover_with_browser_fallback

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
    ):
        """Run source discovery and return result with previews/counters."""


@dataclass(slots=True)
class ShopifyParserEngine:
    """Shopify parser engine adapter."""

    parser_type: ParserType = "shopify"

    def discover(
        self,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
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
        )
        return discover_with_browser_fallback(
            primary_result=primary_result,
            base_url=base_url,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
        )


_ENGINES: dict[ParserType, ParserEngine] = {
    "shopify": ShopifyParserEngine(),
    "crawlee": CrawleeParserEngine(),
}


def get_parser_engine(parser_type: str) -> ParserEngine:
    """Resolve parser engine by parser_type or raise ValidationError."""
    engine = _ENGINES.get(parser_type)  # type: ignore[arg-type]
    if not engine:
        raise ValidationError(f"Неподдерживаемый parser_type: {parser_type}")
    return engine
