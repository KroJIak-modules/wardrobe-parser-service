from __future__ import annotations

import re
from html import unescape

from bs4 import BeautifulSoup


class DescriptionTextService:
    @staticmethod
    def normalize(raw: object) -> str | None:
        original_text = str(raw or "").strip()
        text = original_text
        if not text:
            return None

        try:
            text = unescape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
            if DescriptionTextService._looks_like_html(text):
                text = DescriptionTextService._html_to_text(text)
            else:
                text = DescriptionTextService._markdown_to_text(text)
            text = DescriptionTextService._cleanup_spacing(text)
            return text or None
        except Exception:
            fallback = DescriptionTextService._cleanup_spacing(
                original_text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
            )
            return fallback or None

    @staticmethod
    def _looks_like_html(text: str) -> bool:
        return bool(re.search(r"<[a-zA-Z][^>]*>", text))

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()

        # Remove common translator overlays/noise blocks.
        for node in soup.find_all(
            attrs={
                "id": re.compile(r"(gtx|translate|translator)", re.I),
            }
        ):
            node.decompose()
        for node in soup.find_all(
            attrs={
                "class": re.compile(r"(gtx|translate|translator)", re.I),
            }
        ):
            node.decompose()

        # Keep paragraph structure readable.
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag_name in ("p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"):
            for node in soup.find_all(tag_name):
                if node.text.strip():
                    node.insert_before("\n")
                    node.insert_after("\n")

        text = soup.get_text("\n")
        return DescriptionTextService._markdown_to_text(text)

    @staticmethod
    def _markdown_to_text(text: str) -> str:
        out = text
        out = re.sub(r"!\[[^\]]*]\(([^)]*)\)", "", out)  # images
        out = re.sub(r"\[([^\]]+)]\(([^)]*)\)", r"\1", out)  # links
        out = re.sub(r"<(https?://[^>]+)>", r"\1", out)  # autolinks
        out = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", out)  # headings
        out = re.sub(r"(?m)^\s*>\s?", "", out)  # blockquote markers
        out = re.sub(r"(?m)^\s*[-*+]\s+", "• ", out)  # unordered list markers
        out = re.sub(r"(?m)^\s*\d+\.\s+", "• ", out)  # ordered list markers
        out = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", out)  # emphasis
        out = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", out)  # inline/code fences content
        out = out.replace("---", "\n").replace("***", "\n")
        return out

    @staticmethod
    def _cleanup_spacing(text: str) -> str:
        normalized = text.replace("\t", " ")
        normalized = re.sub(r"[ \u200b\u200c\u200d]+", " ", normalized)
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)

        lines = [re.sub(r"\s+", " ", line).strip() for line in normalized.split("\n")]
        paragraphs: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            if not buffer:
                return
            paragraph = " ".join(buffer).strip()
            if paragraph:
                paragraphs.append(paragraph)
            buffer.clear()

        for line in lines:
            if not line:
                flush()
                continue
            if line.startswith("• "):
                flush()
                paragraphs.append(line)
                continue
            buffer.append(line)
        flush()
        return "\n\n".join(paragraphs).strip()
