"""Standorte einmalig geokodieren und als Datei ablegen.

Läuft nicht bei jedem Scan, sondern nur wenn Standorte dazukommen. Das
Ergebnis (`standorte.json`) wird versioniert — so braucht der eigentliche Lauf
keinen Geocoder und keine Netzverbindung dorthin.

Quelle ist Nominatim (OpenStreetMap). Deren Nutzungsregeln verlangen höchstens
eine Anfrage pro Sekunde und einen identifizierenden User-Agent; beides hält
dieses Skript ein. Es sind rund 35 Abfragen, einmalig — das ist ausdrücklich
erlaubter Gebrauch, kein Bulk-Geocoding.

    python geocode_standorte.py            # fehlende Orte ergänzen
    python geocode_standorte.py --force    # alles neu bestimmen
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim verlangt einen aussagekräftigen User-Agent mit Kontaktmöglichkeit.
UA = "ebike-deals/1.0 (https://github.com/Fortuenchen/ebike-deals)"
OUT = Path("standorte.json")

#: Filialen von fahrrad-xxl. Die IDs stammen aus dem Filter des Listings
#: (`data-branch_id`) und tauchen je Artikel unter `data-availableonbranch` auf.
FAHRRADXXL_FILIALEN = {
    3: "Münster", 5: "Halle (Saale)", 7: "Gelsenkirchen", 8: "Dresden",
    9: "Sankt Augustin", 10: "Mülheim-Kärlich", 11: "Chemnitz", 12: "Koblenz",
    13: "Mainz", 14: "Ludwigshafen am Rhein", 15: "Esslingen am Neckar",
    16: "Bochum", 19: "Griesheim", 42: "Taucha", 44: "Fürth",
    47: "Dortmund", 54: "Plankstadt", 56: "Pforzheim",
}

#: Sitz der Shops. Nur Häuser mit echtem Ladengeschäft oder Abholung sind für
#: eine regionale Suche interessant; reine Versender stehen hier bewusst nicht.
SHOP_ORTE = {
    "fahrrad24": "Karlsruhe",
    "bikemarket24": "Rostock",
    "bikediscount": "Bonn",
    "denfeld": "Hagen",
    "rad1": "Kiel",
    "radfieber": "Hamburg",
    "lagerverkauf": "Konstanz",
    "mhwbike": "Hövelhof",
    "radwelt": "Rendsburg",
    "nubuk": "Ravensburg",
    "bikeangebot": "Sulzbach",
    "ebikestock": "Berlin",
}


#: Bezugsorte für Nutzer, in deren Nähe kein Shop sitzt. Ohne diese Liste
#: könnte nur wählen, wer zufällig in einer Filialstadt wohnt.
BEZUGSORTE = [
    "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main", "Stuttgart",
    "Düsseldorf", "Leipzig", "Dortmund", "Essen", "Bremen", "Dresden",
    "Hannover", "Nürnberg", "Duisburg", "Bochum", "Wuppertal", "Bielefeld",
    "Bonn", "Münster", "Karlsruhe", "Mannheim", "Augsburg", "Wiesbaden",
    "Mönchengladbach", "Gelsenkirchen", "Braunschweig", "Kiel", "Aachen",
    "Halle (Saale)", "Magdeburg", "Freiburg im Breisgau", "Krefeld", "Lübeck",
    "Oberhausen", "Erfurt", "Rostock", "Kassel", "Hagen", "Saarbrücken",
    "Potsdam", "Regensburg", "Würzburg", "Osnabrück", "Ulm", "Heidelberg",
    "Ingolstadt", "Darmstadt", "Trier", "Koblenz",
]


def geocode(client: httpx.Client, ort: str) -> dict | None:
    r = client.get(
        NOMINATIM,
        params={"q": f"{ort}, Deutschland", "format": "jsonv2", "limit": 1,
                "countrycodes": "de"},
        headers={"User-Agent": UA, "Accept-Language": "de"},
    )
    if r.status_code != 200:
        return None
    hits = r.json()
    if not hits:
        return None
    h = hits[0]
    return {
        "ort": ort,
        "lat": round(float(h["lat"]), 5),
        "lon": round(float(h["lon"]), 5),
        "name": h.get("display_name", "")[:90],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="auch vorhandene neu bestimmen")
    args = p.parse_args()

    data = {"filialen": {}, "shops": {}, "bezugsorte": {},
            "quelle": "OpenStreetMap / Nominatim (ODbL)"}
    if OUT.exists() and not args.force:
        try:
            data.update(json.loads(OUT.read_text(encoding="utf-8")))
        except Exception:
            pass

    todo = [("filialen", str(i), ort) for i, ort in FAHRRADXXL_FILIALEN.items()]
    todo += [("shops", key, ort) for key, ort in SHOP_ORTE.items()]
    todo += [("bezugsorte", ort, ort) for ort in BEZUGSORTE]
    todo = [t for t in todo if args.force or t[1] not in data.get(t[0], {})]

    if not todo:
        print("Alle Standorte bereits bekannt.")
        return 0

    print(f"{len(todo)} Standorte zu bestimmen (1 Anfrage/Sekunde) …")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for bucket, key, ort in todo:
            try:
                hit = geocode(client, ort)
            except Exception as e:
                print(f"  {ort:26s} FEHLER {type(e).__name__}")
                time.sleep(1.1)
                continue
            if hit:
                data.setdefault(bucket, {})[key] = hit
                print(f"  {ort:26s} {hit['lat']:.4f}, {hit['lon']:.4f}")
            else:
                print(f"  {ort:26s} nicht gefunden")
            # Nominatim-Regel: höchstens eine Anfrage pro Sekunde.
            time.sleep(1.1)

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"\n{OUT} geschrieben: {len(data['filialen'])} Filialen, {len(data['shops'])} Shops")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
