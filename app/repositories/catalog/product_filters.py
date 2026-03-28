"""Filtering/query helpers for parser product repository."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_

from app.models import ParserProduct


def apply_vendor_filter(query, vendors: Optional[list[str]], no_brand_filter: str):
    """Apply vendor list filter including explicit no-brand sentinel."""
    if not vendors:
        return query

    brand_values = [value for value in vendors if value != no_brand_filter]
    without_brand = no_brand_filter in vendors
    conditions = []
    if brand_values:
        conditions.append(ParserProduct.vendor.in_(brand_values))
    if without_brand:
        conditions.append(or_(ParserProduct.vendor.is_(None), ParserProduct.vendor == ""))
    if conditions:
        query = query.filter(or_(*conditions))
    return query


def build_filtered_query(
    base_query,
    *,
    source_ids: Optional[list[int]],
    vendors: Optional[list[str]],
    product_types: Optional[list[str]],
    status: Optional[str],
    price_min: Optional[float],
    price_max: Optional[float],
    search_text: Optional[str],
    no_brand_filter: str,
):
    """Build common filtered query used by list and count operations."""
    query = base_query.filter(ParserProduct.deleted_at.is_(None))

    if source_ids:
        query = query.filter(ParserProduct.source_id.in_(source_ids))

    query = apply_vendor_filter(query, vendors, no_brand_filter)

    if product_types:
        query = query.filter(ParserProduct.product_type.in_(product_types))

    if status:
        query = query.filter(ParserProduct.status == status)

    if price_min is not None:
        query = query.filter(ParserProduct.price >= price_min)

    if price_max is not None:
        query = query.filter(ParserProduct.price <= price_max)

    if search_text:
        search_pattern = f"%{search_text}%"
        query = query.filter(
            or_(
                ParserProduct.title.ilike(search_pattern),
                ParserProduct.handle.ilike(search_pattern),
                ParserProduct.vendor.ilike(search_pattern),
            )
        )

    return query
