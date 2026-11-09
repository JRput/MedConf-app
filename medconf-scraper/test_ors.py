"""ORS extractor: menu listing, event blocks, fee grid, abstract lines, save-the-date meetings (offline fixtures)."""
from datetime import date
from pathlib import Path

from extractors import ors

FIX = Path(__file__).parent / "test_fixtures"
TODAY = date(2026, 11, 9)


def _read(name):
    return (FIX / name).read_text()


def test_menu_links_are_the_events_group_only():
    links = ors.menu_event_links(_read("ors_events.html"))
    assert [l["url"] for l in links] == ["https://www.ors.org/psrs-2026/", "https://www.ors.org/2027-annual-meeting/",
                                         "https://www.ors.org/2027tendon/", "https://www.ors.org/2027-ors-musculoskeletal-biology-workshop/"]


def test_event_blocks():
    am = ors.parse_event_block(ors.content_lines(_read("ors_annual_meeting.html"))[:40])
    assert am == {"start": "2027-02-19", "end": "2027-02-23", "venue": "Moscone West Convention Center", "city": "San Francisco", "state": "California"}
    t = ors.parse_event_block(ors.content_lines(_read("ors_tendon.html"))[:40])
    assert (t["start"], t["end"], t["venue"], t["city"], t["state"]) == ("2027-06-02", "2027-06-05", "Hyatt Regency Boston", "Boston", "MA")
    w = ors.parse_event_block(ors.content_lines(_read("ors_workshop.html"))[:40])
    assert (w["start"], w["end"], w["city"]) == ("2027-07-17", "2027-07-22", "Midway")


def test_future_meetings_within_horizon():
    got = ors.parse_future_meetings(_read("ors_future.html"), TODAY)
    assert [g["title"] for g in got] == ["ORS 2027 Annual Meeting", "ORS 2028 Annual Meeting"]          # 2029 is beyond 18 months
    assert got[1]["city"] == "New Orleans" and got[1]["start"] == "2028-02-11"


def test_fee_grid_usd_member_and_non_member():
    lines = ors.content_lines(_read("ors_register2027.html"))
    assert ors.page_heading(lines) == "ORS 2027 Annual Meeting Registration"
    tiers = ors.parse_fee_grid(lines, 2027)
    by = {t["tier_label"]: t for t in tiers}
    assert len(tiers) == 14 and {t["currency"] for t in tiers} == {"USD"}
    assert by["ORS member · Student · Early registration"]["price_gbp"] == 365.0
    assert by["ORS member · Student · Early registration"]["early_bird_deadline"] == "2026-12-31"
    assert by["ORS member · Established · Regular registration"]["price_gbp"] == 1155.0
    assert by["Non-member · Early registration"]["price_gbp"] == 1245.0 and by["Non-member · Regular registration"]["price_gbp"] == 1580.0


def test_abstract_lines():
    tendon = ors.parse_abstract_lines(ors.content_lines(_read("ors_tendon.html")), TODAY)
    assert tendon == {"open": False, "deadline": "2027-02-05", "note": None}          # opens Dec 1; March 29 is only notifications
    am = ors.parse_abstract_lines(ors.content_lines(_read("ors_annual_meeting.html")), TODAY)
    assert am["open"] is True and "late-breaking" in am["note"].lower()
    assert ors.parse_abstract_lines(["nothing here"], TODAY) is None


def test_fee_page_must_name_the_edition(monkeypatch):
    pages = {"https://www.ors.org/register2027/": _read("ors_register2027.html")}
    monkeypatch.setattr(ors, "fetch_html", lambda url, **k: pages.get(url))
    ext = ors.OrsExtractor({"id": 158})
    good = {"title": "ORS 2027 Annual Meeting", "start_date": "2027-02-19", "fee_url": "https://www.ors.org/register2027/"}
    tiers = ext._fees(good)
    assert len(tiers) == 14 and tiers[0]["evidence_url"].endswith("/register2027/") and tiers[0]["evidence_identity"] == "strong"
    pages["https://www.ors.org/msk-2025register/"] = _read("ors_workshop.html")          # heading names no year: never trusted
    stale = {"title": "ORS Musculoskeletal Biology Workshop 2027", "start_date": "2027-07-17", "fee_url": "https://www.ors.org/msk-2025register/"}
    assert ext._fees(stale) == []
    wrong_year = {"title": "ORS 2028 Annual Meeting", "start_date": "2028-02-11", "fee_url": "https://www.ors.org/register2027/"}
    assert ext._fees(wrong_year) == []                                   # a 2027 grid is never attached to a 2028 row
