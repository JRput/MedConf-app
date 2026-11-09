import extractors.aap as aap
from extractors.aap import AapExtractor

MODS = [aap]
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


def _ext(monkeypatch):
    e = AapExtractor({"id": 0})
    monkeypatch.setattr(e, "_get", lambda url, tries=3: fx("aap_future.html"))
    return e


def test_next_edition_with_venue_from_the_block(monkeypatch):
    s = _ext(monkeypatch).list_shells_override()
    assert len(s) == 1 and s[0]["start_date"] == "2027-10-15" and s[0]["end_date"] == "2027-10-19"
    assert s[0]["venue_raw"] == "McCormick Place, Chicago, United States"
    assert AapExtractor({"id": 0}).parse_place(s[0]["venue_raw"]) == ("McCormick Place", "Chicago", "United States", False)


def test_abstract_deadline_is_the_labelled_one_not_session_proposals():
    out = {}
    AapExtractor({"id": 0}).apply_abstracts(out, {"u": fx("aap_cfp.html")}, {"start_date": "2027-10-15", "edition_year": 2027})
    assert out["abstract_deadline"] == "2027-04-09" and out["abstract_open"] is True
    assert "November 20, 2026" in out["abstract_deadline_note"]


def test_2026_registration_page_is_not_attached_to_2027():
    html = "<p>Join us in San Diego for the 2026 National Conference</p><p>Access to recordings until January 31, 2027</p><p>Full Conference</p><p>$735</p><p>$370</p>"
    assert AapExtractor({"id": 0}).fees_from_pages({"https://aapexperience.org/conference-registration/": html}, 2027) == []
