from __future__ import annotations
import time
from urllib.parse import urlparse

from app.adapters.contracts import SourceContext, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError
from app.domain.statuses import SourceRunStatus
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.services.config_validation_service import ConfigValidationService
from app.services.run_logger import RunLogger
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

    @staticmethod
    def _canonical_product_url(url: str) -> str:
        raw = str(url or '').strip()
        if not raw:
            return ''
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw
        parts = [p for p in (parsed.path or '').split('/') if p]
        handle = ''
        for i, p in enumerate(parts):
            if p == 'products' and i + 1 < len(parts):
                handle = parts[i + 1]
        if not handle:
            return raw
        host = (parsed.netloc or '').strip().lower()
        if host.startswith('www.'):
            host = host[4:]
        return f'{parsed.scheme}://{host}/products/{handle}'

    @staticmethod
    def _extract_handle(url: str) -> str:
        raw = str(url or '').strip()
        if not raw:
            return ''
        parsed = urlparse(raw)
        parts = [p for p in (parsed.path or '').split('/') if p]
        for i, p in enumerate(parts):
            if p == 'products' and i + 1 < len(parts):
                return parts[i + 1].strip()
        return ''

    def require_runnable_source(self, source_key: str) -> None:
        source = self.source_repo.get_by_key(source_key)
        if not source.enabled or not source.sync_enabled:
            raise ConfigError(f'source disabled: {source_key}')

    def run(self, source_key: str, *, dry_run: bool = False, run_id: str | None = None) -> SourceRunReport:
        logger = RunLogger(run_id)
        started_at = time.perf_counter()
        source = self.source_repo.get_by_key(source_key)
        adapter = self.adapter_registry.get(source.adapter_key)
        allowed = set(adapter.allowed_strategies)
        logger.event('run_start', source=source.key, adapter=source.adapter_key, dry_run=dry_run)

        strategy_sequence = ConfigValidationService.require_strategy_sequence(source.config, allowed)
        retry_limits = ConfigValidationService.require_retry_limits(source.config)
        ConfigValidationService.require_timeouts(source.config)
        ConfigValidationService.require_strategy_settings(source.config, strategy_sequence)

        context = SourceContext(
            source_id=source.id,
            source_key=source.key,
            source_url=source.url,
            adapter_key=source.adapter_key,
            source_config=dict(source.config),
        )

        report = SourceRunReport(
            source_id=source.id,
            source_key=source.key,
            adapter_key=source.adapter_key,
            dry_run=dry_run,
            status=SourceRunStatus.IN_PROGRESS,
        )

        visible_urls = adapter.discover_visible_catalog(context)
        visible_set = {self._canonical_product_url(x) for x in visible_urls if str(x).strip()}
        visible_handles = {self._extract_handle(x) for x in visible_urls if str(x).strip()}
        visible_handles.discard('')
        report.visible_catalog_products = len(visible_set)
        logger.event('discovery_done', visible_catalog_products=report.visible_catalog_products)
        weight_rules = self.weight_rules_client.fetch().rules if self.weight_rules_client else []
        logger.event('weight_rules_loaded', count=len(weight_rules))

        parsed_urls: set[str] = set()
        parsed_handles: set[str] = set()
        seen_handles: set[str] = set()
        seen_urls: set[str] = set()
        valid_products: list[dict] = []
        weight_source_stats: dict[str, int] = {'source': 0, 'keyword_rule': 0, 'missing': 0}

        for strategy_name in strategy_sequence:
            strategy = self.strategy_registry.get(strategy_name)
            attempt = StrategyAttempt(strategy=strategy_name, success=False)
            max_retries = retry_limits.get(strategy_name, 0)
            workers = context.source_config.get(f'{strategy_name}_workers')
            logger.event('strategy_start', name=strategy_name, retries=max_retries, workers=workers if workers is not None else '-')

            raw_items: list[dict] = []
            last_error: str | None = None
            strategy_context = StrategyContext(source=context, dry_run=dry_run, run_id=run_id or '')
            for _ in range(max_retries + 1):
                try:
                    strategy_context.diagnostics.clear()
                    raw_items = strategy.run(strategy_context)
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
            attempt.diagnostics = dict(strategy_context.diagnostics)
            report.total_found_products += len(raw_items)

            for raw in raw_items:
                normalized = adapter.normalize_product(raw)
                normalized = WeightEnrichmentService.apply_keyword_weight(normalized, weight_rules)
                source = str(normalized.get('weight_source') or 'missing').strip().lower()
                if source not in weight_source_stats:
                    weight_source_stats[source] = 0
                weight_source_stats[source] += 1
                url = self._canonical_product_url(str(normalized.get('url') or '').strip())
                normalized['url'] = url
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
                        parsed_handles.add(handle)
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
                if visible_handles:
                    current_coverage = len(parsed_handles.intersection(visible_handles)) / len(visible_handles)
                else:
                    current_coverage = len(parsed_urls.intersection(visible_set)) / report.visible_catalog_products
                logger.event('strategy_coverage', strategy=strategy_name, coverage=f'{current_coverage:.6f}')
                if current_coverage == 1.0:
                    break

        if report.visible_catalog_products > 0:
            if visible_handles:
                report.parsed_visible_products = len(parsed_handles.intersection(visible_handles))
                report.visible_coverage = report.parsed_visible_products / len(visible_handles)
            else:
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
        logger.event(
            'run_done',
            status=report.status,
            visible=f'{report.parsed_visible_products}/{report.visible_catalog_products}',
            valid=report.total_valid_products,
        )
        report.report_path = str(self.markdown_report_service.write(report))

        return report
