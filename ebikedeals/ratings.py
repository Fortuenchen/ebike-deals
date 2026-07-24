"""Shop ratings from Trusted Shops and Trustpilot.

The two platforms are not equally accessible, and the difference is a policy
one, not a technical one:

* **Trusted Shops** runs a public, key-free API. `/rest/public/v2/shops.json`
  resolves a domain to a shop id, `/quality/reviews.json` returns the grade.
  Their robots.txt permits it.

* **Trustpilot** ends its robots.txt with `User-agent: * / Disallow: /`. Named
  crawlers are allowed, this application is not one of them, and pretending to
  be one would be a false statement about who is asking. So no score is
  fetched. What is shown is a link - and only where the shop publishes its own
  Trustpilot profile, which is evidence the profile exists. Scores can be
  supplied by hand, see MANUAL_FILE.

Two traps in the Trusted Shops lookup, both of which silently attribute a
stranger's reputation to a shop:

* it matches loosely - querying www.bike24.de returns MEGA Bike, fahrrad.de
  returns a terminated ps-fahrrad.de profile. The returned host must therefore
  equal the queried host.
* a shop can hold several profiles per market - jobrad-loop has a German and a
  Dutch one with different grades. The German market wins here.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict

from .cachetags import RATING
from pathlib import Path
from urllib.parse import urlsplit

LOOKUP_URL = "https://api.trustedshops.com/rest/public/v2/shops.json?url={host}"
REVIEWS_URL = "https://api.trustedshops.com/rest/public/v2/shops/{ts_id}/quality/reviews.json"
# Any subdomain: shops link de.trustpilot.com, www.trustpilot.com or the bare
# domain. Restricting this to two-letter locales missed www. links entirely.
TRUSTPILOT_PROFILE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*trustpilot\.com/review/([A-Za-z0-9.\-]+)", re.I
)

#: Ratings move slowly; a week-old grade is fine and saves a request per shop.
CACHE_DAYS = 7
#: Optional hand-maintained file, merged over whatever was fetched.
MANUAL_FILE = "bewertungen_manuell.json"


@dataclass
class Rating:
    platform: str          # "Trusted Shops" | "Trustpilot"
    url: str
    score: float | None = None
    count: int | None = None
    scale: float = 5.0
    manual: bool = False

    @property
    def stars(self) -> str:
        if self.score is None:
            return ""
        return f"{self.score:.2f}".replace(".", ",")


def _host(url: str) -> str:
    netloc = urlsplit(url if "//" in url else "//" + url).netloc or url
    return netloc.lower().removeprefix("www.").split("/")[0].strip()


def _shop_host(raw: str) -> str:
    """Normalise a Trusted Shops profile url, which may carry scheme or path."""
    return _host(raw.strip())


# ---------------------------------------------------------------------------
def fetch_trusted_shops(fetcher, domain: str, market: str = "DEU") -> Rating | None:
    host = _host(domain)
    candidates: list[dict] = []
    for variant in (host, "www." + host):
        try:
            data = fetcher.get_json(LOOKUP_URL.format(host=variant), use_cache=False)
        except Exception:
            continue
        found = ((data.get("response") or {}).get("data") or {}).get("shops") or []
        candidates.extend(found)

    exact = [s for s in candidates if _shop_host(s.get("url", "")) == host]
    if not exact:
        return None
    # Prefer the profile for the target market, then the one without a path
    # suffix (the main storefront rather than a locale sub-shop).
    exact.sort(
        key=lambda s: (
            s.get("targetMarketISO3") != market,
            "/" in s.get("url", "").rstrip("/").split("//")[-1],
        )
    )
    shop = exact[0]
    ts_id = shop.get("tsId")
    if not ts_id:
        return None

    try:
        rd = fetcher.get_json(REVIEWS_URL.format(ts_id=ts_id), use_cache=False)
        ri = rd["response"]["data"]["shop"]["qualityIndicators"]["reviewIndicator"]
    except Exception:
        return None
    score = ri.get("overallMark")
    if score is None:
        return None
    return Rating(
        platform="Trusted Shops",
        url=f"https://www.trustedshops.de/bewertung/info_{ts_id}.html",
        score=round(float(score), 2),
        count=ri.get("totalReviewCount"),
    )


def find_trustpilot_link(shop_html: str, domain: str) -> Rating | None:
    """A Trustpilot profile the shop itself links to - no score, see module docstring."""
    for slug in TRUSTPILOT_PROFILE.findall(shop_html or ""):
        if _host(slug) == _host(domain):
            return Rating(
                platform="Trustpilot",
                url=f"https://de.trustpilot.com/review/{slug}",
            )
    return None


# ---------------------------------------------------------------------------
def collect(adapters, fetcher, cache_path: Path | None) -> dict[str, list[Rating]]:
    """{shop key: [Rating, ...]}, cached on disk and topped up from MANUAL_FILE."""
    cache: dict = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    fresh = cache.get("fetched_at", 0) > time.time() - CACHE_DAYS * 86400
    shops: dict[str, list[dict]] = cache.get("shops", {}) if fresh else {}

    if not fresh:
        for adapter in adapters:
            domain = _host(adapter.source_url)
            entries: list[Rating] = []
            ts = fetch_trusted_shops(fetcher, domain)
            if ts:
                entries.append(ts)
            try:
                # Startseite des Shops, nur fuer die Bewertungssuche geholt -
                # nicht mit dem Listing-Cache des Shops vermischen.
                with fetcher.scope(adapter.key, RATING, "profil"):
                    html = fetcher.get(adapter.source_url)
                tp = find_trustpilot_link(html, domain)
                if tp:
                    entries.append(tp)
            except Exception:
                pass
            shops[adapter.key] = [asdict(e) for e in entries]
        if cache_path:
            try:
                cache_path.write_text(
                    json.dumps({"fetched_at": time.time(), "shops": shops},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

    out = {k: [Rating(**d) for d in v] for k, v in shops.items()}
    _merge_manual(out, cache_path)
    return out


def _merge_manual(ratings: dict[str, list[Rating]], cache_path: Path | None) -> None:
    """Hand-entered scores win over fetched ones and are flagged as manual.

    Format: {"shopkey": {"Trustpilot": {"score": 4.3, "count": 1200,
                                        "url": "https://..."}}}
    """
    base = (cache_path.parent if cache_path else Path(".")) / MANUAL_FILE
    if not base.exists():
        return
    try:
        manual = json.loads(base.read_text(encoding="utf-8"))
    except Exception:
        return
    for key, platforms in (manual or {}).items():
        entries = ratings.setdefault(key, [])
        for platform, vals in (platforms or {}).items():
            if not isinstance(vals, dict) or vals.get("score") is None:
                continue
            entries[:] = [e for e in entries if e.platform != platform]
            entries.append(Rating(
                platform=platform,
                url=vals.get("url", ""),
                score=float(vals["score"]),
                count=vals.get("count"),
                scale=float(vals.get("scale", 5.0)),
                manual=True,
            ))
