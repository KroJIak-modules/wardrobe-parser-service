"""XML parsing utilities for Shopify sitemaps."""

import logging
import xml.etree.ElementTree as ET
from typing import Iterator

LOGGER = logging.getLogger(__name__)


class ShopifyXMLParser:
    """Parse Shopify XML sitemaps."""

    @staticmethod
    def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
        """
        Parse root sitemap.xml.

        Returns: (product_sitemap_urls, direct_product_urls)
        """
        product_sitemaps: list[str] = []
        direct_product_urls: list[str] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            LOGGER.warning(f"Failed to parse sitemap XML: {exc}")
            return product_sitemaps, direct_product_urls

        # Extract sitemap and direct loc URLs from root
        for url_elem in root.iter():
            tag_local = ShopifyXMLParser._xml_local_name(url_elem.tag)

            if tag_local == "sitemap":
                # <sitemap><loc>...</loc></sitemap>
                for child in url_elem:
                    if ShopifyXMLParser._xml_local_name(child.tag) == "loc":
                        if child.text:
                            url = child.text.strip()
                            if url:
                                product_sitemaps.append(url)
                        break

            elif tag_local == "url":
                # Direct <url><loc>...</loc></url> (not in <image:image>)
                for child in url_elem:
                    if ShopifyXMLParser._xml_local_name(child.tag) == "loc":
                        if child.text:
                            url = child.text.strip()
                            if url:
                                direct_product_urls.append(url)
                        break

        return product_sitemaps, direct_product_urls

    @staticmethod
    def extract_loc_urls(xml_text: str) -> Iterator[str]:
        """Extract all <loc> URLs from product sitemap (XML format)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return

        for url_elem in root.iter():
            if ShopifyXMLParser._xml_local_name(url_elem.tag) != "url":
                continue

            for child in url_elem:
                if ShopifyXMLParser._xml_local_name(child.tag) != "loc":
                    continue
                if child.text:
                    value = child.text.strip()
                    if value:
                        yield value
                break

    @staticmethod
    def _xml_local_name(tag: str) -> str:
        """Strip XML namespace prefix."""
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag
