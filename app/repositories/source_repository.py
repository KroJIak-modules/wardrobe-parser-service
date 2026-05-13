from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class SourceRecord:
    id: int
    key: str
    url: str
    adapter_key: str
    enabled: bool
    sync_enabled: bool
    config: dict


class SourceRepository:
    """File-backed source registry for rework stage."""

    def __init__(self, config_path: str = 'config/sources.json') -> None:
        self.config_path = Path(config_path)

    def get_by_key(self, source_key: str) -> SourceRecord:
        if not self.config_path.exists():
            raise KeyError(f'Sources config not found: {self.config_path}')
        raw = json.loads(self.config_path.read_text(encoding='utf-8'))
        items = raw.get('sources') if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise KeyError('Invalid sources config format: expected {"sources": [...]}')
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get('key') or '').strip()
            if key != source_key:
                continue
            return SourceRecord(
                id=int(item.get('id') or 0),
                key=key,
                url=str(item.get('url') or '').strip(),
                adapter_key=str(item.get('adapter_key') or '').strip(),
                enabled=bool(item.get('enabled', True)),
                sync_enabled=bool(item.get('sync_enabled', True)),
                config=dict(item.get('config') or {}),
            )
        raise KeyError(f'Unknown source key: {source_key}')

    def list_all(self) -> list[SourceRecord]:
        if not self.config_path.exists():
            raise KeyError(f'Sources config not found: {self.config_path}')
        raw = json.loads(self.config_path.read_text(encoding='utf-8'))
        items = raw.get('sources') if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise KeyError('Invalid sources config format: expected {"sources": [...]}')
        out: list[SourceRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(
                SourceRecord(
                    id=int(item.get('id') or 0),
                    key=str(item.get('key') or '').strip(),
                    url=str(item.get('url') or '').strip(),
                    adapter_key=str(item.get('adapter_key') or '').strip(),
                    enabled=bool(item.get('enabled', True)),
                    sync_enabled=bool(item.get('sync_enabled', True)),
                    config=dict(item.get('config') or {}),
                )
            )
        return out

    def patch_flags(
        self,
        source_key: str,
        *,
        enabled: bool | None = None,
        sync_enabled: bool | None = None,
        requested_currency_priority: list[str] | None = None,
    ) -> SourceRecord:
        if not self.config_path.exists():
            raise KeyError(f'Sources config not found: {self.config_path}')
        raw = json.loads(self.config_path.read_text(encoding='utf-8'))
        items = raw.get('sources') if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise KeyError('Invalid sources config format: expected {"sources": [...]}')
        found = False
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get('key') or '').strip()
            if key != source_key:
                continue
            if enabled is not None:
                item['enabled'] = bool(enabled)
            if sync_enabled is not None:
                item['sync_enabled'] = bool(sync_enabled)
            if requested_currency_priority is not None:
                cfg = item.get('config') if isinstance(item.get('config'), dict) else {}
                currency_cfg = cfg.get('shopify_currency') if isinstance(cfg.get('shopify_currency'), dict) else {}
                normalized = [str(x).strip().upper() for x in requested_currency_priority if str(x).strip()]
                currency_cfg['requested_currency_priority'] = normalized
                cfg['shopify_currency'] = currency_cfg
                item['config'] = cfg
            found = True
            break
        if not found:
            raise KeyError(f'Unknown source key: {source_key}')
        self.config_path.write_text(json.dumps({'sources': items}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return self.get_by_key(source_key)
