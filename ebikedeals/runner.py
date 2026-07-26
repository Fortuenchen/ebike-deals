"""Orchestration: scrape all shops in parallel, filter, enrich, collect."""

from __future__ import annotations

import concurrent.futures as cf
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ADAPTERS, BY_KEY, Adapter
from .cachetags import LISTING, PRODUCT
from .history import PriceHistory
from . import ratings
from .model import Offer, ShopResult, detect_condition, parse_battery_wh
from .net import Blocked, Disallowed, Fetcher
from .render import Renderer
from .robots import RobotsCache
from .sizes import enrich, read_battery_wh, read_og_image, read_prices


@dataclass
class RunConfig:
    min_discount: float = 50.0
    max_pages: int = 8
    workers: int = 5
    delay: float = 0.8
    shops: list[str] = field(default_factory=list)
    respect_robots: bool = True
    fetch_sizes: bool = True
    include_sold_out: bool = False
    #: how many offers per shop get their price verified against the product
    #: page (offers with missing sizes are always fetched and verified anyway)
    price_check_sample: int = 15
    #: SQLite file holding the price series; None disables history
    history_db: Path | None = None
    #: cache file for shop ratings; None disables rating lookup entirely
    ratings_cache: Path | None = None
    #: render JS-only listings with headless Chromium (needs playwright)
    render: bool = False
    cache_dir: Path | None = None
    cache_ttl: float = 3600.0
    #: Nur diese (Shopify-)Collections scrapen, None = alle. Zusammen mit
    #: page_window teilt das einen grossen Shop (upway) auf mehrere Jobs mit je
    #: eigener WARP-IP auf, sodass keine IP an der Seitenzahl ins 429 laeuft.
    only_collections: list[str] | None = None
    #: Nur dieser Seitenbereich (start, ende inklusive) je Collection, None = alle.
    page_window: tuple[int, int] | None = None


@dataclass
class RunReport:
    config: RunConfig
    results: list[ShopResult] = field(default_factory=list)
    history_stats: dict = field(default_factory=dict)
    history_error: str = ""
    render_error: str = ""
    #: {shop key: [Rating, ...]}
    ratings: dict = field(default_factory=dict)

    @property
    def offers(self) -> list[Offer]:
        out: list[Offer] = []
        for r in self.results:
            out.extend(r.offers)
        out.sort(key=lambda o: -(o.effective_discount_pct or 0))
        return out

    @property
    def total_scanned(self) -> int:
        return sum(r.scanned for r in self.results)


def run(config: RunConfig) -> RunReport:
    fetcher = Fetcher(
        cache_dir=config.cache_dir,
        delay=config.delay,
        cache_ttl=config.cache_ttl,
    )
    # Sharding-Fenster (siehe RunConfig): der Adapter liest sie ueber den Fetcher,
    # ohne dass jede scrape()-Signatur sie durchreichen muss.
    fetcher.page_window = config.page_window
    fetcher.only_collections = config.only_collections
    robots = RobotsCache(fetcher)
    if config.respect_robots:
        fetcher.robots = robots

    # Abgelaufene Eintraege raeumen, bevor neue dazukommen - sonst waechst der
    # Cache unbegrenzt, weil ihn nie jemand aufraeumt.
    if config.cache_dir:
        removed, freed = fetcher.prune_cache()
        if removed:
            print(f"Cache: {removed} abgelaufene Eintraege entfernt "
                  f"({freed / 1048576:.0f} MB frei)", file=sys.stderr)

    selected = [BY_KEY[k] for k in config.shops] if config.shops else list(ADAPTERS)
    report = RunReport(config=config)

    renderer = None
    if config.render and any(c.needs_render for c in selected):
        try:
            renderer = Renderer(delay=max(config.delay, 1.2))
            fetcher.renderer = renderer
        except Exception as e:
            report.render_error = str(e)

    try:
        if config.ratings_cache:
            # Independent of the scrape: a shop with no hits today still has a
            # rating worth showing in the source table.
            try:
                report.ratings = ratings.collect(
                    [c() for c in selected], fetcher, config.ratings_cache
                )
            except Exception:
                report.ratings = {}

        with cf.ThreadPoolExecutor(max_workers=config.workers) as pool:
            futures = {
                pool.submit(_scrape_shop, cls(), fetcher, robots, config): cls
                for cls in selected
            }
            for fut in cf.as_completed(futures):
                report.results.append(fut.result())
    finally:
        if renderer is not None:
            renderer.close()
        fetcher.close()

    # History is recorded once for the whole run, after all shops are in, so a
    # single SQLite connection sees a consistent set and threads never contend.
    if config.history_db:
        try:
            history = PriceHistory(config.history_db)
            history.record_and_enrich(report.offers)
            report.history_stats = history.stats()
        except Exception as e:
            report.history_error = f"{type(e).__name__}: {e}"

    report.results.sort(key=lambda r: (-len(r.offers), r.name))
    return report


