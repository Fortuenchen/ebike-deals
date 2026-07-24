"""Plausibilitätsprüfung nach einem automatischen Lauf.

Ein Scraper, der aus einem Rechenzentrum läuft, wird irgendwann von einem Teil
der Shops abgewiesen. Das Ergebnis ist dann kein Fehler, sondern ein *kleinerer*
Bericht — und der sähe aus wie ein Tag mit wenigen Angeboten. Ohne Prüfung
würde so ein Lauf die gute Historie überschreiben und niemandem auffallen.

Der Vergleich läuft gegen den letzten Tag in `preise.db` und ist damit
selbstkalibrierend: Es gibt keine feste Erwartung, sondern nur die Aussage
"deutlich weniger als gestern ist verdächtig".

Exit-Code 1 heißt: Ergebnis nicht übernehmen.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

DEALS = Path(os.environ.get("DEALS_JSON", "deals.json"))
HISTORY = Path(os.environ.get("HISTORY_DB", "preise.db"))

#: Unterschreitet der Lauf diesen Anteil des Vortages, gilt er als kaputt.
MIN_RATIO = float(os.environ.get("MIN_RATIO", "0.5"))
#: Absolute Untergrenze für den allerersten Lauf, wenn es noch keinen Vortag gibt.
MIN_OFFERS = int(os.environ.get("MIN_OFFERS", "200"))
#: So viele Shops dürfen mit einem Fehler enden, bevor der Lauf verworfen wird.
MAX_ERROR_SHOPS = int(os.environ.get("MAX_ERROR_SHOPS", "3"))


def previous_day_count(db_path: Path, today: str) -> tuple[str, int] | None:
    """(Datum, Angebotszahl) des letzten Laufs vor heute."""
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as db:
            row = db.execute(
                "SELECT seen_on, COUNT(*) FROM prices WHERE seen_on < ? "
                "GROUP BY seen_on ORDER BY seen_on DESC LIMIT 1",
                (today,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return (row[0], row[1]) if row else None


def main() -> int:
    if not DEALS.exists():
        print(f"FEHLER: {DEALS} wurde nicht geschrieben - der Lauf ist abgebrochen.")
        return 1

    data = json.loads(DEALS.read_text(encoding="utf-8"))
    offers = data.get("offers") or []
    shops = data.get("shops") or []

    # Bewusst übersprungene Shops (bike24, lucky-bike ohne --render) sind kein
    # Fehler - sie stehen mit Begründung im Bericht.
    errored = [s for s in shops if s.get("error")]
    active = [s for s in shops if not s.get("error") and not s.get("skipped_reason")]
    empty = [s for s in active if s.get("scanned", 0) == 0]

    print(f"Angebote:            {len(offers)}")
    print(f"Shops gesamt:        {len(shops)}")
    print(f"  mit Fehler:        {len(errored)}  {[s['key'] for s in errored]}")
    print(f"  übersprungen:      {sum(1 for s in shops if s.get('skipped_reason'))}")
    print(f"  aktiv, 0 Produkte: {len(empty)}  {[s['key'] for s in empty]}")

    problems: list[str] = []

    if len(errored) > MAX_ERROR_SHOPS:
        problems.append(
            f"{len(errored)} Shops mit Fehler (erlaubt: {MAX_ERROR_SHOPS}) - "
            f"sieht nach Blockade der Runner-IP aus"
        )

    if empty:
        # Kein Abbruch: ein einzelner Shop ohne Treffer kann echt sein. Aber
        # sichtbar, weil genau das schon einmal ein stiller Fehlschlag war.
        print(f"HINWEIS: {len(empty)} aktive Shops lieferten 0 Produkte")

    today = date.today().isoformat()
    prev = previous_day_count(HISTORY, today)
    if prev:
        prev_day, prev_count = prev
        ratio = len(offers) / prev_count if prev_count else 1.0
        print(f"Vortag ({prev_day}):    {prev_count} Angebote  →  {ratio:.0%}")
        if ratio < MIN_RATIO:
            problems.append(
                f"nur {ratio:.0%} der Angebote von {prev_day} "
                f"({len(offers)} statt {prev_count})"
            )
    else:
        print("Vortag:              keine Historie - absolute Untergrenze greift")
        if len(offers) < MIN_OFFERS:
            problems.append(f"nur {len(offers)} Angebote (Minimum {MIN_OFFERS})")

    if problems:
        print()
        for p in problems:
            print(f"FEHLER: {p}")
        print("\nErgebnis wird nicht übernommen.")
        return 1

    print("\nLauf plausibel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
