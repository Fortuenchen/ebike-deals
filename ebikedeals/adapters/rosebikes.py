"""rosebikes.de - Rose Bikes, eigener Spryker-Shop.

Produktkachel:

    <div class="catalog-product-tile ...">
      <a href="/p/<slug>-<id>"> ...
      <span class="product-tile-title__brand">Rose</span>
      <... class="product-tile-title">Rose Backroad FF GRX ...</...>
      <span class="product-tile-price__current-value">4.000,00 €</span>
      <span class="product-tile-price__old-value">4.500,00 €</span>   (Prefix "statt")

12 Produkte je Seite (?page=N). Die Sale-Kategorie mischt E-Bike und Fahrrad,
daher wird der Typ inhaltlich bestimmt (bike_type_hint = ""). Rabatt kommt aus
statt-Preis vs. aktuellem Preis - der eigene Schwellenfilter trennt die echten
Reduzierungen heraus (das "42" auf der Kachel ist die Zahl der Bewertungen, kein
Rabatt).
"""

from __future__ import annotations

from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing


class RoseBikes(Adapter):
    key = "rose"
    name = "rosebikes.de"
    # Sale über alle Radgattungen (E-Bike + Fahrrad); ä ist url-kodiert.
    source_url = "https://www.rosebikes.de/sale/fahrr%C3%A4der"
    bike_type_hint = ""  # gemischt -> classify_bike_type entscheidet je Angebot

    @staticmethod
    def page_url(base: str, page: int) -> str:
        if page <= 1:
            return base
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}page={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [
                self._to_offer(n) for n in doc.walk() if n.has_class("catalog-product-tile")
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, box: Node) -> Offer | None:
        link = None
        for a in box.find_all("a"):
            if (a.get("href") or "").startswith("/p/"):
                link = a
                break
        if link is None:
            return None

        price = parse_price(first_text(box, "product-tile-price__current-value"))
        if price is None:
            return None
        list_price = parse_price(first_text(box, "product-tile-price__old-value"))

        brand = first_text(box, "product-tile-title__brand")
        title = first_text(box, "product-tile-title") or link.get("title") or ""
        img = box.find("img")
        return Offer(
            shop=self.key,
            title=title.strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price,
            brand=brand,
            image=image_url(img),
        )
