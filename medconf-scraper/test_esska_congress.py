import datetime as _dt
from pathlib import Path

import pytest

import extractors.esska_congress as m1
from extractors.esska_congress import EsskaCongressExtractor
from extractors.single_congress import html_lines

FIX = Path(__file__).parent / "test_fixtures"
HOME, ABOUT, PROG = "https://esska-congress.org/", "https://esska-congress.org/about-esska-congress/", "https://esska-congress.org/scientific-programme/"


class _Today(_dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 20)


def fx(name):
    return (FIX / name).read_text()


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    import extractors.single_congress as sc
    for m in (sc, m1):
        monkeypatch.setattr(m, "date", _Today, raising=False)


def _extractor(monkeypatch):
    e = EsskaCongressExtractor({"id": 0})
    pages = {ABOUT: fx("esska_about.html"), PROG: fx("esska_programme.html"), HOME: fx("esska_home.html")}
    monkeypatch.setattr(e, "_get", lambda u, tries=3: pages.get(u))
    return e, pages


def test_listing_one_shell_with_dates(monkeypatch):
    e, _ = _extractor(monkeypatch)
    shells = e.list_shells_override()
    assert len(shells) == 1
    assert (shells[0]["title"], shells[0]["start_date"], shells[0]["end_date"]) == ("ESSKA Congress 2028", "2028-06-07", "2028-06-09")


def test_venue_hook_skips_menu_entry():
    assert EsskaCongressExtractor({"id": 0}).venue_from_lines(html_lines(fx("esska_about.html"))) == "Svenska Mässan Gothia Towers"


def test_detail_place_venue_description_and_no_invented_fees(monkeypatch):
    e, _ = _extractor(monkeypatch)
    shell = e.list_shells_override()[0]
    out = e.detail_from_html(fx("esska_home.html"), HOME, shell, None)
    assert (out["city"], out["region"], out["venue_name"]) == ("Gothenburg", "Sweden", "Svenska Mässan Gothia Towers")
    assert out["event_format"] == "in_person" and out["specialty"] == "Orthopaedics"
    assert out["description"].startswith("ESSKA Congress 2028. Gothenburg, 7-9 June 2028")
    assert "pricing_tiers" not in out and "abstract_deadline" not in out


def test_venue_hook_duplicated_menu_past_index_12_real_block_wins():
    menu = ["Congress", "About ESSKA Congress", "Congress Leadership", "Congress Venue", "Programme", "Scientific Programme",
            "Session Types", "Industry", "Partners", "Exhibitors", "Compliance", "About ESSKA", "Contact"]
    lines = menu + ["Some heading"] + menu + ["Svenska prose line here is long enough to be prose, really."] \
        + ["Congress Venue", "Svenska Mässan Gothia Towers", "Northern Europe\u2019s largest meeting place in the heart of Gothenburg."]
    assert lines.index("Congress Venue", 20) > 12
    assert EsskaCongressExtractor({"id": 0}).venue_from_lines(lines) == "Svenska Mässan Gothia Towers"


def test_venue_hook_menu_only_returns_none():
    menu = ["Congress", "About ESSKA Congress", "Congress Leadership", "Congress Venue", "Programme", "Scientific Programme",
            "Session Types", "Industry", "Partners"]
    assert EsskaCongressExtractor({"id": 0}).venue_from_lines(["x"] * 20 + menu + menu) is None
