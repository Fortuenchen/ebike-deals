"""littlejohnbikes.de - Little John Bikes.

Custom-Frontend (Tailwind-Utility-Klassen) hinter Cloudflare. Der Zugang braucht
den Chrome-TLS-Fingerabdruck (curl_cffi / env IMPERSONATE), den die Pipeline
ohnehin setzt - ein reiner httpx-Abruf bekommt 403. Kein JS nötig, die Produkte
stehen server-seitig im HTML.

Weil die Klassen reine Utility-Klassen sind, wird an *Struktur* verankert, nicht
an Klassennamen: jedes reduzierte Produkt hat genau ein ``<span class="line-through">``
(UVP). Von dort hoch zur Kachel (erster Vorfahr mit einem ``/produkt/``-Link);
der aktuelle Preis ist der 2-Dezimal-Betrag, der nicht der Streichpreis ist.

Offset-Paginierung (``?offset=N``, 12/Seite). Auf Wunsch die ersten 6 Seiten
(nach Rabatt sortiert - danach fallen die Rabatte unter die Schwelle).
"""

from __future__ import annotations

import re
from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, parse_price
from ..net import Fetcher
from .base import Adapter, fetch_page, image_url

_PER_PAGE = 12
_MAX_PAGES = 6

_PRICE = re.compile(r"\d[.,]\d{2}")


class LittleJohn(Adapter):
    key = "littlejohn"
    name = "littlejohnbikes.de"
    # /collection/sale mischt E-Bike und Fahrrad -> Typ inhaltlich bestimmen.
    source_url = (
        "https://littlejohnbikes.de/collection/sale"
        "?order=-discountPercentageBetweenZeroAndOne"
    )
    bike_type_hint = ""

    def pages_for(self, max_pages: int) -> int:
        return min(_MAX_PAGES, super().pages_for(max_pages))

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        seen: set[str] = set()
        for page in range(1, self.pages_for(max_pages) + 1):
            off = (page - 1) * _PER_PAGE
            url = self.source_url if off == 0 else f"{self.source_url}&offset={off}"
            html = fetch_page(fetcher, url, page)
            if html is None:
                break
            doc = parse(html)
            new = 0
            for lt in doc.find_all(cls="line-through"):
                tile = self._tile_of(lt)
                if tile is None:
                    continue
                offer = self._to_offer(tile, lt)
                if offer and offer.url not in seen:
                    seen.add(offer.url)
                    new += 1
                    yield offer
            if new == 0:
                break

    @staticmethod
    def _tile_of(lt: Node) -> Node | None:
        node = lt
        for _ in range(8):
            node = node.parent
            if node is None:
                return None
            if any(a.tag == "a" and "/produkt/" in (a.get("href") or "") for a in node.find_all("a")):
                return node
        return None

    def _to_offer(self, tile: Node, old_el: Node) -> Offer | None:
        prod = [a for a in tile.find_all("a") if "/produkt/" in (a.get("href") or "")]
        if not prod:
            return None
        list_price = parse_price(old_el.text)

        # Aktueller Preis: 2-Dezimal-Betrag > 50, der nicht der Streichpreis ist.
        price = None
        for n in tile.walk():
            if n.has_class("line-through"):
                continue
            tx = n.own_text or ""
            if _PRICE.search(tx):
                p = parse_price(tx)
                if p and p > 50 and (list_price is None or p < list_price):
                    price = p
                    break
        if price is None:
            return None

        title = max((re.sub(r"\s+", " ", (a.text or "")).strip() for a in prod), key=len, default="")
        slug = prod[0].get("href").split("/produkt/")[-1].split("/")[0]
        brand = slug.split("-")[0].title() if slug else ""
        if not title:
            title = slug.replace("-", " ").title()
        if brand and brand.lower() not in title.lower():
            title = f"{brand} {title}".strip()

        img = tile.find("img")
        return Offer(
            shop=self.key,
            title=title,
            url=self.abs_url(prod[0].get("href").split("?")[0]),
            price=price,
            list_price=list_price if (list_price and list_price > price) else None,
            brand=brand,
            image=image_url(img),
        )
