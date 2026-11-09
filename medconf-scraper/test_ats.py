import extractors.ats as m1
from extractors.ats import AtsExtractor

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


def test_closed_main_call_and_late_breaking_date():
    out = {}
    AtsExtractor({"id": 0}).apply_abstracts(out, {"u": fx("ats_abstracts.html")}, {})
    assert out["abstract_open"] is False and out["abstract_deadline"] == "2027-01-27"
    assert "Main abstract call closed" in out["abstract_deadline_note"]


def test_no_nav_discovery():
    import re
    assert AtsExtractor({"id": 0})._discover("<a href='/conference/x'>Register</a>", "https://site.thoracic.org/conference", re.compile("regist"), None) == []