def _scrape_shop(
    adapter: Adapter, fetcher: Fetcher, robots: RobotsCache, config: RunConfig
) -> ShopResult:
    result = ShopResult(key=adapter.key, name=adapter.name, source_url=adapter.source_url)

    if adapter.needs_render and getattr(fetcher, "renderer", None) is None:
        result.skipped_reason = adapter.skipped_reason
        return result
    if adapter.skipped_reason and not adapter.needs_render:
        result.skipped_reason = adapter.skipped_reason
        return result

    if config.respect_robots:
        verdict = robots.check(adapter.source_url)
        if not verdict.allowed:
            result.skipped_reason = f"robots.txt untersagt diesen Pfad ({verdict.reason})"
            return result

    hits: list[Offer] = []
    try:
        # Der Scope muss waehrend der Iteration aktiv sein, nicht nur beim
        # Erzeugen des Generators - deshalb liegt die Schleife darin. Alles,
        # was der Adapter abruft, landet unter diesem Shop und wird auch nur
        # dort wieder gesucht.
        with fetcher.scope(adapter.key, LISTING):
            for offer in adapter.scrape(fetcher, config.max_pages):
                result.scanned += 1
                discount = offer.effective_discount_pct
                if discount is None or discount < config.min_discount:
                    continue
                if offer.in_stock is False and not config.include_sold_out:
                    result.sold_out += 1
                    continue
                # Titles/URLs plus whatever the adapter already noted
                # (jobrad-loop states "refurbished" in the variant attributes,
                # not the title).
                offer.condition = (
                    detect_condition(offer.title, offer.url, offer.note)
                    or adapter.default_condition
                )
                if offer.battery_wh is None:
                    offer.battery_wh = parse_battery_wh(offer.title, offer.note)
                if offer.condition and offer.condition.lower() not in offer.note.lower():
                    offer.note = " · ".join(filter(None, [offer.note, offer.condition]))
                hits.append(offer)
    except Disallowed as e:
        result.skipped_reason = str(e)
    except Blocked as e:
        result.error = str(e)
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"

    # Deduplicate (a product can appear in two collections of the same shop).
    seen: set[tuple] = set()
    unique: list[Offer] = []
    for o in hits:
        k = o.dedup_key()
        if k in seen:
            continue
        seen.add(k)
        unique.append(o)

    if config.fetch_sizes:
        # Fetching the product page for every hit dominated the runtime once the
        # threshold dropped to 50 % (hundreds of hits per shop). Two facts make
        # that unnecessary: sizes are only missing for some offers, and a
        # listing-vs-detail price discrepancy is a property of the shop's
        # template, not of the individual bike. So: always fetch when sizes are
        # missing, otherwise cross-check only a sample per shop.
        checked = 0
        for offer in unique:
            needs_sizes = not offer.sizes
            if not needs_sizes and checked >= config.price_check_sample:
                continue
            try:
                # Produktseiten liegen getrennt von den Listen: Sie veralten
                # anders und lassen sich so gezielt verwerfen.
                with fetcher.scope(adapter.key, PRODUCT):
                    html = fetcher.get(offer.url)
            except Exception:
                continue
            if needs_sizes:
                offer.sizes = enrich(offer, html)
            if offer.battery_wh is None:
                # Free of charge: the page is already fetched and loaded.
                offer.battery_wh = read_battery_wh(html)
            if not offer.image:
                # Likewise free: rescues listings that build their thumbnails
                # in JavaScript (nubuk), so the static listing HTML had none.
                offer.image = read_og_image(html)
            _cross_check_price(offer, html)
            checked += 1

    unique.sort(key=lambda o: -(o.effective_discount_pct or 0))
    result.offers = unique
    return result


def _cross_check_price(offer: Offer, html: str) -> None:
    """Compare the listing price with the product page and flag disagreement.

    The listing value stays authoritative - it is what the shop advertised and
    what we filtered on - but a mismatch is surfaced rather than hidden, since
    it changes what the buyer will actually pay.
    """
    price, list_price = read_prices(html)
    if price is None:
        return
    offer.detail_price = price
    offer.detail_list_price = list_price

    notes: list[str] = []
    if abs(price - offer.price) > 0.5:
        notes.append(f"Produktseite nennt {price:,.2f} € statt {offer.price:,.2f} €")
    if list_price and offer.list_price and abs(list_price - offer.list_price) > 0.5:
        real = round((1 - offer.price / list_price) * 100, 1)
        notes.append(
            f"UVP auf Produktseite {list_price:,.2f} € (Liste: {offer.list_price:,.2f} €) "
            f"→ effektiv −{real:.1f} %"
        )
    if notes:
        offer.note = " · ".join(filter(None, [offer.note] + notes))
