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
