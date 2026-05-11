from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from app.schemas.run_report import SourceRunReport


class RunReportMarkdownService:
    def __init__(self, reports_root: str = 'reports/runs') -> None:
        self.reports_root = Path(reports_root)

    def write(self, report: SourceRunReport) -> Path:
        ts = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        run_dir = self.reports_root / f'{report.source_key}-{ts}'
        run_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append(f'# Отчет прогона: {report.source_key}')
        lines.append('')
        lines.append('## Сводка')
        lines.append('')
        lines.append('| Метрика | Значение |')
        lines.append('|---|---:|')
        lines.append(f'| Статус | {report.status.value} |')
        lines.append(f'| Видимый каталог | {report.visible_catalog_products} |')
        lines.append(f'| Покрыто видимых товаров | {report.parsed_visible_products} |')
        lines.append(f'| Покрытие | {report.visible_coverage:.4f} |')
        lines.append(f'| Найдено стратегиями | {report.total_found_products} |')
        lines.append(f'| Валидных товаров | {report.total_valid_products} |')
        lines.append(f'| Длительность, сек | {report.duration_sec:.2f} |')
        lines.append('')

        lines.append('## Стратегии')
        lines.append('')
        lines.append('| Стратегия | Успех | Raw | Валидных | Ошибка | Диагностика |')
        lines.append('|---|---|---:|---:|---|---|')
        for attempt in report.attempts:
            diagnostics = ', '.join(f'{key}={value}' for key, value in sorted(attempt.diagnostics.items())) if attempt.diagnostics else '—'
            lines.append(
                f'| {attempt.strategy} | {self._fmt(attempt.success)} | {attempt.raw_count} | '
                f'{attempt.parsed_count} | {self._fmt(attempt.error)} | {diagnostics} |'
            )
        lines.append('')

        lines.append('## Качество')
        lines.append('')
        if report.weight_source_stats:
            lines.append('| Источник веса | Количество |')
            lines.append('|---|---:|')
            lines.append(f"| Из источника | {int(report.weight_source_stats.get('source', 0))} |")
            lines.append(f"| По ключевым словам | {int(report.weight_source_stats.get('keyword_rule', 0))} |")
            lines.append(f"| Без веса | {int(report.weight_source_stats.get('missing', 0))} |")
            lines.append('')
        if report.aggregated_unavailable_reasons:
            lines.append('| Причина невалидности | Количество |')
            lines.append('|---|---:|')
            for reason, count in sorted(report.aggregated_unavailable_reasons.items()):
                lines.append(f'| {reason} | {count} |')
            lines.append('')
        lines.append(f'- Карантин URL: **{len(report.quarantined_urls)}**')
        lines.append(f'- Ошибки: **{len(report.errors)}**')
        if report.errors:
            lines.append('')
            lines.append('Первые ошибки:')
            for error in report.errors[:10]:
                lines.append(f'- `{error}`')
        lines.append('')

        lines.append('## Примеры товаров')
        lines.append('')
        lines.append('| # | Название | Handle | Цена | Вес | Вес источник | URL |')
        lines.append('|---:|---|---|---:|---:|---|---|')

        for idx, product in enumerate(report.top_valid_products[:10], start=1):
            lines.append(
                f'| {idx} | {self._fmt(product.get("title"))} | {self._fmt(product.get("handle"))} | '
                f'{self._fmt(product.get("price"))} {self._fmt(product.get("currency"))} | '
                f'{self._fmt(product.get("weight_grams"))} | {self._fmt(product.get("weight_source"))} | '
                f'{self._fmt(product.get("url"))} |'
            )

        md_path = run_dir / 'report.md'
        md_path.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
        if report.missing_weight_products:
            (run_dir / 'missing_weight_products.json').write_text(
                json.dumps(report.missing_weight_products, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8',
            )
        return md_path

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return '—'
        text = str(value).replace('\n', ' ').strip()
        return text if text else '—'
