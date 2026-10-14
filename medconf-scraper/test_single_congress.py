"""Tests for extractors.single_congress (Wave 2c batch 4b): pure parsing on saved snippets, no network."""
from datetime import date

from extractors.single_congress import (
    SingleCongressExtractor, fee_matrix, fees_current, find_edition, html_lines, key_date_entries,
    norm_dates, parse_amount, parse_place, place_candidates,
)

TODAY = date(2026, 10, 14)

UKIO_HTML = """<html><head><title>UKIO &#8211; Multidisciplinary congress</title></head><body>
<nav><a href="/x">Menu</a></nav>
<p>UKIO and ROCE are pleased to acknowledge the Industry Partnership with AXREM</p>
<p>7-9 June 2027 &middot; Liverpool Experience Campus</p>
<h2>UKIO 2027: People. Precision. Partnership.</h2>
<p>UKIO 2026 took place on 8-10 June 2026 in Liverpool.</p></body></html>"""

# JSON-LD describes the PAST edition; the visible header line is the next one (CCR London).
CCR_HTML = """<html><head><title>CCR</title>
<script type="application/ld+json">{"@type":"Event","name":"CCR London","startDate":"2026-10-01T09:00:00","endDate":"2026-10-02T16:30:00"}</script>
</head><body><p>14 &amp; 15 October 2027</p><p>Excel London</p><p>Register your interest</p></body></html>"""

# Edition microsite: dates have no year, the year is in the <title> (EAPS 2027).
EAPS_HTML = """<html><head><title>Home - EAPS 2027</title></head><body>
<p>The 13th Congress of the</p><p>16-19 SEPTEMBER | BERLIN &amp; ONLINE</p><p>Join the global paediatric community.</p></body></html>"""

LD_HTML = """<html><head><title>NHS ConfedExpo</title>
<script type="application/ld+json">{"@type":"Event","name":"NHS ConfedExpo","startDate":"2027-06-16T00:00:00Z","endDate":"2027-06-17T00:00:00Z",
"location":{"@type":"Place","name":"Manchester Central","address":{"addressLocality":"Manchester","addressCountry":"GB"}}}</script>
</head><body><p>hello</p></body></html>"""


def test_header_line_edition_with_venue():
    lines = html_lines(UKIO_HTML)
    ed = find_edition(UKIO_HTML, lines, "https://x/", TODAY)
    assert (ed["start"], ed["end"], ed["source"]) == ("2027-06-07", "2027-06-09", "header-line")
    assert place_candidates(lines, ed)[0] == "Liverpool Experience Campus"


def test_past_json_ld_is_skipped_and_ampersand_day_range_parsed():
    ed = find_edition(CCR_HTML, html_lines(CCR_HTML), "https://x/", TODAY)
    assert (ed["start"], ed["end"]) == ("2027-10-14", "2027-10-15")
    assert norm_dates("14 & 15 October 2027") == "14-15 October 2027"


def test_yearless_dates_take_year_from_page_title():
    lines = html_lines(EAPS_HTML)
    ed = find_edition(EAPS_HTML, lines, "https://eaps2027.kenes.com/", TODAY)
    assert (ed["start"], ed["end"]) == ("2027-09-16", "2027-09-19")
    v, c, k, hybrid = parse_place(place_candidates(lines, ed)[0])
    assert (c, hybrid) == ("Berlin", True)


def test_upcoming_json_ld_wins():
    ed = find_edition(LD_HTML, html_lines(LD_HTML), "https://x/", TODAY)
    assert ed["source"] == "json-ld" and ed["start"] == "2027-06-16"


def test_no_upcoming_edition_returns_none():
    html = "<html><body><p>EAPS 2026 brought us together in Athens from 24-27 September 2026.</p></body></html>"
    assert find_edition(html, html_lines(html), "https://x/", TODAY) is None


def test_deadline_lines_are_not_the_congress_dates():
    html = "<html><body><p>Abstract submission deadline: 5-9 November 2026</p><p>Registration opens 1-2 December 2026</p></body></html>"
    assert find_edition(html, html_lines(html), "https://x/", TODAY) is None


def test_parse_place_variants():
    assert parse_place("NASHVILLE, TN")[1:3] == ("Nashville", "United States")
    assert parse_place("San Diego, California")[1:3] == ("San Diego", "United States")
    assert parse_place("Washington, D.C. & Online")[1:] == ("Washington, D.C.", "United States", True)
    assert parse_place("PAS 2027 – Minneapolis, Minnesota")[1:3] == ("Minneapolis", "United States")
    assert parse_place("Athens, Greece")[1:3] == ("Athens", "Greece")
    assert parse_place("Join us in Vienna")[1] == "Vienna"
    assert parse_place("Berlin​")[1] == "Berlin"


def test_parse_amount_formats():
    assert parse_amount("EUR 800", "EUR") == (800.0, "EUR")
    assert parse_amount("€ 1.060", "EUR") == (1060.0, "EUR")
    assert parse_amount("$1,395", "USD") == (1395.0, "USD")
    assert parse_amount("Complimentary", "USD") == (0.0, "USD")
    assert parse_amount("Member 1", "USD") is None
    assert parse_amount("2027", "USD") is None            # a bare number is a year, not a fee


