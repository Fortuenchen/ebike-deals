"""Shops with bespoke listing markup: fahrrad-xxl.de, radfieber.de, rad1.de."""

from __future__ import annotations

import json
import re
from typing import Iterator

from ..htmlutil import Node, parse, script_blocks
from ..model import Offer, dedup_sizes, looks_like_size, parse_percent, parse_price
from ..net import Fetcher
from .base import Adapter, paged_listing


class FahrradXXL(Adapter):
    """fahrrad-xxl.de - custom theme, German class names ('artikel').

    Card layout:
        <a artikelnr=".." href=".." class="fxxl-element-artikel__link">
          <div class="fxxl-element-artikel__brand">Cube</div>
          <div class="fxxl-element-artikel__title">..</div>
        <div class="fxxl-element-artikel__price-content">
          <div class="..__price--new">3.699,99 €</div>
          <div class="..__price--old"><span class="fxxl-strike-price">4.399,- €</span></div>
          <div class="..__price--discount">-15%</div>
    """

    key = "fahrradxxl"
    name = "fahrrad-xxl.de"
    # The sale category is the better entry point here - it yields twice the
    # hits of the full catalogue - but it is not a superset: a handful of
    # reduced bikes appear only in the general category, so both are scanned.
    source_url = "https://www.fahrrad-xxl.de/angebote/angebote-fahrraeder/e-bike-pedelec/"
    extra_urls = ["https://www.fahrrad-xxl.de/fahrraeder/e-bike/"]

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page == 1 else f"{base}?page={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            # Every card also carries "...--slider" (that is the per-card image
            # slider, not a carousel), so the class alone identifies a product.
            return [
                self._to_offer(n) for n in doc.walk() if n.has_class("fxxl-element-artikel")
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, card: Node) -> Offer | None:
        link = card.find(cls="fxxl-element-artikel__link")
        if link is None or not link.get("href"):
            return None

        prices = card.find(cls="fxxl-element-artikel__price-content")
        if prices is None:
            return None

        price = list_price = None
        shop_pct = None
        for el in prices.find_all():
            if el.has_class("fxxl-element-artikel__price--new") and price is None:
                price = parse_price(el.text)
            elif el.has_class("fxxl-element-artikel__price--old") and list_price is None:
                strike = el.find(cls="fxxl-strike-price")
                list_price = parse_price(strike.text if strike is not None else el.text)
            elif el.has_class("fxxl-element-artikel__price--discount") and shop_pct is None:
                shop_pct = parse_percent(el.text)
        if price is None:
            return None

        brand_el = card.find(cls="fxxl-element-artikel__brand")
        title_el = card.find(cls="fxxl-element-artikel__title")
        brand = brand_el.text if brand_el is not None else ""
        title = title_el.text if title_el is not None else link.get("title")
        img = card.find("img")

        # The listing prints the available frame sizes under "Größe(n):".
        sizes = dedup_sizes(
            el.text for el in card.find_all(cls="fxxl-element-artikel__variant-slider-size-item")
        )

        return Offer(
            shop=self.key,
            title=f"{brand} {title}".strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price,
            brand=brand,
            sizes=sizes,
            image=img.get("src") if img is not None else "",
            shop_discount_pct=shop_pct,
        )


