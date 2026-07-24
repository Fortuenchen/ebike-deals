"""Preisverlauf ueber mehrere Laeufe.

Alles andere in diesem Projekt ist eine Momentaufnahme: Es kann sagen "60 %
unter UVP", aber nicht "guenstiger als je zuvor". Ein Shop kann seinen
Referenzpreis anheben und so einen Rabatt herstellen; nur eine Reihe echter
Verkaufspreise widerlegt das.

Zwei Speicher mit klarer Rollenverteilung:

* **`historie/YYYY-MM-DD.jsonl.xz`** ist die Wahrheit und wird versioniert.
  Eine Datei je Lauftag, LZMA-komprimiert (rund 65 KB fuer 1750 Angebote,
  Faktor 4,5). Einmal geschrieben, aendert sie sich nie wieder.
* **`preise.db`** ist nur ein abgeleiteter SQLite-Index fuer schnelle Abfragen.
  Sie wird bei Bedarf aus dem Archiv wiederhergestellt und ist deshalb *nicht*
  versioniert.

Warum nicht einfach die SQLite-Datei committen: Sie waechst taeglich, und Git
legt bei jedem Commit eine neue Kopie der *ganzen* Datei ab. Nach einem Jahr
waeren das ~640.000 Zeilen, eine ~220 MB grosse Datei und mehrere Gigabyte
Git-Historie - in einem oeffentlichen Repository, das taeglich von einem Bot
beschrieben wird. Unveraenderliche Tagesdateien kosten dieselbe Information in
rund 23 MB pro Jahr, weil Git jede Datei genau einmal speichert.
"""

from __future__ import annotations

import json
import lzma
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from .model import Offer

