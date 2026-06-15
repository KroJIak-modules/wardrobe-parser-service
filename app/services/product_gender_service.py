from __future__ import annotations

import re
import unicodedata


class ProductGenderService:
    _ALLOWED = {"male", "female", "unisex"}
    _DEFAULT = "unisex"
    _UNISEX_KEYWORDS = (
        "unisex",
        "унисекс",
        "ユニセックス",
    )
    _FEMALE_KEYWORDS = (
        "women",
        "womens",
        "womenswear",
        "woman",
        "female",
        "ladies",
        "lady",
        "girl",
        "girls",
        "wms",
        "femme",
        "donna",
        "жен",
        "zhen",
    )
    _MALE_KEYWORDS = (
        "men",
        "mens",
        "menswear",
        "man",
        "male",
        "homme",
        "uomo",
        "муж",
        "muzh",
    )

    @classmethod
    def infer(cls, *, normalized_product: dict, raw_product: dict | None = None, source_key: str = "") -> str:
        raw = raw_product if isinstance(raw_product, dict) else {}
        stages: tuple[list[str], ...] = (
            cls._coerce_text_list(normalized_product.get("tags")),
            cls._coerce_text_list([normalized_product.get("category")]),
            cls._coerce_text_list([normalized_product.get("title")]),
            cls._coerce_text_list(
                [
                    normalized_product.get("description"),
                    normalized_product.get("description_html"),
                ]
            ),
            cls._source_specific_texts(raw_product=raw, source_key=source_key),
        )
        for texts in stages:
            resolved = cls._resolve_stage(texts)
            if resolved is not None:
                return resolved
        return cls._DEFAULT

    @classmethod
    def normalize(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in cls._ALLOWED else cls._DEFAULT

    @classmethod
    def _source_specific_texts(cls, *, raw_product: dict, source_key: str) -> list[str]:
        hints = raw_product.get("source_gender_hints") if isinstance(raw_product.get("source_gender_hints"), dict) else {}
        if source_key == "grailed.com":
            return cls._coerce_text_list(
                [
                    hints.get("department"),
                    hints.get("category_path"),
                ]
            )
        if source_key == "vinted.com":
            return cls._coerce_text_list(
                [
                    hints.get("root_breadcrumb_title"),
                    hints.get("root_breadcrumb_href"),
                ]
            )
        return []

    @classmethod
    def _resolve_stage(cls, texts: list[str]) -> str | None:
        seen: set[str] = set()
        for text in texts:
            resolved = cls._resolve_text(text)
            if resolved is not None:
                seen.add(resolved)
        if not seen:
            return None
        if "unisex" in seen:
            return "unisex"
        if seen == {"male"}:
            return "male"
        if seen == {"female"}:
            return "female"
        return None

    @classmethod
    def _resolve_text(cls, text: str) -> str | None:
        normalized = cls._normalize_text(text)
        if not normalized:
            return None
        if cls._contains_any(normalized, cls._UNISEX_KEYWORDS):
            return "unisex"
        has_female = cls._contains_any(normalized, cls._FEMALE_KEYWORDS)
        has_male = cls._contains_any(normalized, cls._MALE_KEYWORDS)
        if has_female and not has_male:
            return "female"
        if has_male and not has_female:
            return "male"
        return None

    @staticmethod
    def _coerce_text_list(values: object) -> list[str]:
        if isinstance(values, (str, bytes)):
            values = [values]
        if not isinstance(values, list):
            return []
        out: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text:
                out.append(text)
        return out

    @staticmethod
    def _normalize_text(value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
        return f" {re.sub(r'\\s+', ' ', text).strip()} "

    @staticmethod
    def _contains_any(normalized_text: str, keywords: tuple[str, ...]) -> bool:
        return any(f" {keyword} " in normalized_text for keyword in keywords)
