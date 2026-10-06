"""Venue-name trimming for the Tribe family and ISUOG (no network)."""
from extractors.tribe_events import clean_prose_venue, clip_venue
from extractors.esp_pathology import EspPathologyExtractor
from extractors.isuog import clean_venue_line


def test_stops_at_labels():
    assert clean_prose_venue("Lottle Hotel Seoul, Seoul, South KoreaSessions: Lectures and poster exhibition More information") == "Lottle Hotel Seoul, Seoul, South Korea"
    assert clean_prose_venue("Swissôtel Tallinn Address: Tornimäe tn 3, 10145 Tallinn Accommodation: reduced rate") == "Swissôtel Tallinn"
    assert clean_prose_venue("Manchester Grand Hyatt San Diego Sessions: Lectures and e-poster session More information is available here.\\u00a0 This is an external event") == "Manchester Grand Hyatt San Diego"


def test_keeps_abbreviations_and_clips_at_word():
    assert clean_prose_venue("St. James Hotel, London") == "St. James Hotel, London"
    out = clip_venue("A" * 10 + " " + "word " * 30)
    assert len(out) <= 80 and not out.endswith("wor")


def test_empty():
    assert clean_prose_venue(None) is None
    assert clean_prose_venue("Sessions: x") is None


def test_esp_hook_venue_and_city():
    ext = EspPathologyExtractor.__new__(EspPathologyExtractor)
    text = "KSP 2026 05 – 06 November, 2026 Seoul, South Korea 78th Annual Meeting. Venue: Lottle Hotel Seoul, Seoul, South KoreaSessions: Lectures"
    venue, city, country = ext.location_from_text(text, {})
    assert clean_prose_venue(venue) == "Lottle Hotel Seoul, Seoul, South Korea"
    assert city == "Seoul"
    # no header city, only a Venue label (EScoP Brussels style)
    v2, c2, _ = ext.location_from_text("Course. Venue: ESP Headquarters, Brussels, Belgium Address: Sq. de Meeus 18", {})
    assert clean_prose_venue(v2) == "ESP Headquarters, Brussels, Belgium" and c2 is None


def test_isuog_venue_line():
    assert clean_venue_line("Malmö, SWEDEN, Skane University Hospital, Medicinskt Konferenscentrum (MKC), Jan Waldenströms gata 1, Jubileumsaulan") == \
        "Malmö, SWEDEN, Skane University Hospital, Medicinskt Konferenscentrum (MKC)"
    # prose sentence is not a venue
    assert clean_venue_line("Indore,” the cleanest city of India (record held uninterrupted since 2017)”. The Congress will be held from 23 rd") is None
