"""Retry/backoff policy helpers for Shopify HTTP client."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
import time

import requests

from app.core.config import settings

MAX_RETRY_AFTER_COOLDOWN_SEC = 45.0


def retry_after_seconds(response: requests.Response) -> float | None:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        dt = parsedate_to_datetime(raw)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        return None


def is_bot_protection_429(response: requests.Response) -> bool:
    """Detect challenge pages where retries are typically useless."""
    try:
        body = (response.text or "")[:4096].lower()
    except Exception:
        body = ""
    markers = (
        "verifying your connection",
        "challenge-platform",
        "cf-chl",
        "security challenge",
    )
    return any(marker in body for marker in markers)


def retry_backoff(attempt: int, retry_backoff_sec: float) -> float:
    return retry_backoff_sec * (2**attempt)


def timeout_cooldown() -> float:
    return max(0.0, settings.parser_timeout_cooldown_sec)


def rate_limit_cooldown(
    *,
    attempt: int,
    retry_backoff_sec: float,
    retry_after_sec: float | None,
) -> float:
    return min(
        max(
            settings.parser_rate_limit_min_cooldown_sec,
            retry_after_sec or 0.0,
            retry_backoff(attempt, retry_backoff_sec),
        ),
        MAX_RETRY_AFTER_COOLDOWN_SEC,
    )


def min_bot_protection_cooldown(retry_backoff_sec: float) -> float:
    return max(settings.parser_rate_limit_min_cooldown_sec, retry_backoff_sec)


def deadline_remaining(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return deadline_monotonic - time.monotonic()


def request_timeout(timeout_sec: float, deadline_monotonic: float | None) -> float:
    remaining = deadline_remaining(deadline_monotonic)
    if remaining is None:
        return timeout_sec
    return max(0.2, min(timeout_sec, remaining))


def cap_sleep_by_deadline(sleep_sec: float, deadline_monotonic: float | None) -> tuple[float, bool]:
    remaining = deadline_remaining(deadline_monotonic)
    if remaining is None:
        return sleep_sec, True
    if remaining <= 0:
        return 0.0, False
    return min(sleep_sec, remaining), True
