# extractors/http_fetch.py
"""Shared HTTP-fetch helper with a Playwright fallback for bot-blocked sources.

Some sources (Resus, BTOG) 403/429/503/202 or serve a bot-challenge page when
fetched via httpx from a datacenter IP (GitHub Actions runners), while
working fine from a home IP or a real browser. fetch_html() tries httpx
first (cheap, no browser needed) and — only when the response looks
blocked — falls back to the extractor's already-launched Playwright browser,
so listings/details still resolve in CI.

Playwright caveat: the fallback ALWAYS opens a brand-new browser context
(and a page in it) and closes both afterwards. It never navigates a page
the caller is still using (e.g. the detail page `extract_detail` is
mid-way through parsing), so it's safe to call from both
list_shells_override() (which owns the browser outright) and
extract_detail() (whose `page` is already parked on the event's detail
URL). A fresh context is used rather than `page.context.new_page()`
because BrowserController's page comes from `Browser.new_page()`, whose
implicit context only supports a single page.
"""

import re
import time
from typing import Any, Optional

import httpx

from logger import logger

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Treat these as "the site refused us", not "the page really is empty".
_BLOCKED_STATUSES = {403, 429, 503, 202}

# Markers of bot-challenge interstitials (Cloudflare, SiteGround sgcaptcha, etc.)
_CHALLENGE_MARKERS = re.compile(
    r"sgcaptcha|just a moment|cf-chl|checking your browser|"
    r"cf-browser-verification|attention required|challenge-platform|"
    r"/cdn-cgi/challenge-platform",
    re.I,
)

# A real listing/detail page is never this short; a 200 this small is
# almost always an interstitial or an error page dressed as 200.
_MIN_PLAUSIBLE_BODY_LEN = 500


def _looks_blocked(status_code: int, body: Optional[str]) -> Optional[str]:
    """Return a reason string if the response looks like a bot block, else None."""
    if status_code in _BLOCKED_STATUSES:
        return f"status {status_code}"
    if status_code == 200:
        if _CHALLENGE_MARKERS.search(body or ""):
            return "challenge markers in body"
        if len(body or "") < _MIN_PLAUSIBLE_BODY_LEN:
            return f"suspiciously short 200 body ({len(body or '')} chars)"
    return None


def _fetch_httpx(url: str, headers: dict, timeout: float):
    """Returns (status_code, body) or (None, None) on a transport-level failure."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as c:
            resp = c.get(url)
            return resp.status_code, resp.text
    except Exception as e:
        logger.warning(f"http_fetch: httpx GET {url} failed: {e!r}")
        return None, None


def _fetch_via_browser(url: str, page: Any, wait_s: float = 10.0) -> Optional[str]:
    """Fetch `url` in a brand-new context+page on `page`'s Browser, waiting
    briefly for a challenge interstitial to auto-resolve. Never touches
    `page` itself.

    NOTE: `page.context.new_page()` is not usable here — when a page comes
    from `Browser.new_page()` (the shortcut BrowserController uses), its
    context was created implicitly for exactly one page and Playwright
    refuses a second one ("Please use browser.new_context()"). So we go
    one level up to `page.context.browser` and open a fresh context there.
    """
    new_context = None
    new_page = None
    try:
        new_context = page.context.browser.new_context()
        new_page = new_context.new_page()
        new_page.goto(url, wait_until="load", timeout=30000)
        body = new_page.content()
        deadline = time.time() + wait_s
        while time.time() < deadline and _CHALLENGE_MARKERS.search(body or ""):
            new_page.wait_for_timeout(1000)
            body = new_page.content()
        return body
    except Exception as e:
        logger.warning(f"http_fetch: Playwright fetch of {url} failed: {e}")
        return None
    finally:
        if new_page is not None:
            try:
                new_page.close()
            except Exception:
                pass
        if new_context is not None:
            try:
                new_context.close()
            except Exception:
                pass


def fetch_html(
    url: str,
    *,
    browser: Any = None,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
) -> Optional[str]:
    """Fetch a URL's HTML, trying httpx first and falling back to a real
    browser when the response looks bot-blocked.

    `browser` may be:
      - a BrowserController (exposes `.page`, a Playwright Page), or
      - a Playwright Page directly, or
      - None — no fallback is attempted; a blocked/failed httpx response
        just returns None.

    Never raises. Returns None if both paths fail (or if httpx succeeds
    with what looks like a real page, in which case the browser is never
    touched at all).
    """
    req_headers = {**DEFAULT_HEADERS, **(headers or {})}

    status, body = _fetch_httpx(url, req_headers, timeout)
    if status is not None:
        reason = _looks_blocked(status, body)
        if reason is None:
            if status >= 400:
                # Genuine error (404, 500…) — not a bot block, so a browser
                # retry won't help. Don't hand an error page to the parser.
                logger.warning(f"http_fetch: {url} returned status {status}")
                return None
            return body
        logger.warning(f"http_fetch: {url} looks blocked via httpx ({reason})")
    else:
        logger.warning(f"http_fetch: {url} httpx transport failure; trying browser fallback")

    page = getattr(browser, "page", browser) if browser is not None else None
    if page is None:
        logger.warning(f"http_fetch: no browser available for {url}; giving up")
        return None

    logger.warning(f"http_fetch: falling back to Playwright (new page) for {url}")
    return _fetch_via_browser(url, page)
