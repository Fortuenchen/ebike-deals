"""Shopware 6 shops - bike-angebot.de, denfeld.de, bike-discount.de.

All three share the stock listing markup:

    <div class="card product-box" data-product-information='{"name":...,"brand":...}'>
      <a class="product-image-link" href="...">
      <label class="product-detail-configurator-option-label" title="L">L</label>   <- sizes
      <div class="product-price-wrapper">
        <span class="product-price with-list-price">
          4.299,00 €                                   <- sale price (bare text node)
          <span class="list-price">
            <span class="list-price-price">UVP* 10.999,00 €</span>
            <span class="list-price-percentage">(23.09% gespart)</span>

The sale price is a bare text node next to the list-price element, which is why
`own_text` exists in htmlutil.
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, dedup_sizes, looks_like_size, parse_percent, parse_price
from ..net import Fetcher
from .base import Adapter, image_url, nearest_product_link, paged_listing


class Shopware6Adapter(Adapter):
    page_param = "p"

    def page_url(self, base: str, page: int) -> str:
        base = re.sub(rf"[?&]{self.page_param}=\d+", "", base)
        if page <= 1:
            # Keep page 1 free of a paging parameter: some shops disallow
            # query URLs in robots.txt, and the bare path is the same listing.
            return base
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{self.page_param}={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.has_class("product-box")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    # ------------------------------------------------------------------
    def _to_offer(self, box: Node) -> Offer | None:
        info = {}
        raw = box.get("data-product-information")
        if raw:
            try:
                info = json.loads(raw)
            except Exception:
                info = {}

        link_el = box.find(cls="product-image-link") or box.find(cls="product-name")
        href = link_el.get("href") if link_el is not None else ""
        title = ""
        if link_el is not None:
            title = link_el.get("title") or link_el.text
        if not href:
            href, title = nearest_product_link(box)
        if not href:
            return None
        title = (info.get("name") or title or "").strip()

        wrapper = box.find(cls="product-price-wrapper")
        if wrapper is None:
            return None
        price_el = wrapper.find(cls="product-price")
        if price_el is None:
            return None

        # Sale price: the bare text directly inside .product-price.
        price = parse_price(price_el.own_text)
        list_el = price_el.find(cls="list-price-price")
        list_price = parse_price(list_el.text) if list_el is not None else None
        pct_el = price_el.find(cls="list-price-percentage")
        shop_pct = parse_percent(pct_el.text) if pct_el is not None else None

        if price is None:
            # Some themes wrap the sale price in its own span.
            for cand in price_el.find_all("span"):
                if cand.has_class("list-price") or cand.has_class("list-price-price"):
                    continue
                price = parse_price(cand.own_text)
                if price:
                    break
        if price is None or (list_price and price >= list_price):
            if price is None:
                return None

        sizes = dedup_sizes(
            lbl.get("title") or lbl.text
            for lbl in box.find_all(cls="product-detail-configurator-option-label")
            if looks_like_size(lbl.get("title") or lbl.text)
        )

        img = box.find("img")
        return Offer(
            shop=self.key,
            title=title,
            url=self.abs_url(href),
            price=price,
            list_price=list_price,
            brand=(info.get("brand") or "").strip(),
            sizes=sizes,
            image=image_url(img),
            shop_discount_pct=shop_pct,
        )


class BikeAngebot(Shopware6Adapter):
    key = "bikeangebot"
    name = "bike-angebot.de"
    # The shop's own e-bike sale listing rather than the full e-bike category.
    source_url = "https://bike-angebot.de/hot-deals/e-bikes-im-sale"
    extra_urls = ["https://bike-angebot.de/e-bikes-pedelecs"]


class Denfeld(Shopware6Adapter):
    key = "denfeld"
    name = "denfeld.de"
    source_url = "https://www.denfeld.de/e-bikes/aktuelle-angebote/"


class MhwBike(Shopware6Adapter):
    key = "mhwbike"
    name = "mhw-bike.de"
    source_url = "https://mhw-bike.de/sale/e-bikes/"
    # "2. Wahl" are B-stock bikes - typically the deepest discounts on the site.
    extra_urls = ["https://mhw-bike.de/sale/2.-wahl/e-bikes/"]


class RadweltShop(Shopware6Adapter):
    key = "radwelt"
    name = "radwelt-shop.de"
    source_url = "https://www.radwelt-shop.de/sale/e-bike-sale/"


class BikeDiscount(Shopware6Adapter):
    key = "bikediscount"
    name = "bike-discount.de"
    # The URL from the brief carries ?properties=...&order=topseller, but
    # bike-discount's robots.txt has "Disallow: /*?" for all agents, so every
    # query variant - including pagination - is off limits. The bare category
    # path is explicitly allowed and lists the same products, so we use that
    # and accept that only the first page is reachable.
    source_url = "https://www.bike-discount.de/de/e-bike-kaufen"
