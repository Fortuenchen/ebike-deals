"""Magento 2 shops - fahrrad24.de, fahrradlagerverkauf.com.

Magento renders machine-readable prices on every listing tile:

    <div class="price-box" data-role="priceBox" data-product-id="138532">
      <span data-price-amount="1590" data-price-type="finalPrice">
      <span data-price-amount="3499" data-price-type="oldPrice">

so no currency parsing is needed. Sizes are not on the listing tile - they are
filled in later from the product page by the size enricher.
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from ..htmlutil import Node, parse, script_blocks
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, nearest_product_link, paged_listing


class MagentoAdapter(Adapter):
    def page_url(self, base: str, page: int) -> str:
        base = re.sub(r"[?&]p=\d+", "", base)
        if page <= 1:
            return base
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}p={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            stock = _availability_by_url(html)
            return [
                self._to_offer(n, stock)
                for n in doc.walk()
                if n.get("data-role") == "priceBox"
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    # ------------------------------------------------------------------
    def _to_offer(self, box: Node, stock: dict[str, bool] | None = None) -> Offer | None:
        final_price = old_price = None
        for el in box.walk():
            amount = el.get("data-price-amount")
            if not amount:
                continue
            kind = el.get("data-price-type")
            value = parse_price(amount)
            if kind == "finalPrice" and final_price is None:
                final_price = value
            elif kind == "oldPrice" and old_price is None:
                old_price = value
        if final_price is None:
            return None

        href, title = nearest_product_link(box)
        if not href:
            return None

        container = box.parent
        brand = ""
        for _ in range(6):
            if container is None:
                break
            b = container.find(cls="cs-product-tile__brand-text") or container.find(cls="product-brand")
            if b is not None:
                brand = b.text
                break
            container = container.parent

        url = self.abs_url(href)
        in_stock = (stock or {}).get(url.split("?")[0])
        return Offer(
            shop=self.key,
            title=(title or "").strip(),
            url=url,
            price=final_price,
            list_price=old_price,
            brand=brand,
            in_stock=in_stock,
            availability=(
                "" if in_stock is None else ("verfügbar" if in_stock else "nicht auf Lager")
            ),
        )


def _availability_by_url(html: str) -> dict[str, bool]:
    """url -> in stock, from the listing's JSON-LD.

    The price tiles carry no stock marker, so a listing that also shows sold-out
    products would otherwise report them as live offers. Every fahrrad24 product
    is InStock today; this keeps that from silently changing.
    """
    out: dict[str, bool] = {}
    for block in script_blocks(html, "application/ld+json"):
        try:
            data = json.loads(block)
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            url = (item.get("url") or "").split("?")[0]
            offers = item.get("offers")
            for off in offers if isinstance(offers, list) else [offers]:
                if isinstance(off, dict) and url:
                    availability = str(off.get("availability") or "")
                    if availability:
                        out[url] = "outofstock" not in availability.lower()
    return out


class Fahrrad24(MagentoAdapter):
    key = "fahrrad24"
    name = "fahrrad24.de"
    source_url = "https://www.fahrrad24.de/e-bikes/super-e-bike-sale.html"
    # "Super E-Bike Sale" is a curated selection, not the list of everything
    # reduced: 89 products against 474 in the full category, and 31 offers
    # above 50 % exist only outside it - including a 64 % Corwen F750 MTB.
    extra_urls = ["https://www.fahrrad24.de/e-bikes.html"]
    #: the full category runs to ~475 products at 37 per page
    page_budget = 15


class Fahrradlagerverkauf(MagentoAdapter):
    key = "lagerverkauf"
    name = "fahrradlagerverkauf.com"
    source_url = "https://www.fahrradlagerverkauf.com/e-bikes"