class Radfieber(Adapter):
    """radfieber.de - OXID with a custom 'Zok' theme.

    Prices come from the card; sizes come free of charge from the page's
    JSON-LD ItemList, where each ProductGroup lists its hasVariant entries
    ("Schindelhauer EMILIA VI X20 S (45cm) / lavendelblau").
    """

    key = "radfieber"
    name = "radfieber.de"
    source_url = "https://www.radfieber.de/ebikes/sale/"

    @staticmethod
    def page_url(base: str, page: int) -> str:
        # Pagination is a path segment ("/ebikes/sale/2/"), not a query
        # parameter - ?pgNr= is silently ignored and returns page 1 forever.
        return base if page == 1 else f"{base.rstrip('/')}/{page}/"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            sizes_by_url = self._sizes_from_jsonld(html)
            doc = parse(html)
            return [
                self._to_offer(n, sizes_by_url)
                for n in doc.walk()
                if n.has_class("Zok-Oxid-Model-Product")
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    @staticmethod
    def _sizes_from_jsonld(html: str) -> dict[str, list[str]]:
        """url -> frame sizes, harvested from ProductGroup.hasVariant names."""
        out: dict[str, list[str]] = {}
        for block in script_blocks(html, "application/ld+json"):
            try:
                data = json.loads(block)
            except Exception:
                continue
            for item in _iter_list_items(data):
                url = item.get("url") or item.get("@id") or ""
                variants = item.get("hasVariant") or []
                labels: list[str] = []
                for v in variants:
                    name = v.get("name") or ""
                    # "... EMILIA VI X20 S (45cm) / lavendelblau"
                    m = re.search(r"\b([A-Z]{1,3}|\d{2})\s*\((\d{2})\s*cm\)", name)
                    if m:
                        labels.append(f"{m.group(1)} ({m.group(2)} cm)")
                        continue
                    m = re.search(r"\b(\d{2})\s*cm\b", name)
                    if m:
                        labels.append(f"{m.group(1)} cm")
                if url and labels:
                    out[url.split("?")[0]] = dedup_sizes(labels)
        return out

    def _to_offer(self, card: Node, sizes_by_url: dict) -> Offer | None:
        title_link = None
        for a in card.find_all("a"):
            if a.has_class("title"):
                title_link = a
                break
        if title_link is None:
            return None
        href = self.abs_url(title_link.get("href"))

        box = card.find(cls="Zok-Oxid-Model-Product-pricebox")
        if box is None:
            return None
        cur = box.find(cls="current")
        old = box.find(cls="old")
        price = parse_price(cur.text) if cur is not None else None
        list_price = parse_price(old.text) if old is not None else None
        if price is None:
            return None

        badge = card.find(cls="savings")
        stock = card.find(cls="Zok-Oxid-Model-Product-stockstatus")
        img = card.find("img")

        return Offer(
            shop=self.key,
            title=(title_link.get("title") or title_link.text).strip(),
            url=href,
            price=price,
            list_price=list_price,
            sizes=sizes_by_url.get(href.split("?")[0], []),
            image=img.get("src") if img is not None else "",
            availability=stock.text if stock is not None else "",
            shop_discount_pct=parse_percent(badge.text) if badge is not None else None,
        )


class Rad1(Adapter):
    """rad1.de - Shopware 5.

        <div class="product--box" data-ordernumber="920480">
          <a class="product--title" href="..">Name</a>
          <span class="price--default is--discount">ab 1.999,00 €*</span>
          <span class="price--pseudo"><span class="price--discount">UVP 3.199,00 €</span></span>
    """

    key = "rad1"
    name = "rad1.de"
    source_url = "https://www.rad1.de/e-bikes/"
    # rad1 has no e-bike-only sale category; /sale/ mixes bikes with helmets
    # and road bikes, so non-e-bikes are filtered out below.
    extra_urls = ["https://www.rad1.de/sale/"]

    _EBIKE = re.compile(r"e-?bike|pedelec|e-mtb|e-trekking|e-city", re.I)

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page == 1 else f"{base}?p={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            offers = [
                self._to_offer(n)
                for n in doc.walk()
                if n.has_class("product--box") and not n.has_class("box--slider")
            ]
            if "/e-bikes" in base:
                return offers  # already an e-bike-only category
            return [
                o for o in offers
                if o and (self._EBIKE.search(o.title) or self._EBIKE.search(o.url))
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, card: Node) -> Offer | None:
        title_link = card.find(cls="product--title")
        if title_link is None or not title_link.get("href"):
            return None

        price_el = card.find(cls="price--default")
        pseudo = card.find(cls="price--pseudo")
        price = parse_price(price_el.text) if price_el is not None else None
        list_price = None
        if pseudo is not None:
            disc = pseudo.find(cls="price--discount")
            list_price = parse_price((disc or pseudo).text)
        if price is None:
            return None

        img = card.find("img")
        note = "Preis ab (Variantenpreis)" if price_el is not None and price_el.text.strip().lower().startswith("ab") else ""
        return Offer(
            shop=self.key,
            title=(title_link.get("title") or title_link.text).strip(),
            url=self.abs_url(title_link.get("href")),
            price=price,
            list_price=list_price,
            image=img.get("src") if img is not None else "",
            note=note,
        )


class NubukBikes(Adapter):
    """nubuk-bikes.de - plentymarkets shop with a Nuxt/Tailwind frontend.

        <div data-testid="product-card">
          <div data-testid="productcard-manufacturer">Haibike</div>
          <a class="product-card__name" href="...">Titel</a>
          <div class="product-card__price-row">
            <span>UVP</span><span>5.399,00 €</span>
            <span class="product-card__price">3.499,00 €</span>
    """

    key = "nubuk"
    name = "nubuk-bikes.de"
    source_url = "https://www.nubuk-bikes.de/sale/e-bike-sale"

    @staticmethod
    def page_url(base: str, page: int) -> str:
        return base if page == 1 else f"{base}?page={page}"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        def extract(html: str, base: str):
            doc = parse(html)
            return [
                self._to_offer(n)
                for n in doc.walk()
                if n.get("data-testid") == "product-card"
            ]

        yield from paged_listing(self, fetcher, max_pages, self.page_url, extract)

    def _to_offer(self, card: Node) -> Offer | None:
        link = card.find(cls="product-card__name")
        if link is None or not link.get("href"):
            return None

        row = card.find(cls="product-card__price-row")
        if row is None:
            return None
        price_el = row.find(cls="product-card__price")
        price = parse_price(price_el.text) if price_el is not None else None
        if price is None:
            return None

        # The UVP block is the price-row column that is not the sale price;
        # it prints the label and the amount in separate spans.
        list_price = None
        for col in row.find_all("div"):
            text = col.text
            if "UVP" in text:
                list_price = parse_price(text.replace("UVP", ""))
                break

        brand_el = None
        for n in card.walk():
            if n.get("data-testid") == "productcard-manufacturer":
                brand_el = n
                break
        brand = brand_el.text if brand_el is not None else ""
        img = card.find("img")

        return Offer(
            shop=self.key,
            title=(link.text or link.get("title") or "").strip(),
            url=self.abs_url(link.get("href")),
            price=price,
            list_price=list_price,
            brand=brand,
            image=img.get("src") if img is not None else "",
        )


def _iter_list_items(data):
    """Yield Product / ProductGroup nodes out of a JSON-LD document."""
    if isinstance(data, list):
        for d in data:
            yield from _iter_list_items(d)
        return
    if not isinstance(data, dict):
        return
    t = data.get("@type")
    if t in ("Product", "ProductGroup"):
        yield data
    for key in ("itemListElement", "item", "@graph"):
        if key in data:
            yield from _iter_list_items(data[key])
