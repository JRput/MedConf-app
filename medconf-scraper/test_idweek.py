"""Tests for IdweekExtractor.list_shells_override verified-empty reporting (no network)."""
import datetime as _dt

import pytest

import extractors.idweek as idweek_mod
from extractors.idweek import IdweekExtractor

SRC = {"id": 55, "name": "IDWeek", "url": "https://www.idweek.org/"}


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch):
    monkeypatch.setattr(idweek_mod, "_today", lambda: _dt.date(2026, 10, 30), raising=False)


def _ext(html):
    e = IdweekExtractor(SRC)
    e._fetch = lambda url: html
    return e


def test_upcoming_edition_yields_shell():
    e = _ext("<html><body><h1>IDWeek 2027</h1><p>Oct 21 – 25, 2027 | Atlanta, GA</p></body></html>")
    shells = e.list_shells_override()
    assert len(shells) == 1
    s = shells[0]
    assert s["title"] == "IDWeek 2027"
    assert (s["start_date"], s["end_date"], s["city"]) == ("2027-10-21", "2027-10-25", "Atlanta")
    assert e.verified_empty is None


def test_on_demand_homepage_is_verified_empty():
    e = _ext("<html><body><p>IDWeek 2026. Purchase on-Demand Access</p><p>Claim Your IDWeek 2026 CE Credits</p></body></html>")
    assert e.list_shells_override() == []
    assert "2026" in e.verified_empty


def test_past_edition_is_verified_empty():
    e = _ext("<html><body><p>Oct 21 – 25, 2025 | Los Angeles, CA</p></body></html>")
    assert e.list_shells_override() == []
    assert "2025" in e.verified_empty


def test_homepage_unavailable_has_no_flag():
    e = _ext(None)
    assert e.list_shells_override() == []
    assert e.verified_empty is None


def test_unexpected_page_has_no_flag():
    e = _ext("<html><body><p>Welcome to our conference</p></body></html>")
    assert e.list_shells_override() == []
    assert e.verified_empty is None


def test_stale_reason_is_reset_on_retry():
    e = _ext("<html><body><p>IDWeek 2026 on-demand</p></body></html>")
    e.list_shells_override()
    assert e.verified_empty
    e._fetch = lambda url: None
    assert e.list_shells_override() == []
    assert e.verified_empty is None


def test_over_signal_with_current_year_is_verified_empty():
    e = _ext("<html><body><p>IDWeek 2026 is over. Thank you for attending.</p></body></html>")
    assert e.list_shells_override() == []
    assert e.verified_empty and "2026" in e.verified_empty


def test_next_edition_advertised_without_date_line_is_a_parser_break():
    e = _ext("<html><body><p>IDWeek 2027 coming soon. IDWeek 2026 Purchase on-Demand Access</p></body></html>")
    assert e.list_shells_override() == []
    assert e.verified_empty is None


def test_year_mention_without_over_signal_has_no_flag():
    e = _ext("<html><body><p>Welcome to IDWeek 2026</p></body></html>")
    assert e.list_shells_override() == []
    assert e.verified_empty is None
