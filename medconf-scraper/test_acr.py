import extractors.acr as acr
from extractors.acr import AcrExtractor

MODS = [acr]
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


def test_place_refuses_date_label_and_strips_location_label():
    e = AcrExtractor({"id": 0})
    assert e.parse_place("Date") == (None, None, None, False)
    assert e.parse_place("Location: Orlando, FL") == (None, "Orlando", "United States", False)
    assert e.parse_place("Orange County Convention Center, Orlando, Florida") == ("Orange County Convention Center", "Orlando", "United States", False)


def test_fee_grids_skip_expired_early_rate():
    t = AcrExtractor({"id": 0}).fees_from_pages({"https://rheumatology.org/annual-meeting-registration": fx("acr_registration.html")}, 2026)
    by = {x["tier_label"]: x["price_gbp"] for x in t}
    assert by["In Person · Member · ACR · General rate (through November 11)"] == 1400.0
    assert by["In Person Plus · Member · Student/Resident · General rate (through November 11)"] == 0.0
    assert by["In Person · Nonmember · Physician · General rate (through November 11)"] == 2150.0
    assert by["On Demand · Nonmember"] == 1225.0 and by["Add-on · Guest Pass"] == 285.0
    assert not any("Early" in k for k in by) and all(x["currency"] == "USD" for x in t)


def test_description_and_no_cpd_points(monkeypatch):
    e = AcrExtractor({"id": 0})
    monkeypatch.setattr(e, "_get", lambda u, tries=3: fx("acr_registration.html"))
    shell = {"title": "ACR Convergence 2026", "start_date": "2026-11-06", "end_date": "2026-11-11", "edition_year": 2026}
    out = e.detail_from_html(fx("acr_event.html"), "https://rheumatology.org/meetings/acr-convergence/", shell, None)
    assert out["description"].startswith("ACR Convergence is an in-person event")
    assert "cpd_points" not in out and out["city"] == "Orlando"


def test_after_the_edition_ends_listing_is_verified_empty(monkeypatch):
    class Later(_Today):
        @classmethod
        def today(cls):
            return cls(2026, 11, 12)
    import extractors.single_congress as sc
    monkeypatch.setattr(sc, "date", Later)
    e = AcrExtractor({"id": 0})
    monkeypatch.setattr(e, "_get", lambda u, tries=3: fx("acr_event.html"))
    assert e.list_shells_override() == [] and "no 2027 edition" in e.verified_empty
    monkeypatch.setattr(e, "_get", lambda u, tries=3: None)           # fetch failure is NOT verified empty
    assert e.list_shells_override() == [] and e.verified_empty is None
