from dataclasses import dataclass


@dataclass
class SourceRecord:
    id: int
    key: str
    url: str
    adapter_key: str
    enabled: bool
    sync_enabled: bool
    config: dict


class SourceRepository:
    """Stage-2 pilot repository with explicit per-site config."""

    def get_by_key(self, source_key: str) -> SourceRecord:
        if source_key != 'jadedldn.com':
            raise KeyError(f'Unknown source key for pilot stage: {source_key}')

        return SourceRecord(
            id=1,
            key=source_key,
            url='https://jadedldn.com/',
            adapter_key='jadedldn__v1',
            enabled=True,
            sync_enabled=True,
            config={
                'strategy_sequence': ['shopify_json', 'shopify_js', 'browser_export'],
                'retry_limits': {
                    'shopify_json': 1,
                    'shopify_js': 1,
                    'browser_export': 0,
                },
                'timeouts': {'product_sec': 10, 'source_run_sec': 300},
                'visible_catalog_set': [
                    'https://jadedldn.com/products/alpha-jacket',
                    'https://jadedldn.com/products/beta-hoodie',
                ],
                'strategy_payloads': {
                    'shopify_json': [
                        {
                            'url': 'https://jadedldn.com/products/alpha-jacket',
                            'title': 'Alpha Jacket',
                            'price': 220,
                            'currency': 'USD',
                            'weight_grams': 900,
                            'variants': [{'title': 'M', 'available': True}],
                        }
                    ],
                    'shopify_js': [
                        {
                            'url': 'https://jadedldn.com/products/beta-hoodie',
                            'title': 'Beta Hoodie',
                            'price': 140,
                            'currency': 'USD',
                            'weight_grams': 700,
                            'variants': [{'title': 'L', 'available': True}],
                        }
                    ],
                    'browser_export': [],
                },
            },
        )
