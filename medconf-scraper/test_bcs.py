"""BCS extractor: listing cards, EventsAir fee blocks, conference dates from the rate-card text (offline fixtures)."""
import re
from datetime import date
from pathlib import Path

from extractors import bcs
from extractors.tribe_events import html_to_lines

FIX = Path(__file__).parent / "test_fixtures"
TODAY = date(2026, 11, 9)


def _read(name):
    return (FIX / name).read_text()


def _lines(name):
    return html_to_lines(re.sub(r"(?is)<(script|style|svg|nav|header|footer)\b.*?</\1>", " ", _read(name)))


def test_listing_cards_are_upcoming_eventsair_links():
    shells = bcs.parse_courses_listing(_read("bcs_courses.html"), TODAY)
    assert len(shells) == 7
    first = shells[0]
    assert first["title"] == "Year in Cardiology 2026" and first["start_date"] == "2026-12-11"
    assert first["booking_url"].startswith("https://bcs-year-in-cardiology-2026.eventsair")
    assert first["venue_raw"] == "Royal College of Physicians, London"
    assert any("&" in s["title"] and "&amp;" not in s["title"] for s in shells)          # entities unescaped
    assert next(s for s in shells if "Webinar" in s["title"])["category"] == "webinar"
    assert bcs.parse_courses_listing(_read("bcs_courses.html"), date(2027, 6, 1)) == []


def test_fee_block_regular_and_early_bird_on_one_line():
    tiers = bcs.parse_fee_tiers(_lines("bcs_course_mayo.html"))
    by = {t["tier_label"]: t for t in tiers}
    assert by["Members · Regular"]["price_gbp"] == 998.0 and not by["Members · Regular"]["is_early_bird"]
    assert by["Members · Early bird"]["price_gbp"] == 898.0 and by["Members · Early bird"]["is_early_bird"]
    assert by["Non-members · Early bird"]["price_gbp"] == 1596.0
    assert "Enter code" not in " ".join(by)
    assert {t["currency"] for t in tiers} == {"GBP"}


def test_fee_block_attendance_fee_heading_and_colon_labels():
    tiers = bcs.parse_fee_tiers(_lines("bcs_course_cvd.html"))
    assert [(t["tier_label"], t["price_gbp"]) for t in tiers] == [
        ("BCS Associate BCJA and Affiliate members", 105.0), ("BCS Ordinary and International members", 216.0), ("Non-members", 462.0)]


def test_webinar_has_no_fee_and_dates():
    lines = _lines("bcs_course_webinar.html")
    assert bcs.parse_fee_tiers(lines) == []
    assert bcs.parse_course_dates(lines) == ("2026-11-30", None)


def test_date_range_and_place():
    assert bcs.parse_course_dates(_lines("bcs_course_mayo.html")) == ("2027-03-15", "2027-03-19")
    assert bcs.parse_course_dates(["29 Nov - 1 Dec 2026"]) == ("2026-11-29", "2026-12-01")
    p = bcs.split_place("BMA House, Tavistock Square, London WC1H 9JP")
    assert p["city"] == "London" and p["venue_name"] == "BMA House, Tavistock Square" and p["event_format"] == "in_person"
    assert bcs.split_place("Online") == {"event_format": "online"}


def test_annual_conference_dates_come_from_the_rate_card_text_only():
    txt = "BCS Annual Conference Monday 7 - Wednesday 9 June 2027, Manchester Central Exhibition Stand and Sponsored Symposium Packages 2027"
    assert bcs.parse_conference_dates(txt, TODAY) == {"start": "2027-06-07", "end": "2027-06-09", "venue": "Manchester Central"}
    assert bcs.parse_conference_dates("Annual Conference 2027 watch this space", TODAY) is None
    assert bcs.parse_conference_dates(txt, date(2027, 7, 1)) is None


def test_extract_detail_course(monkeypatch):
    html = _read("bcs_course_mayo.html")
    monkeypatch.setattr(bcs, "fetch_html", lambda *a, **k: html)
    ext = bcs.BcsExtractor({"id": 155})
    shell = {"title": "BCS & Mayo Clinic Cardiology Review Course 2027", "booking_url": "https://bcs-x.eventsairsite.com", "start_date": "2027-03-15",
             "venue_raw": "Royal College of Physicians, London", "category": "course"}
    out = ext.extract_detail(None, shell, lambda p: None)
    assert out["event_type"] == "course" and out["specialty"] == "Cardiology" and out["end_date"] == "2027-03-19"
    assert out["venue_name"] == "Royal College of Physicians" and out["city"] == "London" and len(out["pricing_tiers"]) == 9


class _Page:
    def __init__(self, url, html):
        self.url, self._html = url, html

    def content(self):
        return self._html


def test_error_page_is_discarded_and_course_fetched_afresh(monkeypatch):
    html = _read("bcs_course_mayo.html")
    seen = {}

    def fake_fetch(url, **kw):
        seen["loaded_page"] = kw.get("loaded_page", "missing")
        return html
    monkeypatch.setattr(bcs, "fetch_html", fake_fetch)
    shell = {"title": "BCS & Mayo Clinic Cardiology Review Course 2027", "booking_url": "https://bcs-x.eventsairsite.com", "start_date": "2027-03-15",
             "venue_raw": "Royal College of Physicians, London", "category": "course"}
    for bad in (_Page("chrome-error://chromewebdata/", "<html><body>This site can't be reached</body></html>"),
                _Page("https://bcs-x.eventsairsite.com", "<html><body>empty</body></html>")):
        seen.clear()
        out = bcs.BcsExtractor({"id": 155}).extract_detail(bad, shell, lambda p: None)
        assert seen["loaded_page"] is None                                   # the error page was NOT passed on
        assert len(out["pricing_tiers"]) == 9
    good = _Page("https://bcs-x.eventsairsite.com", html)
    assert bcs.usable_loaded_page(good) is good and bcs.usable_loaded_page(None) is None


def test_own_site_requests_respect_crawl_delay(monkeypatch):
    sleeps, clock = [], [100.0]
    monkeypatch.setattr(bcs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bcs.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)))
    saved = bcs._last_own_fetch[0]
    bcs._last_own_fetch[0] = 0.0
    bcs._own_site_wait()
    clock[0] += 3
    bcs._own_site_wait()
    bcs._last_own_fetch[0] = saved
    assert sleeps == [7.0]
