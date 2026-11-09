"""robots.txt gate for discovery fetches."""
import pytest

import robots_gate
from extractors import discovery


@pytest.fixture(autouse=True)
def _clean():
    robots_gate.reset()
    yield
    robots_gate.reset()


def _robots(monkeypatch, text, calls=None):
    def fake(origin):
        if calls is not None:
            calls.append(origin)
        if isinstance(text, Exception):
            return None
        return text
    monkeypatch.setattr(robots_gate, "_fetch_robots_text", fake)


def _stream(monkeypatch):
    seen = []

    def fake(url, timeout, max_bytes, headers=None):
        seen.append(url)
        return 200, b"<html><body>" + b"<p>Annual Meeting registration open now</p>" * 20 + b"</body></html>", "utf-8"
    monkeypatch.setattr(discovery, "_stream_body", fake)
    monkeypatch.setattr("safe_fetch.enabled", lambda: False)
    return seen


def test_disallowed_path_skipped(monkeypatch):
    _robots(monkeypatch, "User-agent: *\nDisallow: /registration\n")
    seen = _stream(monkeypatch)
    assert discovery._fetch_html("https://a.org/registration/fees", 5) is None
    assert seen == []


def test_disallow_all_host_skipped(monkeypatch):
    _robots(monkeypatch, "User-agent: *\nDisallow: /\n")
    seen = _stream(monkeypatch)
    assert discovery._fetch_html("https://a.org/", 5) is None
    assert discovery._fetch_bytes("https://a.org/f.pdf", 5) is None
    assert seen == []


def test_allowed_path_fetched(monkeypatch):
    _robots(monkeypatch, "User-agent: *\nDisallow: /private\n")
    seen = _stream(monkeypatch)
    assert discovery._fetch_html("https://a.org/registration", 5) is not None
    assert seen == ["https://a.org/registration"]


def test_robots_fetch_error_allows(monkeypatch):
    _robots(monkeypatch, RuntimeError("boom"))
    seen = _stream(monkeypatch)
    assert discovery._fetch_html("https://a.org/x", 5) is not None
    assert seen


def test_robots_fetched_once_per_host(monkeypatch):
    calls = []
    _robots(monkeypatch, "User-agent: *\nDisallow:\n", calls)
    _stream(monkeypatch)
    discovery._fetch_html("https://a.org/one", 5)
    discovery._fetch_html("https://a.org/two", 5)
    assert calls == ["https://a.org"]


def test_crawl_delay_sleeps_capped(monkeypatch):
    _robots(monkeypatch, "User-agent: *\nCrawl-delay: 60\n")
    _stream(monkeypatch)
    slept = []
    monkeypatch.setattr(robots_gate.time, "sleep", lambda s: slept.append(s))
    discovery._fetch_html("https://a.org/one", 5)
    discovery._fetch_html("https://a.org/two", 5)
    assert len(slept) == 1 and 0 < slept[0] <= robots_gate.CRAWL_DELAY_CAP


def test_disallowed_image_not_sent_to_vision(monkeypatch):
    _robots(monkeypatch, "User-agent: *\nDisallow: /img\n")
    import vision
    monkeypatch.setattr(vision, "extract_pricing_from_images",
                        lambda *a, **k: pytest.fail("vision must not fetch a disallowed image"))
    assert discovery._vision_pricing(["https://a.org/img/fees.png"], 0, 5) == []
