"""Mission P6: pipeline-level submission detection + call-for-papers follow."""
from datetime import date
from types import SimpleNamespace

from extractors import abstract_classifier as ac
from llm_agent import AgentLoop

TODAY = date(2026, 10, 4)
BASE = "https://advance-he.ac.uk/programmes-events/teaching-learning-conference/"
HTML = (
    '<a href="/wp-content/uploads/2026/09/Call-for-papers-TLC-2027.pdf">Download the call for papers</a>'
    '<a href="https://advancehe.smapply.org/prog/tlc_2027/">Submit your proposal</a>'
    '<a href="/contact">Contact us</a>'
)
PAGE_TEXT = "Call for Papers. We welcome submissions. Download the call for papers."
PDF_TEXT = "Call for papers. The deadline for submissions is 4 December 2026."


def test_picks_pdf_over_portal_and_parses_deadline():
    calls = []

    def fetcher(url):
        calls.append(url)
        return "pdf", b"%PDF fake"

    orig = ac.pdf_bytes_to_text
    ac.pdf_bytes_to_text = lambda b, max_pages=20: PDF_TEXT
    try:
        hit = ac.follow_call_for_papers(HTML, BASE, fetcher, TODAY, date(2027, 4, 1))
    finally:
        ac.pdf_bytes_to_text = orig
    assert calls == ["https://advance-he.ac.uk/wp-content/uploads/2026/09/Call-for-papers-TLC-2027.pdf"]
    assert hit == (True, date(2026, 12, 4),
                   "Deadline from call for papers (Call-for-papers-TLC-2027.pdf)")


def test_portal_html_path():
    html = '<a href="https://advancehe.smapply.org/prog/x/">Submit your proposal</a>'
    seen = []

    def fetcher(url):
        seen.append(url)
        return "html", "<html><body><p>Submission deadline: 15 January 2027</p></body></html>"

    hit = ac.follow_call_for_papers(html, BASE, fetcher, TODAY, date(2027, 4, 1))
    assert seen == ["https://advancehe.smapply.org/prog/x/"]
    assert hit[1] == date(2027, 1, 15) and "advancehe.smapply.org" in hit[2]


def test_no_link_leaves_nothing():
    called = []
    assert ac.follow_call_for_papers('<a href="/contact">Contact</a>', BASE,
                                     lambda u: called.append(u), TODAY) is None
    assert not called


def test_fetch_failure_never_raises():
    def boom(url):
        raise RuntimeError("net down")
    assert ac.follow_call_for_papers(HTML, BASE, boom, TODAY) is None


def test_classify_page_submission_follows_when_page_has_no_date():
    ac_pdf = ac.pdf_bytes_to_text
    ac.pdf_bytes_to_text = lambda b, max_pages=20: PDF_TEXT
    try:
        out = ac.classify_page_submission(PAGE_TEXT, HTML, BASE, TODAY, date(2027, 4, 1),
                                          fetcher=lambda u: ("pdf", b"x"))
    finally:
        ac.pdf_bytes_to_text = ac_pdf
    assert out[:2] == (True, date(2026, 12, 4)) and out[3] == "call for papers"


def test_classify_page_submission_note_when_nothing_found():
    out = ac.classify_page_submission(PAGE_TEXT, "", BASE, TODAY)
    assert out[0] is False and out[1] is None and "Call for papers" in out[2]


def _agent(text, html=""):
    a = AgentLoop.__new__(AgentLoop)
    a.browser = SimpleNamespace(get_page_text=lambda: text,
                                page=SimpleNamespace(content=lambda: html))
    return a


def test_merge_step_fills_when_extractor_did_not():
    rec = {"start_date": "2026-11-11", "abstract_open": False,
           "abstract_deadline": None, "abstract_deadline_note": None}
    _agent("Poster competition. The deadline for submissions is 7th November 2026.") \
        ._ensure_submission_info(rec, BASE)
    assert rec["abstract_open"] is True and rec["abstract_deadline"] == "2026-11-07"


def test_extractor_values_win():
    rec = {"start_date": "2026-11-11", "abstract_open": False,
           "abstract_deadline": "2026-09-01", "abstract_deadline_note": None}
    _agent("Poster competition. The deadline for submissions is 7th November 2026.") \
        ._ensure_submission_info(rec, BASE)
    assert rec["abstract_deadline"] == "2026-09-01" and rec["abstract_open"] is False
    rec2 = {"start_date": "2026-11-11", "abstract_open": True,
            "abstract_deadline": None, "abstract_deadline_note": None}
    _agent("Call for papers. Deadline for submissions is 7th November 2026.") \
        ._ensure_submission_info(rec2, BASE)
    assert rec2["abstract_deadline"] is None


