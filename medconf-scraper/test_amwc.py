import extractors.amwc as amwc
from extractors.amwc import AmwcExtractor

MODS = [amwc]
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


def test_header_range_beats_json_ld_end_date():
    e = AmwcExtractor({"id": 0})
    ed = e._edition_from("https://www.amwc-conference.com/", fx("amwc_home.html"))
    assert (ed["start"], ed["end"]) == ("2027-04-01", "2027-04-03")


def test_pass_prices_struck_original_is_final_rate():
    t = AmwcExtractor({"id": 0}).fees_from_pages({"https://www.amwc-conference.com/register/": fx("amwc_register.html")}, 2027)
    by = {x["tier_label"]: x for x in t}
    assert by["Scientific Programme Pass · Early bird · until 14 January 2027"]["price_gbp"] == 1000.0
    assert by["Scientific Programme Pass · Final rate · from 15 January 2027"]["price_gbp"] == 1120.0
    assert all(x["currency"] == "EUR" for x in t) and len(t) == 6          # membership subscription is not a registration fee


def test_abstract_deadlines_get_the_year_before_the_congress():
    out = {}
    AmwcExtractor({"id": 0}).apply_abstracts(out, {"u": fx("amwc_abstract.html")}, {"start_date": "2027-04-01"})
    assert out["abstract_deadline"] == "2026-12-31" and out["abstract_open"] is True
    assert "Oral presentation 31 October 2026" in out["abstract_deadline_note"]
