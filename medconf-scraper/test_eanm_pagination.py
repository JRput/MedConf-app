"""EANM (51): a catalogue of exactly N*100 events makes the walk request one
page past the end; WordPress answers HTTP 400 rest_post_invalid_page_number,
which must end the walk, not abort it (2026-10-16)."""
import json
import httpx
from extractors import eanm


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self.text = json.dumps(payload)


def test_past_end_400_ends_the_walk(monkeypatch):
    pages = {1: _Resp(200, [{"id": 1}] * eanm.PER_PAGE),
             2: _Resp(400, {"code": "rest_post_invalid_page_number", "data": {"status": 400}})}
    monkeypatch.setattr(httpx, "get", lambda url, **k: pages[int(url.rsplit("page=", 1)[1])])
    monkeypatch.setattr(eanm, "fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fallback")))
    ex = eanm.EanmExtractor.__new__(eanm.EanmExtractor)
    assert len(ex._fetch_page(1)) == eanm.PER_PAGE
    assert ex._fetch_page(2) == []


def test_other_400s_still_fall_back(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _Resp(400, {"code": "rest_invalid_param"}))
    calls = []
    monkeypatch.setattr(eanm, "fetch_html", lambda *a, **k: calls.append(1) or None)
    monkeypatch.setattr(eanm.time, "sleep", lambda s: None)
    ex = eanm.EanmExtractor.__new__(eanm.EanmExtractor)
    assert ex._fetch_page(1) is None
    assert len(calls) == eanm.FETCH_TRIES
