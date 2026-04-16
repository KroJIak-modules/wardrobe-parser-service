"""Helpers for deriving persisted product status from variant availability."""

from __future__ import annotations

from typing import Any

from app.models import ProductStatus


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "in_stock"}:
        return True
    if normalized in {"0", "false", "no", "n", "out_of_stock"}:
        return False
    return None


def _variant_is_available(variant: dict[str, Any]) -> bool | None:
    available_flag = _to_bool(variant.get("available"))
    if available_flag is True:
        return True

    inventory_raw = variant.get("inventory_quantity")
    if inventory_raw is not None:
        try:
            return float(inventory_raw) > 0
        except (TypeError, ValueError):
            pass

    if available_flag is False:
        return False
    return None


def resolve_product_status(
    *,
    variants: list[dict[str, Any]] | None,
    preview_available: bool | None = None,
    existing_status: ProductStatus | str | None = None,
) -> ProductStatus:
    """Resolve product status with strict no-variants -> out_of_stock policy."""
    if existing_status == ProductStatus.HIDDEN or str(existing_status or "").strip().lower() == ProductStatus.HIDDEN.value:
        return ProductStatus.HIDDEN

    parsed_variants: list[dict[str, Any]] = [item for item in (variants or []) if isinstance(item, dict)]
    if not parsed_variants:
        return ProductStatus.OUT_OF_STOCK

    has_signal = False
    for item in parsed_variants:
        variant_available = _variant_is_available(item)
        if variant_available is None:
            continue
        has_signal = True
        if variant_available:
            return ProductStatus.AVAILABLE

    if has_signal:
        return ProductStatus.OUT_OF_STOCK
    if preview_available is True:
        return ProductStatus.AVAILABLE
    return ProductStatus.OUT_OF_STOCK
