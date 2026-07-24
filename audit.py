"""Audit every adapter's output for the mistakes that hide behind plausible data.

Each shop is scraped for two pages and checked against invariants that held for
every shop when the adapters were written. A violation is either a shop change
or an adapter bug - both are worth seeing before trusting a report.

    python audit.py            # all shops
    python audit.py upway      # one shop
    python audit.py --render   # include shops that need a browser
"""

import re
import sys
from collections import Counter
from pathlib import Path

from ebikedeals.adapters import ADAPTERS, BY_KEY
from ebikedeals.cachetags import LISTING
from ebikedeals.model import looks_like_size
from ebikedeals.net import Fetcher
from ebikedeals.render import Renderer
from ebikedeals.robots import RobotsCache

PAGES = 2
CACHE = Path(__file__).parent / ".cache"

# MTB frames really are sized 15"-23", so only sizes no frame can have count as
# a wheel-size mix-up. 26" is included: it is a classic wheel size and there is
# no 26" frame.
WHEEL_SIZE = re.compile(r'^(26|27[,.]5|28|29)\s*("|zoll)$', re.I)


def audit(adapter, fetcher) -> list[str]:
    problems: list[str] = []
    offers = []
    try:
        # Derselbe Cache-Kontext wie im Runner. Ohne ihn landeten die Abrufe im
        # abgeleiteten Fach (`upway.de/api` statt `upway/listing`), Audit und
        # Lauf teilten sich nichts und fragten die Shops doppelt.
        with fetcher.scope(adapter.key, LISTING):
            for o in adapter.scrape(fetcher, PAGES):
                offers.append(o)
    except Exception as e:
        return [f"scrape schlug fehl: {type(e).__name__}: {e}"]

    if not offers:
        return ["keine Produkte geliefert - Adapter oder Kategorie pruefen"]

    urls = Counter(o.url for o in offers)
    dupes = [u for u, n in urls.items() if n > 1]
    if dupes:
        problems.append(f"{len(dupes)} doppelte URLs (Dedup greift nicht)")

    rel = [o.url for o in offers if not o.url.startswith("http")]
    if rel:
        problems.append(f"{len(rel)} relative URLs, z. B. {rel[0][:60]}")

    no_title = [o for o in offers if not o.title.strip()]
    if no_title:
        problems.append(f"{len(no_title)} Angebote ohne Titel")

    bad_price = [o for o in offers if not o.price or o.price <= 0]
    if bad_price:
        problems.append(f"{len(bad_price)} Angebote mit Preis <= 0")

    cheap = [o for o in offers if o.price and 0 < o.price < 150]
    if cheap:
        problems.append(
            f"{len(cheap)} Angebote unter 150 € - vermutlich Zubehör statt Rad "
            f"(z. B. {cheap[0].title[:40]!r} {cheap[0].price} €)"
        )

    inverted = [o for o in offers if o.list_price and o.list_price < o.price]
    if inverted:
        problems.append(f"{len(inverted)} Angebote mit UVP < Verkaufspreis")

    extreme = [o for o in offers if (o.effective_discount_pct or 0) > 95]
    if extreme:
        problems.append(
            f"{len(extreme)} Angebote über 95 % Rabatt - Streichpreis prüfen "
            f"(z. B. {extreme[0].title[:36]!r})"
        )

    with_list = [o for o in offers if o.list_price]
    if not with_list:
        problems.append("kein einziger Streichpreis erkannt - Selektor prüfen")

    # Accessories and non-bikes leaking in from a broad category: upway's "all"
    # collection mixes in insurance policies and bike parts.
    cheap_share = len([o for o in offers if o.price and o.price < 400]) / len(offers)
    if cheap_share > 0.05:
        problems.append(
            f"{cheap_share:.0%} der Angebote unter 400 € - vermutlich Zubehör "
            f"in einer zu breiten Kategorie"
        )

    # A shop where every product is "sold out" is almost always an adapter bug,
    # not a shop with an empty warehouse - and it is invisible in the report
    # because those offers are filtered out before they are ever shown.
    known_stock = [o for o in offers if o.in_stock is not None]
    if known_stock and not any(o.in_stock for o in known_stock):
        problems.append(
            f"alle {len(known_stock)} Angebote gelten als ausverkauft - "
            f"Verfügbarkeitslogik prüfen"
        )
    elif known_stock:
        # A category that is mostly sold out may be an archive rather than live
        # stock - upway's "all" holds 3500 bikes of which 126 are buyable, and
        # picking it over "sale" once cost 646 real offers. But scanning an
        # archive *in addition* to live stock is legitimate, so the ratio alone
        # is not the signal: what matters is whether anything buyable came back.
        available = sum(1 for o in known_stock if o.in_stock)
        sold_share = 1 - available / len(known_stock)
        if sold_share > 0.7 and available < 50:
            problems.append(
                f"{sold_share:.0%} ausverkauft und nur {available} lieferbare Angebote - "
                f"Kategorie prüfen, das sieht nach Archiv statt Lagerbestand aus"
            )

    # Sizes must be frame sizes, never wheel sizes.
    wheels = [
        (o.title, s) for o in offers for s in o.sizes if WHEEL_SIZE.match(s.strip())
    ]
    if wheels:
        problems.append(
            f"{len(wheels)} Größen sehen nach Laufradgröße aus, z. B. {wheels[0][1]!r}"
        )

    junk = [
        (o.title, s)
        for o in offers
        for s in o.sizes
        if not looks_like_size(s) and not s.startswith("für Körpergröße")
    ]
    if junk:
        problems.append(f"{len(junk)} unplausible Größenwerte, z. B. {junk[0][1]!r}")

    huge = [o for o in offers if len(o.sizes) > 12]
    if huge:
        problems.append(
            f"{len(huge)} Angebote mit >12 Größen - vermutlich eine Größentabelle"
        )

    # Shop-wide condition should be visible on every offer of such a shop.
    if adapter.default_condition and any(not o.title for o in offers):
        problems.append("default_condition gesetzt, aber Titel fehlen")

    return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    use_render = "--render" in sys.argv
    keys = args or [a.key for a in ADAPTERS]

    fetcher = Fetcher(cache_dir=CACHE, delay=0.6)
    fetcher.robots = RobotsCache(fetcher)
    renderer = Renderer(delay=1.2) if use_render else None
    if renderer is not None:
        fetcher.renderer = renderer

    failed = 0
    for key in keys:
        cls = BY_KEY.get(key)
        if cls is None:
            print(f"?? unbekannter Shop {key}")
            continue
        adapter = cls()
        if adapter.needs_render and renderer is None:
            print(f"--  {adapter.name:24s} übersprungen (braucht --render)")
            continue
        if adapter.skipped_reason and not adapter.needs_render:
            print(f"--  {adapter.name:24s} übersprungen ({adapter.skipped_reason[:44]})")
            continue
        problems = audit(adapter, fetcher)
        if problems:
            failed += 1
            print(f"!!  {adapter.name}")
            for p in problems:
                print(f"      - {p}")
        else:
            print(f"OK  {adapter.name}")
    if renderer is not None:
        renderer.close()
    fetcher.close()
    print(f"\n{len(keys) - failed}/{len(keys)} ohne Befund")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
