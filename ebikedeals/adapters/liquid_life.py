"""liquid-life.de - Shopify, aber /products.json ist gesperrt, daher HTML-Scrape
der product-card-Kacheln (Theme mit Custom-Elementen).

    <div class="product-card">
      <a class="product-card__vendor">Haibike</a>                 <- Marke
      <a class="product-card__title" href="/products/...">All-Mountain CF 10 …</a>
      <sale-price class="text-on-sale">6.799,00 €*</sale-price>   <- aktueller Preis
      <span class="line-through">8.000,00 €</span>                <- UVP/Streichpreis
      <span class="product-card__variant">S</span> …              <- Größen

E-Bike-Sale-Kategorie -> bike_type_hint bleibt "ebike".
"""

from __future__ import annotations

from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, dedup_sizes, looks_like_size, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing


class LiquidLife(Adapter):
    key = "liquidlife"
    name = "liquid-life.de"
    source_url = "https://www.liquid-life.de/collections/e-bike-sale"

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page <= 1 else f"{base}?page={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.has_class("product-card")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, box: Node) -> Offer | None:
        link = next(
            (a for a in box.find_all("a") if "/products/" in (a.get("href") or "")), None
        )
        if link is None:
            return None

        sale = box.find("sale-price") or box.find(cls="text-on-sale")
        price = parse_price(sale.text) if sale is not None else None
        if price is None:
            return None
        old = box.find(cls="line-through")
        list_price = parse_price(old.text) if old is not None else None

        brand = first_text(box, "product-card__vendor")
        title = first_text(box, "product-card__title") or (link.text or "").strip()
        sizes = dedup_sizes(
            v.text for v in box.find_all(cls="product-card__variant") if looks_like_size(v.text)
        )
        img = box.find("img")
        return Offer(
            shop=self.key,
            title=f"{brand} {title}".strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price if (list_price and list_price > price) else None,
            brand=brand,
            sizes=sizes,
            image=image_url(img),
        )
