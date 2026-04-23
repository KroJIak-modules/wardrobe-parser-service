"""Parser engine registry for parser_type-based dispatch."""

from __future__ import annotations

from typing import cast

from app.core.exceptions import ValidationError
from app.parsers.crawlee.engine import CrawleeParserEngine
from app.parsers.engines.contracts import ParserEngine, ParserType
from app.parsers.shopify.engine import ShopifyParserEngine


_ENGINES: dict[ParserType, ParserEngine] = {
    "shopify": ShopifyParserEngine(),
    "crawlee": CrawleeParserEngine(),
}


def get_parser_engine(parser_type: str) -> ParserEngine:
    """Resolve parser engine by parser_type or raise ValidationError."""
    engine = _ENGINES.get(cast(ParserType, parser_type))
    if not engine:
        raise ValidationError(f"Неподдерживаемый parser_type: {parser_type}")
    return engine
