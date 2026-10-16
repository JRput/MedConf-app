"""RCEM (6/7): when every listing fetch times out, the run is `unreachable`
(tolerated), not `failed` (2026-10-16: five timeouts turned group A red)."""
import httpx
from extractors import http_fetch, rcem


def test_all_timeouts_register_unreachable(monkeypatch):
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr("time.sleep", lambda s: None)
    http_fetch.reset_blocks()
    ex = rcem.RCEMExtractor.__new__(rcem.RCEMExtractor)
    ex.source_id = rcem.RCEMExtractor.EVENTS_CALENDAR_ID
    ex.source = {"base_url": "https://rcem.ac.uk/events-calendar/"}
    assert ex.list_shells_override() is None
    assert http_fetch.last_fetch_problem["unreachable"] == 1
    assert http_fetch.last_fetch_problem["url"]["unreachable"] == "https://rcem.ac.uk/events-calendar/"
