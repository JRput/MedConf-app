"""BOPA (source 13): an events API that answers 200 with no events is a verified-empty
listing, never a hand-off to the generic page walker (2026-11-19: the walker made 60
'Events Search and Views Navigation' rows from /events/list/page/N/)."""
import httpx

from extractors import bopa


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)

    def __init_subclass__(cls, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self._responses.pop(0)


def _patch(monkeypatch, responses):
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: _Client(responses))


def _extractor():
    return bopa.BOPAExtractor({"id": 13, "source_name": "BOPA"})


def test_api_with_events_returns_shells(monkeypatch):
    ev = {"title": "BOPA AI Hackathon", "url": "https://www.bopa.org.uk/event/hack/",
          "start_date": "2027-03-01 09:00:00", "end_date": "2027-03-01 17:00:00",
          "categories": [], "venue": {}, "cost": "-", "description": ""}
    _patch(monkeypatch, [_Resp(200, {"events": [ev], "total": 1}), _Resp(200, {"events": []})])
    x = _extractor()
    shells = x.list_shells_override()
    assert [s["title"] for s in shells] == ["BOPA AI Hackathon"]
    assert x.verified_empty is None


def test_api_answering_zero_events_is_verified_empty_not_fallback(monkeypatch):
    _patch(monkeypatch, [_Resp(200, {"events": [], "total": 0, "total_pages": 0})])
    x = _extractor()
    assert x.list_shells_override() == []          # [] = use it, no DOM walker
    assert x.verified_empty


def test_api_failure_still_falls_back(monkeypatch):
    _patch(monkeypatch, [_Resp(503, {})])
    x = _extractor()
    assert x.list_shells_override() is None         # None = generic walker as before
    assert x.verified_empty is None


def test_ended_events_skipped_but_ongoing_kept(monkeypatch):
    from datetime import date, timedelta
    t = date.today()
    over = {"title": "Old webinar", "url": "https://www.bopa.org.uk/event/old/",
            "start_date": f"{t - timedelta(days=9)} 13:00:00",
            "end_date": f"{t - timedelta(days=9)} 14:00:00", "categories": [], "venue": {}}
    ongoing = {"title": "BOPA AI Hackathon", "url": "https://www.bopa.org.uk/event/hack/",
               "start_date": f"{t - timedelta(days=2)} 12:00:00",
               "end_date": f"{t + timedelta(days=5)} 14:30:00", "categories": [], "venue": {}}
    _patch(monkeypatch, [_Resp(200, {"events": [over, ongoing]}), _Resp(200, {"events": []})])
    x = _extractor()
    assert [s["title"] for s in x.list_shells_override()] == ["BOPA AI Hackathon"]
    assert x.verified_empty is None


def test_only_ended_events_is_verified_empty(monkeypatch):
    from datetime import date, timedelta
    d = f"{date.today() - timedelta(days=3)} 10:00:00"
    over = {"title": "Old", "url": "https://www.bopa.org.uk/event/old/", "start_date": d,
            "end_date": d, "categories": [], "venue": {}}
    _patch(monkeypatch, [_Resp(200, {"events": [over]}), _Resp(200, {"events": []})])
    x = _extractor()
    assert x.list_shells_override() == []
    assert x.verified_empty


HERO_HTML = """<html><body><nav>Latest Conference 2027</nav>
<div class="hero">\n\t\t\t\t\t1-3 October 2027  - Harrogate Convention Centre\t\t\t\t</div>
<h1>2027 BOPA Conference</h1>
<p>The 30th BOPA Annual Conference in 2027 will be held at the Harrogate Convention Centre on 1-3 October 2027.</p>
<p>More info will follow.</p><p>SAVE THE DATE</p>
<a href="https://www.bopa.org.uk/abstract-submission-the-29th-annual-bopa-conference-in-2026/">Submit your abstract for BOPA 2026</a>
</body></html>"""


def test_conference_page_shell_from_hero_line():
    sh = bopa.conference_page_shell(HERO_HTML, "https://www.bopa.org.uk/latest-conference-2027/", 2027)
    assert sh["title"] == "30th BOPA Annual Conference 2027"
    assert (sh["start_date"], sh["end_date"]) == ("2027-10-01", "2027-10-03")
    assert sh["venue_name"] == "Harrogate Convention Centre" and sh["city"] == "Harrogate"
    assert sh["flagship_page"] and sh["save_the_date"]
    assert bopa.conference_page_shell(HERO_HTML, "u", 2028) is None      # wrong year
    assert bopa.conference_page_shell("<html>no hero</html>", "u", 2027) is None


def test_conference_page_detail_is_flagship_in_person_no_abstract_call():
    sh = bopa.conference_page_shell(HERO_HTML, "https://www.bopa.org.uk/latest-conference-2027/", 2027)
    out = _extractor().extract_detail(None, sh, lambda p: None)
    assert out["event_format"] == "in_person" and out["venue_name"] == "Harrogate Convention Centre"
    assert out["city"] == "Harrogate" and out["is_flagship"] is True
    assert out["abstract_open"] is False and out["abstract_deadline_note"] == "Abstract submission not yet announced"
    assert out["event_type"] == "conference"


def test_listing_adds_conference_page_after_api(monkeypatch):
    from datetime import date
    y = date.today().year + 1
    html = HERO_HTML.replace("2027", str(y))

    class _Page(_Resp):
        text = html
        url = f"https://www.bopa.org.uk/latest-conference-{y}/"
    # API: zero events; conference page for this year: 404; next year: the hero page
    _patch(monkeypatch, [_Resp(200, {"events": []}), _Resp(404, {}), _Page(200, {})])
    x = _extractor()
    shells = x.list_shells_override()
    assert [s["title"] for s in shells] == [f"30th BOPA Annual Conference {y}"]
    assert x.verified_empty is None


def test_past_year_page_does_not_stop_the_search(monkeypatch):
    from datetime import date
    y = date.today().year
    past = HERO_HTML.replace("1-3 October 2027", f"2-3 January {y}").replace("2027", str(y))
    nxt = HERO_HTML.replace("2027", str(y + 1))

    class _P(_Resp):
        def __init__(self, text, url):
            super().__init__(200, {})
            self.text, self.url = text, url
    _patch(monkeypatch, [_Resp(200, {"events": []}),
                         _P(past, f"https://www.bopa.org.uk/latest-conference-{y}/"),
                         _P(nxt, f"https://www.bopa.org.uk/latest-conference-{y + 1}/")])
    shells = _extractor().list_shells_override()
    assert [s["title"] for s in shells] == [f"30th BOPA Annual Conference {y + 1}"]


def test_virtual_venue_is_online():
    out = _extractor().extract_detail(None, {"title": "BOPA AI Hackathon 2026", "venue_name": "Virtual &#8211; Online",
                                             "categories": []}, lambda p: None)
    assert out["event_format"] == "online" and "venue_name" not in out
