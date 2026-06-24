from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from app.core.config import settings


@dataclass
class SourceSeedRecord:
    id: int
    key: str
    url: str
    adapter_key: str
    enabled: bool
    sync_enabled: bool
    config: dict


class SourceSeedRepository:
    def __init__(self, config_path: str | None = None) -> None:
        resolved_path = config_path if config_path is not None else settings.sources_config_path
        self.config_path = Path(resolved_path)

    def list_all(self) -> list[SourceSeedRecord]:
        if not self.config_path.exists():
            raise KeyError(f"Sources config not found: {self.config_path}")
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        items = raw.get("sources") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise KeyError('Invalid sources config format: expected {"sources": [...]}')
        out: list[SourceSeedRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            url = str(item.get("url") or "").strip()
            adapter_key = str(item.get("adapter_key") or "").strip()
            if not key or not url or not adapter_key:
                continue
            out.append(
                SourceSeedRecord(
                    id=int(item.get("id") or 0),
                    key=key,
                    url=url,
                    adapter_key=adapter_key,
                    enabled=bool(item.get("enabled", True)),
                    sync_enabled=bool(item.get("sync_enabled", True)),
                    config=dict(item.get("config") or {}),
                )
            )
        return out
