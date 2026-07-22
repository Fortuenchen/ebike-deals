"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .adapters import ADAPTERS
from .report import print_console, write_html, write_json
from .runner import RunConfig, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ebike-deals",
        description="Findet E-Bike-Angebote mit hohem Rabatt über mehrere Shops "
                    "und listet Direktlink plus verfügbare Größen/Rahmenhöhen.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Shops: " + ", ".join(a.key for a in ADAPTERS),
    )
    p.add_argument("-d", "--min-discount", type=float, default=50.0,
                   help="Mindestrabatt in Prozent (Standard: 50)")
    p.add_argument("-p", "--max-pages", type=int, default=8,
                   help="Maximale Listenseiten je Shop (Standard: 8)")
    p.add_argument("-s", "--shop", action="append", dest="shops", metavar="KEY",
                   help="nur diesen Shop scrapen (mehrfach möglich)")
    p.add_argument("-w", "--workers", type=int, default=5,
                   help="parallele Shops (Standard: 5)")
    p.add_argument("--delay", type=float, default=0.8,
                   help="Mindestpause je Host in Sekunden (Standard: 0.8)")
    p.add_argument("-o", "--out", type=Path, default=Path("bericht.html"),
                   help="HTML-Bericht (Standard: bericht.html)")
    p.add_argument("--json", type=Path, default=None, help="zusätzlich JSON schreiben")
    p.add_argument("--no-sizes", action="store_true",
                   help="Produktseiten für fehlende Größen nicht nachladen")
    p.add_argument("--include-sold-out", action="store_true",
                   help="auch ausverkaufte Artikel listen (Standard: nur kaufbare)")
    p.add_argument("--price-check", type=int, default=15, metavar="N",
                   help="Preise von N Treffern je Shop gegen die Produktseite prüfen "
                        "(Standard: 15, 0 = aus)")
    p.add_argument("--ignore-robots", action="store_true",
                   help="robots.txt ignorieren (standardmäßig wird sie beachtet)")
    p.add_argument("--cache", type=Path, default=None,
                   help="Verzeichnis für HTTP-Cache (beschleunigt Wiederholungsläufe)")
    p.add_argument("--history", type=Path, default=Path("preise.db"),
                   help="SQLite-Datei für den Preisverlauf (Standard: preise.db)")
    p.add_argument("--no-history", action="store_true",
                   help="Preisverlauf weder lesen noch schreiben")
    p.add_argument("--open", action="store_true", help="Bericht im Browser öffnen")
    p.add_argument("--quiet", action="store_true", help="keine Konsolenliste ausgeben")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    valid = {a.key for a in ADAPTERS}
    for key in args.shops or []:
        if key not in valid:
            print(f"Unbekannter Shop: {key}\nVerfügbar: {', '.join(sorted(valid))}",
                  file=sys.stderr)
            return 2

    config = RunConfig(
        min_discount=args.min_discount,
        max_pages=args.max_pages,
        workers=args.workers,
        delay=args.delay,
        shops=args.shops or [],
        respect_robots=not args.ignore_robots,
        fetch_sizes=not args.no_sizes,
        include_sold_out=args.include_sold_out,
        price_check_sample=args.price_check,
        cache_dir=args.cache,
        history_db=None if args.no_history else args.history,
    )

    print(f"Scanne {len(config.shops) or len(ADAPTERS)} Shops "
          f"(≥ {config.min_discount:.0f} % Rabatt, bis {config.max_pages} Seiten/Shop) …",
          file=sys.stderr)

    report = run(config)

    if not args.quiet:
        print_console(report)

    write_html(report, args.out)
    print(f"HTML-Bericht: {args.out.resolve()}", file=sys.stderr)
    if args.json:
        write_json(report, args.json)
        print(f"JSON:         {args.json.resolve()}", file=sys.stderr)
    if args.open:
        webbrowser.open(args.out.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