ECR_LINES = [
    "ECR 2027 Registration Fees", "Ticket type", "Opening Fee", "(until Nov 4, 2026)", "Early Fee", "(until Dec 16, 2026)",
    "Late Fee", "(Dec 17, 2026 onwards)", "Full Member 1", "€ 710", "€ 870", "€ 950",
    "Full Fee Non-Member", "€ 1.040", "€ 1.360", "€ 1.420",
]


def test_fee_matrix_with_column_headers_and_thousand_separators():
    t = fee_matrix(ECR_LINES, "EUR")
    assert len(t) == 6
    assert t[0]["tier_label"] == "Registration · Full Member · Opening Fee"
    assert (t[0]["price_gbp"], t[0]["currency"], t[0]["is_early_bird"], t[0]["early_bird_deadline"]) == (710.0, "EUR", True, "2026-11-04")
    assert t[2]["price_gbp"] == 950.0 and not t[2]["is_early_bird"]
    assert t[5]["price_gbp"] == 1420.0


def test_fee_matrix_section_heading_and_free_cell():
    lines = ["Onsite Registration Fees", "Category", "On or Before March 10", "March 11-May 13", "On or After May 14", "Member", "Any physician or researcher.",
             "Complimentary", "$231", "$289", "Nonmember", "$693", "$793", "$851"]
    t = fee_matrix(lines, "USD")
    assert t[0]["tier_label"] == "Onsite · Member · On or Before March 10" and t[0]["price_gbp"] == 0.0
    assert [x["price_gbp"] for x in t[3:]] == [693.0, 793.0, 851.0]


def test_stale_or_unopened_fee_pages_are_rejected():
    stale = ["Registration for DDW 2026 will open on Jan. 14, 2026", "Category", "Member", "$252", "$378"]
    assert not fees_current(stale, 2027)
    unopened = ["Registration for ESCMID Global 2027 will open on 28 October 2026.", "Member regular", "EUR 800", "EUR 900"]
    assert not fees_current(unopened, 2027)
    acog_old = ["Your membership must be valid through May 3, 2026.", "Fellow", "$750", "$850", "$950"]
    assert not fees_current(acog_old, 2027)
    assert fees_current(ECR_LINES, 2027)


def test_key_dates_label_then_date_and_date_then_label():
    pas = ["2027 KEY DATES", "PAS 2027 – Minneapolis, Minnesota", "April 30 – May 3, 2027", "Call for Abstracts",
           "August 12 – November 2, 2026", "Abstract Notification", "January 19, 2027"]
    got = {lab: (s.isoformat(), e.isoformat()) for lab, s, e in key_date_entries(pas)}
    assert got["Call for Abstracts"] == ("2026-08-12", "2026-11-02")
    toronto = ["Important Dates", "March 24, 2026", "Regular Abstract Submission Opens", "May 7, 2026", "Regular Abstract Submission Closes",
               "July 16, 2026", "Late-Breaking Abstract Submission Closes"]
    got = {lab: e.isoformat() for lab, s, e in key_date_entries(toronto)}
    assert got["Regular Abstract Submission Closes"] == "2026-05-07" and got["Late-Breaking Abstract Submission Closes"] == "2026-07-16"


def test_key_dates_yearless_and_colon_forms():
    ecr = ["TIMELINE TO ECR 2027", "August 3 – October 5", "Abstract submission open for Oral presentations", "November 30",
           "ESR Membership final deadline", "December 16 – January 11", "Late Breaking Abstract submission", "March 3 – 7, 2027"]
    got = {lab: e.isoformat() for lab, s, e in key_date_entries(ecr, date(2027, 3, 3))}
    assert got["Late Breaking Abstract submission"] == "2027-01-11"
    croi = ["General Abstract Submission Cycle: August 27, 2026 – October 1, 2026", "Late-Breaking Abstract Submission Cycle: December 1, 2026 – January 19, 2027"]
    got = {lab: e.isoformat() for lab, s, e in key_date_entries(croi)}
    assert got["Late-Breaking Abstract Submission Cycle"] == "2027-01-19"


class _Stub(SingleCongressExtractor):
    HOME_URL = "https://stub.example/"
    SOCIETY = "STUB"
    EVENT_NAME = "STUB"
    DEFAULT_SPECIALTY = "Radiology"
    DEFAULT_CURRENCY = "EUR"

    def __init__(self):
        super().__init__({"id": 1, "source_name": "stub"})

    def _get(self, url, tries=3):          # no network in tests
        return None


def test_detail_end_to_end_without_network():
    ex = _Stub()
    shell = {"title": "STUB 2027", "start_date": "2027-06-07", "end_date": "2027-06-09", "edition_year": 2027, "booking_url": "https://stub.example/"}
    out = ex.detail_from_html(UKIO_HTML, "https://stub.example/", shell, None)
    assert out["venue_name"] == "Liverpool Experience Campus"
    assert out["event_format"] == "in_person"
    assert out["specialty"] == "Radiology"
    assert out["start_date"] == "2027-06-07" and out["end_date"] == "2027-06-09"
    assert "pricing_tiers" not in out                       # nothing invented when no fee page is reachable
    assert "UKIO 2026" not in out.get("description", "")    # previous edition's prose never becomes the description
