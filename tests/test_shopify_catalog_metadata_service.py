from app.services.shopify_catalog_metadata_service import ShopifyCatalogMetadataService


def test_shopify_catalog_metadata_service_prefers_product_type() -> None:
    assert ShopifyCatalogMetadataService.resolve_category(
        {"product_type": "Outerwear", "type": "Jackets"}
    ) == "Outerwear"


def test_shopify_catalog_metadata_service_falls_back_to_type() -> None:
    assert ShopifyCatalogMetadataService.resolve_category(
        {"product_type": "", "type": "Footwear"}
    ) == "Footwear"


def test_shopify_catalog_metadata_service_falls_back_to_html_category(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        text = '<script type="application/ld+json">{"category":"Trucker Jackets"}</script>'

    monkeypatch.setattr(
        "app.services.shopify_catalog_metadata_service.ShopifyHttpClient.get_text",
        lambda url, timeout: FakeResponse(),
    )

    assert ShopifyCatalogMetadataService.resolve_category(
        {"product_type": "", "type": "", "tags": []},
        product_url="https://example.com/products/demo",
        timeout=10,
    ) == "Trucker Jackets"


def test_shopify_catalog_metadata_service_falls_back_to_tag_category() -> None:
    assert ShopifyCatalogMetadataService.resolve_category(
        {"product_type": "", "type": "", "tags": ["June DROP", "women-shorts", "White"]},
    ) == "Shorts"
