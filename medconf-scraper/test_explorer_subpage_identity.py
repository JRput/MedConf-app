"""T4: same-site explorer sub-pages must pass discovery.page_identity (STRONG)."""
import re
import html as _h
import pytest

from remediator import explorer
from remediator.explorer import (
    AuditTrail, ExploreBudget, _follow_registration_subpages, _subpage_identity,
    explore_for_pricing,
)

HOST = "https://www.rcpsych.ac.uk"
CONGRESS = HOST + "/events/congress/international-congress-2026/registration"
ROW_1752 = {
    "id": 1752, "conference_name": "Faculty of Medical Psychotherapy Annual Conference 2027",
    "start_date": "2027-04-14",
    "source_url": HOST + "/events/conferences/detail/2027/04/14/default-calendar/"
                         "faculty-of-medical-psychotherapy-annual-conference-2027",
}
ROW_1423 = {
    "id": 1423, "conference_name": "Rehabilitation 10th Annual Forum 2026",
    "start_date": "2026-12-02",
    "source_url": HOST + "/events/conferences/detail/2026/12/02/default-calendar/"
                         "rehabilitation-10th-annual-forum-2026",
}
TABLE = ("<table><tr><th>Ticket</th><th>Fee</th></tr>"
         "<tr><td>Whole conference member</td><td>£795</td></tr>"
         "<tr><td>Whole conference non-member</td><td>£995</td></tr>"
         "<tr><td>One day member</td><td>£450</td></tr></table>")


def page(h1, extra=""):
    return f"<html><head><title>{h1}</title></head><body><h1>{h1}</h1>{extra}{TABLE}</body></html>"


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    explorer.reset_fetch_state()
    monkeypatch.setattr(explorer, "render_page", lambda url: (None, None, []))
    yield
    explorer.reset_fetch_state()


def fake(monkeypatch, pages):
    def fetch(url, **kw):
        h = pages.get(url)
        if h is None:
            return None, None
        t = _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()
        return t, h
    monkeypatch.setattr(explorer, "fetch_page_text_and_html", fetch)


def walk(row, pages, monkeypatch, nav_href=CONGRESS, shell_titles=None):
    fake(monkeypatch, pages)
    if shell_titles is not None:
        row = {**row, "_shell_titles": shell_titles}
    base = row["source_url"]
    main = (f'<html><body><h1>{row["conference_name"]}</h1>'
            f'<nav><a href="{nav_href}">Registration</a></nav></body></html>')
    pages = dict(pages)
    pages[base] = main
    fake(monkeypatch, pages)
    return explore_for_pricing(row=row, page_text="x", page_html=main, base_url=base,
                               llm_call=lambda p: "no")


def test_congress_page_rejected_for_1752(monkeypatch):
    res = walk(ROW_1752, {CONGRESS: page("International Congress 2026 — Registration")}, monkeypatch)
    assert not any(m.startswith("subpage_table:") for m in [res.method or ""])
    assert not res.found or "international-congress" not in (res.method or "")
    assert any(n.startswith(f"subpage_rejected: {CONGRESS} (other_year_path") for n in res.audit_trail.notes)


def test_congress_page_rejected_for_1423(monkeypatch):
    res = walk(ROW_1423, {CONGRESS: page("International Congress 2026 — Registration")}, monkeypatch,
               shell_titles=["International Congress 2026", ROW_1423["conference_name"]])
    assert not res.found
    assert any(n.startswith(f"subpage_rejected: {CONGRESS} (") for n in res.audit_trail.notes)
    v, why = _subpage_identity({**ROW_1423}, CONGRESS, page("International Congress 2026 — Registration"),
                               "International Congress 2026 Registration", ["International Congress 2026"])
    assert v == "REJECTED"


def test_own_path_page_is_strong_and_prices(monkeypatch):
    own = ROW_1752["source_url"] + "/registration"
    res = walk(ROW_1752, {own: page("Registration", "<p>Faculty of Medical Psychotherapy Annual Conference 2027</p>")}, monkeypatch, nav_href=own)
    assert res.found and res.method.startswith(("subpage_table:", "subpage_text:"))
    assert res.method.endswith("/registration")


def test_h1_equals_title_on_other_path_is_strong(monkeypatch):
    other = HOST + "/events/book-faculty-of-medical-psychotherapy"
    res = walk(ROW_1752, {other: page(ROW_1752["conference_name"])}, monkeypatch, nav_href=other)
    assert res.found and res.method.startswith(("subpage_table:", "subpage_text:"))


def test_external_host_unaffected(monkeypatch):
    ext = "https://events.example.org/reg"
    base = "https://events.example.org/"
    html = f'<a href="{ext}">Register</a>'
    fake(monkeypatch, {ext: page("Some Other Heading 2019")})
    trail = AuditTrail()
    row = {**ROW_1752}
    got = _follow_registration_subpages(html, base, ExploreBudget(), trail, row=row)
    assert got is not None and got[1] == ext
    assert not any(n.startswith("subpage_rejected") for n in trail.notes)


def test_identity_error_fails_closed(monkeypatch):
    import extractors.discovery as d
    monkeypatch.setattr(d, "page_identity", lambda *a, **k: 1 / 0)
    assert _subpage_identity(ROW_1752, CONGRESS, "", "") == ("REJECTED", "identity_error")
