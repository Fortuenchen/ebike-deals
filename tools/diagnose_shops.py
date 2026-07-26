"""Probe jeden Shop von der aktuellen IP aus - welche blocken, und wie?

Laeuft in GitHub Actions (ubuntu-latest), um zu messen, welche Shops die
Runner-IP abweisen und ob ein anderer Egress (Cloudflare WARP) das behebt.
Kein Ersatz fuer den echten Lauf: nur die erste Listenseite je Shop, damit die
Diagnose schnell bleibt. Wichtig ist die Fehlerart (429 / 403 / Interstitial),
nicht die genaue Angebotszahl.
"""

from __future__ import annotations

import time

import ebikedeals.net as net
from ebikedeals.net import Blocked, Disallowed, Fetcher
from ebikedeals.robots import RobotsCache
from ebikedeals.adapters import ADAPTERS

# Diagnose soll schnell sein: nach 20 s 429-Warten je Host gilt die IP als
# abgewiesen. Fuer die Frage "blockt der Shop diese IP?" reicht das - im echten
# Lauf bleibt das grosszuegige Budget aus net.py.
net.RATE_LIMIT_BUDGET_PER_HOST = 20.0


def main() -> None:
    f = Fetcher(delay=1.0, timeout=45)
    f.robots = RobotsCache(f)

    print(f"{'shop':14} {'ergebnis':9} detail")
    print("-" * 60)
    ok = leer = blocked = err = robots = skip = 0
    kaputt: list[str] = []

    for cls in ADAPTERS:
        a = cls()
        if getattr(a, "skipped_reason", ""):
            print(f"{a.key:14} SKIP      {a.skipped_reason[:44]}")
            skip += 1
            continue
        t = time.time()
        try:
            offers = list(a.scrape(f, max_pages=1))
            dt = time.time() - t
            if offers:
                print(f"{a.key:14} OK        {len(offers)} Angebote ({dt:.0f}s)")
                ok += 1
            else:
                print(f"{a.key:14} LEER      0 Angebote ({dt:.0f}s)")
                leer += 1
                kaputt.append(a.key)
        except Blocked as e:
            print(f"{a.key:14} BLOCKED   {str(e)[:46]}")
            blocked += 1
            kaputt.append(a.key)
        except Disallowed as e:
            print(f"{a.key:14} ROBOTS    {str(e)[:44]}")
            robots += 1
        except Exception as e:
            print(f"{a.key:14} ERROR     {type(e).__name__}: {str(e)[:36]}")
            err += 1
            kaputt.append(a.key)

    print("-" * 60)
    print(f"OK={ok}  LEER={leer}  BLOCKED={blocked}  ERROR={err}  "
          f"ROBOTS={robots}  SKIP={skip}")
    if kaputt:
        print("FEHLERHAFT: " + ", ".join(kaputt))
    f.close()


if __name__ == "__main__":
    main()
