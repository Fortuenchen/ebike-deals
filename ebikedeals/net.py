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
import os
import random
import subprocess
import threading
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

try:
    # Optional: nur auf den GitHub-Runnern gebraucht (siehe Fetcher.__init__).
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

from .cachetags import LISTING, CacheTags, derive

#: Kompressionsstufe fuer Cache-Eintraege, siehe Modul-Docstring.
CACHE_PRESET = 1

#: Wartezeiten bei HTTP 429, falls der Server kein Retry-After mitschickt.
RATE_LIMIT_BASE = 8.0
RATE_LIMIT_MAX = 90.0
#: So viele Zusatzversuche darf ein Rate-Limit ueber das normale Budget hinaus
#: kosten, bevor der Shop als gescheitert gilt.
MAX_RATE_LIMIT_RETRIES = 4
#: Geduld je Host, in Sekunden. Ist sie aufgebraucht, gilt 429 als dauerhafte
#: Abweisung statt als Bitte um Geduld.
#:
#: Der Unterschied ist praktisch wichtig: Ein echtes Rate-Limit loest sich durch
#: Warten. Wird dagegen eine ganze IP abgelehnt - Shopify signalisiert das
#: ebenfalls mit 429 - hilft kein Warten. Auf einem GitHub-Runner hat genau das
#: 41 Minuten Laufzeit gekostet und am Ergebnis nichts geaendert. Nach dem
#: Budget wird deshalb schnell aufgegeben, damit der Fehlschlag sichtbar wird,
#: statt sich in Wartezeit zu verstecken.
RATE_LIMIT_BUDGET_PER_HOST = 120.0


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
        impersonate: str | None = None,
    ):
        # curl_cffi ahmt den TLS-/JA3-Fingerabdruck von Chrome nach. Zusammen mit
        # einem unverdaechtigen Egress (Cloudflare WARP im Workflow) kommen so auch
        # die Shops durch, die den nackten httpx-Fingerabdruck einer
        # Rechenzentrums-IP mit 429/403 abweisen - gemessen: von einer WARP-IP
        # schalten fahrrad24, bike-discount, mhw-bike, ebike-24 und alle fuenf
        # Shopify-Shops erst mit diesem Fingerabdruck frei. Lokal (Wohn-IP) ist das
        # unnoetig, daher nur ueber IMPERSONATE zugeschaltet.
        imp = impersonate if impersonate is not None else os.environ.get("IMPERSONATE", "")
        self.impersonate = imp if (imp and cffi_requests is not None) else ""
        if self.impersonate:
            self.client = cffi_requests.Session(
                impersonate=self.impersonate,
                allow_redirects=True,
                timeout=timeout,
                # Nur die Sprache mitgeben - UA und sec-ch-ua setzt die
                # Impersonation selbst; ein zweiter, abweichender UA waere ein
                # Widerspruch, den genau diese Schutzsysteme suchen.
                headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
            )
            # Der cffi-Client IST schon der Fingerabdruck-Trick; der
            # subprocess-curl-Fallback (nicht impersoniert) wuerde nichts beitragen.
            allow_curl_fallback = False
        else:
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
        #: Aktueller Kategorie-Kontext, pro Thread getrennt (siehe scope()).
        self._scope = threading.local()
        #: Bereits mit Warten auf Rate-Limits verbrachte Zeit je Host.
        self._rate_limit_spent: dict[str, float] = {}
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

    # -- Kategorisierung --------------------------------------------------
    @contextmanager
    def scope(self, shop: str, kind: str = LISTING, label: str = ""):
        """Kontext, unter dem die naechsten Abrufe abgelegt und gesucht werden.

        Thread-lokal, und das ist keine Feinheit: Der Runner scrapt bis zu fuenf
        Shops gleichzeitig ueber *einen* Fetcher. Ein gemeinsamer Scope wuerde
        zwischen den Threads auslaufen und Eintraege unter dem falschen Shop
        ablegen.
        """
        previous = getattr(self._scope, "tags", None)
        self._scope.tags = CacheTags(shop=shop, kind=kind, label=label)
        try:
            yield
        finally:
            self._scope.tags = previous

    def _tags_for(self, url: str, override: CacheTags | None = None) -> CacheTags:
        if override is not None:
            return override
        current = getattr(self._scope, "tags", None)
        if current is not None:
            # Das Label kommt aus der URL, der Rest aus dem gesetzten Kontext -
            # so bleiben verschiedene Kategorien eines Shops unterscheidbar,
            # ohne dass jeder Aufrufer sie einzeln benennen muss.
            derived = derive(url, shop=current.shop, kind=current.kind)
            return CacheTags(current.shop, current.kind, current.label or derived.label)
        return derive(url)

    # -- cache ------------------------------------------------------------
    def _cache_path(self, url: str, tags: CacheTags) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir.joinpath(*tags.parts) / f"{h}.xz"

    def _cache_read(self, url: str, tags: CacheTags) -> str | None:
        p = self._cache_path(url, tags)
        if p and p.exists() and (time.time() - p.stat().st_mtime) < self.cache_ttl:
            try:
                _, body = _split_entry(lzma.decompress(p.read_bytes()))
                return body
            except (OSError, lzma.LZMAError, UnicodeDecodeError, ValueError):
                # Abgebrochener Schreibvorgang o. ae. - Eintrag ist wertlos,
                # aber kein Grund, den Lauf zu beenden.
                return None
        return None

    def _cache_write(self, url: str, body: str, tags: CacheTags) -> None:
        p = self._cache_path(url, tags)
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Kopfzeile im Eintrag: Der Cache beschreibt sich damit selbst und
            # laesst sich durchsuchen, ohne einen zweiten Index zu pflegen,
            # der mit dem Dateibestand auseinanderlaufen koennte.
            header = json.dumps(
                {"url": url, "ts": int(time.time()), **tags.as_dict()},
                ensure_ascii=False,
            )
            payload = (header + "\n" + body).encode("utf-8")
            # Erst daneben schreiben, dann umbenennen: ein abgebrochener Lauf
            # hinterlaesst so keine halbe Datei, die spaeter als gueltiger
            # Cache-Treffer gelesen wuerde.
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(lzma.compress(payload, preset=CACHE_PRESET))
            tmp.replace(p)
        except OSError:
            pass

    # -- Abfragen und Aufraeumen ------------------------------------------
    def cache_entries(
        self, shop: str | None = None, kind: str | None = None,
        label: str | None = None, include_expired: bool = True,
    ) -> list[dict]:
        """Eintraege auflisten, gefiltert nach Merkmalen (None heisst egal)."""
        if not self.cache_dir or not self.cache_dir.exists():
            return []
        now = time.time()
        found: list[dict] = []
        for path in self.cache_dir.rglob("*.xz"):
            try:
                rel = path.relative_to(self.cache_dir).parts
                tags = CacheTags(shop=rel[0], kind=rel[1]) if len(rel) >= 3 else CacheTags()
                header = {}
                try:
                    raw = lzma.decompress(path.read_bytes())
                    header, _ = _split_entry(raw, body=False)
                except (lzma.LZMAError, ValueError, UnicodeDecodeError):
                    pass
                tags = CacheTags(
                    shop=header.get("shop", tags.shop),
                    kind=header.get("kind", tags.kind),
                    label=header.get("label", ""),
                )
                if not tags.matches(shop=shop, kind=kind, label=label):
                    continue
                age = now - path.stat().st_mtime
                if not include_expired and age >= self.cache_ttl:
                    continue
                found.append({
                    "path": path, "bytes": path.stat().st_size, "age": age,
                    "expired": age >= self.cache_ttl,
                    "url": header.get("url", ""), **tags.as_dict(),
                })
            except OSError:
                continue
        return found

    def prune_cache(
        self, shop: str | None = None, kind: str | None = None,
        expired_only: bool = True,
    ) -> tuple[int, int]:
        """Eintraege loeschen - standardmaessig nur abgelaufene.

        Bisher hat nichts den Cache aufgeraeumt, er wuchs unbegrenzt weiter
        (350 MB nach wenigen Tagen). Mit den Merkmalen laesst sich das jetzt
        auch gezielt: nur ein Shop, nur Produktseiten.

        Rueckgabe: (geloeschte Dateien, freigegebene Bytes)
        """
        if not self.cache_dir or not self.cache_dir.exists():
            return (0, 0)
        removed = freed = 0

        for entry in self.cache_entries(shop=shop, kind=kind):
            if expired_only and not entry["expired"]:
                continue
            try:
                entry["path"].unlink()
                removed += 1
                freed += entry["bytes"]
            except OSError:
                pass

        # Reste aus der Zeit vor der Kategorisierung: flache .xz-Dateien direkt
        # im Wurzelverzeichnis, unkomprimierte .cache-Dateien, halbe .tmp.
        if shop is None and kind is None:
            for stale in list(self.cache_dir.glob("*.xz")) + \
                    list(self.cache_dir.rglob("*.cache")) + \
                    list(self.cache_dir.rglob("*.tmp")):
                try:
                    size = stale.stat().st_size
                    stale.unlink()
                    removed += 1
                    freed += size
                except OSError:
                    pass

        # Leere Faecher hinterlassen nur Verwirrung.
        for d in sorted(self.cache_dir.rglob("*"), key=lambda p: -len(p.parts)):
            if d.is_dir():
                try:
                    d.rmdir()
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
    def get(self, url: str, *, headers: dict | None = None, use_cache: bool = True,
            tags: CacheTags | None = None) -> str:
        # robots.txt is evaluated for every URL, not just the entry point -
        # some shops allow a listing path but disallow its paginated variants.
        if self.robots is not None and not url.rstrip("/").endswith("/robots.txt"):
            verdict = self.robots.check(url)
            if not verdict.allowed:
                raise Disallowed(f"robots.txt: {verdict.reason}")

        entry_tags = self._tags_for(url, tags)
        if use_cache:
            cached = self._cache_read(url, entry_tags)
            if cached is not None:
                return cached

        host = httpx.URL(url).host or ""
        if host in self.curl_hosts:
            body = self._curl_get(url)
            if use_cache:
                self._cache_write(url, body, entry_tags)
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
                            self._cache_write(url, body, entry_tags)
                        return body
                raise Blocked(f"HTTP {r.status_code} - Zugriff verweigert (Bot-Schutz)")
            if r.status_code == 404:
                raise httpx.HTTPStatusError("404", request=httpx.Request("GET", url), response=r)
            if r.status_code == 429:
                # Rate-Limit ist kein Ausschluss, sondern eine Bitte um Geduld.
                # Auf einem GitHub-Runner teilen sich viele Nutzer eine IP,
                # entsprechend schnell greift Shopifys Limit: Fuenf Shops sind
                # daran gescheitert, weil hier vorher pauschal 2-6 Sekunden
                # gewartet und der Retry-After-Header ignoriert wurde.
                last_exc = httpx.HTTPStatusError(
                    "HTTP 429", request=httpx.Request("GET", url), response=r
                )
                with self._lock:
                    verbraucht = self._rate_limit_spent.get(host, 0.0)
                if verbraucht >= RATE_LIMIT_BUDGET_PER_HOST:
                    raise Blocked(
                        "HTTP 429 dauerhaft - der Host weist diese IP ab, "
                        "nicht nur diese Anfrage"
                    )
                wait = _retry_after_seconds(r)
                if wait is None:
                    wait = min(RATE_LIMIT_BASE * (2 ** attempt), RATE_LIMIT_MAX)
                wait = min(wait, RATE_LIMIT_MAX,
                           RATE_LIMIT_BUDGET_PER_HOST - verbraucht) + random.uniform(0, 1.0)
                time.sleep(max(wait, 0.5))
                with self._lock:
                    self._rate_limit_spent[host] = verbraucht + wait
                rate_limit_hits += 1
                continue
            if r.status_code in (500, 502, 503, 504):
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {r.status_code}", request=httpx.Request("GET", url), response=r
                )
                time.sleep(2.0 * (attempt + 1))
                continue

            body = r.text
            if _is_bot_interstitial(body):
                raise Blocked("Bot-Schutz-Interstitial (Akamai/JS-Challenge)")
            if use_cache:
                self._cache_write(url, body, entry_tags)
            return body

        raise last_exc or RuntimeError(f"Konnte {url} nicht laden")

    def get_json(self, url: str, *, use_cache: bool = True,
                 tags: CacheTags | None = None) -> Any:
        body = self.get(
            url,
            headers={"Accept": "application/json,text/plain,*/*"},
            use_cache=use_cache,
            tags=tags,
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


def _split_entry(raw: bytes, body: bool = True) -> tuple[dict, str]:
    """Kopfzeile und Inhalt eines Cache-Eintrags trennen."""
    head, sep, rest = raw.partition(b"\n")
    if not sep:
        raise ValueError("Eintrag ohne Kopfzeile")
    header = json.loads(head.decode("utf-8"))
    if not isinstance(header, dict) or "url" not in header:
        raise ValueError("Kopfzeile unbrauchbar")
    return header, (rest.decode("utf-8") if body else "")


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
