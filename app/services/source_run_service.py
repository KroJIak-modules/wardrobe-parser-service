from __future__ import annotations
from collections.abc import Callable
import time
from urllib.parse import unquote, urlparse

from app.adapters.contracts import SourceContext, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError, StorefrontBlockedError
from app.domain.statuses import SourceRunStatus
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.schemas.source_product import SourceProductDraft
from app.services.config_validation_service import ConfigValidationService
from app.services.description_text_service import DescriptionTextService
from app.services.product_gender_service import ProductGenderService
from app.services.run_logger import RunLogger
from app.services.weight_enrichment_service import WeightEnrichmentService
from app.strategies.registry import StrategyRegistry


class SourceRunService:
    def __init__(
        self,
        source_repo: SourceRepository,
        adapter_registry: AdapterRegistry,
        strategy_registry: StrategyRegistry,
    ) -> None:
        self.source_repo = source_repo
        self.adapter_registry = adapter_registry
        self.strategy_registry = strategy_registry

    @staticmethod
    def _normalize_product_url(url: str) -> str:
        raw = str(url or '').strip()
        if not raw:
            return ''
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw
        return parsed._replace(query='', fragment='').geturl()

    @staticmethod
    def _extract_handle(url: str) -> str:
        raw = str(url or '').strip()
        if not raw:
            return ''
        parsed = urlparse(raw)
        parts = [p for p in (parsed.path or '').split('/') if p]
        for i, p in enumerate(parts):
            if p == 'products' and i + 1 < len(parts):
                return unquote(parts[i + 1]).strip()
        return ''

    def require_runnable_source(self, source_key: str) -> None:
        source = self.source_repo.get_by_key(source_key)
        if not source.enabled or not source.sync_enabled:
            raise ConfigError(f'source disabled: {source_key}')

    def _normalize_service_product(
        self,
        *,
        adapter,
        raw_product: dict,
        context: SourceContext,
    ) -> SourceProductDraft:
        normalized = dict(adapter.normalize_product(raw_product))
        resolution = WeightEnrichmentService.resolve(normalized)

        product: SourceProductDraft = {
            'url': self._normalize_product_url(str(normalized.get('url') or '').strip()),
            'handle': str(normalized.get('handle') or '').strip(),
            'title': str(normalized.get('title') or '').strip(),
            'description_html': str(normalized.get('description_html') or '').strip() or None,
            'description': DescriptionTextService.normalize(normalized.get('description_html')),
            'published_at': str(normalized.get('published_at') or '').strip() or None,
            'designer': str(normalized.get('designer') or '').strip() or None,
            'category': str(normalized.get('category') or '').strip() or None,
            'tags': normalized.get('tags') if isinstance(normalized.get('tags'), list) else [],
            'source_weight_grams': resolution.source_weight_grams,
            'weight_source': resolution.weight_source,
            'images': normalized.get('images') if isinstance(normalized.get('images'), list) else [],
            'variants': normalized.get('variants') if isinstance(normalized.get('variants'), list) else [],
            'gender': ProductGenderService.infer(
                normalized_product=normalized,
                raw_product=raw_product,
                source_key=context.source_key,
            ),
        }
        if 'buyer_total_price_amount' in normalized:
            product['buyer_total_price_amount'] = normalized.get('buyer_total_price_amount')
        if 'buyer_service_fee_amount' in normalized:
            product['buyer_service_fee_amount'] = normalized.get('buyer_service_fee_amount')
        if isinstance(raw_product.get('source_ref'), dict):
            product['source_ref'] = dict(raw_product.get('source_ref') or {})
        return product

    @staticmethod
    def _validation_reasons(*, adapter, product: SourceProductDraft, raw_has_variants: bool) -> list[str]:
        SourceRunService._normalize_variant_currencies(product)
        _, reasons = adapter.validate_product(product)
        reasons_set = {str(x).strip().lower() for x in reasons if str(x).strip()}
        variant_currency = SourceRunService._derive_currency_from_variants(product)
        normalized_variants = product.get('variants') if isinstance(product.get('variants'), list) else []

        if not raw_has_variants or not normalized_variants:
            reasons_set.add('missing_variants')
        if variant_currency:
            reasons_set.discard('missing_currency')
        else:
            reasons_set.add('missing_currency')
        return sorted(reasons_set)

    def run(
        self,
        source_key: str,
        *,
        dry_run: bool = False,
        run_id: str | None = None,
        candidate_urls: list[str] | tuple[str, ...] | None = None,
        prefer_candidate_urls: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SourceRunReport:
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
            source_key=source.key,
            source_url=source.url,
            adapter_key=source.adapter_key,
            source_config=dict(source.config),
        )

        report = SourceRunReport(
            source_key=source.key,
            adapter_key=source.adapter_key,
            dry_run=dry_run,
            status=SourceRunStatus.RUNNING,
        )

        sync_mode = str(source.config.get('mode') or 'auto').strip().lower()
        if sync_mode not in {'auto', 'manual'}:
            sync_mode = 'auto'
        force_candidates = bool(prefer_candidate_urls and candidate_urls)
        if sync_mode == 'manual' or force_candidates:
            visible_urls = [str(x).strip() for x in (candidate_urls or []) if str(x).strip()]
            if force_candidates:
                logger.event('discovery_skipped_force_candidates', provided_candidates=len(visible_urls))
            else:
                logger.event('discovery_skipped_manual_mode', provided_candidates=len(visible_urls))
        else:
            try:
                visible_urls = adapter.discover_visible_catalog(context)
            except StorefrontBlockedError as exc:
                raise ConfigError(f'storefront_blocked:{exc}') from exc
        visible_set = {self._normalize_product_url(x) for x in visible_urls if str(x).strip()}
        visible_handles = {self._extract_handle(x) for x in visible_urls if str(x).strip()}
        visible_handles.discard('')
        report.visible_catalog_products = len(visible_set)
        logger.event('discovery_done', visible_catalog_products=report.visible_catalog_products)
        parsed_urls: set[str] = set()
        parsed_handles: set[str] = set()
        seen_handles: set[str] = set()
        seen_urls: set[str] = set()
        valid_products: list[dict] = []
        unavailable_products: list[dict] = []
        weight_source_stats: dict[str, int] = {'source': 0, 'missing': 0}
        pending_candidate_urls: set[str] = set(visible_set)

        for strategy_name in strategy_sequence:
            strategy = self.strategy_registry.get(strategy_name)
            attempt = StrategyAttempt(strategy=strategy_name, success=False)
            strategy_seen_urls: set[str] = set()
            strategy_seen_handles: set[str] = set()
            max_retries = retry_limits.get(strategy_name, 0)
            workers = context.source_config.get(f'{strategy_name}_workers')
            logger.event('strategy_start', name=strategy_name, retries=max_retries, workers=workers if workers is not None else '-')

            raw_items: list[dict] = []
            last_error: str | None = None
            strategy_context = StrategyContext(
                source=context,
                dry_run=dry_run,
                run_id=run_id or '',
                candidate_urls=tuple(sorted(pending_candidate_urls)) if pending_candidate_urls else (),
                candidate_only=bool(sync_mode == 'manual' or force_candidates),
                should_cancel=cancel_check,
            )
            if cancel_check is not None and cancel_check():
                logger.event('strategy_skip_canceled', name=strategy_name)
                attempt.success = True
                report.attempts.append(attempt)
                break
            if (sync_mode == 'manual' or force_candidates) and not strategy_context.candidate_urls:
                logger.event('strategy_skip_manual_no_candidates', name=strategy_name)
                attempt.success = True
                report.attempts.append(attempt)
                continue
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

            next_pending_candidate_urls: set[str] = set()
            for raw in raw_items:
                raw_variants = raw.get('variants') if isinstance(raw.get('variants'), list) else []
                raw_has_variants = bool(raw_variants)
                normalized = self._normalize_service_product(
                    adapter=adapter,
                    raw_product=raw,
                    context=context,
                )
                source = str(normalized.get('weight_source') or 'missing').strip().lower()
                if source not in weight_source_stats:
                    weight_source_stats[source] = 0
                weight_source_stats[source] += 1
                url = str(normalized.get('url') or '').strip()
                normalized['url'] = url
                handle = str(normalized.get('handle') or '').strip()

                # Exact repeats inside one source run are transport noise, not business dedup.
                # Keep the first normalized delivery and silently ignore the rest.
                if url and url in strategy_seen_urls:
                    continue
                if handle and handle in strategy_seen_handles:
                    continue
                if url:
                    strategy_seen_urls.add(url)
                if handle:
                    strategy_seen_handles.add(handle)

                if url and url in seen_urls:
                    continue
                if handle and handle in seen_handles:
                    continue

                # Any successfully normalized unique product is considered delivered
                # for coverage/fallback semantics; validation controls availability.
                if url:
                    parsed_urls.add(url)
                    seen_urls.add(url)
                if handle:
                    seen_handles.add(handle)
                    parsed_handles.add(handle)
                attempt.parsed_count += 1

                reasons = self._validation_reasons(
                    adapter=adapter,
                    product=normalized,
                    raw_has_variants=raw_has_variants,
                )
                ok = len(reasons) == 0
                if ok:
                    valid_products.append(normalized)
                else:
                    unavailable_snapshot = dict(normalized)
                    unavailable_snapshot['status_reasons'] = list(reasons)
                    unavailable_products.append(unavailable_snapshot)
                    for reason in reasons:
                        report.aggregated_status_reasons[reason] = report.aggregated_status_reasons.get(reason, 0) + 1

            attempt.success = True
            report.attempts.append(attempt)

            # Fallback semantics: stop sequence as soon as we got full visible coverage.
            if report.visible_catalog_products > 0:
                if visible_handles:
                    current_coverage = len(parsed_handles.intersection(visible_handles)) / len(visible_handles)
                else:
                    current_coverage = len(parsed_urls.intersection(visible_set)) / report.visible_catalog_products
                logger.event('strategy_coverage', strategy=strategy_name, coverage=f'{current_coverage:.6f}')
                # Fallback always processes only missing visible candidates.
                if visible_handles:
                    missing_handles = visible_handles.difference(parsed_handles)
                    pending_candidate_urls = {
                        x for x in visible_set
                        if self._extract_handle(x) in missing_handles
                    }
                else:
                    pending_candidate_urls = visible_set.difference(parsed_urls)
                if current_coverage == 1.0:
                    break
            else:
                pending_candidate_urls = next_pending_candidate_urls

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

        manual_no_candidates = (
            sync_mode == 'manual'
            and report.visible_catalog_products == 0
            and not force_candidates
        )
        if manual_no_candidates:
            report.visible_coverage = 1.0
            report.status = SourceRunStatus.SUCCESS
            logger.event('manual_no_candidates_noop', status=report.status, visible='0/0')
        elif report.visible_coverage == 1.0:
            report.status = SourceRunStatus.SUCCESS
        elif report.visible_coverage == 0.0:
            report.status = SourceRunStatus.FAILED
        else:
            report.status = SourceRunStatus.PARTIAL
        if cancel_check is not None and cancel_check() and report.status in {SourceRunStatus.SUCCESS, SourceRunStatus.FAILED}:
            report.status = SourceRunStatus.PARTIAL
            logger.event('run_canceled_midway', status=report.status)

        report.reconcile_missing = sync_mode == 'auto' and not force_candidates and report.status == SourceRunStatus.SUCCESS
        report.total_valid_products = len(valid_products)
        report.valid_products = valid_products
        report.unavailable_products = unavailable_products
        report.weight_source_stats = weight_source_stats
        report.duration_sec = time.perf_counter() - started_at
        logger.event(
            'run_done',
            status=report.status,
            visible=f'{report.parsed_visible_products}/{report.visible_catalog_products}',
            valid=report.total_valid_products,
        )

        return report

    @staticmethod
    def _derive_currency_from_variants(product: dict) -> str:
        variants = product.get('variants') if isinstance(product.get('variants'), list) else []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            cur = str(variant.get('currency_code') or '').strip().upper()
            if len(cur) == 3:
                return cur
        return ''

    @staticmethod
    def _normalize_variant_currencies(product: dict) -> None:
        variants = product.get('variants') if isinstance(product.get('variants'), list) else []
        if not variants:
            return
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            current = str(variant.get('currency_code') or '').strip().upper()
            if len(current) == 3:
                variant['currency_code'] = current
            else:
                variant['currency_code'] = None

    @staticmethod
    def _jsonable_value(value):
        if isinstance(value, Decimal):
            return float(value)
        return value
