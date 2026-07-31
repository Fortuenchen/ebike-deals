"""canyon.com - Canyon, Salesforce Commerce Cloud (Demandware).

Direktvertrieb, kein Bot-Schutz. Produktkachel trägt ``data-pid``:

    <... data-pid="...">
      <a class="productTileDefault__productName" href="...">Pathlite:ON 6 SUV</a>
      <span class="productTile__priceSale">2.399 €</span>       <- aktueller Preis
      <span class="productTile__priceOriginal">3.799 €</span>   <- UVP/Streichpreis
      <span class="productBadge__text">-37%</span>

Paginierung SFCC-typisch über ``?start=<offset>&sz=24`` (Offset, nicht Seite).
Das Outlet ``/fahrrad-outlet/e-bikes/`` ist E-Bike-rein (bike_type_hint "ebike").
"""

from __future__ import annotations

import re
from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_percent, parse_price
from ..net import Fetcher
from .base import Adapter, first_text, image_url, paged_listing

_PAGE = 24


class Canyon(Adapter):
    key = "canyon"
    name = "canyon.com"
    source_url = (
        "https://www.canyon.com/de-de/fahrrad-outlet/e-bikes/"
        "?srule=sort-by-discount&start=0&sz=24"
    )

    @staticmethod
    def page_url(base: str, page: int) -> str:
        start = (page - 1) * _PAGE
        if "start=" in base:
            return re.sub(r"start=\d+", f"start={start}", base)
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}start={start}&sz={_PAGE}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [self._to_offer(n) for n in doc.walk() if n.get("data-pid")]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, tile: Node) -> Offer | None:
        link = tile.find(cls="productTileDefault__productName")
        if link is None or not link.get("href"):
            return None
        price = parse_price(first_text(tile, "productTile__priceSale"))
        if price is None:
            return None
        list_price = parse_price(first_text(tile, "productTile__priceOriginal"))

        # Rabatt-Badge ("-37%") als Rückfall, falls kein UVP dasteht.
        badge = None
        for n in tile.walk():
            if "productBadge__text" in (n.get("class") or "") and "%" in (n.own_text or ""):
                badge = parse_percent(n.own_text)
                break

        img = tile.find("img")
        return Offer(
            shop=self.key,
            title=(link.text or link.get("title") or "").strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price if (list_price and list_price > price) else None,
            image=image_url(img),
            shop_discount_pct=badge,
        )
