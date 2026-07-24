"""Cache ansehen und gezielt aufräumen.

    python cache_tool.py                          # Übersicht nach Shop und Typ
    python cache_tool.py --shop fahrrad24         # nur dieser Shop
    python cache_tool.py --kind product           # nur Produktseiten
    python cache_tool.py --list --shop upway      # einzelne Einträge zeigen
    python cache_tool.py --drop --shop fahrrad24  # diesen Shop verwerfen
    python cache_tool.py --drop-expired           # alles Abgelaufene wegräumen
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from ebikedeals.net import Fetcher


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache", type=Path, default=Path(".cache"))
    p.add_argument("--shop", help="nur Einträge dieses Shops")
    p.add_argument("--kind", help="listing | product | api | robots | rating")
    p.add_argument("--label", help="nur diesen Ausschnitt (z. B. super-e-bike-sale)")
    p.add_argument("--list", action="store_true", help="einzelne Einträge auflisten")
    p.add_argument("--drop", action="store_true", help="passende Einträge löschen")
    p.add_argument("--drop-expired", action="store_true",
                   help="nur abgelaufene Einträge löschen")
    p.add_argument("--ttl", type=float, default=3600.0,
                   help="Gültigkeitsdauer in Sekunden (Standard: 3600)")
    args = p.parse_args()

    if not args.cache.exists():
        print(f"Kein Cache unter {args.cache}")
        return 0

    f = Fetcher(cache_dir=args.cache, cache_ttl=args.ttl, allow_curl_fallback=False)
    try:
        if args.drop or args.drop_expired:
            removed, freed = f.prune_cache(
                shop=args.shop, kind=args.kind, expired_only=not args.drop
            )
            what = "abgelaufene " if not args.drop else ""
            scope = " ".join(filter(None, [
                f"Shop={args.shop}" if args.shop else "",
                f"Typ={args.kind}" if args.kind else "",
            ])) or "alle"
            print(f"{removed} {what}Einträge gelöscht ({human(freed)} frei) — {scope}")
            return 0

        entries = f.cache_entries(shop=args.shop, kind=args.kind, label=args.label)
        if not entries:
            print("Keine passenden Einträge.")
            return 0

        if args.list:
            for e in sorted(entries, key=lambda x: (x["shop"], x["kind"], -x["bytes"])):
                state = "abgelaufen" if e["expired"] else f"{e['age'] / 60:.0f} min alt"
                print(f"  {e['shop']:<16} {e['kind']:<8} {e['label'][:24]:<24} "
                      f"{human(e['bytes']):>9}  {state:<12} {e['url'][:60]}")
            print()

        grouped: dict[tuple[str, str], list] = defaultdict(list)
        for e in entries:
            grouped[(e["shop"], e["kind"])].append(e)

        print(f"{'Shop':<18} {'Typ':<9} {'Einträge':>9} {'Größe':>10} {'davon alt':>10}")
        print("  " + "─" * 58)
        total_n = total_b = 0
        for (shop, kind), items in sorted(grouped.items()):
            size = sum(i["bytes"] for i in items)
            old = sum(1 for i in items if i["expired"])
            total_n += len(items)
            total_b += size
            print(f"{shop:<18} {kind:<9} {len(items):>9} {human(size):>10} {old:>10}")
        print("  " + "─" * 58)
        print(f"{'gesamt':<18} {'':<9} {total_n:>9} {human(total_b):>10}")
        return 0
    finally:
        f.close()


if __name__ == "__main__":
    raise SystemExit(main())
