"""Shops whose listing is a JS app but ships its state inside the HTML.

- bikeexchange.de: Next.js App Router. The RSC "flight" payload is split across
  many self.__next_f.push([1,"..."]) chunks; concatenating and unescaping them
  yields a JSON blob containing productList with per-size prices AND per-size
  direct links - the richest source in this project.
- jobrad-loop.com: classic Next.js, state in <script id="__NEXT_DATA__">.
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from ..model import Offer, dedup_sizes, looks_like_size, parse_battery_wh, parse_percent
from ..net import Fetcher
from .base import Adapter, fetch_page


def _as_values(raw) -> list[str]:
    """Normalise an attribute value (scalar or list) to a list of strings."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [str(v).strip() for v in items if str(v).strip()]


def _extract_json_value(text: str, start: int) -> str | None:
    """Return the JSON literal beginning at `start` (must be '[' or '{')."""
    if start >= len(text) or text[start] not in "[{":
        return None
    opening = text[start]
    closing = "]" if opening == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


class BikeExchange(Adapter):
    key = "bikeexchange"
    name = "bikeexchange.de"
    source_url = "https://www.bikeexchange.de/de-DE/bike/e-bike-sale?order=discount&dir=desc"

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = self.source_url if page == 1 else f"{self.source_url}&page={page}"
            html = fetch_page(fetcher, url, page)
            if html is None:
                break
            products = self._product_list(html)
            if not products:
                break
            new = 0
            for p in products:
                offer = self._to_offer(p)
                if offer and offer.url not in seen:
                    seen.add(offer.url)
                    new += 1
                    yield offer
            if new == 0:
                break

    # ------------------------------------------------------------------
    @staticmethod
    def _flight_payload(html: str) -> str:
        parts: list[str] = []
        for m in re.finditer(r"self\.__next_f\.push\(\[1,", html):
            i = html.find('"', m.end())
            if i < 0:
                continue
            j = i + 1
            while j < len(html):
                if html[j] == "\\":
                    j += 2
                    continue
                if html[j] == '"':
                    break
                j += 1
            try:
                parts.append(json.loads(html[i:j + 1]))
            except Exception:
                continue
        return "".join(parts)

    def _product_list(self, html: str) -> list[dict]:
        flight = self._flight_payload(html)
        key = '"productList":'
        idx = flight.find(key)
        if idx < 0:
            return []
        raw = _extract_json_value(flight, idx + len(key))
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        return [p for p in data if isinstance(p, dict)]

    def _to_offer(self, p: dict) -> Offer | None:
        def money(node) -> float | None:
            if isinstance(node, dict) and isinstance(node.get("amount"), (int, float)):
                return round(node["amount"] / 100.0, 2)
            return None

        list_price = money(p.get("price"))
        price = money(p.get("reducedPrice")) or list_price
        if price is None:
            return None

        sizes: list[str] = []
        size_links: dict[str, str] = {}
        for s in p.get("sizes") or []:
            label = (s.get("size") or "").strip()
            if not label:
                continue
            sizes.append(label)
            href = s.get("href") or ""
            if href:
                size_links[label] = self.abs_url(href)

        selected = p.get("selectedSize") or {}
        href = selected.get("href") or (p.get("sizes") or [{}])[0].get("href", "")
        image = ((p.get("imageWithBrandLogo") or {}).get("image") or {}).get("image") or {}
        flex = p.get("flexTag") or {}

        title = p.get("description") or ""
        brand = ""
        logo = ((p.get("imageWithBrandLogo") or {}).get("logo") or {}).get("image") or {}
        if logo.get("alt"):
            brand = logo["alt"].strip().title()

        # keyFeatures look like ["Yamaha", "630wh", "Kettenschaltung"].
        features = [str(x) for x in (p.get("keyFeatures") or [])]

        return Offer(
            shop=self.key,
            title=f"{brand} {title}".strip(),
            url=self.abs_url(href),
            price=price,
            list_price=list_price,
            brand=brand,
            battery_wh=parse_battery_wh(*features),
            sizes=dedup_sizes(sizes),
            size_links=size_links,
            image=image.get("src", ""),
            availability=(p.get("conditionTag") or {}).get("title", ""),
            shop_discount_pct=parse_percent(flex.get("title") or ""),
        )


