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
    a = ap.parse_args()

    # Bewusst OHNE history_db und ratings_cache: Preisverlauf und Bewertungen
    # macht der Merge-Schritt einmal ueber alle Shards zusammen.
    config = RunConfig(
        min_discount=a.min_discount,
        max_pages=a.max_pages,
        shops=a.shops,
        render=a.render,
        history_db=None,
        ratings_cache=None,
    )
    print(f"Shard [{', '.join(a.shops)}] (render={a.render})", file=sys.stderr)
    report = run(config)

    a.out.write_bytes(pickle.dumps(report.results))

    offers = sum(len(r.offers) for r in report.results)
    scanned = sum(r.scanned for r in report.results)
    print(f"{offers} Angebote aus {scanned} geprueft -> {a.out}", file=sys.stderr)
    for r in sorted(report.results, key=lambda r: r.key):
        note = r.error or r.skipped_reason or f"{len(r.offers)} Angebote"
        print(f"  {r.key:14} scanned={r.scanned:<6} {note[:44]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
