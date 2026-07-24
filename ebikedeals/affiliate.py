"""Partnerlinks.

Nur zwei Dinge sind hier heikel, und beide sind bewusst so gelöst:

**Kennzeichnung.** Wer mit Links Geld verdient, muss das kenntlich machen
(§ 5a Abs. 4 UWG). Der Bericht blendet den Hinweis deshalb automatisch ein,
sobald mindestens ein Link umgeschrieben wurde — er lässt sich nicht abschalten,
ohne die Partnerlinks selbst abzuschalten. Ein vergessener Hinweis ist
abmahnfähig, und die Entscheidung darf nicht davon abhängen, ob jemand daran
denkt.

**Die Partner-ID gehört nicht ins Repository.** Sie ist kein Geheimnis im
engeren Sinn — sie steht in jedem ausgehenden Link. Aber sie ist Ihre Identität
gegenüber dem Netzwerk: Wer sie kennt, kann sie in fremde Seiten einbauen und
Ihr Konto durch auffälliges Klickverhalten sperren lassen. In einem öffentlichen
Repository hat sie deshalb nichts verloren. `affiliate.json` steht in
`.gitignore`; für den automatischen Lauf gibt es den Weg über GitHub-Secrets.

Ohne Konfiguration passiert nichts: Die Links bleiben unverändert, der Hinweis
erscheint nicht. Die Funktion ist damit ausgeschaltet, bis sie jemand bewusst
einrichtet.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

KONFIG_DATEI = "affiliate.json"
#: Für den CI-Lauf: derselbe Inhalt als JSON in einer Umgebungsvariable.
KONFIG_ENV = "EBIKE_AFFILIATE"


@dataclass
class Partnerlink:
    """Vorlage für einen Shop.

    `template` enthält `{url}` als Platzhalter für die Ziel-URL. Die meisten
    Netzwerke arbeiten so ("Deeplink-Generator"): Sie hängen die Ziel-URL
    kodiert an eine Weiterleitung an.
    """

    shop: str
    template: str
    netzwerk: str = ""

    def anwenden(self, ziel_url: str) -> str:
        if "{url}" not in self.template:
            return ziel_url
        return self.template.replace("{url}", quote(ziel_url, safe=""))


def laden(pfad: str | Path = KONFIG_DATEI) -> dict[str, Partnerlink]:
    """Konfiguration aus Datei oder Umgebungsvariable lesen.

    Die Umgebungsvariable hat Vorrang, damit der automatische Lauf sie über ein
    GitHub-Secret setzen kann, ohne dass eine Datei im Repository liegt.
    """
    roh = os.environ.get(KONFIG_ENV)
    if roh:
        try:
            daten = json.loads(roh)
        except ValueError:
            return {}
    else:
        p = Path(pfad)
        if not p.exists():
            return {}
        try:
            daten = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    out: dict[str, Partnerlink] = {}
    for shop, eintrag in (daten or {}).items():
        if shop.startswith("_"):          # Kommentarfelder überspringen
            continue
        if isinstance(eintrag, str):
            eintrag = {"template": eintrag}
        if not isinstance(eintrag, dict):
            continue
        template = (eintrag.get("template") or "").strip()
        # Ohne Platzhalter wäre es keine Weiterleitung auf das Produkt, sondern
        # ein Link auf die Startseite - das ist fast immer ein Konfigurationsfehler.
        if "{url}" not in template:
            continue
        out[shop] = Partnerlink(
            shop=shop, template=template, netzwerk=eintrag.get("netzwerk", "")
        )
    return out


class Partnerlinks:
    """Wendet die Vorlagen an und zählt, wie oft das geschah."""

    def __init__(self, konfig: dict[str, Partnerlink] | None = None):
        self.konfig = konfig if konfig is not None else laden()
        self.umgeschrieben = 0
        self.shops: set[str] = set()

    @property
    def aktiv(self) -> bool:
        return bool(self.konfig)

    def link(self, shop: str, url: str) -> tuple[str, bool]:
        """(Link, ist_partnerlink). Ohne Vorlage bleibt die URL unverändert."""
        eintrag = self.konfig.get(shop)
        if not eintrag or not url:
            return url, False
        neu = eintrag.anwenden(url)
        if neu == url:
            return url, False
        self.umgeschrieben += 1
        self.shops.add(shop)
        return neu, True

    def netzwerke(self) -> list[str]:
        return sorted({e.netzwerk for e in self.konfig.values() if e.netzwerk})
