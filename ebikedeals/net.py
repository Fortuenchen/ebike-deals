"""HTTP layer: one polite, retrying, optionally caching client for all adapters."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx

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
        return self.cache_dir / f"{h}.cache"

    def _cache_read(self, url: str) -> str | None:
        p = self._cache_path(url)
        if p and p.exists() and (time.time() - p.stat().st_mtime) < self.cache_ttl:
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return None
        return None

    def _cache_write(self, url: str, body: str) -> None:
        p = self._cache_path(url)
        if p:
            try:
                p.write_text(body, encoding="utf-8")
            except OSError:
                pass

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
        for attempt in range(self.retries):
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
            if r.status_code in (429, 500, 502, 503, 504):
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
