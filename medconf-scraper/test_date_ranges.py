"""Unit tests for per-source date-range parsing (RCGP, RSM, RCEM, RCPSG)."""
from datetime import date

from extractors.rcgp import RCGPExtractor
from extractors.rsm import RSMExtractor
from extractors.rcem import RCEMExtractor
from extractors.rcpsg import RCPSGExtractor


class FakePage:
    def __init__(self, text):
        self.text = text

    def evaluate(self, *_a, **_k):
        return self.text


def test_rcgp_event_end_field():
    ex = RCGPExtractor({"id": 1})
    text = "Event start: 29 October 2026, 09:00 (GMT)\nEvent end: 30 October 2026, 17:30 (GMT)"
    assert ex._extract_end_date_from_shell_or_page({"start_date": "2026-10-29", "title": "Annual Conference 2026"}, FakePage(text)) == "2026-10-30"
    text = "Event start: 04 January 2027, 19:00 (GMT)\nEvent end: 08 March 2027, 21:00 (GMT)"
    assert ex._extract_end_date_from_shell_or_page({"start_date": "2027-01-04", "title": "Mindfulness for Life Course - 8 weeks"}, FakePage(text)) == "2027-03-08"


def test_rcgp_fallbacks():
    ex = RCGPExtractor({"id": 1})
    # No field -> N-day title heuristic
    assert ex._extract_end_date_from_shell_or_page({"start_date": "2026-10-05", "title": "Two 3-day course"}, FakePage("nothing")) == "2026-10-07"
    # No field, no hint -> None (single day)
    assert ex._extract_end_date_from_shell_or_page({"start_date": "2026-10-05", "title": "Workshop"}, FakePage("")) is None
    # Event end before start is rejected
    text = "Event end: 01 October 2026, 17:00 (GMT)"
    assert ex._extract_end_date_from_shell_or_page({"start_date": "2026-10-05", "title": "x"}, FakePage(text)) is None


def test_rsm_ranges():
    p = RSMExtractor._parse_date_range
    assert p("Mon 30 Nov 2026 from 8:30am to 1 Dec 2026 at 4:00pm") == ("2026-11-30", "2026-12-01")
    assert p("Mon 18 May 2026 to Tue 19 May 2026") == ("2026-05-18", "2026-05-19")
    assert p("18-19 May 2026") == ("2026-05-18", "2026-05-19")
    assert p("18 – 19 May 2026") == ("2026-05-18", "2026-05-19")
    assert p("18—19 May 2026") == ("2026-05-18", "2026-05-19")
    assert p("30 Nov – 1 Dec 2026") == ("2026-11-30", "2026-12-01")
    # single-day strings are not ranges
    assert p("Tue 8 Dec 2026 from 9:00am to 4:00pm") is None
    assert p("Fri 4 Dec 2026 from 8:15am to 4:30pm") is None


def test_rsm_end_date_from_page():
    ex = RSMExtractor({"id": 3})
    page = FakePage("About this event Date and time Mon 30 Nov 2026 from 8:30am to 1 Dec 2026 at 4:00pm Location RSM")
    assert ex._extract_end_date(page, {"start_date": "2026-11-30"}) == "2026-12-01"
    page = FakePage("About this event Date and time Tue 8 Dec 2026 from 9:00am to 4:00pm Location RSM")
    assert ex._extract_end_date(page, {"start_date": "2026-12-08"}) is None


def test_rcem_ranges():
    ex = RCEMExtractor({"id": 6})
    f = lambda t: ex._extract_dates(t, "", FakePage(""), False)
    assert f("Wednesday 11 – Thursday 12 November 2026 | Hybrid event") == ("2026-11-11", "2026-11-12", None)
    assert f("Wednesday 11 - Thursday 12 November 2026") == ("2026-11-11", "2026-11-12", None)
    assert f("11 to 12 November 2026") == ("2026-11-11", "2026-11-12", None)
    assert f("4 - 5 June 2026") == ("2026-06-04", "2026-06-05", None)
    assert f("29 June - 2 July 2026") == ("2026-06-29", "2026-07-02", None)
    assert f("Friday 19 June 2026 | RCEM") == ("2026-06-19", None, None)
    assert f("Available until 24 June 2026") == ("2026-06-24", None, None)


def test_rcem_yearless_range_resolves_to_next_occurrence():
    ex = RCEMExtractor({"id": 6})
    s, e, _ = ex._extract_dates("Tuesday 17 – Wednesday 18 November | Virtual event | 10-CPD points (5 per day)", "", FakePage(""), False)
    assert s and e and s < e and s[5:] == "11-17" and e[5:] == "11-18"
    assert s >= date.today().isoformat()


def test_rcem_yearless_single_takes_first_date():
    ex = RCEMExtractor({"id": 6})
    s, e, _ = ex._extract_dates("Thursday 9 July | Online", "", FakePage(""), False)
    assert s[5:] == "07-09" and e is None


def test_rcpsg_range_line():
    p = RCPSGExtractor._parse_range_lines
    assert p("Title\n5–6 October 2026\nClinical Anatomy Skills Centre") == ("2026-10-05", "2026-10-06")
    assert p("x\n5-6 October 2026\n") == ("2026-10-05", "2026-10-06")
    assert p("x\n30 September – 1 October 2026\n") == ("2026-09-30", "2026-10-01")
    # single date / prose are ignored
    assert p("x\n7 October 2026\nThe course runs over two day") is None
    assert p("This two day course runs 5-6 October 2026 at the centre") is None