#: Tagesdateien werden einmal geschrieben und nie wieder angefasst - hier lohnt
#: ein hoeheres Preset als beim Cache, es kostet nur einmalig Zeit.
ARCHIVE_PRESET = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    url        TEXT NOT NULL,
    seen_on    TEXT NOT NULL,
    price      REAL NOT NULL,
    list_price REAL,
    shop       TEXT,
    title      TEXT,
    PRIMARY KEY (url, seen_on)
);
CREATE INDEX IF NOT EXISTS idx_prices_url ON prices(url);
CREATE INDEX IF NOT EXISTS idx_prices_day ON prices(seen_on);
"""


class PriceHistory:
    def __init__(self, path: Path, archive_dir: Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Standard: Archiv liegt neben der Datenbank in "historie/"
        self.archive_dir = Path(archive_dir) if archive_dir else self.path.parent / "historie"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
            db.commit()
        self.restored_days = self._restore_from_archive()

    # -- Archiv ---------------------------------------------------------
    def _archive_path(self, day: str) -> Path:
        return self.archive_dir / f"{day}.jsonl.xz"

    def _restore_from_archive(self) -> int:
        """Tage aus dem Archiv nachziehen, die der Index noch nicht kennt.

        Damit ist `preise.db` jederzeit wegwerfbar: Auf einem frischen
        CI-Runner existiert sie gar nicht und wird hier vollstaendig aus den
        versionierten Tagesdateien aufgebaut.
        """
        if not self.archive_dir.exists():
            return 0
        with closing(sqlite3.connect(self.path)) as db:
            known = {r[0] for r in db.execute("SELECT DISTINCT seen_on FROM prices")}
            restored = 0
            for file in sorted(self.archive_dir.glob("*.jsonl.xz")):
                day = file.name.removesuffix(".jsonl.xz")
                if day in known:
                    continue
                try:
                    rows = _read_archive(file, day)
                except (OSError, lzma.LZMAError, ValueError):
                    # Eine kaputte Tagesdatei darf den Lauf nicht verhindern -
                    # die uebrigen Tage sind weiterhin brauchbar.
                    continue
                if rows:
                    db.executemany(
                        "INSERT OR REPLACE INTO prices "
                        "(url, seen_on, price, list_price, shop, title) "
                        "VALUES (?,?,?,?,?,?)",
                        rows,
                    )
                    restored += 1
            if restored:
                db.commit()
        return restored

    def _write_archive(self, day: str) -> Path:
        """Den vollstaendigen Tag aus dem Index ins Archiv schreiben.

        Bewusst aus der Datenbank und nicht aus den Angeboten des laufenden
        Durchgangs: Ein Teillauf (`--shop denfeld`) haette sonst die Tagesdatei
        aller Shops durch seine paar Zeilen ersetzt. Genau das ist beim Testen
        passiert - 1717 Angebote wurden zu einem. Der Index kennt den ganzen
        Tag, also ist er die richtige Quelle.
        """
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        target = self._archive_path(day)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT url, price, list_price, shop, title FROM prices "
                "WHERE seen_on = ? ORDER BY url",
                (day,),
            ).fetchall()
        payload = "".join(
            json.dumps(
                {"u": u, "p": p, "l": lp, "s": shop, "t": title},
                ensure_ascii=False,
            )
            + "\n"
            for u, p, lp, shop, title in rows
        ).encode("utf-8")
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(lzma.compress(payload, preset=ARCHIVE_PRESET))
        tmp.replace(target)
        return target

    # -- Aufzeichnen ----------------------------------------------------
    def record_and_enrich(self, offers: list[Offer], today: str | None = None) -> None:
        """Erst die Historie an die Angebote haengen, dann den Tag festschreiben.

        Die Reihenfolge ist wesentlich: Andernfalls stuende der heutige Preis
        schon in der Tabelle und jedes Angebot waere automatisch auf
        "Tiefstpreis".
        """
        if not offers:
            return
        today = today or date.today().isoformat()

        with closing(sqlite3.connect(self.path)) as db:
            for offer in offers:
                rows = db.execute(
                    "SELECT seen_on, price FROM prices WHERE url = ? ORDER BY seen_on",
                    (offer.url,),
                ).fetchall()
                past = [(d, p) for d, p in rows if d != today]

                if past:
                    offer.first_seen = past[0][0]
                    offer.price_prev = past[-1][1]
                    offer.price_min = min([p for _, p in past] + [offer.price])
                else:
                    offer.first_seen = today
                    offer.price_prev = None
                    offer.price_min = offer.price
                offer.price_points = [[d, p] for d, p in past] + [[today, offer.price]]

            db.executemany(
                "INSERT INTO prices (url, seen_on, price, list_price, shop, title) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url, seen_on) DO UPDATE SET "
                "price=excluded.price, list_price=excluded.list_price",
                [(o.url, today, o.price, o.list_price, o.shop, o.title) for o in offers],
            )
            db.commit()

        # Ein zweiter Lauf am selben Tag aktualisiert die Tagesdatei, statt die
        # Reihe aufzublaehen - dasselbe Verhalten wie im SQLite-Index.
        self._write_archive(today)

    def stats(self) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            runs = db.execute("SELECT COUNT(DISTINCT seen_on) FROM prices").fetchone()[0]
            urls = db.execute("SELECT COUNT(DISTINCT url) FROM prices").fetchone()[0]
            first = db.execute("SELECT MIN(seen_on) FROM prices").fetchone()[0]
        archive_bytes = sum(
            f.stat().st_size for f in self.archive_dir.glob("*.jsonl.xz")
        ) if self.archive_dir.exists() else 0
        return {
            "runs": runs,
            "urls": urls,
            "since": first,
            "archive_bytes": archive_bytes,
            "restored_days": self.restored_days,
        }


def _read_archive(file: Path, day: str) -> list[tuple]:
    rows: list[tuple] = []
    for line in lzma.decompress(file.read_bytes()).decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        rows.append(
            (rec["u"], day, rec["p"], rec.get("l"), rec.get("s"), rec.get("t"))
        )
    return rows
