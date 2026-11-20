"""HIMSS Global Health Conference & Exhibition extractor: hooks proven on saved page fragments, no network."""
import os
from datetime import date

from extractors.himss_conference import HimssConferenceExtractor

FX = os.path.join(os.path.dirname(__file__), "test_fixtures")


def _read(n):
    return open(os.path.join(FX, n), encoding="utf-8").read()


PAGES = {
    "https://www.himssconference.com/register/": _read("himss_register.html"),
    "https://www.himssconference.com/call-for-posters/": _read("himss_cfp.html"),
}


def _ex(monkeypatch):
    ex = HimssConferenceExtractor({"id": 166, "source_name": "HIMSS"})
    monkeypatch.setattr(ex, "_get", lambda url, tries=3: PAGES.get(url))
    return ex


def test_fee_cards_early_bird_then_advance_skipping_suppliers_and_press():
    ex = HimssConferenceExtractor({"id": 166, "source_name": "HIMSS"})
    tiers = ex.fees_from_pages({"https://www.himssconference.com/register/": PAGES["https://www.himssconference.com/register/"]}, 2027)
    labels = {t["tier_label"]: t for t in tiers}
    assert len(tiers) == 23 and {t["currency"] for t in tiers} == {"USD"}
    early = labels["Conference Plus Pass · HIMSS Members · Early bird (until 20 December 2026)"]
    assert (early["price_gbp"], early["is_early_bird"], early["early_bird_deadline"]) == (1695.0, True, "2026-12-20")
    adv = labels["Conference Plus Pass · Non-Members · Advance (from 21 December 2026)"]
    assert (adv["price_gbp"], adv["is_early_bird"]) == (2295.0, False)
    assert labels["Additional Access · Student Pass · Standard"]["price_gbp"] == 325.0
    assert not [l for l in labels if "Market" in l or "Press" in l]


def test_detail_header_line_city_description_and_closed_call_for_posters(monkeypatch):
    ex = _ex(monkeypatch)
    shell = {"title": "HIMSS Global Health Conference & Exhibition 2027", "start_date": "2027-04-05", "end_date": "2027-04-08", "edition_year": 2027}
    out = ex.detail_from_html(_read("himss_home.html"), "https://www.himssconference.com/", shell, None)
    assert out["venue_name"] == "McCormick Place Convention Center"
    assert (out["city"], out["region"], out["event_format"]) == ("Chicago", "United States", "in_person")
    assert out["description"].startswith("Join HIMSS27") and "Las Vegas" not in out["description"]
    assert (out["abstract_open"], out["abstract_deadline"]) == (False, "2026-10-11")
    assert len(out["pricing_tiers"]) == 23


REG = "https://www.himssconference.com/register/"


def _tiers(html):
    return HimssConferenceExtractor({"id": 166, "source_name": "HIMSS"}).fees_from_pages({REG: html}, 2027)


def test_eligibility_subtitle_is_in_the_label_marketing_subtitle_is_not():
    labels = [t["tier_label"] for t in _tiers(PAGES[REG])]
    assert "Executive Plus Pass · Qualified Providers · HIMSS Members · Early bird (until 20 December 2026)" in labels
    assert "Conference Pass · General Admission · Non-Members · Advance (from 21 December 2026)" in labels
    assert not [l for l in labels if "Best Value" in l or "Exhibits" in l]


def test_missing_or_reworded_switch_sentence_emits_advance_price_as_standard():
    html = PAGES[REG].replace("Advance Pricing goes into effect", "Prices are subject to change from")
    tiers = _tiers(html)
    assert tiers and not [t for t in tiers if t["is_early_bird"] or t["early_bird_deadline"]]
    plus = next(t for t in tiers if t["tier_label"] == "Conference Plus Pass · HIMSS Members · Standard")
    assert plus["price_gbp"] == 1945.0
    assert not [t for t in tiers if t["price_gbp"] == 1695.0]
    student = next(t for t in tiers if "Student" in t["tier_label"])
    assert student["price_gbp"] == 325.0           # single-price card stays at its one price


def test_description_token_follows_the_edition_year():
    ex = HimssConferenceExtractor({"id": 166, "source_name": "HIMSS"})
    html = _read("himss_home.html").replace("HIMSS27", "HIMSS28").replace("2027", "2028")
    shell = {"title": "HIMSS 2028", "start_date": "2028-03-06", "end_date": "2028-03-09", "edition_year": 2028}
    ex._get = lambda url, tries=3: None
    assert ex.detail_from_html(html, "https://www.himssconference.com/", shell, None)["description"].startswith("Join HIMSS28")


def _abs(text, start="2027-04-05"):
    out = {}
    ex = HimssConferenceExtractor({"id": 166, "source_name": "HIMSS"})
    ex.apply_abstracts(out, {"u": f"<html><body><h1>Call for Posters</h1><p>{text}</p><p>The conference will be held April 5-8, 2027.</p></body></html>"}, {"start_date": start, "edition_year": 2027})
    return out


def test_poster_deadline_word_boundary_and_not_after_start():
    assert "abstract_deadline" not in _abs("We follow this closely. Posters are shown on October 11, 2026.")
    assert "abstract_deadline" not in _abs("The submission window closes on May 1, 2027.")
    assert _abs("The window closed on October 11, 2026.")["abstract_deadline"] == "2026-10-11"
