#!/usr/bin/env python3
"""Offline unit tests for extractors/http_fetch.py — no network, all fakes.

Run with either:
    ./.venv/bin/python test_http_fetch.py
    ./.venv/bin/pytest test_http_fetch.py -v
"""

import sys
import types
from typing import Optional

from extractors import http_fetch


# ---------------------------------------------------------------------- #
# Fakes
# ---------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class FakeHttpxClient:
    """Stand-in for httpx.Client used as a context manager."""

    # Each test sets FakeHttpxClient.NEXT to a FakeResponse or an Exception
    # instance/class to raise.
    NEXT = None
    CALLS = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        FakeHttpxClient.CALLS.append(url)
        nxt = FakeHttpxClient.NEXT
        if isinstance(nxt, Exception) or (isinstance(nxt, type) and issubclass(nxt, Exception)):
            raise nxt
        return nxt


class FakePage:
    """Stand-in for a Playwright Page, used only via .context.new_page()."""

    def __init__(self, content_sequence):
        # content_sequence: list of HTML strings returned by successive
        # .content() calls (simulates a challenge page resolving over time).
        self._content_sequence = list(content_sequence)
        self.closed = False
        self.goto_calls = []
        self.wait_calls = 0

    def goto(self, url, wait_until="load", timeout=30000):
        self.goto_calls.append(url)

    def set_default_timeout(self, ms):
        pass

    def wait_for_load_state(self, state="load", timeout=5000):
        pass

    def content(self):
        if len(self._content_sequence) > 1:
            return self._content_sequence.pop(0)
        return self._content_sequence[0]

    def wait_for_timeout(self, ms):
        self.wait_calls += 1
        # Consume the next queued content on each poll so the loop can
        # observe the challenge "resolving".
        if len(self._content_sequence) > 1:
            self._content_sequence.pop(0)

    def close(self):
        self.closed = True


class FakeNewContext:
    """A freshly-opened browser context (what page.context.browser.new_context()
    returns) — supports new_page() and close()."""

    def __init__(self, page_to_return):
        self._page_to_return = page_to_return
        self.new_page_calls = 0
        self.closed = False

    def new_page(self):
        self.new_page_calls += 1
        return self._page_to_return

    def close(self):
        self.closed = True


class FakeBrowser:
    """Stand-in for the Playwright Browser (page.context.browser)."""

    def __init__(self, new_context_to_return):
        self._new_context_to_return = new_context_to_return
        self.new_context_calls = 0

    def new_context(self):
        self.new_context_calls += 1
        return self._new_context_to_return


class FakeExistingContext:
    """The implicit single-page context the caller's page already lives in
    (as created by Browser.new_page()) — only exposes `.browser`."""

    def __init__(self, browser):
        self.browser = browser


class FakeCallerPage:
    """The page a caller (extractor) is already using — must never be
    navigated or closed by fetch_html."""

    def __init__(self, context):
        self.context = context
        self.goto_calls = []
        self.closed = False

    def goto(self, *a, **kw):
        self.goto_calls.append(a)

    def close(self):
        self.closed = True


class FakeBrowserController:
    """Stand-in for browser.py's BrowserController — exposes `.page`."""

    def __init__(self, page):
        self.page = page


def _make_caller_page(new_page_for_fallback):
    """Build the chain: caller_page.context.browser.new_context().new_page()
    -> new_page_for_fallback, mirroring real Playwright's single-page-context
    restriction that http_fetch.py works around."""
    new_context = FakeNewContext(new_page_for_fallback)
    browser = FakeBrowser(new_context)
    existing_context = FakeExistingContext(browser)
    return FakeCallerPage(existing_context), new_context


def _patch_httpx_client(monkeypatch_target, response_or_exc):
    FakeHttpxClient.NEXT = response_or_exc
    FakeHttpxClient.CALLS = []
    http_fetch.httpx.Client = FakeHttpxClient


def _restore_httpx_client(original):
    http_fetch.httpx.Client = original


# ---------------------------------------------------------------------- #
# Tests
# ---------------------------------------------------------------------- #

def test_looks_blocked_status_403():
    assert http_fetch._looks_blocked(403, "whatever") == "status 403"


def test_looks_blocked_status_202():
    assert http_fetch._looks_blocked(202, "Accepted") == "status 202"


def test_looks_blocked_status_429_503():
    assert http_fetch._looks_blocked(429, "x") == "status 429"
    assert http_fetch._looks_blocked(503, "x") == "status 503"


def test_looks_blocked_challenge_body_on_200():
    body = "<html><body>Just a moment...</body></html>"
    reason = http_fetch._looks_blocked(200, body)
    assert reason is not None and "challenge" in reason


