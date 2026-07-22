"""Adapter contract + helpers shared by the concrete shop adapters."""

from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from ..htmlutil import Node
from ..model import Offer
from ..net import Fetcher

# Links inside a product card that are never the product itself.
_NON_PRODUCT_HREF = re.compile(
    r"(wishlist|merkzettel|vergleich|compare|checkout|cart|warenkorb|add|login|/media/|\.jpg|\.png|javascript:|^#)",
    re.I,
)

# Taxonomy links that sit inside product cards (brand logo, category chip) and
# would otherwise be mistaken for the product link.
_TAXONOMY_HREF = re.compile(r"/(marke|marken|brand|hersteller|kategorie|category)/", re.I)


class Adapter:
    """One shop. Subclasses yield Offers; the runner handles filtering/reporting."""

    key: str = ""
    name: str = ""
    source_url: str = ""
    #: Extra listing URLs beyond source_url. Prefer a shop's own sale/outlet
    #: category here - pre-filtered listings mean far fewer requests and far
    #: less noise than paging through a full catalogue.
    extra_urls: list[str] = []
    #: Per-shop page budget for shops that have no sale filter and therefore
    #: need deeper paging. None = use the run-wide default.
    page_budget: int | None = None
    #: Condition that applies to the shop's whole range. Some shops sell only
    #: refurbished bikes without saying so per product - without this the
    #: report would present them as new stock.
    default_condition: str = ""
    #: set when the shop cannot be scraped over plain HTTP
    skipped_reason: str = ""

    def listing_urls(self) -> list[str]:
        return [self.source_url, *self.extra_urls]

    def pages_for(self, max_pages: int) -> int:
        return max(max_pages, self.page_budget or 0)

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        raise NotImplementedError

    # -- helpers ----------------------------------------------------------
    def abs_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("//"):
            return "https:" + href
        return urljoin(self.source_url, href)


def nearest_product_link(node: Node, max_up: int = 8) -> tuple[str, str]:
    """Walk up from `node` until an ancestor contains a real product link.

    Returns (href, link_text).

    A product card usually links the product two or three times (image, title,
    sometimes a button) but links a brand or category at most once, so the most
    repeated non-utility href is the product. Taxonomy links only win if there
    is nothing else - which is why they are ranked last rather than dropped.
    """
    cur = node
    fallback: tuple[str, str] = ("", "")
    for _ in range(max_up):
        if cur is None:
            break
        counts: dict[str, int] = {}
        texts: dict[str, str] = {}
        for a in cur.find_all("a"):
            href = a.get("href")
            if not href or _NON_PRODUCT_HREF.search(href):
                continue
            counts[href] = counts.get(href, 0) + 1
            text = (a.text or a.get("title") or "").strip()
            # Keep the most descriptive label seen for this href.
            if len(text) > len(texts.get(href, "")):
                texts[href] = text

        real = {h: c for h, c in counts.items() if not _TAXONOMY_HREF.search(h)}
        if real:
            best = max(real, key=lambda h: (real[h], len(texts.get(h, ""))))
            return best, texts.get(best, "")
        # Only brand/category links at this level - remember one and keep
        # climbing; a card that links its brand always links its product too,
        # just one level further out.
        if counts and not fallback[0]:
            h = next(iter(counts))
            fallback = (h, texts.get(h, ""))
        cur = cur.parent
    return fallback


def fetch_page(fetcher: Fetcher, url: str, page: int) -> str | None:
    """Fetch one listing page.

    A failure on page 1 means the adapter is broken or the shop blocked us -
    that must surface in the report, so it propagates. A failure on a later
    page just means we ran past the end of the listing.
    """
    try:
        return fetcher.get(url)
    except Exception:
        if page == 1:
            raise
        return None


def paged_listing(adapter, fetcher, max_pages, page_url, extract):
    """Walk every listing URL of an adapter, paging each until it runs dry.

    `page_url(base, page)` builds a page URL, `extract(html, base)` returns
    Offers - `base` lets an adapter treat its listings differently (rad1 needs
    to drop non-e-bikes from the mixed /sale/ category but not from /e-bikes/).
    Deduplication spans all listing URLs, because a shop's sale category and
    its main category overlap by design.
    """
    seen: set[str] = set()
    for base in adapter.listing_urls():
        for page in range(1, adapter.pages_for(max_pages) + 1):
            html = fetch_page(fetcher, page_url(base, page), page)
            if html is None:
                break
            offers = [o for o in extract(html, base) if o]
            if not offers:
                break
            new = 0
            for offer in offers:
                if offer.url in seen:
                    continue
                seen.add(offer.url)
                new += 1
                yield offer
            # A page whose entries we have all seen means we looped back to
            # the start of the listing - stop rather than fetch it forever.
            if new == 0:
                break


def first_text(container: Node | None, *classes: str) -> str:
    """Text of the first descendant carrying any of the given classes."""
    if container is None:
        return ""
    for cls in classes:
        el = container.find(cls=cls)
        if el is not None:
            t = el.text
            if t:
                return t
    return ""
