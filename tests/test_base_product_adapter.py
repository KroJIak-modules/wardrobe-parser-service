from app.adapters.base import BaseProductAdapter


def test_normalize_tags_accepts_comma_separated_string() -> None:
    assert BaseProductAdapter._normalize_tags('active_test, runway , active_test,  ') == [
        'active_test',
        'runway',
    ]


def test_normalize_tags_accepts_single_scalar() -> None:
    assert BaseProductAdapter._normalize_tags('active_test') == ['active_test']


def test_normalize_tags_preserves_distinct_case() -> None:
    assert BaseProductAdapter._normalize_tags(['Tag', 'tag', 'Tag']) == ['Tag', 'tag']
