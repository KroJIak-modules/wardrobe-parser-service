"""Helpers to map parser discovery result into source-run state."""

from __future__ import annotations

from app.models import SourceRunStatus


def is_non_fatal_warning(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "bot_protection_429" in text
        or "fallback used" in text
        or "список previews обрезан" in text
        or "второй проход:" in text
    )


def build_run_error_message(result, *, error_details_limit: int) -> str | None:
    details = [str(item).strip() for item in (result.error_details or []) if str(item).strip()]
    if details:
        return "; ".join(details[:error_details_limit])

    warnings = [str(item).strip() for item in (result.warnings or []) if str(item).strip()]
    if (
        warnings
        and int(getattr(result, "products_fetch_failed", 0) or 0) == 0
        and int(getattr(result, "product_urls_found", 0) or 0) > 0
        and all(is_non_fatal_warning(item) for item in warnings)
    ):
        return None
    if warnings:
        return "; ".join(warnings[:2])
    return None


def resolve_source_run_status(result) -> SourceRunStatus:
    if int(getattr(result, "products_fetch_failed", 0) or 0) > 0:
        return SourceRunStatus.PARTIAL
    if int(getattr(result, "product_urls_found", 0) or 0) == 0:
        return SourceRunStatus.PARTIAL
    return SourceRunStatus.SUCCESS


def extract_result_counters(result) -> tuple[int, int, int, int]:
    return (
        int(getattr(result, "products_fetch_succeeded", 0) or 0),
        int(getattr(result, "products_fetch_failed", 0) or 0),
        int(getattr(result, "http_429_count", 0) or 0),
        int(getattr(result, "http_5xx_count", 0) or 0),
    )
