from app.domain.statuses import SourceRunStatus
from app.schemas.run_report import SourceRunReport
from app.services.run_report_markdown_service import RunReportMarkdownService


def test_markdown_report_uses_compact_product_weight_table(tmp_path) -> None:
    report = SourceRunReport(
        source_id=1,
        source_key='jadedldn.com',
        adapter_key='jadedldn__v1',
        status=SourceRunStatus.SUCCESS,
        top_valid_products=[
            {
                'url': 'https://jadedldn.com/products/example',
                'handle': 'example',
                'title': 'Example Pants',
                'price': 85,
                'currency': 'USD',
                'weight_grams': 680,
                'weight_source': 'keyword_rule',
                'variants': [{'title': 'W30', 'price': '85.00', 'grams': 0, 'available': True}],
            }
        ],
    )
    path = RunReportMarkdownService(reports_root=str(tmp_path)).write(report)
    content = path.read_text(encoding='utf-8')
    assert '| 1 | Example Pants | example | 85 USD | 680 | keyword_rule | https://jadedldn.com/products/example |' in content
    assert 'Варианты' not in content


def test_markdown_report_writes_missing_weight_artifact(tmp_path) -> None:
    report = SourceRunReport(
        source_id=5,
        source_key='essxnyc.com',
        adapter_key='essxnyc__v1',
        status=SourceRunStatus.PARTIAL,
        missing_weight_products=[
            {
                'url': 'https://essxnyc.com/products/example',
                'handle': 'example',
                'title': 'Example Object',
                'product_type': 'Accessories',
                'tags': ['mens'],
                'price': 120,
                'currency': 'USD',
                'weight_source': 'missing',
            }
        ],
    )
    path = RunReportMarkdownService(reports_root=str(tmp_path)).write(report)
    artifact = path.parent / 'missing_weight_products.json'
    assert artifact.exists()
    content = artifact.read_text(encoding='utf-8')
    assert 'Example Object' in content
    assert 'Accessories' in content
