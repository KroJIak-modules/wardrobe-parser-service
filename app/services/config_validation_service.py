from app.core.exceptions import ConfigError
from app.services.shopify_policies import ALLOWED_CURRENCY_CODES, MAX_PRODUCTS_LIMIT, MAX_REQUEST_RETRIES


class ConfigValidationService:
    @staticmethod
    def require_strategy_sequence(config: dict, allowed: set[str]) -> list[str]:
        sequence = config.get('strategy_sequence')
        if not isinstance(sequence, list) or not sequence:
            raise ConfigError('Missing required source.config.strategy_sequence')
        for item in sequence:
            if not isinstance(item, str) or item not in allowed:
                raise ConfigError(f'Invalid strategy in strategy_sequence: {item}')
        return sequence

    @staticmethod
    def require_retry_limits(config: dict) -> dict[str, int]:
        raw = config.get('retry_limits')
        if not isinstance(raw, dict) or not raw:
            raise ConfigError('Missing required source.config.retry_limits')
        out: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, int) or value < 0:
                raise ConfigError(f'Invalid retry limit for {key}')
            out[key] = value
        return out

    @staticmethod
    def require_timeouts(config: dict) -> dict[str, int]:
        raw = config.get('timeouts')
        if not isinstance(raw, dict) or not raw:
            raise ConfigError('Missing required source.config.timeouts')
        required = {'product_sec', 'source_run_sec'}
        if not required.issubset(raw.keys()):
            raise ConfigError('Missing required timeout keys: product_sec, source_run_sec')
        out: dict[str, int] = {}
        for key in required:
            value = raw.get(key)
            if not isinstance(value, int) or value <= 0:
                raise ConfigError(f'Invalid timeout value for {key}')
            out[key] = value
        return out

    @staticmethod
    def require_strategy_settings(config: dict, strategy_sequence: list[str]) -> None:
        if any(item.startswith('shopify_') for item in strategy_sequence):
            ConfigValidationService._require_shopify_sitemap_policy(config)
            ConfigValidationService._require_shopify_currency_policy(config)
        if 'shopify_json' in strategy_sequence:
            ConfigValidationService._require_shopify_json_quality(config)
        if 'shopify_js' in strategy_sequence:
            workers = config.get('shopify_js_workers')
            if not isinstance(workers, int) or workers <= 0:
                raise ConfigError('Missing or invalid source.config.shopify_js_workers')
            ConfigValidationService._require_shopify_js_quality(config)
        if 'shopify_browser_extension' in strategy_sequence:
            ConfigValidationService._require_shopify_browser_extension_quality(config)

    @staticmethod
    def _require_shopify_sitemap_policy(config: dict) -> None:
        raw = config.get('shopify_sitemap')
        if not isinstance(raw, dict):
            raise ConfigError('Missing source.config.shopify_sitemap')
        max_products = raw.get('max_products')
        if not isinstance(max_products, int) or max_products <= 0 or max_products > MAX_PRODUCTS_LIMIT:
            raise ConfigError(f'Invalid source.config.shopify_sitemap.max_products: must be 1..{MAX_PRODUCTS_LIMIT}')
        include_locale_sitemaps = raw.get('include_locale_sitemaps')
        if not isinstance(include_locale_sitemaps, bool):
            raise ConfigError('Invalid source.config.shopify_sitemap.include_locale_sitemaps')
        request_retries = raw.get('request_retries')
        if not isinstance(request_retries, int) or request_retries < 0 or request_retries > MAX_REQUEST_RETRIES:
            raise ConfigError('Invalid source.config.shopify_sitemap.request_retries')


    @staticmethod
    def _require_shopify_currency_policy(config: dict) -> None:
        raw = config.get('shopify_currency')
        if not isinstance(raw, dict):
            raise ConfigError('Missing source.config.shopify_currency')
        method = str(raw.get('method') or 'priority_list').strip().lower()
        if method not in {'priority_list', 'locked_param_currency', 'locked_no_currency'}:
            raise ConfigError('Invalid source.config.shopify_currency.method')
        priority = raw.get('requested_currency_priority')
        if not isinstance(priority, list) or not priority:
            raise ConfigError('Missing source.config.shopify_currency.requested_currency_priority')
        valid_codes: list[str] = []
        for value in priority:
            code = str(value or '').strip().upper()
            if code == 'GBR':
                code = 'GBP'
            if code in ALLOWED_CURRENCY_CODES:
                valid_codes.append(code)
        # Ignore unknown currencies (for example JPY in legacy configs),
        # but require at least one supported code so runtime selection remains deterministic.
        if not valid_codes:
            raise ConfigError('Invalid source.config.shopify_currency.requested_currency_priority')
        if method in {'locked_param_currency', 'locked_no_currency'}:
            locked = str(raw.get('locked_currency') or '').strip().upper()
            if locked == 'GBR':
                locked = 'GBP'
            if locked not in ALLOWED_CURRENCY_CODES:
                raise ConfigError('Invalid source.config.shopify_currency.locked_currency')
        locked_country = str(raw.get('locked_country') or '').strip().upper()
        if locked_country and (len(locked_country) != 2 or not locked_country.isalpha()):
            raise ConfigError('Invalid source.config.shopify_currency.locked_country')
    @staticmethod
    def _require_shopify_json_quality(config: dict) -> None:
        raw = config.get('shopify_json_quality')
        if not isinstance(raw, dict):
            raise ConfigError('Missing source.config.shopify_json_quality')
        enrich_from_js_fields = raw.get('enrich_from_js_fields')
        if not isinstance(enrich_from_js_fields, list):
            raise ConfigError('Missing source.config.shopify_json_quality.enrich_from_js_fields')
        allowed_enrichment_fields = {'price', 'images'}
        for field in enrich_from_js_fields:
            if not isinstance(field, str) or field not in allowed_enrichment_fields:
                raise ConfigError('Invalid source.config.shopify_json_quality.enrich_from_js_fields')
        ConfigValidationService._require_number(raw, 'antibot_pause_sec')
        ConfigValidationService._require_backoffs(raw, 'shopify_json_quality')

    @staticmethod
    def _require_shopify_js_quality(config: dict) -> None:
        raw = config.get('shopify_js_quality')
        if not isinstance(raw, dict):
            raise ConfigError('Missing source.config.shopify_js_quality')
        progress_every = raw.get('progress_every')
        if not isinstance(progress_every, int) or progress_every <= 0:
            raise ConfigError('Invalid source.config.shopify_js_quality.progress_every')
        ConfigValidationService._require_number(raw, 'wait_log_sec')
        ConfigValidationService._require_number(raw, 'pause_poll_sec')
        ConfigValidationService._require_number(raw, 'antibot_pause_sec')
        ConfigValidationService._require_backoffs(raw, 'shopify_js_quality')

    @staticmethod
    def _require_shopify_browser_extension_quality(config: dict) -> None:
        raw = config.get('shopify_browser_extension_quality')
        if not isinstance(raw, dict):
            raise ConfigError('Missing source.config.shopify_browser_extension_quality')
        progress_every = raw.get('progress_every')
        if not isinstance(progress_every, int) or progress_every <= 0:
            raise ConfigError('Invalid source.config.shopify_browser_extension_quality.progress_every')
        ConfigValidationService._require_backoffs(raw, 'shopify_browser_extension_quality')

    @staticmethod
    def _require_number(raw: dict, key: str) -> None:
        value = raw.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f'Invalid source.config.{key}')

    @staticmethod
    def _require_backoffs(raw: dict, section: str) -> None:
        values = raw.get('retry_backoff_sec')
        if not isinstance(values, list) or not values:
            raise ConfigError(f'Missing source.config.{section}.retry_backoff_sec')
        for value in values:
            if not isinstance(value, (int, float)) or value <= 0:
                raise ConfigError(f'Invalid source.config.{section}.retry_backoff_sec')
