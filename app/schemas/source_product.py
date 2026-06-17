from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from app.adapters.contracts import AdapterVariantDraft


WeightSource = Literal["source", "keyword_rule", "missing"]


class SourceProductDraft(TypedDict):
    url: str
    handle: str
    title: str
    description_html: str | None
    description: str | None
    designer: str | None
    category: str | None
    tags: list[str]
    source_weight_grams: int | None
    resolved_weight_grams: int | None
    # Backward-compatible alias for downstream legacy payload builders.
    weight_grams: int | None
    weight_source: WeightSource
    images: list[str]
    variants: list[AdapterVariantDraft]
    gender: str
    buyer_total_price_amount: NotRequired[object | None]
    buyer_service_fee_amount: NotRequired[object | None]
    source_ref: NotRequired[dict]
