"""Adapter registry - one entry per shop URL the user asked for."""

from __future__ import annotations

from .base import Adapter
from .bunnyhop import BunnyHop
from .canyon import Canyon
from .custom_html import FahrradXXL, NubukBikes, Rad1, Radfieber
from .fischer import FischerBike
from .liquid_life import LiquidLife
from .js_apps import BikeExchange, JobradLoop
from .luckybike import LuckyBike
from .magento import DasRadhaus, Fahrrad24, Fahrradlagerverkauf
from .rosebikes import RoseBikes
from .shopify import Bikester, BikeMarket24, Boc24, EBikeOnly, FahrradDe, Upway
from .stadler import ZweiradStadler
from .shopware6 import BikeAngebot, BikeDiscount, Denfeld, MhwBike, RadweltShop, Statera
from .woocommerce import EbikeStock


class Bike24(Adapter):
    """bike24.de is behind Akamai Bot Manager.

    Every request without a solved JS challenge gets an interstitial. Solving
    that challenge means defeating bot detection, so this adapter deliberately
    does nothing and the report links the pre-filtered sale URL instead.
    """

    key = "bike24"
    name = "bike24.de"
    source_url = "https://www.bike24.de/e-bikes.html?saleOnly=1"
    skipped_reason = (
        "Akamai-Bot-Schutz mit JS-Challenge. Automatisches Umgehen wäre ein Bypass "
        "der Bot-Erkennung — bewusst nicht implementiert. Bitte manuell prüfen."
    )

    def scrape(self, fetcher, max_pages):
        return iter(())


ADAPTERS: list[type[Adapter]] = [
    # the 14 shops from the original brief
    Fahrrad24,
    FahrradXXL,
    Fahrradlagerverkauf,
    BikeMarket24,
    Radfieber,
    BikeExchange,
    BikeAngebot,
    Rad1,
    LuckyBike,
    JobradLoop,
    Boc24,
    Denfeld,
    BikeDiscount,
    Bike24,
    # added later, all entered through their own sale/outlet listing
    EBikeOnly,
    FahrradDe,
    MhwBike,
    RadweltShop,
    NubukBikes,
    Upway,
    EbikeStock,
    RoseBikes,
    DasRadhaus,
    ZweiradStadler,
    Bikester,
    Statera,
    FischerBike,
    Canyon,
    LiquidLife,
    BunnyHop,
]

BY_KEY = {a.key: a for a in ADAPTERS}

__all__ = ["ADAPTERS", "BY_KEY", "Adapter"]
