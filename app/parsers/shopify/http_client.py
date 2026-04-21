"""HTTP client for Shopify API requests with resilience and security."""

import logging
import ipaddress
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
from threading import Lock

import requests

from app.core.config import settings
from app.core.exceptions import ValidationError

LOGGER = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    # Keep request signature aligned with testing/parser/shopify_export_products.py
    # to reduce anti-bot divergence between script and service runtime.
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class ShopifyHTTPClient:
    """Low-level HTTP client for Shopify stores with security checks."""
    _domain_cooldown_until: dict[str, float] = {}
    _domain_last_request_at: dict[str, float] = {}
    _domain_cb_state: dict[str, "DomainCircuitState"] = {}
    _cooldown_lock = Lock()

    @dataclass(slots=True)
    class DomainCircuitState:
        consecutive_429: int = 0
        penalty_level: int = 0
        success_streak: int = 0

    @classmethod
    def _host(cls, url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    @classmethod
    def get_adaptive_workers(cls, base_url: str, requested_workers: int) -> int:
        """Return worker count adapted to current circuit-breaker penalty for domain."""
        host = cls._host(base_url)
        if not host:
            return max(1, requested_workers)
        with cls._cooldown_lock:
            state = cls._domain_cb_state.get(host)
            penalty = state.penalty_level if state else 0
        reduced = max(1, requested_workers // (2 ** penalty))
        return reduced

    @classmethod
    def _apply_domain_cooldown_if_needed(
        cls,
        url: str,
        *,
        deadline_monotonic: float | None = None,
    ) -> bool:
        host = cls._host(url)
        if not host:
            return True
        now = time.time()
        with cls._cooldown_lock:
            until = cls._domain_cooldown_until.get(host, 0.0)
            last_request_at = cls._domain_last_request_at.get(host, 0.0)
        if until > now:
            sleep_sec = until - now
            if deadline_monotonic is not None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    return False
                sleep_sec = min(sleep_sec, remaining)
            sleep_sec = min(sleep_sec, cls._MAX_COOLDOWN_SLEEP_SEC)
            if sleep_sec > 0:
                time.sleep(sleep_sec)
        min_gap_sec = max(0.0, settings.parser_request_spacing_sec)
        if min_gap_sec > 0:
            gap_sleep_sec = (last_request_at + min_gap_sec) - time.time()
            if gap_sleep_sec > 0:
                if deadline_monotonic is not None:
                    remaining = deadline_monotonic - time.monotonic()
                    if remaining <= 0:
                        return False
                    gap_sleep_sec = min(gap_sleep_sec, remaining)
                time.sleep(gap_sleep_sec)
        return True

    @classmethod
    def _set_domain_cooldown(cls, url: str, cooldown_sec: float) -> None:
        host = cls._host(url)
        if not host or cooldown_sec <= 0:
            return
        jitter = random.uniform(0.0, max(0.0, settings.parser_rate_limit_jitter_sec))
        candidate_until = time.time() + cooldown_sec + jitter
        with cls._cooldown_lock:
            current = cls._domain_cooldown_until.get(host, 0.0)
            cls._domain_cooldown_until[host] = max(current, candidate_until)

    @classmethod
    def _record_429(cls, url: str) -> None:
        host = cls._host(url)
        if not host:
            return
        with cls._cooldown_lock:
            state = cls._domain_cb_state.get(host)
            if state is None:
                state = ShopifyHTTPClient.DomainCircuitState()
                cls._domain_cb_state[host] = state
            state.consecutive_429 += 1
            state.success_streak = 0
            if state.consecutive_429 >= settings.parser_circuit_breaker_429_threshold:
                state.consecutive_429 = 0
                state.penalty_level = min(
                    settings.parser_circuit_breaker_max_penalty,
                    state.penalty_level + 1,
                )
                penalty = state.penalty_level
            else:
                penalty = state.penalty_level
        if penalty > 0:
            cls._set_domain_cooldown(
                url,
                settings.parser_circuit_breaker_pause_sec * penalty,
            )

    @classmethod
    def _record_success(cls, url: str) -> None:
        host = cls._host(url)
        if not host:
            return
        with cls._cooldown_lock:
            state = cls._domain_cb_state.get(host)
            if state is None:
                state = ShopifyHTTPClient.DomainCircuitState()
                cls._domain_cb_state[host] = state
            state.consecutive_429 = 0
            state.success_streak += 1
            if (
                state.penalty_level > 0
                and state.success_streak >= settings.parser_circuit_breaker_recovery_successes
            ):
                state.penalty_level -= 1
                state.success_streak = 0
            cls._domain_last_request_at[host] = time.time()

    @classmethod
    def _record_attempt(cls, url: str) -> None:
        host = cls._host(url)
        if not host:
            return
        with cls._cooldown_lock:
            cls._domain_last_request_at[host] = time.time()

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
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

    @staticmethod
    def _is_bot_protection_429(response: requests.Response) -> bool:
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

    @staticmethod
    def validate_url(url: str) -> None:
        """Validate URL for SSRF and malformed patterns."""
        url = url.strip()
        if not url:
            raise ValidationError("URL пустой")

        try:
            parsed = urlparse(url)
        except Exception as exc:
            raise ValidationError(f"Некорректный URL: {exc}") from exc

        if not parsed.scheme or not parsed.netloc:
            raise ValidationError("URL должен содержать scheme и hostname")

        if parsed.scheme not in ("http", "https"):
            raise ValidationError(f"Недопустимый scheme: {parsed.scheme}")

        # SSRF detection
        hostname = parsed.hostname or ""
        if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0"):
            raise ValidationError("Локальные адреса не допускаются")

        if hostname.lower().endswith(".local"):
            raise ValidationError("Локальные домены не допускаются")

        try:
            ip_obj = ipaddress.ip_address(hostname)
        except ValueError:
            ip_obj = None

        if ip_obj and (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise ValidationError("Приватные/локальные IP не допускаются")

    @staticmethod
    def request_with_retries(
        url: str,
        *,
        is_json: bool,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
        session: requests.Session | None = None,
        deadline_monotonic: float | None = None,
    ) -> tuple[Any | None, int | None, int, int, str | None]:
        """
        Execute HTTP request with exponential backoff retry logic.

        Returns: (payload, status_code, http_429_count, http_5xx_count, error)
        """
        ShopifyHTTPClient.validate_url(url)
        active_session = session or ShopifyHTTPClient.create_session()

        payload = None
        status_code = None
        error = None
        http_429_count = 0
        http_5xx_count = 0
        last_error = None

        for attempt in range(max_retries + 1):
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                error = "SOURCE_TIMEOUT"
                break
            try:
                if not ShopifyHTTPClient._apply_domain_cooldown_if_needed(
                    url,
                    deadline_monotonic=deadline_monotonic,
                ):
                    error = "SOURCE_TIMEOUT"
                    break
                request_timeout = timeout_sec
                if deadline_monotonic is not None:
                    request_timeout = max(0.2, min(timeout_sec, deadline_monotonic - time.monotonic()))
                response = active_session.get(url, timeout=request_timeout, allow_redirects=True)
                ShopifyHTTPClient._record_attempt(url)
                status_code = response.status_code

                # Password gate detection
                if ShopifyHTTPClient._is_password_gate(response.url):
                    error = "PASSWORD_PROTECTED"
                    break

                if status_code == 429:
                    http_429_count += 1
                    is_bot_429 = ShopifyHTTPClient._is_bot_protection_429(response)
                    if is_bot_429:
                        last_error = "BOT_PROTECTION_429"
                    else:
                        last_error = "HTTP 429"
                    ShopifyHTTPClient._record_429(url)
                    if is_bot_429:
                        # Challenge pages are rarely recoverable by immediate retries.
                        # Fail fast to avoid hanging discovery for many minutes.
                        ShopifyHTTPClient._set_domain_cooldown(
                            url,
                            max(
                                settings.parser_rate_limit_min_cooldown_sec,
                                retry_backoff_sec,
                            ),
                        )
                        error = last_error
                        break
                    retry_after_sec = ShopifyHTTPClient._retry_after_seconds(response)
                    backoff_base = retry_backoff_sec * (2 ** attempt)
                    cooldown_sec = max(
                        settings.parser_rate_limit_min_cooldown_sec,
                        retry_after_sec or 0.0,
                        backoff_base,
                    )
                    cooldown_sec = min(cooldown_sec, ShopifyHTTPClient._MAX_RETRY_AFTER_COOLDOWN_SEC)
                    ShopifyHTTPClient._set_domain_cooldown(url, cooldown_sec)
                    if attempt < max_retries:
                        if deadline_monotonic is not None:
                            sleep_cap = deadline_monotonic - time.monotonic()
                            if sleep_cap <= 0:
                                error = "SOURCE_TIMEOUT"
                                break
                            cooldown_sec = min(cooldown_sec, sleep_cap)
                        time.sleep(cooldown_sec)
                        continue
                    error = last_error
                    break

                if status_code >= 500:
                    http_5xx_count += 1
                    last_error = f"HTTP {status_code}"
                    if attempt < max_retries:
                        backoff = retry_backoff_sec * (2 ** attempt)
                        time.sleep(backoff)
                        continue
                    error = last_error
                    break

                if status_code >= 400:
                    error = f"HTTP {status_code}"
                    break

                ShopifyHTTPClient._record_success(url)
                if is_json:
                    payload = response.json()
                else:
                    payload = response.text

                break

            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                ShopifyHTTPClient._set_domain_cooldown(url, settings.parser_timeout_cooldown_sec)
                if attempt < max_retries:
                    backoff = retry_backoff_sec * (2 ** attempt)
                    if deadline_monotonic is not None:
                        sleep_cap = deadline_monotonic - time.monotonic()
                        if sleep_cap <= 0:
                            error = "SOURCE_TIMEOUT"
                            break
                        backoff = min(backoff, sleep_cap)
                    time.sleep(backoff)
                    continue
                error = last_error

            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
                ShopifyHTTPClient._set_domain_cooldown(url, settings.parser_timeout_cooldown_sec)
                if attempt < max_retries:
                    backoff = retry_backoff_sec * (2 ** attempt)
                    if deadline_monotonic is not None:
                        sleep_cap = deadline_monotonic - time.monotonic()
                        if sleep_cap <= 0:
                            error = "SOURCE_TIMEOUT"
                            break
                        backoff = min(backoff, sleep_cap)
                    time.sleep(backoff)
                    continue
                error = last_error

            except Exception as exc:
                LOGGER.debug("Request error: %s", exc)
                error = str(exc)
                break

        return payload, status_code, http_429_count, http_5xx_count, error

    @staticmethod
    def _is_password_gate(response_url: str) -> bool:
        """Detect if store has password protection redirect."""
        try:
            parsed = urlparse(response_url)
            path = (parsed.path or "").lower().rstrip("/")
            return path == "/password" or path.endswith("/password")
        except Exception:
            return False

    @staticmethod
    def create_session() -> requests.Session:
        """Create configured HTTP session."""
        session = requests.Session()
        session.headers.update(_DEFAULT_HEADERS)
        return session
    _MAX_COOLDOWN_SLEEP_SEC = 8.0
    _MAX_RETRY_AFTER_COOLDOWN_SEC = 45.0
