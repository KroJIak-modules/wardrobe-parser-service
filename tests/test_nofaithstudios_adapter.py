from app.adapters.nofaithstudios_v1 import NofaithstudiosV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert NofaithstudiosV1Adapter._extract_handle('https://nofaithstudios.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert NofaithstudiosV1Adapter._extract_handle('https://nofaithstudios.com/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert NofaithstudiosV1Adapter._extract_handle('https://nofaithstudios.com/products/test%C2%AE-product') == 'test®-product'
