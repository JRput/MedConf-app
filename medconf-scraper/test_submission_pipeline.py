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
