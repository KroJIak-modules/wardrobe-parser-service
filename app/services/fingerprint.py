"""
Fingerprint service for delta detection using SHA256.
"""

import hashlib
import json
from typing import Optional, Tuple

from app.models import ParserProduct, ProductStatus, DeltaType


class FingerprintService:
    """Service for computing and comparing product fingerprints."""

    @staticmethod
    def compute_fingerprint(
        title: str,
        price: Optional[float],
        image_count: int,
        status: str = ProductStatus.AVAILABLE,
    ) -> str:
        """
        Compute SHA256 fingerprint for product.

        Fingerprint includes:
        - title (normalized)
        - price
        - image_count
        - status

        Changes to any of these trigger delta detection.
        """
        data = {
            "title": title.strip().lower(),
            "price": price,
            "image_count": image_count,
            "status": status,
        }
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode()).hexdigest()

    @staticmethod
    def detect_delta(
        old_fingerprint: Optional[str],
        new_fingerprint: str,
        old_product: Optional[ParserProduct] = None,
        new_product_data: dict = None,
    ) -> Tuple[str, dict]:
        """
        Detect type of change between old and new product.

        Returns:
        - delta_type: DeltaType (new, updated, unchanged, deleted)
        - change_details: dict with old/new values
        """
        change_details = {}

        # NEW product
        if old_fingerprint is None:
            return DeltaType.NEW, change_details

        # UNCHANGED
        if old_fingerprint == new_fingerprint:
            return DeltaType.UNCHANGED, change_details

        # UPDATED - compute detailed changes
        if old_product and new_product_data:
            if old_product.price != new_product_data.get("price"):
                change_details["old_price"] = old_product.price
                change_details["new_price"] = new_product_data.get("price")

            if old_product.status != new_product_data.get("status"):
                change_details["old_status"] = old_product.status
                change_details["new_status"] = new_product_data.get("status")

            if old_product.image_count != new_product_data.get("image_count", 0):
                change_details["old_image_count"] = old_product.image_count
                change_details["new_image_count"] = new_product_data.get("image_count", 0)

        return DeltaType.UPDATED, change_details

    @staticmethod
    def extract_json_snapshot(product: ParserProduct) -> dict:
        """Extract product data for fingerprinting."""
        return {
            "title": product.title,
            "price": product.price,
            "image_count": product.image_count,
            "status": product.status,
        }
