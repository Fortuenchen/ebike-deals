"""Dev smoke test: run each adapter for 1 page and show what it extracted."""

import sys
from pathlib import Path

from ebikedeals.adapters import ADAPTERS, BY_KEY
from ebikedeals.net import Fetcher

CACHE = Path(__file__).parent / ".cache"


def main() -> None:
    keys = sys.argv[1:] or [a.key for a in ADAPTERS]
    f = Fetcher(cache_dir=CACHE, delay=0.6)
    for key in keys:
        cls = BY_KEY.get(key)
        if cls is None:
            print(f"?? unknown adapter {key}")
            continue
        ad = cls()
        if ad.skipped_reason:
            print(f"\n### {ad.name}: SKIP - {ad.skipped_reason[:70]}")
            continue
        print(f"\n### {ad.name}")
        n = 0
        best = []
        try:
            for offer in ad.scrape(f, max_pages=1):
                n += 1
                d = offer.effective_discount_pct
                best.append((d if d is not None else -1, offer))
        except Exception as e:
            print(f"    ERROR {type(e).__name__}: {e}")
            continue
        best.sort(key=lambda t: -t[0])
        print(f"    products: {n}")
        for d, o in best[:3]:
            print(f"    -{d:5.1f}%  {o.price:>9,.2f} von {str(o.list_price or '-'):>10}  "
                  f"sizes={o.sizes[:5]}  {o.title[:52]}")
            print(f"            {o.url[:110]}")
        if n and not any(d > 0 for d, _ in best):
            print("    !! no discounts parsed - check list-price selector")
    f.close()


if __name__ == "__main__":
    main()
