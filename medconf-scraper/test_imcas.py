"""IMCAS extractor: own-congress menu parsing, third-party agenda dropped, congress page (offline fixtures)."""
from datetime import date
from pathlib import Path

from extractors import imcas

FIX = Path(__file__).parent / "test_fixtures"
TODAY = date(2026, 11, 9)


def _read(name):
    return (FIX / name).read_text()


def test_menu_keeps_own_congresses_and_drops_invest():
    m = imcas.parse_menu(_read("imcas_menu.html"), TODAY)
    assert [(c["title"], c["start_date"], c["end_date"]) for c in m["kept"]] == [
        ("IMCAS World 2027", "2027-01-28", "2027-01-30"), ("IMCAS Americas 2027", "2027-05-20", "2027-05-22"),
        ("IMCAS Asia 2027", "2027-06-04", "2027-06-06"), ("IMCAS China 2027", "2027-08-26", "2027-08-28")]
    assert m["kept"][0]["booking_url"] == "https://www.imcas.com/en/imcas-world-2027"
    assert len(m["dropped"]) == 1 and "INVEST" in m["dropped"][0]
    assert imcas.parse_menu(_read("imcas_menu.html"), date(2027, 12, 1))["kept"] == []


def test_third_party_agenda_titles_are_listed_for_the_drop_log():
    titles = imcas.parse_agenda_titles(_read("imcas_menu.html"))
    assert len(titles) >= 20 and any("ASDS" in t for t in titles) and not any(t.startswith("IMCAS") for t in titles)


def test_place_split():
    assert imcas.split_place("PARIS & ONLINE") == {"city": "Paris", "region": "France", "event_format": "hybrid"}
    assert imcas.split_place("SAO PAULO - SP")["region"] == "Brazil"
    p = imcas.split_place("Palais des Congrès de Paris, Paris")
    assert p["venue_name"] == "Palais des Congrès de Paris" and p["city"] == "Paris" and p["event_format"] == "in_person"


def test_extract_detail_world_2027(monkeypatch):
    html = _read("imcas_world_2027.html")
    monkeypatch.setattr(imcas, "fetch_html", lambda *a, **k: html)
    shell = {"title": "IMCAS World 2027", "booking_url": "https://www.imcas.com/en/imcas-world-2027", "start_date": "2027-01-28",
             "end_date": "2027-01-30", "venue_raw": "PARIS & ONLINE"}
    out = imcas.ImcasExtractor({"id": 157}).extract_detail(None, shell, lambda p: None)
    assert out["venue_name"] == "Palais des Congrès de Paris" and out["city"] == "Paris" and out["event_format"] == "hybrid"
    assert out["end_date"] == "2027-01-30" and out["pricing_tiers"] == [] and out["event_type"] == "conference"
    assert out["description"].startswith("IMCAS World 2027: Step into the future of dermatology")
    assert imcas.ImcasExtractor.DISCOVERY_ENABLED is False             # robots.txt disallows /*/registration


def test_description_names_the_event():
    assert imcas.with_title_token("Step into the future of dermatology.", "IMCAS World 2027").startswith("IMCAS World 2027: Step into")
    assert imcas.with_title_token("IMCAS Americas 2027 in Sao Paulo is the central meeting point.", "IMCAS Americas 2027").startswith("IMCAS Americas")
