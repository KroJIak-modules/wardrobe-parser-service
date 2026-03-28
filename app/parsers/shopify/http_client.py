"""HTTP client for Shopify API requests with resilience and security."""

import logging
import ipaddress
import time
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.exceptions import ValidationError

LOGGER = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/xml, application/xml, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class ShopifyHTTPClient:
    """Low-level HTTP client for Shopify stores with security checks."""

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
            try:
                response = active_session.get(url, timeout=timeout_sec, allow_redirects=True)
                status_code = response.status_code

                # Password gate detection
                if ShopifyHTTPClient._is_password_gate(response.url):
                    error = "PASSWORD_PROTECTED"
                    break

                if status_code == 429:
                    http_429_count += 1
                    last_error = "HTTP 429"
                    if attempt < max_retries:
                        backoff = retry_backoff_sec * (2 ** attempt)
                        time.sleep(backoff)
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

                if is_json:
                    payload = response.json()
                else:
                    payload = response.text

                break

            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                if attempt < max_retries:
                    backoff = retry_backoff_sec * (2 ** attempt)
                    time.sleep(backoff)
                    continue
                error = last_error

            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
                if attempt < max_retries:
                    backoff = retry_backoff_sec * (2 ** attempt)
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
