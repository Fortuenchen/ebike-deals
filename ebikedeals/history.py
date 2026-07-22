"""Price history across runs.

Everything else in this project is a snapshot: it can say "60 % below RRP" but
not "cheaper than it has ever been". A shop can raise its reference price and
manufacture a discount; only a record of actual asking prices over time
disproves that.

One SQLite file (stdlib, no dependency, survives concurrent runs better than a
JSON blob). One row per (url, run) so a re-run on the same day updates rather
than inflates the series.

    prices(url, seen_on, price, list_price, shop, title)
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from .model import Offer

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
"""


class PriceHistory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
            db.commit()

    def record_and_enrich(self, offers: list[Offer], today: str | None = None) -> None:
        """Attach each offer's history, then record today's price.

        Reading before writing matters: otherwise every offer would look like
        it had just hit its all-time low, because today's price would already
        be in the table when the minimum is computed.
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
                [
                    (o.url, today, o.price, o.list_price, o.shop, o.title)
                    for o in offers
                ],
            )
            db.commit()

    def stats(self) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            runs = db.execute("SELECT COUNT(DISTINCT seen_on) FROM prices").fetchone()[0]
            urls = db.execute("SELECT COUNT(DISTINCT url) FROM prices").fetchone()[0]
            first = db.execute("SELECT MIN(seen_on) FROM prices").fetchone()[0]
        return {"runs": runs, "urls": urls, "since": first}
