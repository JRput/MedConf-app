"""ESTRO listing: empty HTML is only a verified-empty result when the site's events API agrees."""
from extractors import estro


def _ext():
    return estro.ESTROExtractor({"id": 19, "source_name": "ESTRO", "base_url": estro.LISTING_URL})


def test_api_empty_marks_verified_empty(monkeypatch):
    monkeypatch.setattr(estro, "_walk_listing", lambda: [])
    monkeypatch.setattr(estro, "_published_congresses_via_api", lambda: [])
    e = _ext()
    assert e.list_shells_override() == []
    assert "no published upcoming congresses" in e.verified_empty


def test_api_has_live_but_html_empty_is_failure(monkeypatch):
    monkeypatch.setattr(estro, "_walk_listing", lambda: [])
    monkeypatch.setattr(estro, "_published_congresses_via_api", lambda: [{"msevtmgt_name": "ESTRO 2027"}])
    e = _ext()
    assert e.list_shells_override() is None
    assert e.verified_empty is None


def test_api_unreadable_is_failure(monkeypatch):
    monkeypatch.setattr(estro, "_walk_listing", lambda: [])
    monkeypatch.setattr(estro, "_published_congresses_via_api", lambda: None)
    e = _ext()
    assert e.list_shells_override() is None
    assert e.verified_empty is None


def test_html_shells_win(monkeypatch):
    monkeypatch.setattr(estro, "_walk_listing", lambda: [{"title": "ESTRO 2027"}])
    e = _ext()
    assert e.list_shells_override() == [{"title": "ESTRO 2027"}]
    assert e.verified_empty is None
