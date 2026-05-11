from app.adapters.essxnyc_v1 import EssxnycV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert EssxnycV1Adapter._extract_handle('https://essxnyc.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert EssxnycV1Adapter._extract_handle('https://essxnyc.com/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert EssxnycV1Adapter._extract_handle('https://essxnyc.com/products/test%C2%AE-product') == 'test®-product'
