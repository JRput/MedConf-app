"""BOFAS: when the home page edition is over, the next one comes from the future-dates table (saved page, no network)."""
from datetime import date
from pathlib import Path

from extractors.bofas import BofasExtractor, _FUTURE_URL

FUT = (Path(__file__).parent / "fixtures" / "bofas_future_congress_dates_2026-11-07.html").read_text()


def _ex():
    return BofasExtractor({"id": 109, "source_name": "BOFAS"})


def test_next_edition_from_future_table():
    n = _ex()._next_from_future_table(FUT, date(2026, 11, 7))
    assert (n["year"], n["start"], n["end"], n["venue"]) == (2027, date(2027, 11, 3), date(2027, 11, 5), "Harrogate Convention Centre")


def test_skips_finished_rows():
    assert _ex()._next_from_future_table(FUT, date(2027, 11, 6))["year"] == 2028


def test_listing_falls_back_to_future_table(monkeypatch):
    ex = _ex()
    home = "<html><body><p>BOFAS 2026 will be held in Wales from 4th to 6th of November</p>" + "x" * 600 + "</body></html>"
    monkeypatch.setattr(ex, "_get", lambda url, tries=3: FUT if url == _FUTURE_URL else home)
    monkeypatch.setattr("extractors.bofas.date", type("D", (date,), {"today": staticmethod(lambda: date(2026, 11, 7))}))
    monkeypatch.setattr("extractors.single_congress.date", type("D", (date,), {"today": staticmethod(lambda: date(2026, 11, 7))}))
    shells = ex.list_shells_override()
    assert [(s["title"], s["start_date"], s["end_date"], s["venue_raw"]) for s in shells] == [
        ("BOFAS 2027", "2027-11-03", "2027-11-05", "Harrogate Convention Centre, Harrogate, England")]
