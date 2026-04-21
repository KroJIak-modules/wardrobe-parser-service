"""Execution helpers for parser sync job orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.source_registry import list_sources
from app.core.config import settings
from app.repositories import ParserSourceRepository


@dataclass(slots=True)
class JobExecutionTotals:
    """Aggregated counters from one parser sync job run."""

    created: int = 0
    updated: int = 0
    fetched: int = 0
    errors: int = 0
    http_429: int = 0
    http_5xx: int = 0

    def add(self, stats) -> None:
        self.created += stats.created
        self.updated += stats.updated
        self.fetched += stats.fetched
        self.errors += stats.errors
        self.http_429 += stats.http_429
        self.http_5xx += stats.http_5xx


def resolve_enabled_sources(*, source_repo: ParserSourceRepository | None = None):
    """Return enabled configured sources, respecting configured max limit."""
    sources = [item for item in list_sources() if item.enabled]
    if source_repo is not None:
        db_sources_by_url = {row.url: row for row in source_repo.get_all_active()}
        filtered = []
        for item in sources:
            db_source = db_sources_by_url.get(item.base_url)
            effective_enabled = db_source.enabled if db_source is not None else item.enabled
            sync_enabled = db_source.sync_enabled if db_source is not None else True
            if effective_enabled and sync_enabled:
                filtered.append(item)
        sources = filtered
    if settings.parser_sync_max_sources > 0:
        sources = sources[: settings.parser_sync_max_sources]
    return sources


def get_or_create_source(
    *,
    source_repo: ParserSourceRepository,
    name: str,
    url: str,
    parser_type: str,
    enabled: bool,
):
    """Upsert parser source row by URL and keep name/parser_type up to date."""
    source = source_repo.get_by_url(url)
    if source:
        source.name = name
        source.parser_type = parser_type
        source.enabled = enabled
        return source

    return source_repo.create_source(
        name=name,
        url=url,
        parser_type=parser_type,
        enabled=enabled,
    )
