from app.adapters.juliusgarden_v1 import JuliusgardenV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert JuliusgardenV1Adapter._extract_handle('https://julius-garden.online/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert JuliusgardenV1Adapter._extract_handle('https://julius-garden.online/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert JuliusgardenV1Adapter._extract_handle('https://julius-garden.online/products/test%C2%AE-product') == 'test®-product'
