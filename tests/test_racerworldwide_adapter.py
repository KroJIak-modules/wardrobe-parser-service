from app.adapters.racerworldwide_v1 import RacerworldwideV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert RacerworldwideV1Adapter._extract_handle('https://www.racerworldwide.net/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert RacerworldwideV1Adapter._extract_handle('https://www.racerworldwide.net/en-us/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert RacerworldwideV1Adapter._extract_handle('https://www.racerworldwide.net/products/vibram%C2%AE-desert-boots') == 'vibram®-desert-boots'
