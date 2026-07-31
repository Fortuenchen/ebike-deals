"""bunnyhop.de - e-vendo-Shop (Legacy-System).

Kachel ``<article class="item">``:

    <span class="name">Giant AnyTour E+ 3 RT Eclipse</span>   <- Titel (weitere .name = Größen)
    <a class="prodlink" href="FAHRRAD/E-BIKE/...">             <- relativer Produktlink
    <span class="amount">3.799,00</span> (UVP, 2x) …
    <span class="amount">2.599,99</span>                      <- aktueller Preis (niedrigster)
    <span class="percent">31</span>                           <- Rabatt %

Paginierung ``?…&Start=<offset>`` mit 120 Artikeln je Seite. Der URL-Pfad der
Produkte (…/E-BIKE/…) weist E-Bikes aus; bike_type_hint bleibt "ebike".
"""

from __future__ import annotations

from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, dedup_sizes, looks_like_size, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing

_PER_PAGE = 120


class BunnyHop(Adapter):
    key = "bunnyhop"
    name = "bunnyhop.de"
    source_url = "https://www.bunnyhop.de/E-Bike-Sale.htm?a=catalog&p=1260"

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page <= 1 else f"{base}&Start={(page - 1) * _PER_PAGE}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [
                self._to_offer(n)
                for n in doc.walk()
                if n.tag == "article" and n.has_class("item")
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, tile: Node) -> Offer | None:
        link = tile.find(cls="prodlink")
        if link is None or not link.get("href"):
            return None
        # Mehrere .amount: UVP (höher, ggf. doppelt) + aktueller Preis (niedrigster).
        amounts = sorted(
            p for a in tile.find_all(cls="amount") if (p := parse_price(a.text)) and p > 50
        )
        if not amounts:
            return None
        price = amounts[0]
        list_price = amounts[-1] if len(amounts) > 1 and amounts[-1] > price else None

        title = first_text(tile, "name")
        if not title:
            return None
        sizes = dedup_sizes(
            n.text for n in tile.find_all(cls="name") if looks_like_size(n.text)
        )
        img = tile.find("img")
        return Offer(
            shop=self.key,
            title=title.strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price,
            sizes=sizes,
            image=image_url(img),
        )
