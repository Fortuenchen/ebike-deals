"""Fuehrt die Shard-Pickles (siehe scrape_shard.py) zu EINEM Bericht zusammen.

Reproduziert den Abschluss von runner.run(): Bewertungen holen, Preisverlauf
schreiben, dann HTML + JSON erzeugen - nur eben auf den bereits gescrapten
Ergebnissen aller Shards statt auf einem einzelnen Lauf.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebikedeals import ratings as ratings_mod  # noqa: E402
from ebikedeals.adapters import ADAPTERS  # noqa: E402
from ebikedeals.history import PriceHistory  # noqa: E402
from ebikedeals.net import Fetcher  # noqa: E402
from ebikedeals.report import write_html, write_json  # noqa: E402
from ebikedeals.robots import RobotsCache  # noqa: E402
from ebikedeals.runner import RunConfig, RunReport  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pickles", nargs="+", type=Path, help="Shard-Pickles")
    ap.add_argument("--out", type=Path, default=Path("bericht.html"))
    ap.add_argument("--json", type=Path, default=Path("deals.json"))
    ap.add_argument("--history", type=Path, default=Path("preise.db"))
    ap.add_argument("--ratings", type=Path, default=Path("bewertungen.json"))
    ap.add_argument("--min-discount", type=float, default=50.0)
    ap.add_argument("--max-pages", type=int, default=8)
    a = ap.parse_args()

    # Shards einsammeln. Ein Shop kann aus MEHREREN Seitenbereich-Shards kommen
    # (upway: sale / all 1-7 / all 8-16). Dann die Angebote zusammenlegen (nach
    # URL entdoppelt) und die Zaehler addieren, statt den zweiten Teil zu
    # verwerfen - sonst fehlte genau der zweite Seitenbereich.
    by_key: dict = {}
    order: list[str] = []
    for p in a.pickles:
        for r in pickle.loads(p.read_bytes()):
            if r.key in by_key:
                base = by_key[r.key]
                have = {o.url.split("?")[0] for o in base.offers}
                base.offers.extend(o for o in r.offers if o.url.split("?")[0] not in have)
                base.scanned += r.scanned
                base.sold_out += r.sold_out
                if r.error and not base.error:
                    base.error = r.error
            else:
                by_key[r.key] = r
                order.append(r.key)
    results = [by_key[k] for k in order]

    config = RunConfig(
        min_discount=a.min_discount,
        max_pages=a.max_pages,
        history_db=a.history,
        ratings_cache=a.ratings,
    )
    report = RunReport(config=config, results=results)

    # Bewertungen zentral (unabhaengig vom Scrape). Best-effort: scheitert der
    # Abruf, bleibt der Bericht ohne Bewertungen, statt ganz zu kippen.
    try:
        f = Fetcher(delay=0.8)
        f.robots = RobotsCache(f)
        report.ratings = ratings_mod.collect([c() for c in ADAPTERS], f, a.ratings)
        f.close()
    except Exception as e:
        print(f"Bewertungen uebersprungen: {type(e).__name__}: {e}", file=sys.stderr)
        report.ratings = {}

    # Preisverlauf einmal ueber alle Shards schreiben.
    try:
        hist = PriceHistory(a.history)
        hist.record_and_enrich(report.offers)
        report.history_stats = hist.stats()
    except Exception as e:
        report.history_error = f"{type(e).__name__}: {e}"
        print(f"History-Fehler: {report.history_error}", file=sys.stderr)

    report.results.sort(key=lambda r: (-len(r.offers), r.name))
    write_html(report, a.out)
    write_json(report, a.json)

    print(f"Zusammengefuehrt: {len(report.offers)} Angebote aus "
          f"{report.total_scanned} geprueft, {len(results)} Shops", file=sys.stderr)
    for r in sorted(report.results, key=lambda r: r.key):
        note = r.error or r.skipped_reason or f"{len(r.offers)} Angebote"
        print(f"  {r.key:14} scanned={r.scanned:<6} {note[:44]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
