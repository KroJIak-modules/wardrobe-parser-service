"""Product upsert/batch-sync helpers for parser jobs."""

from __future__ import annotations

from typing import Any
from typing import Callable, Optional

from app.core.config import settings
from app.repositories import ParserImageAssetRepository, ParserProductRepository
from app.schemas.parser import WeightRuleResponse
from app.services.product_status_service import resolve_product_status
from app.services.settings.weight_rule_service import WeightRuleService


class ParserProductSyncService:
    """Encapsulates per-source product synchronization logic."""

    IMAGE_ASSET_BATCH_SIZE = 500

    def __init__(
        self,
        product_repo: ParserProductRepository,
        image_repo: ParserImageAssetRepository,
        weight_rule_service: WeightRuleService,
    ):
        self.product_repo = product_repo
        self.image_repo = image_repo
        self.weight_rule_service = weight_rule_service

    @staticmethod
    def _to_float(
        value: Any,
        *,
        payload_source: str | None = None,
        currency: str | None = None,
    ) -> float | None:
        if value is None:
            return None
        normalized_text: str | None = None
        if isinstance(value, str):
            normalized_text = value.strip().replace(",", ".")
            if not normalized_text:
                return None
        try:
            parsed = float(normalized_text if normalized_text is not None else value)
        except (TypeError, ValueError):
            return None

        payload_tag = (payload_source or "").strip().lower()
        normalized_currency = (currency or "").strip().upper()
        # Shopify .js payloads often carry integer cents.
        if (
            payload_tag == "js"
            and parsed.is_integer()
            and normalized_currency not in {"JPY", "KRW"}
        ):
            return parsed / settings.preview_js_price_cents_divisor

        return parsed

    @staticmethod
    def _require_currency(raw_currency: str | None, *, product_url: str | None = None) -> str:
        normalized_currency = (raw_currency or "").strip().upper()
        if len(normalized_currency) != 3:
            if product_url:
                raise ValueError(f"Не удалось определить валюту товара: {product_url}")
            raise ValueError("Не удалось определить валюту товара")
        return normalized_currency

    @classmethod
    def _normalize_variant_money(cls, value: Any, *, payload_source: str | None, currency: str | None) -> Any:
        if value is None:
            return None
        parsed = cls._to_float(value, payload_source=payload_source, currency=currency)
        if parsed is None:
            return value
        rounded = round(parsed, 2)
        if rounded.is_integer():
            return int(rounded)
        return rounded

    @classmethod
    def _normalize_preview_variants(
        cls,
        variants: list[dict],
        *,
        payload_source: str | None,
        currency: str | None,
    ) -> list[dict]:
        normalized: list[dict] = []
        for variant in variants:
            if not isinstance(variant, dict):
                normalized.append(variant)
                continue
            item = dict(variant)
            item["price"] = cls._normalize_variant_money(
                item.get("price"),
                payload_source=payload_source,
                currency=currency,
            )
            if "compare_at_price" in item:
                item["compare_at_price"] = cls._normalize_variant_money(
                    item.get("compare_at_price"),
                    payload_source=payload_source,
                    currency=currency,
                )
            normalized.append(item)
        return normalized

    def _upsert_product_from_preview(
        self,
        *,
        source_id: int,
        preview,
        existing_by_handle: dict[str, Any],
        existing_by_url: dict[str, Any],
        image_asset_cache: dict[str, Any],
        weight_rules: list[WeightRuleResponse],
    ) -> tuple[int, int, int]:
        existing = existing_by_handle.get(preview.handle)
        if existing is None:
            existing = existing_by_url.get(preview.product_url)

        parsed_price = self._to_float(
            preview.price,
            payload_source=getattr(preview, "payload_source", None),
            currency=preview.currency,
        )
        resolved_currency = self._require_currency(preview.currency, product_url=getattr(preview, "product_url", None))
        preview_image_urls = preview.image_urls or []
        assets = [image_asset_cache[url] for url in preview_image_urls if url in image_asset_cache]
        preview_image_asset_ids = [asset.id for asset in assets]
        preview_variants = self._normalize_preview_variants(
            preview.variants or [],
            payload_source=getattr(preview, "payload_source", None),
            currency=resolved_currency,
        )
        status = resolve_product_status(
            variants=preview_variants,
            preview_available=preview.available,
            existing_status=getattr(existing, "status", None),
        )
        weight_grams = preview.weight_grams
        weight_source = preview.weight_source
        weight_match_keyword = preview.weight_match_keyword
        weight_value = preview.weight_value
        weight_unit = preview.weight_unit

        if weight_grams is None:
            matched = WeightRuleService.match_weight_from_rules(
                rules=weight_rules,
                title=preview.title,
                vendor=preview.vendor,
                product_type=preview.product_type,
                handle=preview.handle,
            )
            if matched.weight_grams is not None:
                weight_grams = matched.weight_grams
                weight_source = "keyword"
                weight_match_keyword = matched.matched_keyword
                weight_value = matched.weight_grams
                weight_unit = "g"
            else:
                weight_source = "missing"
                weight_match_keyword = None
                weight_value = None
                weight_unit = None

        if existing is None:
            created = self.product_repo.create_product(
                source_id=source_id,
                handle=preview.handle,
                title=preview.title or preview.handle,
                url=preview.product_url,
                description=preview.description,
                vendor=preview.vendor,
                product_type=preview.product_type,
                price=parsed_price,
                currency=resolved_currency,
                image_count=len(preview_image_urls),
                image_urls=preview_image_urls,
                image_asset_ids=preview_image_asset_ids,
                variants=preview_variants,
                weight_grams=weight_grams,
                weight_source=weight_source,
                weight_match_keyword=weight_match_keyword,
                weight_value=weight_value,
                weight_unit=weight_unit,
                status=status,
                is_auto_added=True,
                auto_hide_force_visible=False,
            )
            existing_by_handle[created.handle] = created
            existing_by_url[created.url] = created
            return 1, 0, int(created.id)

        is_title_locked = bool(getattr(existing, "title_sync_locked", False))
        is_description_locked = bool(getattr(existing, "description_sync_locked", False))
        is_images_locked = bool(getattr(existing, "images_sync_locked", False))

        next_title = existing.title if is_title_locked else (preview.title or preview.handle)
        next_description = existing.description if is_description_locked else preview.description
        next_image_urls = list(existing.image_urls or []) if is_images_locked else preview_image_urls
        next_image_asset_ids = list(existing.image_asset_ids or []) if is_images_locked else preview_image_asset_ids
        next_image_count = int(existing.image_count or 0) if is_images_locked else len(preview_image_urls)

        changed = (
            existing.source_id != source_id
            or existing.handle != preview.handle
            or existing.title != next_title
            or existing.description != next_description
            or existing.url != preview.product_url
            or existing.vendor != preview.vendor
            or existing.product_type != preview.product_type
            or existing.price != parsed_price
            or existing.currency != resolved_currency
            or (existing.image_urls or []) != next_image_urls
            or (existing.image_asset_ids or []) != next_image_asset_ids
            or existing.image_count != next_image_count
            or (existing.variants or []) != preview_variants
            or existing.weight_grams != weight_grams
            or existing.weight_source != weight_source
            or existing.weight_match_keyword != weight_match_keyword
            or existing.weight_value != weight_value
            or existing.weight_unit != weight_unit
            or existing.status != status
        )
        if not changed:
            existing_by_handle[existing.handle] = existing
            existing_by_url[existing.url] = existing
            return 0, 0, int(existing.id)

        self.product_repo.update(
            existing,
            source_id=source_id,
            handle=preview.handle,
            title=next_title,
            url=preview.product_url,
            description=next_description,
            vendor=preview.vendor,
            product_type=preview.product_type,
            price=parsed_price,
            currency=resolved_currency,
            image_count=next_image_count,
            image_urls=next_image_urls,
            image_asset_ids=next_image_asset_ids,
            variants=preview_variants,
            weight_grams=weight_grams,
            weight_source=weight_source,
            weight_match_keyword=weight_match_keyword,
            weight_value=weight_value,
            weight_unit=weight_unit,
            status=status,
            deleted_at=None,
        )
        existing_by_handle[existing.handle] = existing
        existing_by_url[existing.url] = existing
        return 0, 1, int(existing.id)

    def _prepare_image_asset_cache(self, previews: list) -> dict[str, Any]:
        """Preload image assets for the whole source in DB-friendly batches."""
        all_urls = list(
            dict.fromkeys(
                url
                for preview in previews
                for url in (preview.image_urls or [])
                if url
            )
        )
        if not all_urls:
            return {}

        asset_cache: dict[str, Any] = {}
        for start in range(0, len(all_urls), self.IMAGE_ASSET_BATCH_SIZE):
            batch_urls = all_urls[start : start + self.IMAGE_ASSET_BATCH_SIZE]
            for asset in self.image_repo.ensure_assets(batch_urls):
                asset_cache[asset.source_url] = asset
        return asset_cache

    def sync_source_products(
        self,
        source_id: int,
        previews: list,
        on_product_processed: Optional[Callable[[str | None, int, int], None]] = None,
    ) -> tuple[int, int]:
        weight_rules = self.weight_rule_service.get_matching_rules()
        existing_products = self.product_repo.get_by_source(
            source_id,
            skip=0,
            limit=100000,
            active_only=True,
        )
        existing_by_handle = {product.handle: product for product in existing_products if product.handle}
        existing_by_url = {product.url: product for product in existing_products if product.url}
        image_asset_cache = self._prepare_image_asset_cache(previews)
        created_for_source = 0
        updated_for_source = 0
        touched_product_ids: set[int] = set()
        total_previews = len(previews)
        for index, preview in enumerate(previews, start=1):
            created_delta, updated_delta, product_id = self._upsert_product_from_preview(
                source_id=source_id,
                preview=preview,
                existing_by_handle=existing_by_handle,
                existing_by_url=existing_by_url,
                image_asset_cache=image_asset_cache,
                weight_rules=weight_rules,
            )
            created_for_source += created_delta
            updated_for_source += updated_delta
            touched_product_ids.add(product_id)
            if on_product_processed:
                on_product_processed(preview.title, index, total_previews)

        # Any product from this source not seen in current sync should become unavailable.
        for product in existing_products:
            if int(product.id) in touched_product_ids:
                continue
            if str(product.status or "").strip().lower() == "unavailable":
                continue
            self.product_repo.update(product, status="unavailable")
            updated_for_source += 1

        return created_for_source, updated_for_source