def test_looks_blocked_short_200_body():
    reason = http_fetch._looks_blocked(200, "<html>tiny</html>")
    assert reason is not None and "short" in reason


def test_looks_blocked_real_200_page_is_fine():
    body = "<html><body>" + ("real content " * 100) + "</body></html>"
    assert http_fetch._looks_blocked(200, body) is None


def test_httpx_success_path_never_touches_browser():
    original = http_fetch.httpx.Client
    try:
        good_body = "<html><body>" + ("conference listing " * 100) + "</body></html>"
        _patch_httpx_client(None, FakeResponse(200, good_body))

        class ExplodingBrowser:
            @property
            def page(self):
                raise AssertionError("browser fallback should never be touched on httpx success")

        result = http_fetch.fetch_html("https://example.org/events", browser=ExplodingBrowser())
        assert result == good_body
        assert FakeHttpxClient.CALLS == ["https://example.org/events"]
    finally:
        _restore_httpx_client(original)


def test_fallback_used_when_httpx_blocked_403():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))

        good_html = "<html><body>real page</body></html>"
        fake_new_page = FakePage([good_html])
        caller_page, new_context = _make_caller_page(fake_new_page)
        browser = FakeBrowserController(caller_page)

        result = http_fetch.fetch_html("https://example.org/hub", browser=browser, timeout=5.0)

        assert result == good_html
        assert new_context.new_page_calls == 1
        assert new_context.closed is True
        assert fake_new_page.closed is True
        # The caller's own page must never be navigated or closed.
        assert caller_page.goto_calls == []
        assert caller_page.closed is False
    finally:
        _restore_httpx_client(original)


def test_fallback_used_when_httpx_returns_202():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(202, "Accepted"))
        good_html = "<html><body>real page after 202</body></html>"
        caller_page, _ = _make_caller_page(FakePage([good_html]))
        browser = FakeBrowserController(caller_page)

        result = http_fetch.fetch_html("https://example.org/events", browser=browser, timeout=5.0)
        assert result == good_html
    finally:
        _restore_httpx_client(original)


def test_fallback_waits_out_a_challenge_interstitial():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))
        # First .content() call sees the challenge, then it resolves.
        challenge = "<html><body>Just a moment...</body></html>"
        resolved = "<html><body>" + ("real content " * 50) + "</body></html>"
        fake_new_page = FakePage([challenge, resolved])
        caller_page, _ = _make_caller_page(fake_new_page)
        browser = FakeBrowserController(caller_page)

        result = http_fetch.fetch_html("https://example.org/hub", browser=browser, timeout=5.0)
        assert result == resolved
        assert fake_new_page.wait_calls >= 1
    finally:
        _restore_httpx_client(original)


def test_returns_none_when_both_paths_fail_no_browser():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, ConnectionError("boom"))
        result = http_fetch.fetch_html("https://example.org/hub", browser=None, timeout=5.0)
        assert result is None
    finally:
        _restore_httpx_client(original)


def test_returns_none_when_both_paths_fail_with_browser():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))

        class ExplodingNewPage:
            def goto(self, *a, **kw):
                raise RuntimeError("navigation timeout")

            def close(self):
                pass

        caller_page, _ = _make_caller_page(ExplodingNewPage())
        browser = FakeBrowserController(caller_page)
        result = http_fetch.fetch_html("https://example.org/hub", browser=browser, timeout=5.0)
        assert result is None
    finally:
        _restore_httpx_client(original)


def test_accepts_raw_page_in_place_of_browser_controller():
    """browser= may be a Playwright Page directly, not just a BrowserController."""
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))
        good_html = "<html><body>fetched via raw page context</body></html>"
        raw_page, _ = _make_caller_page(FakePage([good_html]))
        result = http_fetch.fetch_html("https://example.org/hub", browser=raw_page, timeout=5.0)
        assert result == good_html
    finally:
        _restore_httpx_client(original)


ALL_TESTS = [
    test_looks_blocked_status_403,
    test_looks_blocked_status_202,
    test_looks_blocked_status_429_503,
    test_looks_blocked_challenge_body_on_200,
    test_looks_blocked_short_200_body,
    test_looks_blocked_real_200_page_is_fine,
    test_httpx_success_path_never_touches_browser,
    test_fallback_used_when_httpx_blocked_403,
    test_fallback_used_when_httpx_returns_202,
    test_fallback_waits_out_a_challenge_interstitial,
    test_returns_none_when_both_paths_fail_no_browser,
    test_returns_none_when_both_paths_fail_with_browser,
    test_accepts_raw_page_in_place_of_browser_controller,
]


if __name__ == "__main__":
    failures = 0
    for t in ALL_TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(ALL_TESTS) - failures}/{len(ALL_TESTS)} passed")
    sys.exit(1 if failures else 0)
