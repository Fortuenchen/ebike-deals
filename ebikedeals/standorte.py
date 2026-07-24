"""Standorte und Entfernungen.

Zwei Ebenen, die man nicht verwechseln darf:

* **Filiale** — dieses konkrete Rad steht dort. fahrrad-xxl weist das je Artikel
  aus (`data-availableonbranch`), und nur das erlaubt die Aussage "in Dresden
  abholbar".
* **Firmensitz** — der Shop hat dort ein Ladengeschäft, über *dieses* Rad sagt
  das nichts. Reine Versender tauchen hier gar nicht auf.

Die Koordinaten stehen in `standorte.json` und werden einmalig von
`geocode_standorte.py` bestimmt, nicht bei jedem Lauf. Damit braucht der
Scanner keinen Geocoder.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

STANDORTE_DATEI = "standorte.json"


@lru_cache(maxsize=1)
def _laden(pfad: str = STANDORTE_DATEI) -> dict:
    p = Path(pfad)
    if not p.exists():
        return {"filialen": {}, "shops": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"filialen": {}, "shops": {}}


def bezugsorte() -> list[dict]:
    """Staedte, die Nutzern als Standortangabe dienen."""
    return sorted(_laden().get("bezugsorte", {}).values(), key=lambda e: e["ort"])


def filiale(branch_id: str | int) -> dict | None:
    return _laden().get("filialen", {}).get(str(branch_id))


def shop_ort(shop_key: str) -> dict | None:
    return _laden().get("shops", {}).get(shop_key)


def orte_fuer(shop_key: str, branches: list[str]) -> list[dict]:
    """Alle Orte, an denen ein Angebot greifbar ist - Filialen zuerst.

    Filialen sind die stärkere Aussage: Sie gelten für genau dieses Rad. Der
    Firmensitz zählt nur, wenn keine Filialangabe vorliegt.
    """
    treffer = [f for f in (filiale(b) for b in branches) if f]
    if treffer:
        return treffer
    sitz = shop_ort(shop_key)
    return [sitz] if sitz else []


def entfernung_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie in Kilometern (Haversine).

    Luftlinie, nicht Fahrstrecke - das ist für "welche Angebote sind in meiner
    Nähe" genau genug und braucht keinen Routing-Dienst.
    """
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def alle_orte() -> list[dict]:
    """Jeder bekannte Ort einmal, für die Auswahl im Bericht."""
    daten = _laden()
    gesehen: dict[str, dict] = {}
    for eintrag in list(daten.get("filialen", {}).values()) + \
            list(daten.get("shops", {}).values()):
        if eintrag and eintrag.get("ort") not in gesehen:
            gesehen[eintrag["ort"]] = eintrag
    return sorted(gesehen.values(), key=lambda e: e["ort"])
