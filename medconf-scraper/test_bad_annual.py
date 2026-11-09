import extractors.bad_annual as m1
from extractors.bad_annual import BadAnnualExtractor

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


def test_city_region_and_description_from_the_intro_paragraph(monkeypatch):
    e = BadAnnualExtractor({"id": 0})
    monkeypatch.setattr(e, "_get", lambda url, tries=3: None)
    shell = {"title": "BAD Annual Meeting 2027", "start_date": "2027-06-29", "end_date": "2027-07-01", "edition_year": 2027}
    out = e.detail_from_html(fx("bad_annual_home.html"), "https://badannualmeeting.co.uk/", shell, None)
    assert out["city"] == "Liverpool" and out["region"] == "England"
    assert out["description"].startswith("We are delighted to be returning to Liverpool")
    assert "pricing_tiers" not in out                                       # 2027 registration opens February 2027
