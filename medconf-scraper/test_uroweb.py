"""EAU / uroweb (source 50): the listing comes from the __NUXT_DATA__ payload of
https://uroweb.org/education-events/events?page=N (saved page, no network).

The HTML `card card--small` blocks are loading placeholders (empty skeletons);
the real entries are only in the payload, 16 per page.
"""
from datetime import date
from pathlib import Path

import pytest

from extractors import uroweb
from extractors.uroweb import UrowebExtractor, parse_listing_payload

FIX = Path(__file__).parent / "test_fixtures" / "uroweb_events_page1_2026-11-20.html"
PAGE1 = FIX.read_text()


def _today(monkeypatch, y, m, d):
    monkeypatch.setattr(uroweb, "date", type("D", (date,), {"today": staticmethod(lambda: date(y, m, d))}))


def _ex():
    ex = UrowebExtractor({"id": 50, "source_name": "EAU"})
    ex.browser = None
    return ex


def test_parses_real_payload(monkeypatch):
    parsed = parse_listing_payload(PAGE1)
    assert parsed["total"] == 42
    assert len(parsed["entries"]) == 16
    _today(monkeypatch, 2026, 11, 20)
    shells = UrowebExtractor._shells_from_entries(parsed["entries"])
    assert len(shells) == 16
    first = shells[0]
    assert first["title"] == "ESU Urology Boot Camp Portugal 2026"
    assert first["booking_url"] == "https://uroweb.org/education-events/esu-urology-boot-camp-portugal-2026"
    assert first["start_date"] == "2026-11-20"
    assert first["city"] == "Lisbon"
    assert set(first) >= {"title", "booking_url", "start_date", "end_date", "city", "venue_name",
                          "event_type", "category", "topics"}
    london = next(s for s in shells if s["title"].startswith("13th Female Urology"))
    assert (london["start_date"], london["end_date"]) == ("2026-11-23", "2026-11-25")
    assert london["venue_name"] == "UCLH Education Centre" and london["city"] == "London"
    assert london["event_type"] == "workshop" and london["topics"] == ["Functional Urology"]
    web = next(s for s in shells if s["title"].startswith("UROwebinar"))
    assert web["city"] == "Online" and web["category"] == "Webinar"


def test_past_events_are_skipped(monkeypatch):
    parsed = parse_listing_payload(PAGE1)
    _today(monkeypatch, 2026, 11, 24)  # Boot Camps (20-21 Nov) and the 23-25 Nov masterclass: first ones over
    shells = UrowebExtractor._shells_from_entries(parsed["entries"])
    titles = [s["title"] for s in shells]
    assert "ESU Urology Boot Camp Portugal 2026" not in titles
    assert any(t.startswith("13th Female Urology") for t in titles)  # ends 25 Nov, still upcoming
    _today(monkeypatch, 2026, 11, 26)
    assert not any(t.startswith("13th Female Urology")
                   for t in (s["title"] for s in UrowebExtractor._shells_from_entries(parsed["entries"])))


def test_pagination_stops_at_entry_count(monkeypatch):
    from extractors import http_fetch
    _today(monkeypatch, 2026, 11, 20)
    monkeypatch.setattr(uroweb, "REQUEST_GAP_S", 0)
    monkeypatch.setattr(uroweb.time, "sleep", lambda s: None)
    monkeypatch.setattr(uroweb, "PAGE_SIZE", 16)
    calls = []

    def fake_fetch(url, **kw):
        calls.append(url)
        if url == uroweb.LISTING_URL:
            return PAGE1
        return PAGE1.replace("education-events\\u002Fesu-urology-boot-camp-portugal-2026",
                             "education-events\\u002Fpage-two-" + url[-1])

    monkeypatch.setattr(http_fetch, "fetch_html", fake_fetch)
    ex = _ex()
    shells = ex.list_shells_override()
    # total 42 -> pages 1, 2, 3 and then stop (no 4th request)
    assert [c.rsplit("=", 1)[-1] if "=" in c else "1" for c in calls] == ["1", "2", "3"]
    assert ex.verified_empty is None
    assert len(shells) == 16 + 1 + 1  # pages 2 and 3 repeat page 1 except one renamed uri each


def test_empty_calendar_is_verified_empty(monkeypatch):
    from extractors import http_fetch
    _today(monkeypatch, 2027, 6, 1)  # every entry in the saved page is over
    monkeypatch.setattr(http_fetch, "fetch_html", lambda url, **kw: PAGE1)
    monkeypatch.setattr(uroweb.time, "sleep", lambda s: None)
    ex = _ex()
    assert ex.list_shells_override() == []
    assert ex.verified_empty and "no upcoming event" in ex.verified_empty


def test_fetch_failure_is_none(monkeypatch):
    from extractors import http_fetch
    monkeypatch.setattr(http_fetch, "fetch_html", lambda url, **kw: None)
    ex = _ex()
    assert ex.list_shells_override() is None
    assert ex.verified_empty is None


def test_changed_markup_is_none(monkeypatch):
    from extractors import http_fetch
    monkeypatch.setattr(http_fetch, "fetch_html", lambda url, **kw: "<html><body>" + "x" * 800 + "</body></html>")
    ex = _ex()
    assert ex.list_shells_override() is None
    assert ex.verified_empty is None


def test_later_page_failure_keeps_earlier_entries(monkeypatch):
    from extractors import http_fetch
    _today(monkeypatch, 2026, 11, 20)
    monkeypatch.setattr(uroweb.time, "sleep", lambda s: None)
    monkeypatch.setattr(http_fetch, "fetch_html", lambda url, **kw: PAGE1 if url == uroweb.LISTING_URL else None)
    shells = _ex().list_shells_override()
    assert len(shells) == 16
