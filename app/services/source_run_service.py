from __future__ import annotations
import time

from app.adapters.contracts import SourceContext, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError
from app.domain.statuses import SourceRunStatus
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.services.config_validation_service import ConfigValidationService
from app.services.run_report_markdown_service import RunReportMarkdownService
from app.services.weight_enrichment_service import WeightEnrichmentService
from app.services.weight_rules_client import WeightRulesClient
from app.strategies.registry import StrategyRegistry


class SourceRunService:
    def __init__(
        self,
        source_repo: SourceRepository,
        adapter_registry: AdapterRegistry,
        strategy_registry: StrategyRegistry,
        markdown_report_service: RunReportMarkdownService | None = None,
        weight_rules_client: WeightRulesClient | None = None,
    ) -> None:
        self.source_repo = source_repo
        self.adapter_registry = adapter_registry
        self.strategy_registry = strategy_registry
        self.markdown_report_service = markdown_report_service or RunReportMarkdownService()
        self.weight_rules_client = weight_rules_client

    def run(self, source_key: str, *, dry_run: bool = False) -> SourceRunReport:
        started_at = time.perf_counter()
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
        weight_rules = self.weight_rules_client.fetch().rules if self.weight_rules_client else []

        parsed_urls: set[str] = set()
        seen_handles: set[str] = set()
        seen_urls: set[str] = set()
        valid_products: list[dict] = []
        weight_source_stats: dict[str, int] = {'source': 0, 'keyword_rule': 0, 'missing': 0}

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
            report.total_found_products += len(raw_items)

            for raw in raw_items:
                normalized = adapter.normalize_product(raw)
                normalized = WeightEnrichmentService.apply_keyword_weight(normalized, weight_rules)
                source = str(normalized.get('weight_source') or 'missing').strip().lower()
                if source not in weight_source_stats:
                    weight_source_stats[source] = 0
                weight_source_stats[source] += 1
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
                    valid_products.append(normalized)
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

        report.total_valid_products = len(valid_products)
        report.top_valid_products = valid_products[:10]
        report.weight_source_stats = weight_source_stats
        report.duration_sec = time.perf_counter() - started_at
        self.markdown_report_service.write(report)

        return report