def test_colon_form_deadline_with_midnight():
    # Advance HE call-for-papers PDF wording
    out = ac.classify_submission(
        "Call for papers and guide to submissions\nDeadline for submissions: midnight 24 November 2026\n",
        TODAY, date(2027, 7, 6))
    assert out == (True, date(2026, 11, 24), None)


# ---------------------------------------------------------------------------
# Mission P8 (2026-10-05)
# ---------------------------------------------------------------------------
RCEM_NAV = ("On-Demand Events Further Information Information for Speakers Abstract Submission "
            "Event Booking Terms and Conditions Event FAQs Marketing and Sponsorship Opportunities "
            "CPD Continuing Professional Development RCEMLearning CPD Diary Journal Club")


def test_p8_nav_menu_abstract_submission_is_not_a_programme():
    assert not ac.has_submission_programme(RCEM_NAV)
    assert ac.classify_page_submission(RCEM_NAV, "", BASE, TODAY) is None


def test_p8_real_abstract_submission_wording_still_counts():
    assert ac.has_submission_programme("Abstract Submission Abstract submissions are open until the deadline.")
    assert ac.has_submission_programme("Abstract submission deadline 5 May 2027")


def test_p8_late_page_text_is_not_truncated():
    text = ("x " * 70_000) + "Call for Posters will close 7 October 2026. submit an abstract"
    out = ac.classify_page_submission(text, "", BASE, TODAY, date(2027, 4, 20))
    assert out[:2] == (True, date(2026, 10, 7))


def test_p8_follows_submission_form_link_when_page_has_no_date():
    html = ('<a href="/poster-competition/">Poster competition webpage</a>'
            '<a href="/contact">Contact</a>')
    seen = []

    def fetcher(url):
        seen.append(url)
        return "html", "<p>Poster competition. Deadline for entries: 25 October 2026</p>"

    text = "Please submit your abstract through the Poster competition webpage."
    out = ac.classify_page_submission(text, html, BASE, TODAY, date(2026, 12, 4), fetcher)
    assert out[:2] == (True, date(2026, 10, 25)) and out[3] == "call for papers"
    assert seen == ["https://advance-he.ac.uk/poster-competition/"]


def test_p8_closed_programme_does_not_follow_a_link():
    def boom(url):
        raise AssertionError("must not fetch when the call is already closed")
    out = ac.classify_page_submission("Call for posters is now closed.",
                                      '<a href="/abstracts">Abstracts</a>', BASE, TODAY, None, boom)
    assert out[:3] == (False, None, "Call for posters — closed")


def test_p8_fixer_uses_programme_patterns_not_no_abstract_mention():
    from remediator.fixers.abstract import fix_abstract_status
    row = {"start_date": "2026-11-27", "source_url": ""}
    val, method = fix_abstract_status(row, "Call for posters The call for posters is now closed.", lambda p: None)
    assert method == "programme_note"
    assert val == {"abstract_open": False, "abstract_deadline_note": "Call for posters — closed"}
    val, method = fix_abstract_status(
        row, "Call for posters. Enter your submission by 1pm Friday 2 December 2026.", lambda p: None)
    assert method == "programme_deadline" and val["abstract_deadline"] == "2026-12-02"
    assert val["abstract_deadline_note"] is None


def test_p8_detector_flags_workshops_for_abstract_status():
    from remediator.detector import detect_gaps
    row = {"event_type": "workshop", "abstract_open": False, "specialty": "x",
           "event_format": "online", "cpd_points": 1, "cpd_accredited": True}
    assert "abstract_status" in detect_gaps(row, True)
    row["is_on_demand"] = True
    assert "abstract_status" not in detect_gaps(row, True)


def test_p8_detector_reexamines_placeholder_notes_only():
    from remediator.detector import detect_gaps
    base = {"event_type": "conference", "abstract_open": False, "specialty": "x",
            "event_format": "online", "cpd_points": 1, "cpd_accredited": True}
    assert "abstract_status" in detect_gaps(
        {**base, "abstract_deadline_note": "Poster submissions — see page for submission date"}, True)
    assert "abstract_status" not in detect_gaps(
        {**base, "abstract_deadline_note": "Call for posters — closed"}, True)
    assert "abstract_status" not in detect_gaps(
        {**base, "abstract_deadline_note": "Poster submissions — see page for submission date",
         "abstract_deadline": "2026-12-01"}, True)
