"""Shared data model: one normalised Offer regardless of shop platform."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Offer:
    shop: str                       # shop key, e.g. "bikeexchange"
    title: str
    url: str                        # direct link to the product
    price: float                    # current / sale price in EUR
    list_price: float | None = None  # UVP or strike-through price in EUR
    brand: str = ""
    sizes: list[str] = field(default_factory=list)   # frame sizes / heights
    image: str = ""
    availability: str = ""
    # True/False when the shop states it, None when it does not say.
    # Sold-out products keep their strike price, so a 96%-off bike that cannot
    # be bought is not an offer - the runner drops these unless asked not to.
    in_stock: bool | None = None
    size_links: dict[str, str] = field(default_factory=dict)  # size -> direct link
    # Percentage the shop itself advertises. Kept separate from our computed
    # value so a mismatch is visible instead of silently trusted.
    shop_discount_pct: float | None = None
    # Prices as stated on the product page, when it was fetched. Kept next to
    # the listing values so a disagreement between the two is visible.
    detail_price: float | None = None
    detail_list_price: float | None = None
    #: "" for new stock, else why it is cheap ("refurbished", "Testbike", ...)
    condition: str = ""
    #: exact battery capacity in Wh - the spec buyers filter and sort on most
    battery_wh: int | None = None
    #: lower bound only. upway states "300+ Wh" rather than a figure; that
    #: proves "at least 300" and nothing more, so it must not be stored as if
    #: it were exact.
    battery_min_wh: int | None = None
    #: rider body height the bike fits, in cm. Refurbished shops sell single
    #: bikes and state this instead of a frame size, so it is the only way to
    #: filter their stock by fit.
    body_height_min: int | None = None
    body_height_max: int | None = None
    #: Orte, an denen genau dieses Rad vor Ort steht. fahrrad-xxl weist das je
    #: Artikel aus; bei Shops ohne solche Angabe bleibt die Liste leer und es
    #: zählt nur der Firmensitz.
    branches: list[str] = field(default_factory=list)
    note: str = ""

    # -- Datenblatt-Merkmale, aus Titel bzw. Produktseite gewonnen. Abdeckung
    #    teilweise: nur wo der Shop es ausweist (wie battery_wh).
    drivetrain: str = ""     # "Kettenschaltung" / "Nabenschaltung"
    motor: str = ""          # Motor-Hersteller, z. B. "Bosch"
    brakes: str = ""         # "hydraulisch" / "mechanisch"
    wheel_size: str = ""     # z. B. '29"'

    # -- price history, filled by the history store after scraping -------
    first_seen: str = ""          # ISO date this URL was first recorded
    price_prev: float | None = None   # price at the previous run
    price_min: float | None = None    # lowest price ever recorded
    price_points: list = field(default_factory=list)  # [[iso_date, price], ...]

    @property
    def price_change(self) -> float | None:
        """Change against the previous run; negative means it got cheaper."""
        if self.price_prev is None:
            return None
        return round(self.price - self.price_prev, 2)

    @property
    def is_new(self) -> bool:
        return not self.price_points or len(self.price_points) <= 1

    @property
    def is_all_time_low(self) -> bool:
        # Only meaningful once we have seen more than one price.
        if self.price_min is None or len(self.price_points) < 2:
            return False
        return self.price <= self.price_min + 0.01

    @property
    def discount_pct(self) -> float | None:
        """Discount computed from list price vs. sale price."""
        if not self.list_price or self.list_price <= 0 or self.price <= 0:
            return None
        if self.price >= self.list_price:
            return 0.0
        return round((1 - self.price / self.list_price) * 100, 1)

    @property
    def effective_discount_pct(self) -> float | None:
        """Discount used for filtering: computed value, else the shop's badge."""
        computed = self.discount_pct
        if computed is not None:
            return computed
        return self.shop_discount_pct

    @property
    def saving(self) -> float | None:
        if self.list_price and self.list_price > self.price:
            return round(self.list_price - self.price, 2)
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["discount_pct"] = self.discount_pct
        d["effective_discount_pct"] = self.effective_discount_pct
        d["saving"] = self.saving
        d["price_change"] = self.price_change
        d["is_all_time_low"] = self.is_all_time_low
        return d

    def dedup_key(self) -> tuple:
        return (self.shop, self.url.split("?")[0])


@dataclass
class ShopResult:
    """Outcome of scraping one shop - success or a stated reason for failure."""

    key: str
    name: str
    source_url: str
    offers: list[Offer] = field(default_factory=list)
    scanned: int = 0            # products seen before filtering
    sold_out: int = 0           # over the discount threshold but not buyable
    pages: int = 0
    error: str = ""
    skipped_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.skipped_reason


# --------------------------------------------------------------------------
# German price / size parsing helpers
# --------------------------------------------------------------------------

_PRICE_RE = re.compile(r"(\d{1,3}(?:[.   ]\d{3})*|\d+)(?:,(\d{1,2}|-))?")


