"""Ticket E: venue/city printed on the event page (AACR banner, Resus rows)."""
from pathlib import Path

from extractors import aacr
from extractors.resus import ResusExtractor as R
from extractors.location_evidence import find_location_evidence

FX = Path(__file__).parent / "fixtures"


# ---- AACR ----------------------------------------------------------------
def test_aacr_banner_fixture_event_960():
    html = (FX / "aacr_event960_main.html").read_text()
    assert aacr._parse_header_location(html) == (
        "Sheraton Grand Chicago Riverwalk", "Chicago", "Illinois")


def test_aacr_banner_text_fallback():
    html = "<h1>X</h1><p><strong>Feb 28 - Mar 3, 2027</strong><br><strong>JW Marriott Los Angeles L.A. Live</strong><br><strong>Los Angeles, California</strong></p>"
    v, c, r = aacr._parse_header_location(html)
    assert (c, r) == ("Los Angeles", "California") and v.startswith("JW Marriott")


def test_aacr_city_only_has_no_venue():
    html = '<span class="header-meta"><span class="date">June 1 - 3, 2027</span><span class="location">Kyoto, Japan</span></span>'
    assert aacr._parse_header_location(html) == (None, "Kyoto", "Japan")


def test_aacr_webinar_is_not_a_place():
    html = '<span class="header-meta"><span class="date">June 1, 2027</span><span class="location">Webinar</span></span>'
    assert aacr._parse_header_location(html) == (None, None, None)


# ---- Resus ---------------------------------------------------------------
def _rows():
    return R.__new__(R)._parse_rows((FX / "resus_event1544_p0.html").read_text())


def test_resus_picks_row_matching_start_date_chorley_not_london():
    rows = _rows()
    assert len(rows) >= 2
    loc = R._location_for_start(rows, "2026-11-09")
    assert loc["city"] == "Chorley"
    assert loc["venue_name"] == "The ATACC Group Ltd"


def test_resus_no_matching_row_leaves_location_absent():
    assert R._location_for_start(_rows(), "2031-01-01") == {"venue_name": None, "city": None, "region": None}


def test_resus_same_date_two_centres_is_ambiguous():
    rows = [
        {"start_date": "2026-11-06", "venue_name": "A Ltd", "city": "Birmingham", "region": None},
        {"start_date": "2026-11-06", "venue_name": "B Ltd", "city": "Leeds", "region": None},
    ]
    assert R._location_for_start(rows, "2026-11-06")["city"] is None


# ---- shared evidence helper ----------------------------------------------
BANNER = ('<h1>AACR-NCI-EORTC International Conference</h1><span class="header-meta">'
          '<span class="date">October 26 - 30, 2027</span>'
          '<span class="location">Sheraton Grand Chicago Riverwalk </span>'
          '<span class="location">Chicago, Illinois</span></span>')


def test_evidence_flags_aacr_banner():
    assert find_location_evidence(BANNER) is not None


def test_evidence_flags_plain_text_banner():
    ev = find_location_evidence("<div>Feb 28 - Mar 3, 2027 JW Marriott Los Angeles L.A. Live Los Angeles, California</div>")
    assert ev and "banner" in ev


def test_evidence_flags_venue_line_under_h1():
    ev = find_location_evidence("<h1>Spring Meeting</h1><p>Riverside Exhibition Park, Leeds</p><p>Some prose follows here about the programme.</p>")
    assert ev and "h1" in ev.lower()


def test_evidence_ignores_footer_address():
    html = "<h1>Course</h1><p>Book now.</p><footer>October 26 - 30, 2027 Acme House Springfield, Illinois</footer>"
    assert find_location_evidence(html) is None


def test_evidence_ignores_sponsor_address():
    html = "<h1>Course</h1><p>Sponsored by Acme Pharma, 1 Industrial Estate, Slough.</p><p>Dates: 12 May 2027 Our sponsor Acme Pharma Ltd Reading, Berkshire</p>"
    assert find_location_evidence(html) is None
