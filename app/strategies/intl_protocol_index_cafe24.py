from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger


class IntlProtocolIndexCafe24Strategy:
    name = "intl_protocol_index_cafe24"
    _ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    _ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    def run(self, context: StrategyContext) -> list[dict]:
        logger = RunLogger(context.run_id)
        cfg = context.source.source_config
        timeout = int((cfg.get("timeouts") or {}).get("product_sec", 12))
        workers = max(1, int(cfg.get("intl_protocol_index_workers") or 6))
        max_products = int((cfg.get("shopify_sitemap") or {}).get("max_products", 50000))
        category_max_pages = max(1, int(cfg.get("intl_protocol_index_category_max_pages") or 12))
        base_url = context.source.source_url.rstrip("/")

        product_urls = self._discover_product_urls(
            base_url=base_url,
            timeout=timeout,
            limit=max_products,
            category_max_pages=category_max_pages,
            logger=logger,
        )
        logger.strategy_event("progress", self.name, stage="discover_done", discovered=len(product_urls))
        out: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._fetch_one, url, timeout): url for url in product_urls}
            done = 0
            for fut in as_completed(futures):
                done += 1
                url = futures[fut]
                try:
                    out.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    logger.strategy_event("progress", self.name, stage="fetch_skip", url=url, reason=str(exc))
                if done % 10 == 0 or done == len(product_urls):
                    logger.strategy_event("progress", self.name, stage="fetch_progress", processed=f"{done}/{len(product_urls)}", parsed=len(out))

        context.diagnostics.update(
            {
                "candidate_urls": len(product_urls),
                "mapped_products": len(out),
                "workers": workers,
            }
        )
        logger.strategy_event("progress", self.name, stage="run_done", parsed=len(out), discovered=len(product_urls))
        return out

    def _discover_product_urls(
        self,
        *,
        base_url: str,
        timeout: int,
        limit: int,
        category_max_pages: int,
        logger: RunLogger,
    ) -> list[str]:
        # Union of sources:
        # 1) sitemap product URLs (fast baseline)
        # 2) category pagination crawl (captures URLs missing from sitemap)
        seen: set[str] = set()
        out: list[str] = []

        for u in self._discover_product_urls_from_sitemap(base_url=base_url, timeout=timeout):
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                return out
        logger.strategy_event("progress", self.name, stage="discover_sitemap_done", discovered=len(out))

        for u in self._discover_product_urls_from_categories(
            base_url=base_url,
            timeout=timeout,
            max_pages=category_max_pages,
            logger=logger,
        ):
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                break
        return out

    def _discover_product_urls_from_sitemap(self, *, base_url: str, timeout: int) -> list[str]:
        sm_url = urljoin(base_url + "/", "sitemap.xml")
        resp = requests.get(sm_url, timeout=timeout, headers={"User-Agent": self._ua})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        locs = [n.text.strip() for n in root.findall(".//sm:loc", self._ns) if n.text]
        return [u for u in locs if "/product/" in u]

    def _discover_product_urls_from_categories(
        self,
        *,
        base_url: str,
        timeout: int,
        max_pages: int,
        logger: RunLogger,
    ) -> list[str]:
        shop_home = self._resolve_shop_home(base_url)
        origin = f"{urlparse(shop_home).scheme}://{urlparse(shop_home).netloc}"
        headers = {"User-Agent": self._ua, "Referer": shop_home}

        # Get category ids from shop home menu.
        home = requests.get(shop_home, timeout=timeout, headers=headers)
        home.raise_for_status()
        cate_ids = self._extract_category_ids(home.text)
        logger.strategy_event("progress", self.name, stage="discover_categories", categories=len(cate_ids))
        if not cate_ids:
            return []

        found: set[str] = set()
        pattern = re.compile(r"/shop2/product/[^\"']+?/\d+/?")

        for idx, cate in enumerate(cate_ids, start=1):
            page_no_new = 0
            for page in range(1, max_pages + 1):
                list_url = f"{origin}/shop2/product/list.html?cate_no={cate}&page={page}"
                try:
                    r = requests.get(list_url, timeout=timeout, headers=headers)
                    if r.status_code >= 400:
                        break
                    links = {urljoin(origin, m) for m in pattern.findall(r.text)}
                    before = len(found)
                    found.update(links)
                    added = len(found) - before
                    if added == 0:
                        page_no_new += 1
                    else:
                        page_no_new = 0
                    if page_no_new >= 2:
                        break
                except Exception:
                    break
            if idx % 3 == 0 or idx == len(cate_ids):
                logger.strategy_event(
                    "progress",
                    self.name,
                    stage="discover_category_progress",
                    processed=f"{idx}/{len(cate_ids)}",
                    found=len(found),
                )
        return sorted(found)

    @staticmethod
    def _resolve_shop_home(base_url: str) -> str:
        # intl-protocol-index.com storefront routes to protocolindex.cafe24.com/shop2/
        parsed = urlparse(base_url)
        if "protocolindex.cafe24.com" in parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/shop2/"
        return "https://protocolindex.cafe24.com/shop2/"

    @staticmethod
    def _extract_category_ids(html: str) -> list[int]:
        ids: set[int] = set()
        for raw in re.findall(r"/product/list\.html\?cate_no=(\d+)", html):
            try:
                ids.add(int(raw))
            except Exception:
                continue
        # Keep deterministic order.
        return sorted(ids)

    def _fetch_one(self, url: str, timeout: int) -> dict:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": self._ua})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        title = self._extract_title(soup)
        price = self._extract_price(soup)
        images = self._extract_images(soup, url)
        variants = self._extract_variants(soup, price)
        handle = self._extract_handle(url)

        return {
            "url": url,
            "handle": handle,
            "title": title,
            "description": self._extract_description(soup),
            "vendor": "",
            "product_type": "",
            "price": price,
            "currency": "USD",
            "image_url": images[0] if images else "",
            "images": images,
            "variants": variants,
            "tags": [],
        }

    @staticmethod
    def _extract_handle(url: str) -> str:
        tail = url.rstrip("/").split("/")[-2:]
        if len(tail) >= 2:
            return tail[-2].strip().lower()
        return url.rstrip("/").split("/")[-1].strip().lower()

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        og = soup.select_one("meta[property='og:title']")
        if og and (og.get("content") or "").strip():
            return og.get("content").strip()
        title = soup.select_one("title")
        return title.get_text(" ", strip=True) if title else ""

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str | None:
        og = soup.select_one("meta[property='og:description']")
        if og and (og.get("content") or "").strip():
            return og.get("content").strip()
        node = soup.select_one(".infoArea")
        return node.get_text("\n", strip=True)[:4000] if node else None

    @staticmethod
    def _extract_price(soup: BeautifulSoup) -> float | None:
        selectors = [".xans-product-detail .price", ".prd_price", "[class*='price']"]
        for sel in selectors:
            for n in soup.select(sel)[:30]:
                txt = n.get_text(" ", strip=True).replace(",", "")
                m = re.search(r"([0-9]+(?:\\.[0-9]+)?)", txt)
                if not m:
                    continue
                try:
                    v = float(m.group(1))
                except Exception:
                    continue
                if v > 0:
                    return v
        return None

    @staticmethod
    def _extract_images(soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        for im in soup.select("img"):
            src = (im.get("src") or "").strip()
            if not src:
                continue
            if src.startswith("//"):
                src = f"https:{src}"
            elif src.startswith("/"):
                src = urljoin(page_url, src)
            low = src.lower()
            if "/web/product/" not in low and "cdn" not in low:
                continue
            urls.append(src)
        seen: set[str] = set()
        out: list[str] = []
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
        return out[:30]

    @staticmethod
    def _extract_variants(soup: BeautifulSoup, price: float | None) -> list[dict]:
        variants: list[dict] = []
        for opt in soup.select("select option"):
            text = opt.get_text(" ", strip=True)
            if not text:
                continue
            lowered = text.lower()
            if "please select" in lowered or "select options" in lowered or "required" in lowered:
                continue
            if text.startswith("---") or text.startswith("- "):
                continue
            variants.append(
                {
                    "id": None,
                    "title": text,
                    "option1": text,
                    "option2": None,
                    "option3": None,
                    "sku": None,
                    "available": True,
                    "inventory_quantity": None,
                    "price": price,
                    "compare_at_price": None,
                    "currency_code": "USD",
                }
            )
        if not variants:
            variants.append(
                {
                    "id": None,
                    "title": "Default",
                    "option1": None,
                    "option2": None,
                    "option3": None,
                    "sku": None,
                    "available": bool(price is not None),
                    "inventory_quantity": None,
                    "price": price,
                    "compare_at_price": None,
                    "currency_code": "USD",
                }
            )
        return variants
