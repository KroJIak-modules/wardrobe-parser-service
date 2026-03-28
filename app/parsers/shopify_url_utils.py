"""URL and collection helpers for Shopify parser flows."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urljoin, urlparse, urlunparse

from app.core.exceptions import ValidationError


def normalize_base_url(base_url: str) -> str:
    raw = base_url.strip()
    if not raw:
        raise ValidationError("Пустой base_url")
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    if not parsed.netloc:
        parsed = urlparse(f"https://{raw}")

    if not parsed.netloc:
        raise ValidationError(f"Некорректный base_url: {base_url}")

    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    normalized = urlunparse((scheme, parsed.netloc.lower(), "", "", "", ""))
    return normalized.rstrip("/")


def normalize_product_url(raw_url: str, base_url: str) -> str | None:
    candidate = raw_url.strip()
    if not candidate:
        return None

    absolute = urljoin(f"{base_url}/", candidate)
    parsed = urlparse(absolute)
    handle = extract_handle_from_path(parsed.path)
    if not handle:
        return None

    return f"{base_url}/products/{handle}"


def extract_handle(product_url: str) -> str | None:
    parsed = urlparse(product_url)
    return extract_handle_from_path(parsed.path)


def extract_handle_from_path(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None
    for index, segment in enumerate(segments):
        if segment != "products":
            continue
        if index + 1 >= len(segments):
            return None
        handle = unquote(segments[index + 1]).strip()
        if handle.endswith(".js"):
            handle = handle[:-3]
        if handle.endswith(".json"):
            handle = handle[:-5]
        return handle or None
    return None


def append_discovered_url(
    product_url: str,
    *,
    discovered_urls: list[str],
    discovered_set: set[str],
    max_products: int,
) -> bool:
    if len(discovered_urls) >= max_products:
        return False
    if product_url in discovered_set:
        return False
    discovered_set.add(product_url)
    discovered_urls.append(product_url)
    return True


def dedupe_and_keep_ordered_previews(*, target_urls: list[str], previews: list[Any]) -> list[Any]:
    by_url: dict[str, Any] = {}
    for preview in previews:
        by_url[preview.product_url] = preview
    ordered: list[Any] = []
    for url in target_urls:
        preview = by_url.get(url)
        if preview:
            ordered.append(preview)
    return ordered


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
