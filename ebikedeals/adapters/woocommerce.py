"""WooCommerce shops via the built-in Store API.

Any WooCommerce shop from version 5.x exposes a read-only JSON API at
/wp-json/wc/store/v1/products. It needs no key and supports `on_sale=true`,
which is exactly the pre-filtered listing this project wants - the same kind of
win Shopify's products.json gives us.

The model:

    prices: {price, regular_price, sale_price, currency_minor_unit}   <- integers
    attributes: [{name, taxonomy, has_variations, terms:[{name}]}]
    is_in_stock / is_purchasable
    categories: [{name, slug}]

Two traps this adapter avoids:
  * `pa_radgroesse` ("Radgröße") is the WHEEL size - 28" is not a frame size.
    Only the attribute that means frame size is used.
  * The API returns the whole catalogue, accessories included, so products are
    kept only when a category or type says e-bike.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..model import Offer, dedup_sizes, looks_like_size
from ..net import Fetcher
from .base import Adapter

# Frame size, not wheel size: "Rahmengröße", "Rahmenhöhe", "frame size".
FRAME_SIZE_ATTR = re.compile(r"rahmen(gr|h(ö|oe)he)|frame[_ -]?size", re.I)
# Anything that identifies the product as an e-bike.
EBIKE_HINT = re.compile(r"e-?bike|elektro|pedelec|e-mtb|e-lasten|e-trekking|e-city", re.I)
# ... but a charger lives in "Elektronische Komponenten" and would match the
# hint above, so parts and accessories are excluded first.
# Deliberately no bare "motor": the category slug "e-bike-mittelmotor" is a
# drive type, so matching it would drop every mid-motor e-bike. Standalone
# motors sit in the parts categories and are caught by those words instead.
ACCESSORY_HINT = re.compile(
    r"ersatzteil|zubeh(ö|oe)r|komponent|ladeger(ä|ae)t|charger|"
    r"helm|schloss|lampe|licht|tasche|gep(ä|ae)cktr(ä|ae)ger|bekleidung|"
    r"schlauch|pedal|sattel|werkzeug|display",
    re.I,
)


class WooCommerceAdapter(Adapter):
    #: shop root, no trailing slash
    base: str = ""
    #: only fetch products the shop itself flags as reduced
    on_sale_only: bool = True
    per_page: int = 100

    def api_url(self, page: int) -> str:
        params = [f"per_page={self.per_page}", f"page={page}"]
        if self.on_sale_only:
            params.append("on_sale=true")
        return f"{self.base}/wp-json/wc/store/v1/products?" + "&".join(params)

    def scrape(self, fetcher: Fetcher, max_pages: int) -> Iterator[Offer]:
        seen: set[str] = set()
        for page in range(1, self.pages_for(max_pages) + 1):
            try:
                products = fetcher.get_json(self.api_url(page))
            except Exception:
                if page == 1:
                    raise
                break
            if not isinstance(products, list) or not products:
                break
            for p in products:
                offer = self._to_offer(p)
                if offer and offer.url not in seen:
                    seen.add(offer.url)
                    yield offer
            if len(products) < self.per_page:
                break

    # ------------------------------------------------------------------
    def _to_offer(self, p: dict) -> Offer | None:
        if not self._is_ebike(p):
            return None

        prices = p.get("prices") or {}
        unit = prices.get("currency_minor_unit", 2)
        price = _money(prices.get("price"), unit)
        list_price = _money(prices.get("regular_price"), unit)
        if price is None:
            return None
        if list_price is not None and list_price <= price:
            list_price = None

        sizes: list[str] = []
        brand = ""
        for attr in p.get("attributes") or []:
            name = f"{attr.get('name', '')} {attr.get('taxonomy', '')}"
            terms = [t.get("name", "") for t in attr.get("terms") or []]
            if FRAME_SIZE_ATTR.search(name):
                sizes.extend(t for t in terms if looks_like_size(t))
            elif re.search(r"\bmarke\b|brand|hersteller", name, re.I) and terms:
                brand = terms[0]
        for b in p.get("brands") or []:
            brand = brand or b.get("name", "")

        images = p.get("images") or []
        in_stock = p.get("is_in_stock")
        return Offer(
            shop=self.key,
            title=_clean(p.get("name", "")),
            url=p.get("permalink", ""),
            price=price,
            list_price=list_price,
            brand=brand,
            sizes=dedup_sizes(sizes),
            image=images[0].get("src", "") if images else "",
            availability="verfügbar" if in_stock else "nicht auf Lager",
            in_stock=bool(in_stock) if in_stock is not None else None,
        )

    @staticmethod
    def _is_ebike(p: dict) -> bool:
        """A complete e-bike, not a part that happens to be electric.

        The Store API returns the full catalogue, and a charger sits in
        categories like "Elektronische Komponenten" that match the e-bike hint.
        Name and category are therefore checked against the accessory list
        first, and the whole listing must still look like a bike.
        """
        name = p.get("name", "")
        cat_names = [c.get("name", "") for c in p.get("categories") or []]
        cat_slugs = [c.get("slug", "") for c in p.get("categories") or []]

        if ACCESSORY_HINT.search(name):
            return False
        if any(ACCESSORY_HINT.search(c) for c in cat_names + cat_slugs):
            return False
        return bool(EBIKE_HINT.search(" ".join([name, p.get("slug", "")] + cat_names + cat_slugs)))


def _money(raw, minor_unit: int) -> float | None:
    """Store API prices are integer strings in the currency's minor unit."""
    if raw in (None, ""):
        return None
    try:
        return round(int(raw) / (10 ** minor_unit), 2)
    except (TypeError, ValueError):
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


class EbikeStock(WooCommerceAdapter):
    key = "ebikestock"
    name = "ebikestock.de"
    base = "https://www.ebikestock.de"
    source_url = "https://www.ebikestock.de/ebikes/elektrofahrrad/e-bike-sale/"
    # Small catalogue (~34 products); the on_sale flag misses reduced items
    # that were never tagged, so scan everything.
    on_sale_only = False