class JobradLoop(Adapter):
    """jobrad-loop.com - refurbished e-bikes, one unique bike per listing.

    Discount is price vs. recommendedPrice (UVP). Because every bike is a
    single used unit there is exactly one size per listing; the size comes from
    the variant attributes (frame_size / frame_height), with the recommended
    body-height range as a fallback.
    """

    key = "jobradloop"
    name = "jobrad-loop.com"
    source_url = "https://jobrad-loop.com/e-bikes"
    # No sale category and no URL-addressable facet: /top-deals renders
    # client-side, and the relative_savings facet only exists in the internal
    # API. 24 bikes per page over ~1270 listings, so page deeper here.
    page_budget = 55

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        seen: set[str] = set()
        cursor = None
        for page in range(1, self.pages_for(max_pages) + 1):
            url = self.source_url
            if cursor:
                url = f"{self.source_url}?cursor={cursor}"
            elif page > 1:
                url = f"{self.source_url}?page={page}"
            html = fetch_page(fetcher, url, page)
            if html is None:
                break
            payload = self._preloaded(html)
            if not payload:
                break
            items = payload.get("items") or []
            if not items:
                break
            new = 0
            for it in items:
                offer = self._to_offer(it)
                if offer and offer.url not in seen:
                    seen.add(offer.url)
                    new += 1
                    yield offer
            cursor = payload.get("nextCursor")
            if new == 0 or not cursor:
                break

    @staticmethod
    def _preloaded(html: str) -> dict:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(1))
        except Exception:
            return {}
        try:
            configs = data["props"]["pageProps"]["data"]["pageFolder"]["dataSourceConfigurations"]
        except (KeyError, TypeError):
            return {}
        for cfg in configs:
            pv = cfg.get("preloadedValue") or {}
            if pv.get("items"):
                return pv
        return {}

    def _to_offer(self, item: dict) -> Offer | None:
        variants = item.get("variants") or []
        if not variants:
            return None
        v = variants[0]

        def money(node) -> float | None:
            if isinstance(node, dict) and isinstance(node.get("centAmount"), (int, float)):
                return round(node["centAmount"] / 10 ** node.get("fractionDigits", 2), 2)
            return None

        price = money(v.get("price"))
        list_price = money(v.get("recommendedPrice"))
        if price is None:
            return None

        attrs = v.get("attributes") or {}
        sizes = dedup_sizes(self._sizes(attrs))

        # Product URLs are "/{slug}/p/{variant-sku}". The item usually carries
        # the ready-made path in _url; build it only as a fallback.
        path = item.get("_url") or ""
        if not path:
            slug, sku = item.get("slug") or "", v.get("sku") or ""
            path = f"/{slug}/p/{sku}" if slug and sku else ""
        url = f"https://jobrad-loop.com{path}" if path else self.source_url

        parts: list[str] = []
        cond = attrs.get("technical_condition")
        if cond:
            parts.append(
                f"Zustand: {', '.join(map(str, cond)) if isinstance(cond, list) else cond}"
            )
        mileage = attrs.get("mileage")
        if isinstance(mileage, (int, float)) and mileage:
            parts.append(f"{int(mileage)} km")
        measured = _as_values(attrs.get("frame_height_measured"))
        if measured:
            parts.append(f"Rahmenhöhe gemessen: {measured[0]}")
        note = " · ".join(parts)

        images = v.get("images") or []
        battery = None
        raw_wh = _as_values(attrs.get("battery_capacity_in_wh"))
        if raw_wh:
            try:
                battery = int(float(raw_wh[0]))
            except (TypeError, ValueError):
                battery = None

        bh_min, bh_max = self._body_height(attrs)
        return Offer(
            shop=self.key,
            title=(item.get("name") or "").strip(),
            url=url,
            price=price,
            list_price=list_price,
            battery_wh=battery,
            body_height_min=bh_min,
            body_height_max=bh_max,
            sizes=sizes,
            image=images[0] if images else "",
            availability="verfügbar" if v.get("isOnStock") else "nicht verfügbar",
            in_stock=bool(v.get("isOnStock")),
            note=note,
        )

    @staticmethod
    def _sizes(attrs: dict) -> list[str]:
        """The size the shop shows as 'Rahmengröße'.

        frame_height_manufacturer is that value (L, XL, 58 cm);
        frame_height_measured is the physically measured frame height and is
        reported separately as a note. wheel_size_* must not be used at all -
        28" is a wheel, not a frame size.
        """
        out: list[str] = []
        for key in ("frame_height_manufacturer", "frame_size", "frame_height"):
            for v in _as_values(attrs.get(key)):
                if looks_like_size(v):
                    out.append(v)
            if out:
                return out

        # Fall back to the recommended body-height range.
        lo, hi = JobradLoop._body_height(attrs)
        return [f"für Körpergröße {lo}–{hi} cm"] if lo else []

    @staticmethod
    def _body_height(attrs: dict) -> tuple[int | None, int | None]:
        """Recommended rider height range in cm.

        Every listing carries this, not just those without a frame size, so it
        is read independently of _sizes - that is what makes a fit filter work
        across the whole shop.
        """
        heights = attrs.get("frame_body_height_recommended")
        if isinstance(heights, list):
            nums = [int(h) for h in heights if isinstance(h, (int, float))]
            if nums:
                return min(nums), max(nums)
        return None, None
