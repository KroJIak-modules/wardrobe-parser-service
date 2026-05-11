from app.adapters.thelastconspiracy_v1 import ThelastconspiracyV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert ThelastconspiracyV1Adapter._extract_handle('https://thelastconspiracy.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert ThelastconspiracyV1Adapter._extract_handle('https://thelastconspiracy.com/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert ThelastconspiracyV1Adapter._extract_handle('https://thelastconspiracy.com/products/test%C2%AE-product') == 'test®-product'
