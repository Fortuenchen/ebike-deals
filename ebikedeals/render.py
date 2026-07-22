"""Optional browser rendering for shops whose listing only exists after JS runs.

Why this is separate from the normal fetcher, and deliberately opt-in:

lucky-bike.de answers a plain HTTP request with the filter UI and a
"recently viewed" slider, but no product tiles - and there is no XHR the list
could be read from instead. Its product pages do serve JSON-LD over plain HTTP,
but without a reference price, so a discount cannot be computed from them. The
data only exists once the page has been rendered.

What this is not: there is no challenge being solved here, no CAPTCHA, no
credential, no forged identity. Headless Chromium is a real browser engine, and
the shop's robots.txt permits these paths (check it with check_robots.py). That
is a different situation from bike24.de, whose Akamai interstitial demands a
proof-of-work before it serves anything - defeating that is bot-detection
circumvention and is not implemented here, by choice.

Still, rendering is heavier on the shop than a GET, so it stays behind
--render, keeps the same per-host delay as the rest of the app, and blocks
images and fonts to cut the transferred bytes.
"""

from __future__ import annotations

import random
import time

BLOCKED_RESOURCES = {"image", "media", "font"}


class RendererUnavailable(RuntimeError):
    """Playwright or its browser binary is missing."""


class Renderer:
    """Lazily started headless Chromium, reused across pages."""

    def __init__(self, delay: float = 1.5, timeout_ms: int = 45_000, headless: bool = True):
        self.delay = delay
        self.timeout_ms = timeout_ms
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self._last_hit = 0.0

    # -- lifecycle --------------------------------------------------------
    def _ensure(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RendererUnavailable(
                "playwright ist nicht installiert - 'pip install playwright' und "
                "'python -m playwright install chromium'"
            ) from e
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
        except Exception as e:
            raise RendererUnavailable(f"Chromium konnte nicht gestartet werden: {e}") from e

        self._context = self._browser.new_context(
            locale="de-DE",
            viewport={"width": 1440, "height": 1000},
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9"},
        )
        self._context.route("**/*", self._filter_requests)

    @staticmethod
    def _filter_requests(route, request) -> None:
        if request.resource_type in BLOCKED_RESOURCES:
            route.abort()
        else:
            route.continue_()

    def close(self) -> None:
        for obj, name in ((self._context, "_context"), (self._browser, "_browser")):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, name, None)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- fetching ---------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.delay - (time.time() - self._last_hit)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.3))
        self._last_hit = time.time()

    def html(
        self,
        url: str,
        wait_for: str | None = None,
        settle_ms: int = 1200,
        scroll_for: str | None = None,
        max_scrolls: int = 30,
    ) -> str:
        """Return the rendered DOM.

        `wait_for` is a selector that must appear; if it never does, whatever
        was rendered is returned anyway so a changed class name degrades to
        "no products found" rather than an exception.

        `scroll_for` turns on infinite-scroll handling: the page is scrolled
        until the number of matching elements stops growing. No adapter needs
        it today - lucky-bike turned out to have a hard 45-per-category limit
        rather than lazy loading - but it is what the next JS-only shop will
        need, and it costs nothing when unused.
        """
        self._ensure()
        self._throttle()
        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=self.timeout_ms // 3)
                except Exception:
                    pass
            page.wait_for_timeout(settle_ms)

            if scroll_for:
                previous = -1
                for _ in range(max_scrolls):
                    try:
                        count = page.locator(scroll_for).count()
                    except Exception:
                        break
                    if count == previous:
                        break  # nothing new arrived, we are at the end
                    previous = count
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(900)

            return page.content()
        finally:
            page.close()


def available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True
