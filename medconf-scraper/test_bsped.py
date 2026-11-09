import extractors.bsped as m1
from extractors.bsped import BspedExtractor

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


def test_city_from_title_line_and_no_registrar_discovery(monkeypatch):
    e = BspedExtractor({"id": 0})
    url = "https://www.bsped.org.uk/meetings/forthcoming-meetings/"
    monkeypatch.setattr(e, "_get", lambda u, tries=3: pytest.fail("no sub-page may be fetched"))
    shell = {"title": "BSPED Annual Meeting 2026", "start_date": "2026-12-08", "end_date": "2026-12-10", "edition_year": 2026}
    out = e.detail_from_html(fx("bsped_home.html"), url, shell, None)
    assert (out["city"], out["region"]) == ("Bristol", "England")
    assert out["description"] == "53rd Meeting of the British Society for Paediatric Endocrinology and Diabetes, Bristol, 8-10 December 2026."
    assert e._discover("<a href='/x'>Registration</a>", url, __import__("re").compile("regist"), None) == []
