from app.strategies.intl_protocol_index_cafe24 import IntlProtocolIndexCafe24Strategy


def test_cafe24_product_mapping_keeps_sitemap_lastmod_only_when_available(monkeypatch) -> None:
    strategy = IntlProtocolIndexCafe24Strategy()
    html = '<meta property=\"og:title\" content=\"Layered Thermal Jersey\" />'

    class Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        'app.strategies.intl_protocol_index_cafe24.requests.get',
        lambda *_args, **_kwargs: Response(),
    )

    mapped_with_date = strategy._fetch_one(
        'https://protocolindex.cafe24.com/shop2/product/layered-thermal-jersey-black/32/',
        10,
        '2026-04-10T17:36:49+09:00',
    )
    mapped_without_date = strategy._fetch_one(
        'https://protocolindex.cafe24.com/shop2/product/3-layered-sweat-pants-black/25/',
        10,
        None,
    )

    assert mapped_with_date['title'] == 'Layered Thermal Jersey'
    assert mapped_with_date['published_at'] == '2026-04-10T17:36:49+09:00'
    assert mapped_without_date['published_at'] is None
