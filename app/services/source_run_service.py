from __future__ import annotations
from decimal import Decimal
import time
from urllib.parse import unquote, urlparse

from app.adapters.contracts import SourceContext, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError, StorefrontBlockedError
from app.domain.statuses import SourceRunStatus
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.services.config_validation_service import ConfigValidationService
from app.services.description_text_service import DescriptionTextService
from app.services.run_logger import RunLogger
from app.services.run_report_markdown_service import RunReportMarkdownService
from app.services.weight_enrichment_service import WeightEnrichmentService
from app.services.weight_rules_client import WeightRulesClient
from app.strategies.registry import StrategyRegistry


class SourceRunService:
    @staticmethod
    def _normalize_title(title: str) -> str:
        return ' '.join(str(title or '').strip().lower().split())

    @staticmethod
    def _normalize_vendor(vendor: str | None) -> str:
        return str(vendor or '').strip().lower()

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _dedup_score(cls, left: dict, right: dict, cfg: dict) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        title_w = float(cfg.get('title_match_weight', 0.45))
        vendor_w = float(cfg.get('vendor_match_weight', 0.2))
        price_w = float(cfg.get('price_close_weight', 0.2))
        handle_w = float(cfg.get('handle_match_weight', 0.35))
        price_ratio_limit = float(cfg.get('price_diff_ratio_limit', 0.05))
        score_cap = float(cfg.get('score_cap', 1.0))

        if cls._normalize_title(str(left.get('title') or '')) == cls._normalize_title(str(right.get('title') or '')):
            score += title_w
            reasons.append('title_match')

        left_vendor = cls._normalize_vendor(left.get('vendor'))
        right_vendor = cls._normalize_vendor(right.get('vendor'))
        if left_vendor and left_vendor == right_vendor:
            score += vendor_w
            reasons.append('vendor_match')

        lp = cls._to_float(left.get('price'))
        rp = cls._to_float(right.get('price'))
        if lp is not None and rp is not None:
            mx = max(lp, rp)
            diff = abs(lp - rp)
            if mx > 0 and diff / mx <= price_ratio_limit:
                score += price_w
                reasons.append('price_close')

        if str(left.get('handle') or '').strip() and str(left.get('handle') or '').strip() == str(right.get('handle') or '').strip():
            score += handle_w
            reasons.append('handle_match')

        return min(score, score_cap), reasons

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
                handle = unquote(parts[i + 1])
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
                return unquote(parts[i + 1]).strip()
        return ''

    def require_runnable_source(self, source_key: str) -> None:
        source = self.source_repo.get_by_key(source_key)
        if not source.enabled or not source.sync_enabled:
            raise ConfigError(f'source disabled: {source_key}')

    def run(
        self,
        source_key: str,
        *,
        dry_run: bool = False,
        run_id: str | None = None,
        candidate_urls: list[str] | tuple[str, ...] | None = None,
        prefer_candidate_urls: bool = False,
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
        unavailable_products: list[dict] = []
        weight_source_stats: dict[str, int] = {'source': 0, 'keyword_rule': 0, 'missing': 0}
        pending_candidate_urls: set[str] = set(visible_set)
        dedup_cfg = source.config.get('dedup') if isinstance(source.config.get('dedup'), dict) else {}
        dedup_enabled = bool(dedup_cfg.get('enabled', True))
        dedup_threshold = float(dedup_cfg.get('score_threshold', 0.75))
        accepted_for_dedup: list[dict] = []

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
            )
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
                normalized = adapter.normalize_product(raw)
                # Preserve critical fields from strategy payload if adapter omitted them.
                if not str(normalized.get('vendor') or '').strip():
                    normalized['vendor'] = str(raw.get('vendor') or raw.get('brand') or '').strip()
                if not str(normalized.get('description') or '').strip():
                    normalized['description'] = str(raw.get('description') or raw.get('body_html') or '').strip() or None
                normalized['description'] = DescriptionTextService.normalize(normalized.get('description'))
                if not isinstance(normalized.get('images'), list) or not normalized.get('images'):
                    normalized['images'] = list(raw.get('images')) if isinstance(raw.get('images'), list) else []
                normalized = WeightEnrichmentService.apply_keyword_weight(normalized, weight_rules)
                source = str(normalized.get('weight_source') or 'missing').strip().lower()
                if source not in weight_source_stats:
                    weight_source_stats[source] = 0
                weight_source_stats[source] += 1
                url = self._canonical_product_url(str(normalized.get('url') or '').strip())
                normalized['url'] = url
                handle = str(normalized.get('handle') or '').strip()

                if url and url in report.quarantined_urls:
                    if url:
                        next_pending_candidate_urls.add(url)
                    continue

                # Duplicate policy should flag duplicates inside a single strategy pass.
                # Cross-strategy repeats are expected during fallback and must be ignored.
                if url and url in strategy_seen_urls:
                    report.errors.append(f'duplicate_url:{url}')
                    report.quarantined_urls.append(url)
                    next_pending_candidate_urls.add(url)
                    continue
                if handle and handle in strategy_seen_handles:
                    report.errors.append(f'duplicate_handle:{handle}')
                    if url:
                        report.quarantined_urls.append(url)
                        next_pending_candidate_urls.add(url)
                    continue
                if url:
                    strategy_seen_urls.add(url)
                if handle:
                    strategy_seen_handles.add(handle)

                if url and url in seen_urls:
                    continue
                if handle and handle in seen_handles:
                    continue

                if dedup_enabled and accepted_for_dedup:
                    best_score = 0.0
                    best_reasons: list[str] = []
                    best_url = ''
                    for prev in accepted_for_dedup:
                        pair_score, pair_reasons = self._dedup_score(prev, normalized, dedup_cfg)
                        if pair_score > best_score:
                            best_score = pair_score
                            best_reasons = pair_reasons
                            best_url = str(prev.get('url') or '').strip()
                    if best_score >= dedup_threshold:
                        report.aggregated_unavailable_reasons['deduplicated'] = report.aggregated_unavailable_reasons.get('deduplicated', 0) + 1
                        report.errors.append(
                            f'dedup_candidate:score={best_score:.3f}:url={url or "-"}:dup_of={best_url or "-"}:reasons={",".join(best_reasons)}'
                        )
                        if url:
                            report.quarantined_urls.append(url)
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

                self._normalize_variant_currencies(normalized)
                ok, reasons = adapter.validate_product(normalized)
                variant_currency = self._derive_currency_from_variants(normalized)
                reasons_set = {str(x).strip().lower() for x in reasons if str(x).strip()}
                if variant_currency:
                    reasons_set.discard('missing_currency')
                else:
                    reasons_set.add('missing_currency')
                reasons = sorted(reasons_set)
                ok = len(reasons) == 0
                # Currency is variant-level only in service output contract.
                normalized.pop('currency', None)
                accepted_for_dedup.append(normalized)
                if ok:
                    valid_products.append(normalized)
                else:
                    unavailable_snapshot = dict(normalized)
                    unavailable_snapshot['unavailable_reasons'] = list(reasons)
                    unavailable_products.append(unavailable_snapshot)
                    for reason in reasons:
                        report.aggregated_unavailable_reasons[reason] = report.aggregated_unavailable_reasons.get(reason, 0) + 1
                    if 'missing_weight' in reasons:
                        report.missing_weight_products.append(self._missing_weight_product_snapshot(normalized))

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

        if report.visible_coverage == 1.0:
            report.status = SourceRunStatus.SUCCESS
        elif report.visible_coverage == 0.0:
            report.status = SourceRunStatus.FAILED
        else:
            report.status = SourceRunStatus.PARTIAL

        report.total_valid_products = len(valid_products)
        report.valid_products = valid_products
        report.unavailable_products = unavailable_products
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

    @staticmethod
    def _derive_currency_from_variants(product: dict) -> str:
        variants = product.get('variants') if isinstance(product.get('variants'), list) else []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            cur = str(variant.get('currency') or '').strip().upper()
            if len(cur) == 3:
                return cur
        return ''

    @staticmethod
    def _normalize_variant_currencies(product: dict) -> None:
        variants = product.get('variants') if isinstance(product.get('variants'), list) else []
        if not variants:
            return
        fallback = str(product.get('currency') or '').strip().upper()
        fallback_currency = fallback if len(fallback) == 3 else ''
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            current = str(variant.get('currency') or '').strip().upper()
            if len(current) == 3:
                variant['currency'] = current
                continue
            if fallback_currency:
                variant['currency'] = fallback_currency

    @staticmethod
    def _missing_weight_product_snapshot(product: dict) -> dict:
        tags = product.get('tags')
        return {
            'url': str(product.get('url') or '').strip(),
            'handle': str(product.get('handle') or '').strip(),
            'title': str(product.get('title') or '').strip(),
            'product_type': str(product.get('product_type') or '').strip(),
            'tags': tags if isinstance(tags, list) else [],
            'price': SourceRunService._jsonable_value(product.get('price')),
            'currency': SourceRunService._derive_currency_from_variants(product),
            'weight_source': str(product.get('weight_source') or '').strip(),
        }

    @staticmethod
    def _jsonable_value(value):
        if isinstance(value, Decimal):
            return float(value)
        return value
