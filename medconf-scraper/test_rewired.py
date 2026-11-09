import extractors.rewired as m1
from extractors.rewired import RewiredExtractor

MODS = [m1]
import datetime as _dt
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "test_fixtures"


class _Today(_dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 9)


def fx(name):
    return (FIX / name).read_text()


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    import extractors.single_congress as sc
    monkeypatch.setattr(sc, "date", _Today)
    for m in MODS:
        monkeypatch.setattr(m, "date", _Today, raising=False)


def test_venue_and_description_from_json_ld(monkeypatch):
    e = RewiredExtractor({"id": 0})
    monkeypatch.setattr(e, "_get", lambda u, tries=3: None)
    shell = {"title": "Digital Health Rewired 2027", "start_date": "2027-03-16", "end_date": "2027-03-17", "edition_year": 2027}
    out = e.detail_from_html(fx("rewired_home.html"), "https://digitalhealthrewired.com/", shell, None)
    assert (out["venue_name"], out["city"], out["region"]) == ("NEC Birmingham", "Birmingham", "England")
    assert out["description"].startswith("Join us for Digital Health Rewired 2027")


def test_ticket_cards():
    import datetime
    e = RewiredExtractor({"id": 0})
    e._start = datetime.date(2027, 3, 16)
    t = e.fees_from_pages({"https://digitalhealthrewired.com/tickets-pricing": fx("rewired_tickets.html")}, 2027)
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [
        ("Two-day pass · Public and third sector · Free", 0.0), ("Two-day pass · Private sector · Book ahead (+VAT)", 789.0),
        ("Two-day pass · Private sector · On the door (+VAT)", 999.0), ("Two-day pass · Start-up company (+VAT)", 199.0)]


def test_closed_speaker_call():
    out = {}
    RewiredExtractor({"id": 0}).apply_abstracts(out, {"u": fx("rewired_speakers.html")}, {})
    assert out["abstract_deadline"] == "2026-09-25" and out["abstract_open"] is False
