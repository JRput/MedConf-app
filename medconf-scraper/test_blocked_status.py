"""Anti-bot 'blocked' outcome: scrape_source status + group exit code."""
import logging

import main
import scraper


class FakeBrowser:
    def __init__(self, challenged):
        self.challenged_count = 1 if challenged else 0
        self.last_challenge_url = "https://arvo.example/events" if challenged else None


class FakeAgent:
    challenged = False
    shells = []

    def __init__(self, source):
        self.browser = FakeBrowser(FakeAgent.challenged)

    def open_browser(self): pass
    def close_browser(self): pass
    def list_shells(self): return FakeAgent.shells


SRC = {"id": 42, "source_name": "ARVO", "base_url": "https://arvo.example"}


def _scrape(monkeypatch, challenged):
    FakeAgent.challenged = challenged
    monkeypatch.setattr(scraper, "AgentLoop", FakeAgent)
    return scraper.scrape_source(SRC)


def test_challenged_zero_cards_is_blocked(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="medconf-scraper"):
        s = _scrape(monkeypatch, True)
    assert s["status"] == "blocked"
    assert "anti-bot" in s["error_details"]
    assert any("ARVO" in r.message and r.levelno == logging.WARNING for r in caplog.records)


def test_zero_cards_without_challenge_is_failed(monkeypatch):
    s = _scrape(monkeypatch, False)
    assert s["status"] == "failed"


def _run_single(monkeypatch, status, history):
    logged = []
    monkeypatch.setattr(main, "get_active_sources", lambda: [SRC])
    monkeypatch.setattr(main, "scrape_source", lambda src: {"source_id": 42, "status": status})
    monkeypatch.setattr(main, "get_recent_log_statuses", lambda sid, n: history[:n])
    monkeypatch.setattr(main, "log_scrape_run", lambda s: logged.append(s))
    monkeypatch.setattr(main, "update_source_last_full_walk", lambda sid: None)
    for fn in ("archive_expired_conferences", "archive_undated_past_conferences",
               "archive_stale_conferences", "close_passed_abstract_deadlines"):
        monkeypatch.setattr(main, fn, lambda *a, **k: 0)
    rc = main.run_single_source(42)
    assert logged and logged[0]["status"] == status  # blocked is recorded, not hidden
    return rc


def test_single_block_does_not_fail_group(monkeypatch):
    assert _run_single(monkeypatch, "blocked", ["success", "success"]) == 2


def test_two_prior_blocked_fails_group(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR, logger="medconf-scraper"):
        assert _run_single(monkeypatch, "blocked", ["blocked", "blocked"]) == 1
    assert any("Source 42 blocked by anti-bot for 3 consecutive runs" in r.message
               for r in caplog.records)


def test_streak_broken_by_success_or_short_history(monkeypatch):
    assert _run_single(monkeypatch, "blocked", ["blocked", "success"]) == 2
    assert _run_single(monkeypatch, "blocked", ["blocked"]) == 2


def test_failed_still_fails_immediately(monkeypatch):
    assert _run_single(monkeypatch, "failed", []) == 1


def test_group_exit_codes(monkeypatch):
    monkeypatch.setattr(main, "run_single_source", lambda sid: 0)
    assert main.run_source_group([42]) == 0
    monkeypatch.setattr(main, "run_single_source", lambda sid: 1)
    assert main.run_source_group([42]) == 1


# --- http_fetch path (BIASP case: httpx 403 + browser fallback fails) ---------
from extractors import http_fetch
from test_http_fetch import (FakeBrowserController, FakeResponse, _make_caller_page,
                             _patch_httpx_client, _restore_httpx_client)


class _DeadNewPage:
    def goto(self, *a, **kw):
        raise RuntimeError("still challenged")

    def close(self):
        pass


def _listing_agent(httpx_status, new_page):
    class Agent(FakeAgent):
        def __init__(self, source):
            caller_page, _ = _make_caller_page(new_page)
            self.browser = FakeBrowserController(caller_page)
            self.browser.challenged_count = 0
            self.browser.last_challenge_url = None

        def list_shells(self):
            http_fetch.fetch_html("https://biasp.example/events/", browser=self.browser, timeout=5.0)
            return []
    return Agent


def test_httpx_403_plus_failed_browser_is_blocked(monkeypatch):
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))
        monkeypatch.setattr(scraper, "AgentLoop", _listing_agent(403, _DeadNewPage()))
        s = scraper.scrape_source({"id": 72, "source_name": "BIASP", "base_url": "https://biasp.example"})
    finally:
        _restore_httpx_client(original)
    assert s["status"] == "blocked"
    assert "biasp.example" in s["error_details"]


def test_httpx_blocked_without_browser_registers_block():
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(403, "Forbidden"))
        http_fetch.reset_blocks()
        assert http_fetch.fetch_html("https://x.example/e", browser=None, timeout=5.0) is None
    finally:
        _restore_httpx_client(original)
    assert http_fetch.last_block["count"] == 1


def test_httpx_404_is_not_a_block(monkeypatch):
    original = http_fetch.httpx.Client
    try:
        _patch_httpx_client(None, FakeResponse(404, "nope"))
        http_fetch.reset_blocks()
        assert http_fetch.fetch_html("https://x.example/e", browser=None, timeout=5.0) is None
    finally:
        _restore_httpx_client(original)
    assert http_fetch.last_block["count"] == 0


def test_stale_block_does_not_leak_into_next_source(monkeypatch):
    http_fetch.last_block["count"] = 5
    s = _scrape(monkeypatch, False)   # scrape_source resets the registry
    assert s["status"] == "failed"
