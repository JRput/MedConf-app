"""Audit: last edition's rate grid on /register must not read as a pricing miss (EADV/BDIAP/CRF, 2026-10-13)."""
from datetime import date

from remediator import audit
from remediator.audit import stale_edition_fees

TODAY = date(2026, 10, 13)

FELLOWS_2026_GRID = """Registration Rates for CRF Fellows Course 2026
Early-Bird Through March 17, 2026 1:59 PM ET
Standard March 17, 2026 2:00 PM EST to April 15, 2026 1:59 PM ET
Late Starting April 15, 2026 2:00 PM ET
Physician $599 $799 $999 $299
Allied Health Professional $299 $399 $499 $199
Industry Professional $1,399 $1,499 $1,599 $699
All figures are in U.S. dollars."""

TCT_2026_GRID = """Registration Rates for TCT 2026
Early Rate Through June 3, 2026
Standard Rate June 4 - September 2, 2026
Physician $1,295 $1,495 $1,695
Nurse $595 $695 $795
All figures are in U.S. dollars."""


def test_previous_edition_grid_is_stale_for_next_years_event():
    why = stale_edition_fees(FELLOWS_2026_GRID, "2027-05-13", today=TODAY)
    assert why and "2026 < event year 2027" in why and "2026-04-15" in why


def test_same_year_grid_is_not_stale():
    assert stale_edition_fees(TCT_2026_GRID, "2026-10-24", today=TODAY) is None


def test_future_deadlines_in_prior_year_are_not_stale():
    text = "Registration Rates for Summit 2027\nEarly Rate Through December 1, 2026\nPhysician $500 $700 $900 $100 $50"
    assert stale_edition_fees(text, "2027-01-20", today=TODAY) is None


def test_heading_year_alone_is_enough_when_no_deadlines():
    text = "Registration Rates for TCT Plus LATAM Valves 2026\nMember Physician R$ 750,00 R$ 950,00 R$ 1.400,00"
    assert stale_edition_fees(text, "2027-03-17", today=TODAY)


def test_no_years_means_unknown_not_stale():
    assert stale_edition_fees("Physician $599 $799 $999 $299 $175", "2027-05-13", today=TODAY) is None


def test_check_pricing_turns_stale_hydration_into_genuinely_absent(monkeypatch):
    monkeypatch.setattr(audit, "_hydrated_registration_probe",
                        lambda url, cache=None, start_date=None: {"url": url + "register/", "count": 16, "evidence": "$599, $799",
                                                                   "stale": stale_edition_fees(FELLOWS_2026_GRID, start_date, today=TODAY)})
    v = audit.check_pricing({"source_url": "https://www.fellowscourse.com/", "start_date": "2027-05-13"},
                            "CRF Fellows Course 2027. Save the date.", "<html></html>", {}, [])
    assert v.status == "GENUINELY_ABSENT" and "Previous-edition" in v.reason


def test_check_pricing_keeps_missing_for_current_edition(monkeypatch):
    monkeypatch.setattr(audit, "_hydrated_registration_probe",
                        lambda url, cache=None, start_date=None: {"url": url + "register/", "count": 16, "evidence": "$1,295", "stale": None})
    v = audit.check_pricing({"source_url": "https://www.tct2026.com/", "start_date": "2026-10-24"},
                            "TCT 2026.", "<html></html>", {}, [])
    assert v.status == "MISSING"
