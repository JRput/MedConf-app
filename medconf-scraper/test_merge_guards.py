"""Merge-step guards found on the first wave-3 batch S scrape (2026-11-09).

A. BAD Annual Meeting: the Playwright DOM lacks the home slider, so the family extractor read the nav
   item after "Venue" ("Wellbeing") as the venue, and the shared abstract classifier took the
   late-breaking deadline (17 May) instead of the main call (11 Jan).
B. ATS 2027: discovery's venue_keyword_line took "Medical University" from a speaker affiliation.
"""
import os
from datetime import date
from types import SimpleNamespace

from extractors import abstract_classifier as ac
from extractors import discovery
from extractors.single_congress import html_lines
from llm_agent import AgentLoop as ExtractionAgent

FX = os.path.join(os.path.dirname(__file__), "test_fixtures")


def _read(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def _agent(html):
    a = ExtractionAgent.__new__(ExtractionAgent)
    a.browser = SimpleNamespace(page=SimpleNamespace(content=lambda: html))
    return a


# ---- A: venue --------------------------------------------------------------------------
def test_nav_menu_item_is_not_a_venue():
    html = _read("bad_annual_live_2026-11-09.html")
    merged = {"venue_name": "Wellbeing", "city": "Liverpool"}
    _agent(html)._drop_nav_venue(merged)
    assert merged["venue_name"] is None
    assert merged["city"] == "Liverpool"


def test_real_venue_survives_nav_guard():
    html = _read("bad_annual_live_2026-11-09.html")
    for v in ("Liverpool Experience Campus", "ACC Liverpool"):
        merged = {"venue_name": v}
        _agent(html)._drop_nav_venue(merged)
        assert merged["venue_name"] == v


# ---- A: abstract deadline --------------------------------------------------------------
def test_main_abstract_deadline_beats_late_breaking():
    text = " ".join(html_lines(_read("bad_annual_abstracts_live_2026-11-09.html")))
    is_open, deadline, _ = ac.classify_submission(text, date(2026, 11, 9), date(2027, 6, 29))
    assert (is_open, deadline) == (True, date(2027, 1, 11))


def test_single_deadline_unchanged():
    is_open, deadline, _ = ac.classify_submission(
        "Call for posters. Poster submission deadline: 5 March 2027.", date(2026, 11, 9), date(2027, 6, 1))
    assert deadline == date(2027, 3, 5)


def test_only_late_breaking_keeps_its_date():
    _, deadline, _ = ac.classify_submission(
        "Submit your abstract. Late Breaking Deadline: 17 May 2027", date(2026, 11, 9), date(2027, 6, 29))
    assert deadline == date(2027, 5, 17)


# ---- B: ATS speaker affiliation ----------------------------------------------------------
def test_speaker_affiliation_is_not_a_venue_line():
    html = _read("ats_live_2026-11-09.html")
    text = _read("ats_live_2026-11-09.txt")
    from remediator.explorer import extract_place_from_html
    pl = extract_place_from_html(html, "https://site.thoracic.org/conference", text)
    assert pl and pl["method"] == "venue_keyword_line"          # the raw heuristic still misfires ...
    assert discovery._venue_line_ok(pl, {"city": "New Orleans"}, text) is False   # ... the gate refuses it


def test_corroborated_venue_line_passes():
    pl = {"venue_name": "Hilton Garden Hotel", "city": None, "method": "venue_keyword_line"}
    text = "Join us\nHilton Garden Hotel\nNew Orleans, Louisiana\n"
    assert discovery._venue_line_ok(pl, {"city": "New Orleans"}, text) is True
    assert discovery._venue_line_ok(pl, {"city": None}, "Join us\nHilton Garden Hotel\n") is False


def test_structured_methods_unaffected():
    assert discovery._venue_line_ok({"venue_name": "ExCeL", "method": "jsonld_location"}, {}, "") is True
