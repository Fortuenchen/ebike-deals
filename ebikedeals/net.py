"""HTTP layer: one polite, retrying, optionally caching client for all adapters.

Der Cache liegt LZMA-komprimiert auf der Platte. Shop-HTML ist extrem
redundant - gemessen an echten Cache-Daten schrumpft es auf ein Zehntel
(350 MB auf rund 33 MB), und zwar ohne zusaetzliche Abhaengigkeit, weil `lzma`
zur Standardbibliothek gehoert.

Warum preset=1 und nicht das Maximum: An 40 echten Cache-Dateien einzeln
gemessen liefert preset 1 den Faktor 10,5 bei derselben Kompressionszeit wie
gzip -6 (Faktor 7,9). Hoehere Presets bringen kaum mehr (preset 3: 10,9x),
kosten aber deutlich mehr Zeit. Ein Cache muss vor allem billig zu schreiben
sein.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import random
import subprocess
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

#: Kompressionsstufe fuer Cache-Eintraege, siehe Modul-Docstring.
CACHE_PRESET = 1

#: Wartezeiten bei HTTP 429, falls der Server kein Retry-After mitschickt.
RATE_LIMIT_BASE = 8.0
RATE_LIMIT_MAX = 90.0
#: So viele Zusatzversuche darf ein Rate-Limit ueber das normale Budget hinaus
#: kosten, bevor der Shop als gescheitert gilt.
MAX_RATE_LIMIT_RETRIES = 4


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Retry-After auswerten - entweder Sekunden oder ein HTTP-Datum."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    delta = target.timestamp() - time.time()
    return max(0.0, delta)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


class Blocked(Exception):
    """The site actively refused automated access (bot protection)."""


class Disallowed(Exception):
    """robots.txt forbids this URL."""


class Fetcher:
    """Shared HTTP client.

    - one connection pool, HTTP/2 where offered
    - per-host delay so we never hammer a shop
    - retries with backoff on 429/5xx
    - optional on-disk cache to make re-runs cheap while developing
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        delay: float = 0.8,
        timeout: float = 45.0,
        retries: int = 3,
        cache_ttl: float = 3600.0,
        allow_curl_fallback: bool = True,
    ):
        self.client = httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout,
            http2=False,
        )
        self.delay = delay
        self.retries = retries
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()
        self.timeout = timeout
        self.allow_curl_fallback = allow_curl_fallback and _curl_available()
        self.curl_hosts: set[str] = set()
        #: set by the runner to a RobotsCache; None disables robots checking
        self.robots = None
        #: set by the runner when --render is active; adapters that need a
        #: browser look for it here
        self.renderer = None
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache ------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / f"{h}.xz"

    def _cache_read(self, url: str) -> str | None:
        p = self._cache_path(url)
        if p and p.exists() and (time.time() - p.stat().st_mtime) < self.cache_ttl:
            try:
                return lzma.decompress(p.read_bytes()).decode("utf-8")
            except (OSError, lzma.LZMAError, UnicodeDecodeError):
                # Abgebrochener Schreibvorgang o. ae. - Eintrag ist wertlos,
                # aber kein Grund, den Lauf zu beenden.
                return None
        return None

    def _cache_write(self, url: str, body: str) -> None:
        p = self._cache_path(url)
        if not p:
            return
        try:
            # Erst daneben schreiben, dann umbenennen: ein abgebrochener Lauf
            # hinterlaesst so keine halbe Datei, die spaeter als gueltiger
            # Cache-Treffer gelesen wuerde.
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(lzma.compress(body.encode("utf-8"), preset=CACHE_PRESET))
            tmp.replace(p)
        except OSError:
            pass

    def prune_cache(self) -> tuple[int, int]:
        """Abgelaufene und altformatige Eintraege loeschen.

        Bisher hat nichts den Cache aufgeraeumt - er wuchs unbegrenzt weiter
        (350 MB nach wenigen Tagen). Abgelaufene Eintraege werden ohnehin nie
        wieder gelesen, sie zu behalten kostet nur Platz. Die unkomprimierten
        `.cache`-Dateien aus der Zeit vor der Kompression fallen hier ebenfalls
        weg.

        Rueckgabe: (geloeschte Dateien, freigegebene Bytes)
        """
        if not self.cache_dir or not self.cache_dir.exists():
            return (0, 0)
        removed = freed = 0
        now = time.time()
        for entry in list(self.cache_dir.iterdir()):
            if not entry.is_file():
                continue
            expired = entry.suffix == ".xz" and (now - entry.stat().st_mtime) >= self.cache_ttl
            legacy = entry.suffix in (".cache", ".tmp")
            if expired or legacy:
                try:
                    size = entry.stat().st_size
                    entry.unlink()
                    removed += 1
                    freed += size
                except OSError:
                    pass
        return (removed, freed)

    # -- throttling -------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        with self._lock:
            last = self._last_hit.get(host, 0.0)
            wait = self.delay - (time.time() - last)
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.25))
            self._last_hit[host] = time.time()

    # -- requests ---------------------------------------------------------
    def get(self, url: str, *, headers: dict | None = None, use_cache: bool = True) -> str:
        # robots.txt is evaluated for every URL, not just the entry point -
        # some shops allow a listing path but disallow its paginated variants.
        if self.robots is not None and not url.rstrip("/").endswith("/robots.txt"):
            verdict = self.robots.check(url)
            if not verdict.allowed:
                raise Disallowed(f"robots.txt: {verdict.reason}")

        if use_cache:
            cached = self._cache_read(url)
            if cached is not None:
                return cached

        host = httpx.URL(url).host or ""
        if host in self.curl_hosts:
            body = self._curl_get(url)
            if use_cache:
                self._cache_write(url, body)
            return body

        last_exc: Exception | None = None
        rate_limit_hits = 0
        attempt = -1
        # Ein Rate-Limit verbraucht keinen regulaeren Versuch: Der Server sagt
        # "spaeter nochmal", nicht "kaputt". Sonst waeren nach drei 429ern alle
        # Versuche aufgebraucht, obwohl nie ein echter Fehler auftrat.
        while attempt + 1 < self.retries + min(rate_limit_hits, MAX_RATE_LIMIT_RETRIES):
            attempt += 1
            self._throttle(url)
            try:
                r = self.client.get(url, headers=headers)
            except Exception as e:  # network-level failure
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status_code in (403, 401):
                # Some shops answer 403 to httpx but 200 to curl - a client
                # fingerprint heuristic, not a policy decision (robots.txt is
                # checked separately and independently). Retry once via curl
                # and remember the host if that works.
                if self.allow_curl_fallback:
                    try:
                        body = self._curl_get(url)
                    except Exception:
                        body = ""
                    if body and not _is_bot_interstitial(body):
                        self.curl_hosts.add(host)
                        if use_cache:
                            self._cache_write(url, body)
                        return body
                raise Blocked(f"HTTP {r.status_code} - Zugriff verweigert (Bot-Schutz)")
            if r.status_code == 404:
                raise httpx.HTTPStatusError("404", request=r.request, response=r)
            if r.status_code == 429:
                # Rate-Limit ist kein Ausschluss, sondern eine Bitte um Geduld.
                # Auf einem GitHub-Runner teilen sich viele Nutzer eine IP,
                # entsprechend schnell greift Shopifys Limit: Fuenf Shops sind
                # daran gescheitert, weil hier vorher pauschal 2-6 Sekunden
                # gewartet und der Retry-After-Header ignoriert wurde.
                last_exc = httpx.HTTPStatusError(
                    "HTTP 429", request=r.request, response=r
                )
                wait = _retry_after_seconds(r)
                if wait is None:
                    wait = min(RATE_LIMIT_BASE * (2 ** attempt), RATE_LIMIT_MAX)
                time.sleep(min(wait, RATE_LIMIT_MAX) + random.uniform(0, 1.0))
                rate_limit_hits += 1
                continue
            if r.status_code in (500, 502, 503, 504):
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {r.status_code}", request=r.request, response=r
                )
                time.sleep(2.0 * (attempt + 1))
                continue

            body = r.text
            if _is_bot_interstitial(body):
                raise Blocked("Bot-Schutz-Interstitial (Akamai/JS-Challenge)")
            if use_cache:
                self._cache_write(url, body)
            return body

        raise last_exc or RuntimeError(f"Konnte {url} nicht laden")

    def get_json(self, url: str, *, use_cache: bool = True) -> Any:
        body = self.get(
            url,
            headers={"Accept": "application/json,text/plain,*/*"},
            use_cache=use_cache,
        )
        return json.loads(body)

    def _curl_get(self, url: str) -> str:
        self._throttle(url)
        proc = subprocess.run(
            [
                "curl", "-sSL", "--compressed",
                "-m", str(int(self.timeout)),
                "-A", UA,
                "-H", "Accept-Language: de-DE,de;q=0.9",
                url,
            ],
            capture_output=True,
            timeout=self.timeout + 15,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"curl exit {proc.returncode}: {proc.stderr[:200]!r}")
        return proc.stdout.decode("utf-8", errors="replace")

    def close(self) -> None:
        self.client.close()


def _curl_available() -> bool:
    try:
        subprocess.run(["curl", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


_INTERSTITIAL_MARKERS = (
    "bm-verify",
    "_sec/verify?provider=interstitial",
    "akamai-loading-screen",
    "Just a moment...",
    "cf-browser-verification",
)


def _is_bot_interstitial(body: str) -> bool:
    if len(body) > 20000:
        return False
    return any(m in body for m in _INTERSTITIAL_MARKERS)
