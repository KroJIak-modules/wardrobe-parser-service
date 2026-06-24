from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import settings
from app.core.exceptions import ConfigError
from app.services.source_registry_bootstrap_service import SourceRegistryBootstrapService


@dataclass
class SourceRecord:
    id: int
    key: str
    url: str
    adapter_key: str
    enabled: bool
    sync_enabled: bool
    config: dict[str, Any]


class SourceRepository:
    """Backend-backed source registry for runtime parser operations."""

    def __init__(self) -> None:
        self._bootstrap = SourceRegistryBootstrapService()

    @staticmethod
    def _base_url() -> str:
        return f"{settings.backend_base_url.rstrip('/')}/api/v1/internal/service/sources"

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"X-Internal-Token": str(settings.internal_api_token or "").strip()}

    @staticmethod
    def _deserialize(item: dict[str, Any]) -> SourceRecord:
        return SourceRecord(
            id=int(item.get("id") or 0),
            key=str(item.get("key") or "").strip(),
            url=str(item.get("url") or "").strip(),
            adapter_key=str(item.get("adapter_key") or "").strip(),
            enabled=bool(item.get("enabled", True)),
            sync_enabled=bool(item.get("sync_enabled", True)),
            config=dict(item.get("config") or {}),
        )

    def list_all(self) -> list[SourceRecord]:
        self._bootstrap.ensure_backend_seeded()
        try:
            response = requests.get(self._base_url(), headers=self._headers(), timeout=(5, 30))
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ConfigError(f"backend_sources_unavailable:{exc}") from exc
        items = payload if isinstance(payload, list) else []
        return [
            self._deserialize(item)
            for item in items
            if isinstance(item, dict) and str(item.get("key") or "").strip()
        ]

    def get_by_key(self, source_key: str) -> SourceRecord:
        normalized = str(source_key or "").strip().lower()
        if not normalized:
            raise KeyError(source_key)
        for item in self.list_all():
            if str(item.key).strip().lower() == normalized:
                return item
        raise KeyError(source_key)
