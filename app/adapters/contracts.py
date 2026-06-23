from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import NotRequired, Protocol, Sequence, TypedDict


@dataclass(frozen=True)
class SourceContext:
    source_key: str
    source_url: str
    adapter_key: str
    source_config: dict


@dataclass(frozen=True)
class StrategyContext:
    source: SourceContext
    dry_run: bool = False
    run_id: str = ''
    candidate_urls: tuple[str, ...] = ()
    candidate_only: bool = False
    diagnostics: dict[str, int | float | str] = field(default_factory=dict)


class AdapterVariantDraft(TypedDict):
    id: str | None
    title: str | None
    sku: str | None
    price_amount: Decimal | None
    currency_code: str | None
    available: bool
    option1: NotRequired[str | None]
    option2: NotRequired[str | None]
    option3: NotRequired[str | None]
    compare_at_price_amount: NotRequired[Decimal | None]


class AdapterProductDraft(TypedDict):
    url: str
    handle: str
    title: str
    description_html: str | None
    designer: str | None
    category: str | None
    tags: list[str]
    source_weight_grams: Decimal | None
    images: list[str]
    variants: list[AdapterVariantDraft]
    buyer_total_price_amount: NotRequired[Decimal | None]
    buyer_service_fee_amount: NotRequired[Decimal | None]


class Strategy(Protocol):
    name: str

    def run(self, context: StrategyContext) -> list[dict]:
        """Return raw product records for this strategy."""


class SiteAdapter(Protocol):
    adapter_key: str
    allowed_strategies: Sequence[str]

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        """Return visible catalog urls for baseline coverage."""

    def normalize_product(self, raw_product: dict) -> AdapterProductDraft:
        """Normalize raw record into strict adapter draft contract."""

    def validate_product(self, normalized_product: AdapterProductDraft) -> tuple[bool, list[str]]:
        """Return validation result and machine-readable reasons."""
