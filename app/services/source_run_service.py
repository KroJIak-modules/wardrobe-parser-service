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
        ConfigValidationService.require_retry_limits(source.config)
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
        report.visible_catalog_products = len(set(visible_urls))

        parsed_urls: set[str] = set()
        for strategy_name in strategy_sequence:
            strategy = self.strategy_registry.get(strategy_name)
            attempt = StrategyAttempt(strategy=strategy_name, success=False)
            try:
                raw_items = strategy.run(StrategyContext(source=context, dry_run=dry_run))
                attempt.raw_count = len(raw_items)

                for raw in raw_items:
                    normalized = adapter.normalize_product(raw)
                    ok, reasons = adapter.validate_product(normalized)
                    if ok:
                        url = str(normalized.get('url') or '').strip()
                        if url:
                            parsed_urls.add(url)
                    else:
                        for reason in reasons:
                            report.aggregated_unavailable_reasons[reason] = report.aggregated_unavailable_reasons.get(reason, 0) + 1
                attempt.success = True
            except Exception as exc:  # noqa: BLE001
                attempt.error = str(exc)
                report.errors.append(f'{strategy_name}: {exc}')
            report.attempts.append(attempt)

        if report.visible_catalog_products > 0:
            report.parsed_visible_products = len(parsed_urls.intersection(set(visible_urls)))
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
