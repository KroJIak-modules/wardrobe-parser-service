from __future__ import annotations

from app.adapters.contracts import SourceContext, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError
from app.domain.statuses import SourceRunStatus
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.services.config_validation_service import ConfigValidationService
from app.strategies.registry import StrategyRegistry


class SourceRunService:
    def __init__(self, source_repo: SourceRepository, adapter_registry: AdapterRegistry, strategy_registry: StrategyRegistry) -> None:
        self.source_repo = source_repo
        self.adapter_registry = adapter_registry
        self.strategy_registry = strategy_registry

    def run(self, source_key: str, *, dry_run: bool = False) -> SourceRunReport:
        source = self.source_repo.get_by_key(source_key)
        adapter = self.adapter_registry.get(source.adapter_key)
        allowed = set(adapter.allowed_strategies)

        strategy_sequence = ConfigValidationService.require_strategy_sequence(source.config, allowed)
        retry_limits = ConfigValidationService.require_retry_limits(source.config)
        ConfigValidationService.require_timeouts(source.config)

        context = SourceContext(
            source_id=source.id,
            source_key=source.key,
            source_url=source.url,
            adapter_key=source.adapter_key,
            source_config=source.config,
        )

        report = SourceRunReport(
            source_id=source.id,
            source_key=source.key,
            adapter_key=source.adapter_key,
            dry_run=dry_run,
            status=SourceRunStatus.IN_PROGRESS,
        )

        visible_urls = adapter.discover_visible_catalog(context)
        visible_set = set(visible_urls)
        report.visible_catalog_products = len(visible_set)

        parsed_urls: set[str] = set()
        seen_handles: set[str] = set()
        seen_urls: set[str] = set()

        for strategy_name in strategy_sequence:
            strategy = self.strategy_registry.get(strategy_name)
            attempt = StrategyAttempt(strategy=strategy_name, success=False)
            max_retries = retry_limits.get(strategy_name, 0)

            raw_items: list[dict] = []
            last_error: str | None = None
            for _ in range(max_retries + 1):
                try:
                    raw_items = strategy.run(StrategyContext(source=context, dry_run=dry_run))
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)

            if last_error is not None:
                attempt.error = last_error
                report.errors.append(f'{strategy_name}: {last_error}')
                report.attempts.append(attempt)
                continue

            attempt.raw_count = len(raw_items)

            for raw in raw_items:
                normalized = adapter.normalize_product(raw)
                url = str(normalized.get('url') or '').strip()
                handle = str(normalized.get('handle') or '').strip()

                if url and url in report.quarantined_urls:
                    continue

                if url and url in seen_urls:
                    report.errors.append(f'duplicate_url:{url}')
                    report.quarantined_urls.append(url)
                    continue
                if handle and handle in seen_handles:
                    report.errors.append(f'duplicate_handle:{handle}')
                    if url:
                        report.quarantined_urls.append(url)
                    continue

                ok, reasons = adapter.validate_product(normalized)
                if ok:
                    if url:
                        parsed_urls.add(url)
                        seen_urls.add(url)
                    if handle:
                        seen_handles.add(handle)
                    attempt.parsed_count += 1
                else:
                    for reason in reasons:
                        report.aggregated_unavailable_reasons[reason] = report.aggregated_unavailable_reasons.get(reason, 0) + 1
                    if url:
                        report.quarantined_urls.append(url)

            attempt.success = True
            report.attempts.append(attempt)

            # Fallback semantics: stop sequence as soon as we got full visible coverage.
            if report.visible_catalog_products > 0:
                current_coverage = len(parsed_urls.intersection(visible_set)) / report.visible_catalog_products
                if current_coverage == 1.0:
                    break

        if report.visible_catalog_products > 0:
            report.parsed_visible_products = len(parsed_urls.intersection(visible_set))
            report.visible_coverage = report.parsed_visible_products / report.visible_catalog_products
        else:
            report.parsed_visible_products = len(parsed_urls)
            report.visible_coverage = 1.0 if parsed_urls else 0.0

        if report.visible_coverage == 1.0:
            report.status = SourceRunStatus.SUCCESS
        elif report.visible_coverage == 0.0:
            report.status = SourceRunStatus.FAILED
        else:
            report.status = SourceRunStatus.PARTIAL

        return report
