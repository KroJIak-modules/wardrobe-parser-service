from __future__ import annotations

import logging

import requests

from app.core.config import settings
from app.core.exceptions import ConfigError
from app.repositories.source_seed_repository import SourceSeedRepository


LOGGER = logging.getLogger(__name__)


class SourceRegistryBootstrapService:
    _seeded = False

    def __init__(self) -> None:
        self.seed_repo = SourceSeedRepository()

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"X-Internal-Token": str(settings.internal_api_token or "").strip()}

    @staticmethod
    def _bootstrap_url() -> str:
        return f"{settings.backend_base_url.rstrip('/')}/api/v1/internal/service/sources/bootstrap"

    @staticmethod
    def _list_url() -> str:
        return f"{settings.backend_base_url.rstrip('/')}/api/v1/internal/service/sources"

    def ensure_backend_seeded(self) -> None:
        if self.__class__._seeded:
            return
        try:
            existing_response = requests.get(
                self._list_url(),
                headers=self._headers(),
                timeout=(5, 30),
            )
            existing_response.raise_for_status()
            existing_payload = existing_response.json()
        except requests.RequestException as exc:
            raise ConfigError(f"backend_source_bootstrap_failed:{exc}") from exc
        if isinstance(existing_payload, list) and existing_payload:
            self.__class__._seeded = True
            LOGGER.info("Source registry already present in backend DB")
            return
        payload = {
            "sources": [
                {
                    "id": int(item.id),
                    "key": str(item.key),
                    "url": str(item.url),
                    "adapter_key": str(item.adapter_key),
                    "enabled": bool(item.enabled),
                    "sync_enabled": bool(item.sync_enabled),
                    "config": dict(item.config or {}),
                }
                for item in self.seed_repo.list_all()
            ]
        }
        try:
            response = requests.post(
                self._bootstrap_url(),
                json=payload,
                headers=self._headers(),
                timeout=(5, 60),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ConfigError(f"backend_source_bootstrap_failed:{exc}") from exc
        self.__class__._seeded = True
        LOGGER.info("Source registry bootstrap finished via backend API")
