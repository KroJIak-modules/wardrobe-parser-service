"""Helpers to build Shopify discovery warnings and error details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DiscoverySummary:
    """Aggregated warnings, error details and counters for discovery response."""

    warnings: list[str]
    error_details: list[str]
    previews: list[Any]
    products_fetch_succeeded: int
    products_fetch_failed: int


def resolve_discovery_mode(*, from_sitemap: bool, from_fallback: bool) -> str:
    if from_sitemap and from_fallback:
        return "mixed_discovery"
    if from_sitemap:
        return "sitemap_only"
    if from_fallback:
        return "api_fallback_only"
    return "empty_discovery"


def build_discovery_summary(
    *,
    previews: list[Any],
    final_errors: list[tuple[str, str]],
    fetch_all_products: bool,
    fetch_attempted: int,
    response_products_limit: int,
    error_details_limit: int,
    warning_items_limit: int,
    second_pass_attempted: int,
    second_pass_recovered: int,
) -> DiscoverySummary:
    warnings: list[str] = []

    if len(previews) > response_products_limit:
        warnings.append(f"Список previews обрезан до response_products_limit={response_products_limit}")
        previews = previews[:response_products_limit]

    if final_errors:
        for product_url, error in final_errors[:warning_items_limit]:
            warnings.append(f"Ошибка чтения карточки {product_url}: {error}")
        if len(final_errors) > warning_items_limit:
            warnings.append(
                "Подробные предупреждения обрезаны: "
                f"показано {warning_items_limit} из {len(final_errors)} ошибок чтения"
            )
    elif fetch_all_products and fetch_attempted:
        warnings.append("Полный обход: все найденные карточки успешно прочитаны")

    if second_pass_attempted:
        warnings.append(
            f"Второй проход: повторно проверено {second_pass_attempted}, "
            f"восстановлено {second_pass_recovered}"
        )

    products_fetch_failed = len(final_errors)
    products_fetch_succeeded = fetch_attempted - products_fetch_failed

    error_details = [f"{url} -> {error}" for url, error in final_errors]
    if not error_details:
        error_details = ["Детальных ошибок не зафиксировано"]
    elif len(error_details) > error_details_limit:
        warnings.append(f"Список error_details обрезан до {error_details_limit}")
        error_details = error_details[:error_details_limit]

    if fetch_all_products and products_fetch_failed:
        warnings.append(
            f"Есть ошибки чтения карточек: {products_fetch_failed} из {fetch_attempted}"
        )

    return DiscoverySummary(
        warnings=warnings,
        error_details=error_details,
        previews=previews,
        products_fetch_succeeded=products_fetch_succeeded,
        products_fetch_failed=products_fetch_failed,
    )
