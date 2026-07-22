"""Check that reported offer URLs actually resolve.

Samples a few offers per shop by default so a run with hundreds of hits stays
quick; pass --all to check every one.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ebikedeals.net import Fetcher

PER_SHOP = 3

offers = json.loads(Path("deals.json").read_text(encoding="utf-8"))["offers"]
if "--all" not in sys.argv:
    by_shop = defaultdict(list)
    for o in offers:
        by_shop[o["shop"]].append(o)
    offers = [o for group in by_shop.values() for o in group[:PER_SHOP]]

f = Fetcher(delay=0.5)
stat = Counter()
bad = []

for o in offers:
    try:
        body = f.get(o["url"], use_cache=False)
        token = (o["title"].split()[0] or "").lower()
        hit = token in body.lower() if token else True
        stat[f"200 {'ok' if hit else 'title-missing'}"] += 1
        if not hit:
            bad.append((o["shop"], o["url"], "Titel nicht auf der Seite gefunden"))
    except Exception as e:
        stat[type(e).__name__] += 1
        bad.append((o["shop"], o["url"], f"{type(e).__name__}: {e}"))

print(f"geprüft: {len(offers)}")
for k, v in stat.most_common():
    print(f"  {k}: {v}")
if bad:
    print("\nProbleme:")
    for shop, url, why in bad[:20]:
        print(f"  [{shop}] {why}\n     {url}")
f.close()
