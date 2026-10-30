"""Dual-currency fee grid (IFPA 2027, 2026-10-30): parse in the billing currency, ignore
<sup> footnote markers, and keep the discovery sweep from inventing tiers out of them."""
import os
import pytest

from extractors.pricing_tables import parse_pricing_tables
from extractors import discovery

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ifpa_register_2026-10-30.html")


@pytest.fixture(scope="module")
def html():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def _by(tiers, cat, tf):
    return next(t for t in tiers if t["tier_label"].startswith(cat) and t["tier_label"].endswith(tf))


def test_ifpa_grid_12_sek_tiers(html):
    tiers = parse_pricing_tables(html)
    assert len(tiers) == 12
    assert {t["currency"] for t in tiers} == {"SEK"}
    assert all(" · " in t["tier_label"] and t["tier_label"].count(" · ") == 1 for t in tiers)
    p = _by(tiers, "Health Care Professionals (Prescribers)", "Early fee")
    assert p["price_gbp"] == 8400 and p["is_early_bird"] and p["early_bird_deadline"] == "2026-12-15"
    assert _by(tiers, "Student", "Regular fee")["price_gbp"] == 4800
    assert _by(tiers, "Non-Clinical Attendees", "Late fee / Onsite")["price_gbp"] == 11300
    assert any(t["tier_label"].startswith("Health Care Professional (Non-Prescribers)") for t in tiers)
    assert [t for t in tiers if not t["is_early_bird"] and t["early_bird_deadline"]] == []


def test_sweep_invents_nothing_from_footnotes(html):
    tiers = discovery._money_sweep(discovery._to_lines(html))
    assert all(t["price_gbp"] >= 5 for t in tiers)
    assert not [t for t in tiers if t["tier_label"].lstrip().startswith(tuple("0123456789"))]
    assert not [t for t in tiers if t["tier_label"].strip().upper() in {"SEK", "EUR", "SEK / EUR"}]


def test_sweep_label_guards():
    for bad in ("SEK", "SEK / EUR", "EUR", "1) EUR values are indicative only.", "Fees are billed in SEK"):
        assert discovery._bad_sweep_label(bad), bad
    assert not discovery._bad_sweep_label("Student registration")


def test_sweep_dual_line_keeps_first_amount():
    t = discovery._money_sweep("Registration fees\nMember registration: 8 400 SEK / 795 EUR\n"
                               "Student registration: 4 000 SEK / 380 EUR")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(8400.0, "SEK"), (4000.0, "SEK")]


def test_sweep_drops_tiny_amounts():
    assert discovery._money_sweep("Registration fees\nMember registration: EUR 1\nStudent registration: EUR 2") == []


def _grid(note, a="100 SEK / 10 EUR", b="200 SEK / 20 EUR"):
    return (f"<h2>Registration fees</h2><table><tr><td>Categories</td><td>Early fee<br>SEK / EUR<sup>1</sup></td>"
            f"<td>Regular fee<br>SEK / EUR<sup>1</sup></td></tr><tr><td>Delegate</td><td>{a}</td><td>{b}</td></tr></table>"
            f"<p>{note}</p>")


def test_billed_in_eur_picks_eur():
    t = parse_pricing_tables(_grid("1) Fees are billed in EUR."))
    assert {(x["currency"], x["price_gbp"]) for x in t} == {("EUR", 10.0), ("EUR", 20.0)}


def test_no_note_first_currency():
    t = parse_pricing_tables(_grid("No note here."))
    assert {x["currency"] for x in t} == {"SEK"}


def test_single_currency_table_unchanged():
    h = ("<h2>Registration fees</h2><table><tr><td>Category</td><td>Fee (EUR)</td></tr>"
         "<tr><td>Delegate</td><td>550.00</td></tr><tr><td>Student</td><td>250.00</td></tr></table>")
    t = parse_pricing_tables(h)
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Registration fees · Delegate", 550.0, "EUR"), ("Registration fees · Student", 250.0, "EUR")]


_TWO = "Registration fees\nMember registration: 8 400 SEK / 795 EUR\nStudent registration: 4 000 SEK / 380 EUR\n"


def test_billing_currency_second_amount_keeps_labels():
    t = discovery._money_sweep(_TWO + "Fees are billed in EUR.")
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Member registration", 795.0, "EUR"), ("Student registration", 380.0, "EUR")]


def test_billing_currency_first_amount_unchanged():
    t = discovery._money_sweep(_TWO + "Prices in SEK.")
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Member registration", 8400.0, "SEK"), ("Student registration", 4000.0, "SEK")]


def test_unrelated_billing_note_far_away_ignored():
    text = ("Registration fees\nMember registration: 500 EUR / 550 USD\n" + "Filler line about the venue.\n" * 80
            + "Parking is charged in USD.")
    t = discovery._money_sweep(text)
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(500.0, "EUR")]


def test_single_currency_dates_row_keeps_heading_and_deadline():
    h = ("<h2>Registration fees</h2><table><tr><td>Category</td><td>Early bird</td><td>Standard</td></tr>"
         "<tr><td>Dates</td><td>Until March 1, 2027</td><td>After March 1, 2027</td></tr>"
         "<tr><td>Physician</td><td>$400</td><td>$500</td></tr></table>")
    t = parse_pricing_tables(h)
    assert [x["tier_label"] for x in t] == ["Registration fees \u00b7 Physician \u00b7 Early bird",
                                            "Registration fees \u00b7 Physician \u00b7 Standard"]
    assert t[0]["early_bird_deadline"] == "2027-03-01" and t[0]["is_early_bird"]
