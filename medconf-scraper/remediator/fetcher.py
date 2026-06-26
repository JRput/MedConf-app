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
            self._browser.page.wait_for_timeout(10000)
            # Scroll to trigger lazy-loaded content
            for _ in range(2):
                self._browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self._browser.page.wait_for_timeout(1500)
            # Snapshot the initial view
            initial = (self._browser.page.evaluate("() => document.body.innerText || ''") or "")
            # Tabbed-page expansion — many Salesforce LWC / idloom / Cvent
            # detail pages tuck fees, CPD, abstracts behind tab clicks. Click
            # each tab in turn, snapshotting after each click so the last
            # click doesn't erase the others' content.
            tab_snapshots = self._click_and_snapshot_tabs()
            # Combine — initial first, then each tab panel's unique content
            combined_parts = [initial]
            for snap in tab_snapshots:
                # Only keep lines from the snapshot that weren't already in `initial`
                init_lines = set(l.strip() for l in initial.splitlines() if l.strip())
                new_lines = [l for l in snap.splitlines() if l.strip() and l.strip() not in init_lines]
                if new_lines:
                    combined_parts.append("\n".join(new_lines))
            combined = "\n\n".join(combined_parts)
            return combined[:50000]
        except Exception as e:
            logger.warning(f"remediator: browser fetch failed for {url}: {e}")
            return None

    # The tab labels we look for. Anything inside a tab/li/button element
    # whose label matches one of these gets clicked. Adding new labels here
    # is the cheap way to teach the remediator about a new source's
    # tab structure.
    _TAB_LABELS = (
        "Fees", "Pricing", "Cost", "Rates", "Tickets",
        "CPD", "CPD credits", "CPD points",
        "Abstracts", "Submissions", "Call for papers", "Submit",
        "Overview", "About", "Description", "Programme", "Agenda",
        "Plan attendance", "Venue", "Location", "Travel",
        "Speakers", "Faculty",
        "Booking options", "Registration", "How to book",
    )

    def _click_and_snapshot_tabs(self) -> list:
        """For each matching tab, click it, wait for its panel to render,
        capture body.innerText, then move on. Returns list of snapshots."""
        snapshots: list = []
        try:
            label_list = list(self._TAB_LABELS)
            # First, locate all distinct tab labels currently in the DOM
            tab_labels_present = self._browser.page.evaluate(
                r"""(labels) => {
                    const wanted = new Set(labels.map(s => s.toLowerCase()));
                    const found = new Set();
                    function walk(root) {
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) walk(el.shadowRoot);
                            if (el.tagName === 'H1' || el.tagName === 'H2') return;
                            if (el.children && el.children.length > 0) return;
                            const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
                            if (!t || t.length > 30) return;
                            if (wanted.has(t.toLowerCase())) found.add(t);
                        });
                    }
                    walk(document);
                    return [...found];
                }""",
                label_list,
            ) or []
            logger.info(f"remediator: tabs present: {tab_labels_present}")

            for label in tab_labels_present:
                try:
                    self._browser.page.evaluate(
                        r"""(label) => {
                            function walk(root) {
                                const all = root.querySelectorAll('*');
                                for (const el of all) {
                                    if (el.shadowRoot) {
                                        if (walk(el.shadowRoot)) return true;
                                    }
                                    if (el.tagName === 'H1' || el.tagName === 'H2') continue;
                                    if (el.children && el.children.length > 0) continue;
                                    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
                                    if (t === label) {
                                        const target = el.closest('button, a, [role=tab], [role=button], [aria-controls], li') || el;
                                        target.click();
                                        return true;
                                    }
                                }
                                return false;
                            }
                            walk(document);
                        }""",
                        label,
                    )
                    self._browser.page.wait_for_timeout(2200)
                    text = self._browser.page.evaluate(
                        "() => document.body.innerText || ''"
                    ) or ""
                    snapshots.append(text)
                except Exception as e:
                    logger.warning(f"remediator: tab click {label!r} failed: {e}")
        except Exception as e:
            logger.warning(f"remediator: tab enumeration failed: {e}")
        return snapshots

    def _expand_tabs(self) -> None:
        """Find clickable tab-like elements (including those in shadow DOM)
        and click each one. Mirror the approach from our manual probe:
        walk shadow DOM, find elements whose EXACT trimmed text matches
        one of the tab labels (skipping h1/h2 to avoid section titles)."""
        try:
            label_list = list(self._TAB_LABELS)
            clicked_count = self._browser.page.evaluate(
                r"""(labels) => {
                    const wanted = new Set(labels.map(s => s.toLowerCase()));
                    const candidates = [];
                    function walk(root) {
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) walk(el.shadowRoot);
                            if (el.tagName === 'H1' || el.tagName === 'H2') return;
                            // Only leaves (no element children) — tab labels are leaf nodes
                            if (el.children && el.children.length > 0) return;
                            const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
                            if (!t || t.length > 30) return;
                            if (wanted.has(t.toLowerCase())) candidates.push(el);
                        });
                    }
                    walk(document);
                    const seen = new WeakSet();
                    let n = 0;
                    for (const el of candidates) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        try {
                            // Click the closest interactive ancestor
                            const target = el.closest('button, a, [role=tab], [role=button], [aria-controls], li') || el;
                            target.click();
                            n++;
                        } catch (e) {}
                    }
                    return n;
                }""",
                label_list,
            )
            logger.info(f"remediator: clicked {clicked_count} tab(s)")
            # Give panels time to render content
            self._browser.page.wait_for_timeout(4000)
            # Scroll after tab expansion in case content extends the page
            self._browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._browser.page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"remediator: tab expansion failed: {e}")

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
