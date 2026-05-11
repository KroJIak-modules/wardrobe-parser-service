from app.adapters.paradoxeparis_v1 import ParadoxeparisV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert ParadoxeparisV1Adapter._extract_handle('https://paradoxeparis.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert ParadoxeparisV1Adapter._extract_handle('https://paradoxeparis.com/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert ParadoxeparisV1Adapter._extract_handle('https://paradoxeparis.com/products/test%C2%AE-product') == 'test®-product'
