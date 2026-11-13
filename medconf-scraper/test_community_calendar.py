"""Offline tests for the YourMembership community-calendar family (eans, theabn) and the WFNS empty-list rule."""
import pytest

from extractors import community_calendar as cc
from extractors import wfns
from extractors.eans import EansExtractor
from extractors.theabn import TheabnExtractor

ROW = ('<tr><td><span id="EventList1"><a href="/events/EventDetails.aspx?id=1&amp;group="><b>A Course</b></a></span><br>'
       '13/12/2099 » 14/12/2099<br><div class="small"><a href="#">Export to Your Calendar</a></div></td></tr>')


def page(inner: str) -> str:
    return f'<html><body><table id="SpContent"><tr><td><table id="EventList" class="ViewTable1">{inner}</table></td></tr></table></body></html>'


@pytest.mark.parametrize("title", [
    "Spine Day 2027, Online", "Masterclass 2027, Virtual", "Summit 2027, Hybrid", "Meeting 2027, TBC", "Meeting 2027, TBA",
    "Webinar 2027, Teams", "Webinar 2027, Zoom", "Course 2027, Webinar", "Annual Meeting 2028, Wales", "Meeting 2027, Part 2",
    "Meeting 2027, on the lake", "Meeting 2027, 12 May", "Meeting 2027", "Meeting 2027, Live",
])
def test_city_from_title_rejects(title):
    assert cc.city_from_title(title) is None


@pytest.mark.parametrize("title,city", [
    ("ABN Annual Meeting 2027, Belfast", "Belfast"),
    ("Congress 2027, New York", "New York"),
    ("Congress 2027, Zürich", "Zürich"),
])
def test_city_from_title_accepts(title, city):
    assert cc.city_from_title(title) == city


def test_empty_signal_positive_cases():
    assert cc.empty_signal(page("<tr><th colspan='2'>Upcoming Events</th></tr>"))
    assert cc.empty_signal(page("<tr><td>There are no upcoming events.</td></tr>"))


def test_empty_signal_negative_cases():
    assert not cc.empty_signal("<html><body>nothing here</body></html>")                  # container absent
    assert not cc.empty_signal(page(ROW))                                                 # rows present
    # container with links/dates the row regex would not match: a parser break, never "empty"
    assert not cc.empty_signal(page("<tr><td><a href='/x'>New markup</a> 13/12/2099</td></tr>"))


def _run(monkeypatch, cls, html):
    monkeypatch.setattr(cc, "fetch_html", lambda *a, **k: html)
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)
    e = cls({"id": 0, "source_name": "t"})
    e.browser = None
    e.extra_shells = lambda: []
    return e, e.list_shells_override()


def test_container_present_no_rows_is_not_verified_empty(monkeypatch):
    e, shells = _run(monkeypatch, TheabnExtractor, page("<tr><td><a href='/x'>New markup</a> 13/12/2099</td></tr>"))
    assert shells == [] and not e.verified_empty


def test_positive_empty_is_verified_empty(monkeypatch):
    e, shells = _run(monkeypatch, EansExtractor, page("<tr><th colspan='2'>Upcoming Events</th></tr>"))
    assert shells == [] and e.verified_empty


def test_rows_parse_and_no_verified_empty(monkeypatch):
    e, shells = _run(monkeypatch, TheabnExtractor, page(ROW))
    assert len(shells) == 1 and shells[0]["start_date"] == "2099-12-13" and not e.verified_empty


def test_wfns_empty_signal():
    assert wfns.empty_signal('<div id="tab1"><p>&nbsp;</p></div><div id="tab2"><a href="/events/1/x/2/y">old</a> 2020</div>')
    assert not wfns.empty_signal('<div id="tab1"><table><tr><td>3 Nov 2027 <b>row markup changed</b></td></tr></table></div><div id="tab2"></div>')
    assert not wfns.empty_signal("<html>no tab container</html>")


class _Page:
    def __init__(self, html):
        self._h = html

    def content(self):
        return self._h


def _wfns_detail(href):
    html = ("<span id='x_lblTitle'>Test Course</span><div id=\"PanelEvent\"><span>(01/02/2099 - 02/02/2099) / Hall, Rome, Italy</span>"
            f"<img src='/images/web.png'> <a href='{href}'>site</a><p>{'A real paragraph of description text. ' * 3}</p></div>"
            "<div class=\"col-sm-12 col-md-3 box\"></div>")
    e = wfns.WfnsExtractor({"id": 0, "source_name": "t"})
    return e.extract_detail(_Page(html), {"title": "Test Course", "booking_url": "https://wfns.org/events/1/x/2/y"}, lambda p: None)


@pytest.mark.parametrize("bad", ["javascript:void(0)", "mailto:a@b.org", "ftp://x.org/a", "https://", "https://teams.live.com/meet/1"])
def test_wfns_organiser_url_rejects(bad):
    assert "organiser_url" not in _wfns_detail(bad)


def test_wfns_organiser_url_accepts_http():
    assert _wfns_detail("https://example.org/reg")["organiser_url"] == "https://example.org/reg"
