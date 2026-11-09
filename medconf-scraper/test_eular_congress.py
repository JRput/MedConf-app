import extractors.eular_congress as m1
from extractors.eular_congress import EularCongressExtractor

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


def test_fee_grid_groups_and_skipped_rows():
    t = EularCongressExtractor({"id": 0}).fees_from_pages({"https://congress.eular.org/congress-registration": fx("eular_reg.html")}, 2027)
    by = {x["tier_label"]: x for x in t}
    assert by["Congress registration · Delegate · Early bird (until 31 March 2027)"]["price_gbp"] == 879.0
    assert by["Congress registration · HPR Delegate · Regular (from 1 April 2027)"]["price_gbp"] == 190.0
    assert by["Congress registration · Patients & Family · Early bird (until 31 March 2027)"]["price_gbp"] == 24.0
    assert by["Congress registration · Exhibitor"]["price_gbp"] == 200.0 and by["Social event · Congress Dinner (11 June 2027)"]["price_gbp"] == 95.0
    assert not any("Student" in k or "Press" in k for k in by) and all(x["currency"] == "EUR" for x in t) and len(t) == 16


def test_venue_is_the_congress_not_the_dinner_location(monkeypatch):
    e = EularCongressExtractor({"id": 0})
    e.fees_from_pages({"https://congress.eular.org/congress-registration": fx("eular_reg.html")}, 2027)
    monkeypatch.setattr(e, "_get", lambda u, tries=3: None)
    shell = {"title": "EULAR Congress 2027", "start_date": "2027-06-09", "end_date": "2027-06-12", "edition_year": 2027}
    out = e.detail_from_html(fx("eular_home.html"), "https://congress.eular.org/", shell, None)
    assert (out["venue_name"], out["city"], out["region"]) == ("Messe Berlin", "Berlin", "Germany")
    assert e.parse_place("EULAR Congress On-Demand Platform") == (None, None, None, False)
