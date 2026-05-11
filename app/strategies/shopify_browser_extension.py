from __future__ import annotations

import json
import os
import subprocess
import re
from decimal import Decimal, InvalidOperation
from shutil import which

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger
from app.services.shopify_policies import ShopifyPolicyFactory


class ShopifyBrowserExtensionStrategy:
    """
    Browser fallback strategy (legacy-like behavior):
    - real Chromium profile + extension runner
    - integrated into new strategy contract
    - candidate-only fallback input
    """

    name = 'shopify_browser_extension'

    def run(self, context: StrategyContext) -> list[dict]:
        logger = RunLogger(context.run_id)
        cfg = context.source.source_config
        quality = ShopifyPolicyFactory.browser_extension_quality(cfg)
        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('source_run_sec', 600))
        candidate_urls = [str(x).strip() for x in context.candidate_urls if str(x).strip()]

        raw_browser_cfg = cfg.get('browser_extension') if isinstance(cfg.get('browser_extension'), dict) else {}
        script_path = str(raw_browser_cfg.get('script_path') or '').strip()
        if not script_path:
            raise RuntimeError('Missing source.config.browser_extension.script_path')

        scenario_id = str(raw_browser_cfg.get('scenario_id') or '').strip()
        export_concurrency = int(raw_browser_cfg.get('export_concurrency', 4))
        js_sample_size = int(raw_browser_cfg.get('js_sample_size', 80))
        max_sitemaps_raw = raw_browser_cfg.get('max_sitemaps')
        max_sitemaps = int(max_sitemaps_raw) if max_sitemaps_raw is not None else 0
        show_ui = bool(raw_browser_cfg.get('show_ui', False))
        export_mode = str(raw_browser_cfg.get('export_mode', 'json')).strip().lower() or 'json'
        export_max_products = int(raw_browser_cfg.get('export_max_products', 0))

        logger.strategy_event('start', self.name, base_url=base_url, total=len(candidate_urls))
        payload = self._run_runner(
            base_url=base_url,
            script_path=script_path,
            timeout=timeout,
            scenario_id=scenario_id,
            export_concurrency=max(1, export_concurrency),
            js_sample_size=max(1, js_sample_size),
            max_sitemaps=max(0, max_sitemaps),
            show_ui=show_ui,
            export_mode=export_mode,
            export_max_products=max(0, export_max_products),
            logger=logger,
        )
        previews = payload.get('previews')
        if not isinstance(previews, list):
            raise RuntimeError('browser_extension_runner_invalid_payload')

        by_url: dict[str, dict] = {}
        for idx, item in enumerate(previews, start=1):
            mapped = self._map_preview(item)
            url = str(mapped.get('url') or '').strip()
            if url:
                by_url[url] = mapped
            if idx % quality.progress_every == 0 or idx == len(previews):
                logger.strategy_event('progress', self.name, processed=f'{idx}/{len(previews)}', indexed=len(by_url))

        if candidate_urls:
            out = [by_url[url] for url in candidate_urls if url in by_url]
        else:
            # Standalone browser mode: no discovery candidates available.
            out = list(by_url.values())

        context.diagnostics.update(
            {
                'candidate_urls': len(candidate_urls),
                'runner_products': len(previews),
                'mapped_products': len(out),
                'products_fetch_attempted': int(payload.get('products_fetch_attempted') or 0),
                'products_fetch_succeeded': int(payload.get('products_fetch_succeeded') or 0),
                'products_fetch_failed': int(payload.get('products_fetch_failed') or 0),
                'http_429_count': int(payload.get('http_429_count') or 0),
                'retry_backoff_sec': ','.join(str(x) for x in quality.retry_backoff_sec),
            }
        )
        logger.strategy_event('done', self.name, parsed=len(out), total=len(candidate_urls))
        return out

    def _run_runner(
        self,
        *,
        base_url: str,
        script_path: str,
        timeout: int,
        scenario_id: str,
        export_concurrency: int,
        js_sample_size: int,
        max_sitemaps: int,
        show_ui: bool,
        export_mode: str,
        export_max_products: int,
        logger: RunLogger,
    ) -> dict:
        if which('node') is None:
            raise RuntimeError('browser_extension_runtime_missing: node not found')
        if which('chromium') is None:
            raise RuntimeError('browser_extension_runtime_missing: chromium not found')
        if which('Xvfb') is None and not show_ui:
            raise RuntimeError('browser_extension_runtime_missing: Xvfb not found')

        cmd = [
            'node',
            script_path,
            '--base-url',
            base_url,
            '--browser-binary',
            'chromium',
            '--export-products',
            'true',
            '--export-mode',
            export_mode,
            '--export-concurrency',
            str(export_concurrency),
            '--js-sample-size',
            str(js_sample_size),
            '--show-ui',
            'true' if show_ui else 'false',
        ]
        if max_sitemaps > 0:
            cmd += ['--max-sitemaps', str(max_sitemaps)]
        if export_max_products > 0:
            cmd += ['--export-max-products', str(export_max_products)]
        if scenario_id:
            cmd += ['--scenario-id', scenario_id]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        assert proc.stdout is not None
        stdout_lines: list[str] = []
        timed_out = False
        try:
            for raw in proc.stdout:
                line = raw.rstrip('\n')
                stdout_lines.append(line)
                self._emit_runner_progress_log(logger, line)
            proc.wait(timeout=max(30, timeout))
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()

        if timed_out:
            tail = '\n'.join(stdout_lines[-20:])
            raise RuntimeError(f'browser_extension_runner_timeout details={tail}')
        if proc.returncode != 0:
            tail = '\n'.join(stdout_lines[-20:])
            raise RuntimeError(f'browser_extension_runner_failed code={proc.returncode} details={tail}')

        for line in reversed(stdout_lines):
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError('browser_extension_runner_no_json_output')

    @staticmethod
    def _emit_runner_progress_log(logger: RunLogger, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if text.startswith('[runner] phase='):
            logger.strategy_event('progress', 'shopify_browser_extension', phase=text.replace('[runner] ', ''))
            return
        if text.startswith('[scenario:shopify]'):
            msg = text.replace('[scenario:shopify]', '').strip()
            m = re.search(r'(\d+)/(\d+)', msg)
            if m:
                cur = int(m.group(1))
                total = max(1, int(m.group(2)))
                percent = round((cur / total) * 100, 1)
                logger.strategy_event('progress', 'shopify_browser_extension', stage=msg, percent=percent)
            else:
                logger.strategy_event('progress', 'shopify_browser_extension', stage=msg)
            return
        if text.startswith('[scenario:live]'):
            msg = text.replace('[scenario:live]', '').strip()
            m = re.search(r'(?:page|navigate page)\s+(\d+)/(\d+)', msg)
            if m:
                cur = int(m.group(1))
                total = max(1, int(m.group(2)))
                percent = round((cur / total) * 100, 1)
                logger.strategy_event('progress', 'shopify_browser_extension', stage=f'live_dom: {msg}', percent=percent)
            else:
                logger.strategy_event('progress', 'shopify_browser_extension', stage=f'live_dom: {msg}')

    @staticmethod
    def _map_preview(item: dict) -> dict:
        variants = item.get('variants') if isinstance(item.get('variants'), list) else []
        image_urls = item.get('image_urls') if isinstance(item.get('image_urls'), list) else []
        return {
            'url': str(item.get('product_url') or '').strip(),
            'handle': str(item.get('handle') or '').strip(),
            'title': str(item.get('title') or '').strip(),
            'product_type': str(item.get('product_type') or '').strip(),
            'tags': [],
            'price': ShopifyBrowserExtensionStrategy._to_decimal(item.get('price')),
            'currency': str(item.get('currency') or '').strip().upper(),
            'weight_grams': None,
            'variants': variants,
            'images': [str(x).strip() for x in image_urls if str(x).strip()],
            'image_url': str(image_urls[0]).strip() if image_urls else '',
        }

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
