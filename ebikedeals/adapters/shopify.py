"""Shopify shops - bikemarket24.de, boc24.de.

Shopify exposes /collections/<handle>/products.json, which returns the full
product model including every variant with price + compare_at_price (= UVP)
and the option names. That is both the cheapest and the most accurate source:
sizes come straight from the variant options, no detail-page fetch needed.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..model import Offer, dedup_sizes, looks_like_size, parse_price
from ..net import Fetcher
from .base import Adapter

# Option names Shopify merchants use for the frame size.
_SIZE_OPTION = re.compile(r"gr(ö|oe|o)ss?e|size|rahmen|frame", re.I)

# upway tags one bike with "size:160cm" ... "size:190cm". Those are the rider
# body heights the bike fits, not frame sizes, so they are collapsed into a
# labelled range instead of being passed off as available frame sizes.
_BODY_HEIGHT_TAG = re.compile(r"^size:(\d{3})\s*cm$", re.I)

# "batteryCapacityThreshold:400+ Wh" - a bucket, not a measurement. A bike can
# carry several; the largest is the strongest provable lower bound.
_BATTERY_THRESHOLD_TAG = re.compile(r"batteryCapacityThreshold:\s*(\d{3,4})\s*\+?\s*Wh", re.I)


def _battery_floor_from_tags(tags) -> int | None:
    bounds = [
        int(m.group(1))
        for tag in tags
        if (m := _BATTERY_THRESHOLD_TAG.search(str(tag)))
    ]
    return max(bounds) if bounds else None


def _body_height_range(tags) -> tuple[int | None, int | None]:
    heights = [
        int(m.group(1))
        for tag in tags
        if (m := _BODY_HEIGHT_TAG.match(str(tag).strip()))
    ]
    return (min(heights), max(heights)) if heights else (None, None)


def _body_height_label(lo: int | None, hi: int | None) -> list[str]:
    if lo is None:
        return []
    return [f"für Körpergröße {lo}–{hi} cm" if lo != hi else f"für Körpergröße {lo} cm"]


# A broad collection carries more than bikes: upway's "all" mixes in insurance
# policies, accessories and non-electric bikes. Filtering by Shopify's
# product_type is exact where the shop sets it.
_NON_BIKE_TYPE = re.compile(r"insurance|versicherung|accessor|zubeh|service|garantie", re.I)
_NON_EBIKE_TYPE = re.compile(r"non-?electric|bio[\s-]?bike|muskelkraft", re.I)


class ShopifyAdapter(Adapter):
    collections: list[str] = []
    page_size = 250

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        seen: set[int] = set()
        for index, handle in enumerate(self.collections):
            for page in range(1, self.pages_for(max_pages) + 1):
                url = (
                    f"{self.base}/collections/{handle}/products.json"
                    f"?limit={self.page_size}&page={page}"
                )
                try:
                    data = fetcher.get_json(url)
                except Exception:
                    # A failure on the very first request means the shop was
                    # not reached at all. Swallowing it reports "0 products
                    # checked", which reads like "no offers today" - fahrrad.de
                    # showed exactly that after a transient error. Later pages
                    # and later collections just end the walk.
                    if page == 1 and index == 0:
                        raise
                    break
                products = data.get("products") or []
                if not products:
                    break
                for p in products:
                    if p.get("id") in seen:
                        continue
                    seen.add(p["id"])
                    offer = self._to_offer(p, handle)
                    if offer:
                        yield offer
                if len(products) < self.page_size:
                    break

    # ------------------------------------------------------------------
    def _to_offer(self, p: dict, handle: str) -> Offer | None:
        variants = p.get("variants") or []
        if not variants:
            return None
        ptype = p.get("product_type") or ""
        if ptype and (_NON_BIKE_TYPE.search(ptype) or _NON_EBIKE_TYPE.search(ptype)):
            return None

        # Which option position holds the size?
        size_idx = None
        for opt in p.get("options") or []:
            if _SIZE_OPTION.search(opt.get("name", "")):
                size_idx = opt.get("position", 1) - 1
                break

        best_price = None
        best_list = None
        sizes: list[str] = []
        available_sizes: list[str] = []
        # Availability must be tracked independently of sizes: shops that sell
        # single bikes (upway) have one "Default Title" variant and therefore
        # no size labels at all - deriving stock from size labels would mark
        # the entire shop as sold out.
        any_available = any(v.get("available") for v in variants)

        for v in variants:
            price = parse_price(v.get("price"))
            compare = parse_price(v.get("compare_at_price"))
            if price is None:
                continue
            # Deepest discount within the product drives the listing entry.
            if compare and compare > price:
                disc = 1 - price / compare
                cur = (1 - best_price / best_list) if (best_price and best_list) else -1
                if disc > cur:
                    best_price, best_list = price, compare
            elif best_price is None:
                best_price = price

            label = self._variant_size(v, size_idx)
            if label:
                sizes.append(label)
                if v.get("available"):
                    available_sizes.append(label)

        if best_price is None:
            return None

        url = f"{self.base}/products/{p['handle']}"
        images = p.get("images") or []
        # Prefer sizes that can actually be bought.
        shown = dedup_sizes(available_sizes or sizes)
        bh_lo, bh_hi = _body_height_range(p.get("tags") or [])
        if not shown:
            shown = _body_height_label(bh_lo, bh_hi)
        # Only meaningful when the product actually has sizes: "no size in
        # stock" is different from "this bike has no size options".
        note = "aktuell keine Größe auf Lager" if (sizes and not available_sizes) else ""

        return Offer(
            shop=self.key,
            title=p.get("title", "").strip(),
            url=url,
            price=best_price,
            list_price=best_list,
            brand=(p.get("vendor") or "").strip(),
            battery_min_wh=_battery_floor_from_tags(p.get("tags") or []),
            sizes=shown,
            body_height_min=bh_lo,
            body_height_max=bh_hi,
            image=images[0].get("src", "") if images else "",
            availability="verfügbar" if any_available else "nicht auf Lager",
            in_stock=any_available,
            note=note,
        )

    @staticmethod
    def _variant_size(v: dict, size_idx: int | None) -> str:
        if size_idx is not None:
            val = v.get(f"option{size_idx + 1}")
            if val and looks_like_size(val):
                return val.strip()
        # Fall back to scanning all options, then the composite title.
        for key in ("option1", "option2", "option3"):
            val = v.get(key)
            if val and looks_like_size(val):
                return val.strip()
        for part in (v.get("title") or "").split("/"):
            part = part.strip()
            if looks_like_size(part):
                return part
        return ""


class BikeMarket24(ShopifyAdapter):
    key = "bikemarket24"
    name = "bikemarket24.de"
    base = "https://bikemarket24.de"
    # Sale collection first; the full e-bike category stays as a safety net
    # because merchants do not always tag every reduced bike.
    source_url = "https://bikemarket24.de/collections/angebote-e-bike"
    collections = ["angebote-e-bike", "e-bike"]


class Boc24(ShopifyAdapter):
    key = "boc24"
    name = "boc24.de (B.O.C.)"
    base = "https://boc24.de"
    # The brief gave the shop homepage; these are its e-bike collections.
    source_url = "https://boc24.de/collections/e-bikes-reduziert"
    collections = ["e-bikes-reduziert", "e-bikes"]


class EBikeOnly(ShopifyAdapter):
    key = "ebikeonly"
    name = "e-bike-only.de"
    base = "https://e-bike-only.de"
    source_url = "https://e-bike-only.de/collections/e-bike-sale"
    # The sale collection holds 256 of 1308 e-bikes and misses 7 offers above
    # 50 % - a curated pick, not every reduced bike.
    collections = ["e-bike-sale", "all-e-bikes"]


class FahrradDe(ShopifyAdapter):
    key = "fahrradde"
    name = "fahrrad.de"
    base = "https://www.fahrrad.de"
    source_url = "https://www.fahrrad.de/collections/e-bike-sale"
    collections = ["e-bike-sale"]


class Upway(ShopifyAdapter):
    """upway.de - refurbished e-bikes, German storefront (EUR).

    Note the domain: upway.co is the US shop and quotes USD, so it must not be
    used here. Every bike is refurbished, which the listing does not say per
    product - hence default_condition.
    """

    key = "upway"
    name = "upway.de"
    base = "https://upway.de"
    # "sale" is the live stock: 796 products, all 796 buyable, 711 above 50 %.
    # "all" is the archive - 3500 products of which only 126 are still
    # available, because a refurbished marketplace keeps sold bikes listed.
    # Ranking the two by discount alone made "all" look like the better source
    # and cost 646 real offers; sale stays primary, all is the supplement that
    # adds another 38 buyable ones.
    source_url = "https://upway.de/collections/sale"
    collections = ["sale", "all"]
    default_condition = "refurbished"
    #: "all" runs to ~3500 products at 250 per page
    page_budget = 16