def parse_price(text: str) -> float | None:
    """Parse a German price string.

    Handles '4.399,- €', '1.590,00 €', 'ab 1.999,00 €', 'UVP 3.199,00 €',
    '2.499,00 €*' and plain '3099.00'.
    """
    if text is None:
        return None
    s = str(text).replace(" ", " ").replace("&nbsp;", " ").strip()
    if not s:
        return None

    # Plain machine-readable decimal (Shopify / JSON-LD): 3099.00, 1590
    if re.fullmatch(r"\d+(\.\d{1,2})?", s):
        return float(s)

    m = _PRICE_RE.search(s)
    if not m:
        return None
    whole = re.sub(r"[.   ]", "", m.group(1))
    frac = m.group(2)
    if frac in (None, "-"):
        frac = "0"
    try:
        return round(float(f"{whole}.{frac.ljust(2, '0')}"), 2)
    except ValueError:
        return None


def parse_percent(text: str) -> float | None:
    """Parse '-61%', '(23.09% gespart)', '15.00 %', '5%'."""
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(text))
    if not m:
        return None
    return round(float(m.group(1).replace(",", ".")), 2)


# Sizes we accept as frame sizes / frame heights.
_SIZE_PATTERNS = [
    re.compile(r"^\d{2}(?:[.,]\d)?\s*(?:cm|zoll|\")?$", re.I),   # 45, 55 cm, 19"
    re.compile(r"^(?:XX?S|XS|S|M|L|XL|XXL|XXXL|X?[SL])$", re.I),  # S, M, L, XL
    re.compile(r"^S[1-6]$|^M[1-6]$|^L[1-6]$", re.I),              # Specialized S1..S6
    re.compile(r"^\d{2}\s*/\s*\d{2}$"),                           # 48/52
    # bikeexchange prints both unit systems: '15" | 38.1cm'
    re.compile(r'^\d{2}\s*"?\s*\|\s*\d{2}(?:[.,]\d)?\s*cm$', re.I),
    # Cargo and compact bikes really do come in one size only.
    re.compile(r"^(?:one[\s-]?size|einheitsgr(ö|oe)(ss|ß)e|uni)$", re.I),
]

_SIZE_NOISE = re.compile(
    r"farbe|color|colour|jahr|year|modell|variante|ausf|zustand|akku|motor|rahmenform",
    re.I,
)


def looks_like_size(value: str) -> bool:
    v = (value or "").strip()
    if not v or len(v) > 24:
        return False
    if _SIZE_NOISE.search(v):
        return False
    v = re.sub(r"\s*\((?:[^)]*)\)\s*$", "", v).strip()  # 'S (45cm)' -> 'S'
    return any(p.match(v) for p in _SIZE_PATTERNS)


def normalise_size(value: str) -> str:
    v = re.sub(r"\s+", " ", (value or "").strip(" -/·|"))
    if re.fullmatch(r"one[\s-]?size|uni", v, re.I):
        return "Einheitsgröße"
    return v


# Words that reveal why a bike is cheap. A 70%-off bike is usually not simply
# last year's model, and the buyer should see that before clicking.
_CONDITION_HINTS = [
    (re.compile(r"leasingr(ü|ue)ckl(ä|ae)ufer", re.I), "Leasingrückläufer"),
    (re.compile(r"testbike|testrad", re.I), "Testbike"),
    (re.compile(r"vorf(ü|ue)hr", re.I), "Vorführmodell"),
    (re.compile(r"lackschaden|kratzer", re.I), "Lackschaden"),
    (re.compile(r"2\.[\s-]?wahl|b-?ware", re.I), "2. Wahl"),
    (re.compile(r"refurbish", re.I), "refurbished"),
    (re.compile(r"gebraucht|second[\s-]?hand", re.I), "gebraucht"),
    (re.compile(r"ausstellungsst(ü|ue)ck", re.I), "Ausstellungsstück"),
]


# "800 Wh", "720Wh", "625 wh". The leading \b matters: without it "12000 Wh"
# would match its trailing "2000". The range check then rejects what is left.
_BATTERY_RE = re.compile(r"\b(\d{3,4})\s*wh\b", re.I)


def parse_battery_wh(*texts: str) -> int | None:
    """Battery capacity in Wh from free text, or None."""
    for text in texts:
        if not text:
            continue
        for m in _BATTERY_RE.finditer(str(text)):
            wh = int(m.group(1))
            if 200 <= wh <= 2000:
                return wh
    return None


def detect_condition(*texts: str) -> str:
    """Return a short condition label found in a title/URL, else ''."""
    haystack = " ".join(t for t in texts if t)
    found = [label for pattern, label in _CONDITION_HINTS if pattern.search(haystack)]
    return ", ".join(dict.fromkeys(found))


def dedup_sizes(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = normalise_size(v)
        if not v:
            continue
        k = v.lower().replace(" ", "")
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out
