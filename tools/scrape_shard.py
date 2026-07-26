"""Scrape eine Teilmenge der Shops und lege die Ergebnisse als Pickle ab.

Teil des Sharding-Ansatzes (siehe .github/workflows/taeglich.yml): Jeder Shard
laeuft in einem eigenen GitHub-Job mit eigener Cloudflare-WARP-IP. So traegt
keine IP die kumulierte Shopify-Last, an der ein einzelner Lauf sonst scheitert
(upway u.a. bekamen 429, sobald die IP von den anderen Shopify-Shops "verbraucht"
war - einzeln auf frischer IP kommen alle durch).

tools/merge_report.py fuehrt die Pickles danach zu einem Bericht zusammen.
Pickle statt JSON, weil beide Seiten denselben Checkout nutzen und so die
Offer-/ShopResult-Objekte verlustfrei erhalten bleiben (die Artefakte sind
selbst erzeugt, also vertrauenswuerdig).
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebikedeals.runner import RunConfig, run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("shops", nargs="+", help="Shop-Keys dieses Shards")
    ap.add_argument("--out", required=True, type=Path, help="Pickle-Ausgabe")
    ap.add_argument("--render", action="store_true", help="JS-Listings rendern (lucky-bike)")
    ap.add_argument("--min-discount", type=float, default=50.0)
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--collections", default=None,
                    help="nur diese Shopify-Collections (Komma-getrennt, z. B. all)")
    ap.add_argument("--pages", default=None, metavar="START-ENDE",
                    help="nur dieser Seitenbereich je Collection (z. B. 8-16)")
    ap.add_argument("--ratings-out", type=Path, default=None, metavar="PFAD",
                    help="Zusaetzlich Bewertungen ALLER Shops holen und als Cache "
                         "ablegen (laeuft so parallel zu den anderen Shards, statt "
                         "den Merge aufzuhalten). Nur EIN Shard sollte das tun.")
    a = ap.parse_args()

    # Bewusst OHNE history_db und ratings_cache: Preisverlauf und Bewertungen
    # macht der Merge-Schritt einmal ueber alle Shards zusammen.
    only = a.collections.split(",") if a.collections else None
    window = None
    if a.pages:
        start, _, end = a.pages.partition("-")
        window = (int(start), int(end) if end else int(start))
    config = RunConfig(
        min_discount=a.min_discount,
        max_pages=a.max_pages,
        shops=a.shops,
        render=a.render,
        history_db=None,
        ratings_cache=None,
        only_collections=only,
        page_window=window,
    )
    print(f"Shard [{', '.join(a.shops)}] (render={a.render})", file=sys.stderr)
    report = run(config)

    a.out.write_bytes(pickle.dumps(report.results))

    # Bewertungen ALLER Shops holen (nicht nur dieses Shards) - der Merge liest
    # den frischen Cache dann nur noch, statt selbst zu fetchen. So ueberlappt
    # der Abruf mit den schweren Shards, statt hinterher den Merge aufzuhalten.
    if a.ratings_out:
        from ebikedeals import ratings as ratings_mod
        from ebikedeals.adapters import ADAPTERS
        from ebikedeals.net import Fetcher
        from ebikedeals.robots import RobotsCache

        print(f"Bewertungen aller Shops -> {a.ratings_out}", file=sys.stderr)
        rf = Fetcher(delay=0.8)
        rf.robots = RobotsCache(rf)
        try:
            ratings_mod.collect([c() for c in ADAPTERS], rf, a.ratings_out)
        except Exception as e:
            print(f"Bewertungen fehlgeschlagen: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            rf.close()

    offers = sum(len(r.offers) for r in report.results)
    scanned = sum(r.scanned for r in report.results)
    print(f"{offers} Angebote aus {scanned} geprueft -> {a.out}", file=sys.stderr)
    for r in sorted(report.results, key=lambda r: r.key):
        note = r.error or r.skipped_reason or f"{len(r.offers)} Angebote"
        print(f"  {r.key:14} scanned={r.scanned:<6} {note[:44]}", file=sys.stderr)

    # Non-null Exit, wenn ein Shop mit Fehler endete (blockiert/Ausnahme): so
    # färbt sich der GitHub-Job rot und man sieht am Job-Namen sofort, welcher
    # Shop klemmt. Das Pickle ist da schon geschrieben (mit dem Fehler drin), der
    # Merge bekommt es also trotzdem. Übersprungene Shops (bike24) und ein Shop
    # mit 0 Treffern bei sauberem Scan zählen NICHT als Fehler.
    errored = [r.key for r in report.results if r.error]
    if errored:
        print(f"::error::Scrape mit Fehler: {', '.join(errored)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
