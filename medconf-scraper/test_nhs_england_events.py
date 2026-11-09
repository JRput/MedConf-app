"""NHS England events portal extractor: card parsing, relevance gate, ticket blocks (offline fixtures)."""
from datetime import date
from pathlib import Path

from extractors import nhs_england_events as nhs

FIX = Path(__file__).parent / "test_fixtures"
TODAY = date(2026, 11, 9)


def _read(name):
    return (FIX / name).read_text()


def test_listing_cards():
    cards = nhs.parse_listing(_read("nhs_england_events_listing.html"), TODAY)
    assert len(cards) >= 17
    c = next(x for x in cards if x["id"] == "/512525")
    assert c["title"] == "Viral Hepatitis Primary Care and GP Champion Network Meeting"
    assert c["start_date"] == "2026-11-17" and c["location"] == "London"
    assert not any("data-add-url" in x["title"] for x in cards)           # opening-tag remnants never leak into titles
    assert nhs.parse_listing(_read("nhs_england_events_listing.html"), date(2027, 1, 1)) == []


def test_relevance_gate_keeps_clinical_and_drops_admin():
    keep = ["GIRFT urology webinar series: Webinar 2 - your questions answered", "Responsible Officer Training",
            "5th Annual East of England Renal Clinical Network Day", "Addressing Delays to Induction of Labour",
            "National Visual Reinforcement Audiometry (VRA) Quality Improvement Webinar"]
    drop = ["NHS Spend Comparison Service – Induction Sessions", "East of England (Re)Discover Copilot", "Crisis Communications",
            "Routes to CIPD Membership - New Members", "AI Digital Diagnostics - Supplier Open Event", "Shine a light on co-production January 2027",
            "In Person One Clock Club"]
    assert all(nhs.is_relevant(t) for t in keep)
    assert not any(nhs.is_relevant(t) for t in drop)


def test_address_split():
    a = nhs.split_address("Park Plaza London Waterloo, 6 Hercules Road, London, SE1 7DP , United Kingdom")
    assert a["city"] == "London" and a["region"] == "London" and a["venue_name"].startswith("Park Plaza London Waterloo")
    b = nhs.split_address("The Nucleus, Chesterfield Research Park, Little Chesterford,, Saffron Walden, East of England, CB10 1TS , United Kingdom")
    assert b["city"] == "Saffron Walden" and b["region"] == "East of England"


def test_free_ticket_block():
    tiers = nhs.parse_tickets(_read("nhs_england_events_detail_free.html"))
    assert tiers == [{"tier_label": "Registration", "price_gbp": 0.0, "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None}]


def test_fully_booked_and_no_ticket_pages():
    booked = _read("nhs_england_events_detail_booked.html")
    assert nhs._is_sold_out(booked) and nhs.parse_tickets(booked)[0]["price_gbp"] == 0.0
    notick = _read("nhs_england_events_detail_nottickets.html")          # 'Ticket sales finished': no ticket block, no tiers, not sold out
    assert nhs.parse_tickets(notick) == [] and not nhs._is_sold_out(notick)


def test_extract_detail(monkeypatch):
    html = _read("nhs_england_events_detail_free.html")
    monkeypatch.setattr(nhs, "fetch_html", lambda *a, **k: html)
    shell = {"title": "Viral Hepatitis Primary Care and GP Champion Network Meeting", "booking_url": "https://www.events.england.nhs.uk/512525",
             "start_date": "2026-11-17", "venue_raw": "London"}
    out = nhs.NhsEnglandEventsExtractor({"id": 156}).extract_detail(None, shell, lambda p: None)
    assert out["start_date"] == "2026-11-17" and out["start_time"] == "09:30" and out["event_format"] == "in_person"
    assert out["city"] == "London" and out["venue_name"].startswith("Park Plaza") and out["pricing_tiers"][0]["price_gbp"] == 0.0
    assert out["society"] == "NHS England" and out["event_type"] == "workshop" and out["description"].startswith("Join us for the in-person meeting")


def test_location_tbc_learning_programme_is_online_and_never_blank_without_cause(monkeypatch):
    html = _read("nhs_england_events_detail_tbc.html")
    monkeypatch.setattr(nhs, "fetch_html", lambda *a, **k: html)
    shell = {"title": "Who gets to be a Physiotherapist? Negotiating Participation in Physiotherapy Education",
             "booking_url": "https://www.events.england.nhs.uk/532291", "start_date": "2026-12-02", "venue_raw": None}
    out = nhs.NhsEnglandEventsExtractor({"id": 156}).extract_detail(None, shell, lambda p: None)
    assert out["event_format"] == "online" and out["end_date"] == "2027-04-28" and "city" not in out
    assert nhs._format_from_cues(["2026-12-01"], "A meeting", "Join us on the day", False) is None     # unknown stays unknown
    assert nhs._format_from_cues([], "A meeting", "", True) == "in_person"
