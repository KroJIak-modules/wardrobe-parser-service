from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import requests

from app.schemas.run_report import SourceRunReport


class RunReportMarkdownService:
    def __init__(self, reports_root: str = 'reports/runs') -> None:
        self.reports_root = Path(reports_root)

    def write(self, report: SourceRunReport) -> Path:
        ts = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        run_dir = self.reports_root / f'{report.source_key}-{ts}'
        images_dir = run_dir / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append(f'# Отчет прогона: {report.source_key}')
        lines.append('')
        lines.append(f'- Название сайта: `{report.source_key}`')
        lines.append(f'- Количество товаров (видимых пользователю): **{report.visible_catalog_products}**')
        lines.append(f'- Количество найденных товаров: **{report.total_found_products}**')
        lines.append(f'- Количество валидных товаров: **{report.total_valid_products}**')
        lines.append(f'- Время прогона: **{report.duration_sec:.2f} сек**')
        if report.weight_source_stats:
            lines.append('- Источник веса:')
            lines.append(f"  - Из источника: **{int(report.weight_source_stats.get('source', 0))}**")
            lines.append(f"  - По ключевым словам: **{int(report.weight_source_stats.get('keyword_rule', 0))}**")
            lines.append(f"  - Без веса: **{int(report.weight_source_stats.get('missing', 0))}**")
        lines.append('')
        lines.append('## Топ 10 товаров')
        lines.append('')

        for idx, product in enumerate(report.top_valid_products[:10], start=1):
            lines.append(f'### {idx}. {product.get("title") or "Без названия"}')
            lines.append('| Атрибут | Значение |')
            lines.append('|---|---|')
            for key in ('url', 'handle', 'title', 'price', 'currency', 'weight_grams', 'weight_source'):
                if key not in product:
                    continue
                label = self._ru_label(key)
                value = self._fmt(product.get(key))
                lines.append(f'| {label} | {value} |')

            variants = product.get('variants')
            if isinstance(variants, list) and variants:
                lines.append('')
                lines.append('**Варианты (первые 8):**')
                lines.append('')
                lines.append('| Название | Цена | Вес (г) | Доступность |')
                lines.append('|---|---:|---:|---|')
                for row in variants[:8]:
                    if not isinstance(row, dict):
                        continue
                    v_title = self._fmt(row.get('title'))
                    v_price = self._fmt(row.get('price'))
                    v_grams = self._fmt(row.get('grams'))
                    v_available = 'Да' if bool(row.get('available')) else 'Нет'
                    lines.append(f'| {v_title} | {v_price} | {v_grams} | {v_available} |')

            image_url = str(product.get('image_url') or '').strip()
            if image_url:
                local_name = f'{idx:02d}.jpg'
                local_path = images_dir / local_name
                if self._download_image(image_url, local_path):
                    rel = (Path('images') / local_name).as_posix()
                    lines.append('')
                    lines.append(f'<img src="{rel}" alt="Фото товара {idx}" width="220" />')
                else:
                    lines.append('')
                    lines.append('Фото: не удалось скачать.')
            else:
                lines.append('')
                lines.append('Фото: отсутствует.')
            lines.append('')

        md_path = run_dir / 'report.md'
        md_path.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
        return md_path

    @staticmethod
    def _ru_label(key: str) -> str:
        mapping = {
            'url': 'Ссылка',
            'handle': 'Хэндл',
            'title': 'Название',
            'price': 'Цена',
            'currency': 'Валюта',
            'weight_grams': 'Вес (граммы)',
            'weight_source': 'Источник веса',
            'source_status': 'Статус товара у источника',
            'variants': 'Варианты',
        }
        return mapping.get(key, key)

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return '—'
        text = str(value).replace('\n', ' ').strip()
        return text if text else '—'

    @staticmethod
    def _download_image(url: str, path: Path) -> bool:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                return False
            path.write_bytes(response.content)
            return True
        except Exception:
            return False
