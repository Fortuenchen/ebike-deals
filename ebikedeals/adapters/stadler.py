"""shop.zweirad-stadler.de - Zweirad Stadler, OXID eShop.

Outlet-Kacheln (``productBox``). Zwei Fallstricke:

* Das Outlet mischt Räder mit Bekleidung, Zubehör und Sportnahrung. Nur die
  eigentlichen Räder liegen unter ``/fahrrad-shop/`` - danach wird gefiltert.
* Die Outlet-Kategorien sind nicht typrein: ``/e-bikes/outlet/`` enthält auch
  reguläre Räder (z. B. ein Gravelbike). Daher ``bike_type_hint = ""`` und der
  Typ wird inhaltlich bestimmt.

Reduzierte Räder zeigen zwei ``priceSpan`` ("3.499.-" UVP durchgestrichen,
"2.492.-" aktuell) plus "X € gespart auf UVP"; ohne zweiten Preis liegt kein
Rabatt vor und der eigene Filter verwirft das Angebot.
"""

from __future__ import annotations

from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing


class ZweiradStadler(Adapter):
    key = "stadler"
    name = "zweirad-stadler.de"
    # Beide Outlet-Kategorien sind gemischt (E-Bike + Fahrrad) -> inhaltlich.
    source_url = "https://shop.zweirad-stadler.de/e-bikes/outlet/"
    extra_urls = ["https://shop.zweirad-stadler.de/fahrraeder/outlet/"]
    bike_type_hint = ""

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page <= 1 else f"{base}?pgNr={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.has_class("productBox")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, box: Node) -> Offer | None:
        link = box.find("a")
        href = (link.get("href") if link is not None else "") or ""
        # Nur echte Räder: das Outlet mischt Bekleidung/Zubehör/Sportnahrung.
        if "/fahrrad-shop/" not in href:
            return None
        title = first_text(box, "productTitle")
        if not title:
            return None

        # Preis(e) aus den priceSpans; >100 verwirft Leasing-/Grundpreis-Rauschen.
        prices = sorted(
            p for span in box.find_all(cls="priceSpan")
            if (p := parse_price(span.own_text or span.text)) and p > 100
        )
        if not prices:
            return None
        price = prices[0]
        list_price = prices[-1] if len(prices) > 1 and prices[-1] > price else None

        img = box.find("img")
        return Offer(
            shop=self.key,
            title=title.strip(),
            url=self.abs_url(href),
            price=price,
            list_price=list_price,
            brand=first_text(box, "productManufacturer"),
            image=image_url(img),
        )
