"""shop.zweirad-stadler.de - Zweirad Stadler, OXID eShop.

Einstieg über die **volle E-Bike-Kategorie als Artikelliste** (``cl=alist``,
96 Artikel je Seite) statt des winzigen Outlets - das Outlet bestand fast nur
aus Bekleidung/Zubehör/Sportnahrung (~2 Räder je Seite), die volle Kategorie
enthält alle E-Bikes und unser Rabattfilter zieht die Reduzierten heraus.

Kachel ``productBox``:
    productTitle / productManufacturer
    zwei ``priceSpan`` ("3.499.-" UVP durchgestrichen, "2.492.-" aktuell) -
    ohne zweiten Preis liegt kein Rabatt vor.

Paginierung ist **0-basiert** über ``pgNr`` (pgNr=0 = Seite 1). Der
``/fahrrad-shop/``-Filter bleibt als Sicherung gegen versprengtes Nicht-Rad.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing


class ZweiradStadler(Adapter):
    key = "stadler"
    name = "zweirad-stadler.de"
    source_url = (
        "https://shop.zweirad-stadler.de/fahrrad-shop/e-bikes/"
        "?cl=alist&ldtype=infogrid&_artperpage=96&pgNr=0"
    )
    bike_type_hint = "ebike"  # typreine E-Bike-Kategorie

    @staticmethod
    def page_url(base: str, page: int) -> str:
        # Stadler/OXID paginiert 0-basiert über pgNr (pgNr=0 = Seite 1).
        return re.sub(r"pgNr=\d+", f"pgNr={page - 1}", base)

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.has_class("productBox")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, box: Node) -> Offer | None:
        link = box.find("a")
        href = (link.get("href") if link is not None else "") or ""
        # Sicherung: nur echte Räder (Outlet-Altlast; die Kategorie ist sauber).
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
