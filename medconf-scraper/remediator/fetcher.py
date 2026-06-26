"""Fetch source page text. Handles JS-rendered sites via existing browser.

Caches per-URL within one remediator run so multiple fixers operating on the
same row don't hit the source N times.
"""

from __future__ import annotations
import logging
import re
from typing import Optional, Dict

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (MedConf remediator/0.1)"

# JS-rendered hosts that need a real browser. Add hosts here as we discover them.
_JS_HOSTS = (
    "my.rcr.ac.uk",        # Salesforce LWC
    "events.engage.rcgp",  # not actually JS but here for safety
    "rcgpac.org.uk",       # rcgp annual conf subsite
)


class PageCache:
    """Per-run cache. One instance per CLI invocation."""

    def __init__(self):
        self._cache: Dict[str, Optional[str]] = {}
        self._browser = None  # lazy-init

    def get(self, url: str) -> Optional[str]:
        """Return body innerText for the URL. None on failure.

        Lazy: uses httpx for most hosts; spins up the existing
        BrowserController for known JS-rendered hosts only.
        """
        if url in self._cache:
            return self._cache[url]
        text = self._fetch(url)
        self._cache[url] = text
        return text

    def _fetch(self, url: str) -> Optional[str]:
        if any(h in url for h in _JS_HOSTS):
            return self._fetch_browser(url)
        return self._fetch_httpx(url)

    def _fetch_httpx(self, url: str) -> Optional[str]:
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                # Strip HTML tags, collapse whitespace
                t = re.sub(r"<[^>]+>", " ", r.text)
                t = re.sub(r"\s+", " ", t).strip()
                return t[:20000]
        except Exception as e:
            logger.warning(f"remediator: httpx fetch failed for {url}: {e}")
            return None

    def _fetch_browser(self, url: str) -> Optional[str]:
        if self._browser is None:
            try:
                from browser import BrowserController
                self._browser = BrowserController()
                self._browser.launch()
            except Exception as e:
                logger.warning(f"remediator: browser launch failed: {e}")
                return None
        try:
            self._browser.navigate(url)
            self._browser.page.wait_for_timeout(8000)
            # Scroll a couple of times to trigger lazy-loaded content
            for _ in range(2):
                self._browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self._browser.page.wait_for_timeout(1500)
            return (self._browser.page.evaluate("() => document.body.innerText || ''") or "")[:20000]
        except Exception as e:
            logger.warning(f"remediator: browser fetch failed for {url}: {e}")
            return None

    def close(self):
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

    # Context-manager convenience
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
