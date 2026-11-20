"""BOPA (source 13): an events API that answers 200 with no events is a verified-empty
listing, never a hand-off to the generic page walker (2026-11-19: the walker made 60
'Events Search and Views Navigation' rows from /events/list/page/N/)."""
import httpx

from extractors import bopa


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)

    def __init_subclass__(cls, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self._responses.pop(0)


def _patch(monkeypatch, responses):
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: _Client(responses))


def _extractor():
    return bopa.BOPAExtractor({"id": 13, "source_name": "BOPA"})


def test_api_with_events_returns_shells(monkeypatch):
    ev = {"title": "BOPA AI Hackathon", "url": "https://www.bopa.org.uk/event/hack/",
          "start_date": "2027-03-01 09:00:00", "end_date": "2027-03-01 17:00:00",
          "categories": [], "venue": {}, "cost": "-", "description": ""}
    _patch(monkeypatch, [_Resp(200, {"events": [ev], "total": 1}), _Resp(200, {"events": []})])
    x = _extractor()
    shells = x.list_shells_override()
    assert [s["title"] for s in shells] == ["BOPA AI Hackathon"]
    assert x.verified_empty is None


def test_api_answering_zero_events_is_verified_empty_not_fallback(monkeypatch):
    _patch(monkeypatch, [_Resp(200, {"events": [], "total": 0, "total_pages": 0})])
    x = _extractor()
    assert x.list_shells_override() == []          # [] = use it, no DOM walker
    assert x.verified_empty


def test_api_failure_still_falls_back(monkeypatch):
    _patch(monkeypatch, [_Resp(503, {})])
    x = _extractor()
    assert x.list_shells_override() is None         # None = generic walker as before
    assert x.verified_empty is None


def test_ended_events_skipped_but_ongoing_kept(monkeypatch):
    from datetime import date, timedelta
    t = date.today()
    over = {"title": "Old webinar", "url": "https://www.bopa.org.uk/event/old/",
            "start_date": f"{t - timedelta(days=9)} 13:00:00",
            "end_date": f"{t - timedelta(days=9)} 14:00:00", "categories": [], "venue": {}}
    ongoing = {"title": "BOPA AI Hackathon", "url": "https://www.bopa.org.uk/event/hack/",
               "start_date": f"{t - timedelta(days=2)} 12:00:00",
               "end_date": f"{t + timedelta(days=5)} 14:30:00", "categories": [], "venue": {}}
    _patch(monkeypatch, [_Resp(200, {"events": [over, ongoing]}), _Resp(200, {"events": []})])
    x = _extractor()
    assert [s["title"] for s in x.list_shells_override()] == ["BOPA AI Hackathon"]
    assert x.verified_empty is None


def test_only_ended_events_is_verified_empty(monkeypatch):
    from datetime import date, timedelta
    d = f"{date.today() - timedelta(days=3)} 10:00:00"
    over = {"title": "Old", "url": "https://www.bopa.org.uk/event/old/", "start_date": d,
            "end_date": d, "categories": [], "venue": {}}
    _patch(monkeypatch, [_Resp(200, {"events": [over]}), _Resp(200, {"events": []})])
    x = _extractor()
    assert x.list_shells_override() == []
    assert x.verified_empty
