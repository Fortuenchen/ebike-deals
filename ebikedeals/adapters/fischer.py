"""fischer-bike.com - FISCHER, Shopware-5-Shop (Outlet/Sale).

Wie rad1 ein Shopware-5-Listing, aber mit eigenen Preis-Klassen:

    <div class="product--box box--emotion">
      <a class="product--title" href="...">Titel</a>
      <span class="product--subtitle">Farbe, 28 Zoll, RH 44 cm ...</span>
      <span class="price--default-values">699,00 € *</span>    <- aktueller Preis
      <span class="price--discount is--nowrap">1.399,00 € *</span>  <- Streichpreis/UVP

FISCHER ist ein E-Bike-Hersteller; das Outlet ist entsprechend E-Bike-lastig
(bike_type_hint bleibt "ebike"). Rahmenhöhen stehen im Untertitel, der Rest der
Größen kommt bei Bedarf aus der Anreicherung.
"""

from __future__ import annotations

from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, image_url, paged_listing


class FischerBike(Adapter):
    key = "fischer"
    name = "fischer-bike.com"
    source_url = "https://fischer-bike.com/de-de/outlet-sale/e-bikes-outlet/"

    @staticmethod
    def page_url(base: str, page: int) -> str:
        # Shopware 5 paginiert über ?p=N; Seite 1 ohne Parameter.
        return base if page <= 1 else f"{base}?p={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.has_class("product--box")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, box: Node) -> Offer | None:
        link = box.find(cls="product--title")
        if link is None or not link.get("href"):
            return None

        cur = box.find(cls="price--default-values")
        price = parse_price(cur.text) if cur is not None else None
        if price is None:
            return None
        # price--discount trägt hier den (höheren) Streich-/UVP-Preis.
        old = box.find(cls="price--discount")
        list_price = parse_price(old.text) if old is not None else None

        img = box.find("img")
        return Offer(
            shop=self.key,
            title=(link.get("title") or link.text or "").strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price if (list_price and list_price > price) else None,
            image=image_url(img),
        )
