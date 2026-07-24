"""Kategorisierung der Cache-Eintraege.

Der Cache war eine flache Halde undurchsichtiger Hashes: `.cache/9f3a....xz`
liess sich weder ansehen noch gezielt ansprechen. Man konnte weder "nur den
Cache von fahrrad24 verwerfen" noch "nur Produktseiten aufraeumen", und ein
Lauf mit `--shop denfeld` fasste denselben Topf an wie ein vollstaendiger Lauf.

Jeder Eintrag traegt jetzt drei Merkmale, die zugleich seinen Ablageort bilden:

    .cache/<shop>/<kind>/<hash>.xz

* **shop**  - der Adapter-Key (`fahrrad24`) oder ersatzweise der Host
* **kind**  - `listing`, `product`, `api`, `robots`, `rating`
* **label** - welcher Ausschnitt des Shops, etwa `super-e-bike-sale`

Gesucht wird ausschliesslich im passenden Fach: Ein Eintrag unter
`fahrrad24/listing` ist nur dann ein Treffer, wenn auch danach gefragt wird.
Das ist nicht bloss Ordnung, sondern verhindert, dass ein Eintrag in einem
Kontext bedient wird, fuer den er nie gedacht war.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Seitentypen. Bewusst wenige - eine Kategorie, die niemand abfragt, ist nur
#: Ballast im Pfad.
LISTING = "listing"
PRODUCT = "product"
API = "api"
ROBOTS = "robots"
RATING = "rating"

#: Pseudo-Shop fuer Eintraege, die keinem Shop-Lauf gehoeren, sondern fuer alle
#: gelten - robots.txt etwa gilt pro Domain, nicht pro Adapter.
SHARED = "_geteilt"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SAFE = re.compile(r"[^a-z0-9._-]")


def _slug(value: str, fallback: str = "-") -> str:
    out = _SLUG_STRIP.sub("-", (value or "").lower()).strip("-")
    return out[:48] or fallback


@dataclass(frozen=True)
class CacheTags:
    """Merkmale eines Cache-Eintrags - zugleich sein Ablagepfad."""

    shop: str = ""
    kind: str = LISTING
    label: str = ""

    def normalised(self) -> "CacheTags":
        return CacheTags(
            shop=_SAFE.sub("-", (self.shop or "unbekannt").lower())[:40],
            kind=_SAFE.sub("-", (self.kind or LISTING).lower())[:20],
            label=_slug(self.label, ""),
        )

    @property
    def parts(self) -> tuple[str, ...]:
        n = self.normalised()
        return (n.shop, n.kind)

    def as_dict(self) -> dict[str, str]:
        n = self.normalised()
        return {"shop": n.shop, "kind": n.kind, "label": n.label}

    def matches(self, shop: str | None = None, kind: str | None = None,
                label: str | None = None) -> bool:
        """Passt der Eintrag auf die gesuchten Merkmale? None heisst egal."""
        n = self.normalised()
        if shop is not None and n.shop != _SAFE.sub("-", shop.lower())[:40]:
            return False
        if kind is not None and n.kind != _SAFE.sub("-", kind.lower())[:20]:
            return False
        if label is not None and n.label != _slug(label, ""):
            return False
        return True


def host_of(url: str) -> str:
    host = (urlsplit(url).netloc or "").lower()
    return host.removeprefix("www.") or "unbekannt"


def derive(url: str, shop: str = "", kind: str = "") -> CacheTags:
    """Tags aus einer URL ableiten, wenn kein Kontext gesetzt ist.

    Der Rueckfall auf den Host haelt jeden Aufruf funktionsfaehig, auch
    solche, die nichts von Tags wissen - der Cache bleibt damit korrekt, nur
    grober sortiert.
    """
    path = urlsplit(url).path
    if not kind:
        if path.rstrip("/").endswith("robots.txt"):
            kind = ROBOTS
        elif path.endswith(".json") or "/api/" in path or "/wp-json/" in path:
            kind = API
        else:
            kind = LISTING
    label = ""
    segments = [s for s in path.split("/") if s]
    if segments:
        last = segments[-1]
        # Dateiendungen sind fuer die Einordnung uninteressant.
        label = _slug(last.rsplit(".", 1)[0] if "." in last else last, "")
    return CacheTags(shop=shop or host_of(url), kind=kind, label=label)
