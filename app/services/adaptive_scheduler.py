from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.site_repository import SiteRepository


@dataclass(frozen=True)
class SchedulePlan:
    site_groups: list[list[str]]
    required_workers: int
    total_expected_sec: float
    has_stats: bool


class AdaptiveScheduler:
    def __init__(self, interval_sec: int, max_workers: int, alpha: float) -> None:
        self._interval_sec = max(interval_sec, 1)
        self._max_workers = max(max_workers, 1)
        self._alpha = max(min(alpha, 1.0), 0.0)

    def build_plan(self, db: Session, site_keys: list[str]) -> SchedulePlan:
        if not site_keys:
            return SchedulePlan(site_groups=[], required_workers=0, total_expected_sec=0.0, has_stats=False)

        sites = []
        for site_key in site_keys:
            site = SiteRepository.get_by_key(db, site_key)
            if site is None:
                site = SiteRepository.create(
                    db,
                    key=site_key,
                    name=site_key,
                    base_url=self._default_site_base_url(site_key),
                )
            avg_time = float(site.avg_parse_time_sec or 0.0)
            sites.append((site_key, avg_time))
        db.commit()

        total_expected = sum(avg for _, avg in sites)
        has_stats = any(avg > 0 for _, avg in sites)
        if not has_stats:
            return SchedulePlan(site_groups=[site_keys], required_workers=1, total_expected_sec=total_expected, has_stats=False)

        required_workers = ceil(total_expected / self._interval_sec) or 1
        required_workers = min(required_workers, self._max_workers, len(site_keys))

        site_groups = self._balance_groups(sites, required_workers)
        return SchedulePlan(
            site_groups=site_groups,
            required_workers=required_workers,
            total_expected_sec=total_expected,
            has_stats=True,
        )

    def _balance_groups(self, sites: list[tuple[str, float]], workers: int) -> list[list[str]]:
        buckets: list[tuple[list[str], float]] = [([], 0.0) for _ in range(workers)]
        for site_key, avg_time in sorted(sites, key=lambda item: item[1], reverse=True):
            idx = min(range(workers), key=lambda i: buckets[i][1])
            buckets[idx][0].append(site_key)
            buckets[idx] = (buckets[idx][0], buckets[idx][1] + avg_time)
        return [bucket[0] for bucket in buckets]

    def _default_site_base_url(self, site_key: str) -> str | None:
        if site_key == "example":
            return settings.example_site_url
        if site_key == "nofaithstudios":
            return settings.nofaithstudios_base_url
        return None

    @property
    def alpha(self) -> float:
        return self._alpha
