"""Ticket H-scraper: degree programmes get event_type='degree' via ONE shared
rule that must stay identical to public.is_degree_title in the SQL migration."""
import re
from pathlib import Path

import pytest

from extractors import degree_rule
from extractors.abstract_classifier import find_call_for_papers_link
import llm_agent
import validator
from remediator.detector import abstract_applicable
from remediator.audit import check_abstract_status, check_event_type

SQL = Path(__file__).resolve().parent.parent / "supabase/migrations/20261027000000_event_type_degree.sql"

POSITIVES = [
    "Postgraduate Diploma in International Expedition and Wilderness Medicine",
    "RCPSG Postgraduate Diploma in Travel Medicine",
    "Diploma in Orthodontic Therapy (DipOT) course",
    "Level 7 Diploma in Injectables",
    "Royal College Advanced Certificate in Clinical Education",
    "MSc in Surgical Sciences", "PgCert Medical Education", "Master's of Public Health",
]
NEGATIVES = [
    "MRCP(UK) Diploma Ceremony",
    "Preparation Course for the Diploma in Special Care Dentistry - Online",
    "PhD Student Symposium",
    "BSCCP Online OSCE Preparation Course",
    "MSc Webinar: Choosing a masters",
    "\u201cFrom Trauma to Transformation: Insights on Ending the Epidemic\u201d A Conversation with Selwyn O. Rogers Jr., MD, MPH, FACS",
    "ESMO Congress 2027", "ATLS Provider Course",
]


def _sql_regexes():
    txt = SQL.read_text()
    body = txt.split("SELECT COALESCE(p_title, '') ~* '", 1)[1]
    inc, rest = body.split("'\n     AND COALESCE(p_title, '') !~* '", 1)
    exc = rest.split("'\n$f$", 1)[0]
    conv = lambda s: s.replace("\\y", r"\b").replace("''", "'")
    return conv(inc), conv(exc)


def test_python_rule_equals_sql_rule():
    inc, exc = _sql_regexes()
    assert degree_rule.INCLUDE_PATTERN == inc
    assert degree_rule.EXCLUDE_PATTERN == exc


@pytest.mark.parametrize("t", POSITIVES)
def test_positive(t):
    assert degree_rule.is_degree_title(t) is True
    assert llm_agent._event_type_from_title(t) == "degree"


@pytest.mark.parametrize("t", NEGATIVES)
def test_negative(t):
    assert degree_rule.is_degree_title(t) is False
    assert llm_agent._event_type_from_title(t) != "degree"


def test_none_title():
    assert degree_rule.is_degree_title(None) is False


def test_validator_allows_degree_and_defaults_invalid():
    base = {"conference_name": "X", "source_url": "https://a.org/x", "start_date": "2027-05-01"}
    cleaned = validator.validate_conference({**base, "event_type": "degree"})["data"]
    assert cleaned["event_type"] == "degree"
    cleaned = validator.validate_conference({**base, "event_type": "bogus"})["data"]
    assert cleaned["event_type"] == "conference"


def test_abstracts_not_applicable_for_degree():
    row = {"event_type": "degree", "conference_name": "MSc with abstract call"}
    assert abstract_applicable(row) is False
    v = check_abstract_status(row, "", "", None)
    assert v.status == "NOT_APPLICABLE"


def test_audit_accepts_degree_event_type():
    assert check_event_type({"event_type": "degree"}, "", "", None).status == "OK"


def test_esmo_defers_to_degree_rule():
    from extractors import esmo
    assert esmo._title_event_type("MSc in Medical Oncology") == "degree"
    assert esmo._title_event_type("ESMO Congress 2027") == "conference"


def test_merge_forces_degree_over_extractor_type():
    from llm_agent import AgentLoop as LLMAgent
    shell = {"title": "RCPSG Postgraduate Diploma in Travel Medicine", "booking_url": "https://x.org/a",
             "start_date": "2027-01-01"}
    agent = LLMAgent.__new__(LLMAgent)
    out = agent._merge_shell_and_detail(shell, {"event_type": "conference"})
    assert out["event_type"] == "degree"


# ---- call-for-papers pick ------------------------------------------------
BASE = "https://www.soc.org/events/2027/annual-meeting"


def test_cfp_beats_booking_form_pdf():
    html = ('<a href="/submit-an-event">Submit an event</a>'
            '<a href="/forms/reg-form.pdf">Booking form</a>'
            '<a href="/am27/call-for-abstracts">Call for abstracts</a>')
    assert find_call_for_papers_link(html, BASE) == "https://www.soc.org/am27/call-for-abstracts"


def test_cfp_pdf_still_preferred_among_strong():
    html = ('<a href="/am27/call-for-abstracts">Call for abstracts</a>'
            '<a href="/am27/abstract-guidelines.pdf">Abstract guidelines</a>')
    assert find_call_for_papers_link(html, BASE).endswith("abstract-guidelines.pdf")


def test_cfp_nav_abstracts_link():
    html = '<nav><a href="/am27/abstracts">Abstracts</a><a href="/am27/venue">Venue</a></nav>'
    assert find_call_for_papers_link(html, BASE) == "https://www.soc.org/am27/abstracts"


def test_cfp_generic_only_still_found():
    html = '<a href="/forms/reg-form.pdf">Booking form</a>'
    assert find_call_for_papers_link(html, BASE) == "https://www.soc.org/forms/reg-form.pdf"
