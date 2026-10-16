"""ESTRO (19): the Power Pages portal renders /Congresses client-side, so the
listing + detail come from the events API record (2026-10-16)."""
from extractors import estro

FMT = "@OData.Community.Display.V1.FormattedValue"
RECORD = {
    "msevtmgt_name": "ESTRO 2027",
    "msevtmgt_readableeventid": "ESTRO_20273718169791",
    "msevtmgt_eventstartdate": "2027-05-21T06:00:00Z",
    "msevtmgt_eventenddate": "2027-05-25T11:00:00Z",
    "_est_cityid_value" + FMT: "Milan",
    "_est_countryid_value" + FMT: "Italy",
    "est_eventoverview": "<p>It is my great pleasure to invite you to ESTRO 2027 taking place from "
                         "21 to 25 May in Milan, Italy - one of Europe's most creative cities, and home "
                         "to many of the world&rsquo;s leading oncology centres.</p><p>Congress Co-Chairs</p>",
    "est_eventformatandparticipation": "<p>Important deadlines&nbsp;</p><p>Abstract submission : 11 November 2026</p>"
                                       "<p>Late-breaking abstract submission: 17-31 March 2027</p>",
    "est_eventvenueandaccomodation": "<p>Allianz MiCo</p><p>Gate 2 Viale Eginardo 20149 Milano Italy</p>",
    "est_eventregistrationandfees": "<p>The Registration will be opened soon.</p>",
    "est_eventpracticalinformation": None,
}


def _detail(shell):
    ex = estro.ESTROExtractor.__new__(estro.ESTROExtractor)
    return ex.extract_detail(None, shell, lambda p: None)


def test_shell_from_api_record():
    (s,) = estro._shells_from_api([RECORD])
    assert s["title"] == "ESTRO 2027"
    assert s["booking_url"] == s["source_url"] == "https://www.estro.org/Congresses/ESTRO_20273718169791"
    assert s["date_raw"] == "21 May 2027 - 25 May 2027"
    assert s["location_raw"] == "Milan, Italy"
    assert "Venue Allianz MiCo" in s["api_text"]


def test_detail_from_api_text_without_fetching(monkeypatch):
    monkeypatch.setattr(estro, "_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))
    (s,) = estro._shells_from_api([RECORD])
    out = _detail(s)
    assert out["start_date"] == "2027-05-21" and out["end_date"] == "2027-05-25"
    assert out["city"] == "Milan" and out["region"] == "Italy"
    assert out["venue_name"] == "Allianz MiCo"
    assert out["abstract_deadline"] == "2026-11-11"
    assert out["description"].startswith("It is my great pleasure to invite you to ESTRO 2027")
    assert "Congress Co-Chairs" not in out["description"]


def test_records_without_id_or_start_are_skipped():
    assert estro._shells_from_api([{"msevtmgt_name": "ESTRO 2028"}]) == []


def test_late_breaking_deadline_is_not_the_regular_one():
    txt = "Important deadlines Late-breaking abstract submission: 17 March 2027 Abstract submission : 11 November 2026"
    assert estro._extract_abstract_deadline_raw(txt) == "11 November 2026"
