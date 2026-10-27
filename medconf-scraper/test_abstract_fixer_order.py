"""X4 abstract-fixer-order: the fixer must not write "no abstracts" from the
main page alone; the terminal verdict belongs to the explorer after it has
read every discovered abstract / call-for link, PDF and the organiser page."""
import pytest

from remediator import explorer
from remediator.fixers.abstract import fix_abstract_status

BASE = "https://www.soc.org/events/2027/annual-meeting"
ROW = {"id": 1, "conference_name": "Society Annual Meeting 2027", "start_date": "2027-05-10",
       "source_url": BASE, "event_type": "conference"}
NOWORDS = "Society Annual Meeting 2027 venue and programme"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    explorer.reset_fetch_state()
    monkeypatch.setattr(explorer, "render_page", lambda url: (None, None, []))
    yield
    explorer.reset_fetch_state()


def fake_pages(monkeypatch, pages):
    import re, html as _h

    def fetch(url, **kw):
        h = pages.get(url)
        if h is None:
            return None, None
        t = _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()
        return t, h
    monkeypatch.setattr(explorer, "fetch_page_text_and_html", fetch)


def _explore(row, html):
    return explorer.explore_for_abstract_status(
        row=row, page_text=NOWORDS, page_html=html, base_url=BASE, llm_call=lambda p: None)


# 1. main page without wording, explorer not run -> unknown, no write
def test_fixer_main_page_without_wording_is_unknown_not_false():
    val, method = fix_abstract_status(ROW, NOWORDS, lambda p: None)
    assert val is None
    assert method == "no_abstract_mention"


# 2. explorer says unknown_unreached -> nothing to write
def test_explorer_unreached_link_is_no_write(monkeypatch):
    main = f'<html><body><p>{NOWORDS}</p><a href="/events/2027/annual-meeting/abstracts-info">Abstracts</a></body></html>'
    fake_pages(monkeypatch, {BASE: main})
    res = _explore(ROW, main)
    assert res.value is None and not res.found
    assert res.method == "unknown_unreached"


# 3. explorer exhausted, nothing anywhere -> False with a verdict method
def test_explorer_exhausted_writes_false(monkeypatch):
    main = f"<html><body><p>{NOWORDS}</p></body></html>"
    fake_pages(monkeypatch, {BASE: main})
    res = _explore(ROW, main)
    assert res.found and res.value == {"abstract_open": False}
    assert res.method == "no_abstract_anywhere"


def test_explorer_organiser_unreached_blocks_false(monkeypatch):
    main = f"<html><body><p>{NOWORDS}</p></body></html>"
    fake_pages(monkeypatch, {BASE: main})  # organiser fetch fails
    row = {**ROW, "organiser_url": "https://congress2027.example.org/"}
    res = _explore(row, main)
    assert res.value is None and res.method == "unknown_unreached"


def test_sub_page_with_call_words_but_no_abstract_word_is_not_false(monkeypatch):
    # previously the fixer returned False for such a sub-page and the explorer accepted it
    cfp = "https://www.soc.org/events/2027/annual-meeting/cfp"
    main = (f'<html><body><p>{NOWORDS}</p>'
            '<a href="/events/2027/annual-meeting/cfp">Call for papers</a></body></html>')
    fake_pages(monkeypatch, {BASE: main, cfp: "<html><body>Call for papers: see the organisers.</body></html>"})
    res = _explore(ROW, main)
    assert res.value != {"abstract_open": False} or res.method == "no_abstract_anywhere"
    assert not (res.found and res.method.startswith("subpage"))


# 4. positive extraction unchanged
def test_main_page_deadline_unchanged():
    text = "Abstracts: deadline for submissions 1 February 2099. Call for abstracts."
    val, method = fix_abstract_status(ROW, text, lambda p: None)
    assert val and val["abstract_open"] is True and val["abstract_deadline"] == "2099-02-01"


def test_closed_wording_unchanged():
    val, method = fix_abstract_status(ROW, "Abstract submissions are closed.", lambda p: None)
    assert val["abstract_open"] is False and method == "programme_note"


# 5. not applicable rows get no verdict
@pytest.mark.parametrize("et,name,applicable", [
    ("course", "Advanced Life Support", False),
    ("course", "Annual Course with call for abstracts", True),
    ("degree", "MSc Oncology", False),
    ("workshop", "Hands-on Workshop", True),
])
def test_not_applicable_rows_get_no_verdict(et, name, applicable):
    row = {**ROW, "event_type": et, "conference_name": name}
    text = "Abstracts: deadline for submissions 1 February 2099."
    val, method = fix_abstract_status(row, text, lambda p: None)
    if applicable:
        assert val is not None
    else:
        assert val is None and method == "not_applicable"
    val2, _ = fix_abstract_status(row, NOWORDS, lambda p: None)
    assert val2 is None
