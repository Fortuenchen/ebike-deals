"""lucky-bike.de - OXID shop whose listing is only present after JS runs.

Card markup (from the rendered DOM):

    <div class="kmt-productbox kmt-productbox--type-grid" kmt-listitem-prod-id="lb68235">
      <span class="kmt-badge kmt-badge--modi-sale" data-value="15.00 %">- 15 %</span>
      <div class="kmt-productbox-head"><a href="...">Cube Stereo Hybrid ...</a></div>
      <div class="kmt-productbox-prices">
        <span class="kmt-price kmt-price--old">
          <span class="kmt-price-whole">2.499,</span><span class="kmt-price-decimal">00</span>
        <span class="kmt-price"><span class="kmt-price-absolute">
          <span class="kmt-price-whole">2.199,</span><span class="kmt-price-decimal">99</span>

The price is split across two spans: the whole part already carries the
thousands separator and a trailing comma ("2.199,"), the decimal span holds the
cents ("99"). Concatenating them yields a normal German price string. Treating
the two as separate numbers turned a 2199.99 EUR bike into 219999 EUR.

The category page itself is a landing page with subcategory tiles, so the
subcategories are what gets scraped.

SCRAPE_LIMIT: each subcategory exposes at most 45 products and offers no way to
reach the rest - no pager, no load-more, no working page parameter, and
scrolling loads nothing further. Roughly 320 of lucky-bike's bikes are therefore
visible to this adapter. Going deeper would mean walking the brand and price
filter combinations, which is a lot of rendered requests for a shop that
contributed two hits.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..htmlutil import Node, parse
from ..model import Offer, dedup_sizes, looks_like_size, parse_percent, parse_price
from ..net import Fetcher
from .base import Adapter

SUBCATEGORIES = [
    "E-Citybike", "E-Trekkingbike", "E-MTB-Hardtail", "E-MTB-Fully",
    "E-Falt-Klappraeder", "E-Kompaktrad", "E-Lastenrad", "E-Rennrad",
    "S-Pedelec", "XXL-E-Bikes",
]


class LuckyBike(Adapter):
    key = "luckybike"
    name = "lucky-bike.de"
    source_url = "https://www.lucky-bike.de/Fahrraeder/E-Bike/"
    needs_render = True
    skipped_reason = (
        "Listing wird nur an echte Browser ausgeliefert. Mit --render "
        "(Playwright) abrufbar — ohne den Schalter übersprungen."
    )

    def listing_urls(self) -> list[str]:
        base = self.source_url.rstrip("/")
        return [f"{base}/{c}/" for c in SUBCATEGORIES]

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        renderer = getattr(fetcher, "renderer", None)
        if renderer is None:
            return
        seen: set[str] = set()
        # No pagination exists: ?pgNr= returns an empty listing, there is no
        # next-page link, no load-more control, and scrolling adds nothing. A
        # subcategory renders 45 products and that is all it exposes - the
        # larger counts on the page are filter facets, not the result set. So
        # one request per subcategory, no page loop. See SCRAPE_LIMIT.
        for url in self.listing_urls():
            if fetcher.robots is not None and not fetcher.robots.check(url).allowed:
                continue
            try:
                html = renderer.html(url, wait_for=".kmt-productbox")
            except Exception:
                continue
            doc = parse(html)
            for box in (n for n in doc.walk() if n.has_class("kmt-productbox")):
                offer = self._to_offer(box)
                if offer and offer.url not in seen:
                    seen.add(offer.url)
                    yield offer

    # ------------------------------------------------------------------
    def _to_offer(self, box: Node) -> Offer | None:
        head = box.find(cls="kmt-productbox-head")
        link = head.find("a") if head is not None else None
        if link is None:
            for a in box.find_all("a"):
                if a.get("href") and ".html" in a.get("href"):
                    link = a
                    break
        if link is None or not link.get("href"):
            return None

        prices = box.find(cls="kmt-productbox-prices")
        if prices is None:
            return None
        current = old = None
        for span in prices.find_all("span"):
            if not span.has_class("kmt-price"):
                continue
            value = self._read_price(span)
            if value is None:
                continue
            if span.has_class("kmt-price--old"):
                old = old or value
            elif current is None:
                current = value
        if current is None:
            return None

        badge = None
        for el in box.find_all(cls="kmt-badge--modi-sale"):
            badge = parse_percent(el.get("data-value") or el.text)
            break

        brand_el = box.find(cls="kmt-productbox-manufacturer")
        brand_img = brand_el.find("img") if brand_el is not None else None
        img = box.find(cls="kmt-productbox-picture")
        img = img.find("img") if img is not None else None

        sizes = dedup_sizes(
            el.text for el in box.find_all(cls="kmt-productbox-size")
            if looks_like_size(el.text)
        )

        return Offer(
            shop=self.key,
            title=(link.text or link.get("title") or "").strip(),
            url=self.abs_url(link.get("href")),
            price=current,
            list_price=old if (old and old > current) else None,
            brand=(brand_img.get("alt") if brand_img is not None else "") or "",
            sizes=sizes,
            image=self.abs_url(img.get("src")) if img is not None else "",
            shop_discount_pct=badge,
        )

    @staticmethod
    def _read_price(span: Node) -> float | None:
        """Reassemble the split price - see the module docstring for the format."""
        whole = span.find(cls="kmt-price-whole")
        dec = span.find(cls="kmt-price-decimal")
        if whole is not None and dec is not None:
            # "2.999," + "99" is already a German price string, so the shared
            # parser handles the thousands separator and the decimal comma.
            return parse_price(f"{whole.text}{dec.text}")
        return parse_price(span.text)
