"""ASH (hematology.org/meetings) listing parser: both sentence wordings."""
from pathlib import Path

from extractors.hematology import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "ash_meetings_2026-10-30.html"


def _page(sentence: str) -> str:
    return (
        "<html><body><main><p>Meetings</p><p>ASH Annual Meeting</p><p>Annual Meeting</p>"
        f"<p>ASH Annual Meeting and Exposition</p><p>{sentence}</p>"
        "<p>Registration is open!</p></main></body></html>"
    )


def test_live_page_new_sentence_form():
    rows = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    annual = [r for r in rows if r["key"] == "annual"]
    assert len(annual) == 1
    r = annual[0]
    assert (r["start"], r["end"]) == ("2026-12-12", "2026-12-15")
    assert r["city"] == "New Orleans"
    assert r["region"] == "United States"
    assert r["format"] == "hybrid"
    assert r["title"] is None  # new copy omits "and Exposition"; list_shells_override uses the default title


def test_old_wording_still_parses():
    rows = parse_listing(_page(
        "The 67th ASH Annual Meeting and Exposition is taking place December 6-9, 2025, in Orlando, Florida."))
    assert len(rows) == 1
    r = rows[0]
    assert (r["start"], r["end"]) == ("2025-12-06", "2025-12-09")
    assert r["city"] == "Orlando"
    assert r["region"] == "United States"
    assert r["format"] == "in_person"


def test_no_date_no_place_gives_nothing():
    assert parse_listing(_page("Details about the meeting will be announced soon.")) == []


def test_date_without_place_gives_nothing():
    assert parse_listing(_page("The meeting will be held from December 12-15, 2026.")) == []


def _rows(key):
    return [r for r in parse_listing(FIXTURE.read_text(encoding="utf-8")) if r["key"] == key]


def test_north_america_four_cities():
    rows = _rows("na")
    got = [(r["city"], r["start"], r["end"], r["region"], r["format"]) for r in rows]
    assert got == [
        ("Chicago", "2027-01-15", "2027-01-16", "United States", "in_person"),
        ("New York", "2027-01-22", "2027-01-23", "United States", "in_person"),
        ("Seattle", "2027-01-22", "2027-01-23", "United States", "in_person"),
        ("Washington, DC", "2027-01-29", "2027-01-30", "United States", "in_person"),
    ]
    assert rows[0]["path"] == "/meetings/highlights-of-ash-in-north-america"


def test_asia_pacific_bangkok():
    rows = _rows("apac")
    assert len(rows) == 1
    r = rows[0]
    assert (r["city"], r["start"], r["end"], r["region"]) == ("Bangkok", "2027-02-12", "2027-02-13", "Thailand")


def test_mmena_athens():
    rows = _rows("memena")
    assert len(rows) == 1
    r = rows[0]
    assert (r["city"], r["start"], r["end"], r["region"]) == ("Athens", "2027-03-19", "2027-03-20", "Greece")


def test_latam_santiago():
    rows = _rows("latam")
    assert len(rows) == 1
    r = rows[0]
    assert (r["city"], r["start"], r["end"], r["region"]) == ("Santiago", "2027-04-02", "2027-04-03", "Chile")


def test_fixture_total_and_annual_unchanged():
    rows = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 8
    a = _rows("annual")[0]
    assert (a["start"], a["end"], a["city"], a["format"]) == ("2026-12-12", "2026-12-15", "New Orleans", "hybrid")


def test_unknown_heading_ignored():
    html = ("<main><p>Highlights of ASH on Mars</p><p>Feb 12 – 13, 2027</p><p>Olympus Mons, Mars</p></main>")
    assert parse_listing(html) == []
