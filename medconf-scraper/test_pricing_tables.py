"""Universal fee-table parser: cell-level currency + multi-column fee grids (IUSTI 2026, found by the owner 2026-10-14)."""
import os

from extractors.pricing_tables import parse_pricing_tables, _cells_currency

HERE = os.path.dirname(__file__)
IUSTI = open(os.path.join(HERE, "fixtures", "iusti_2026_fees.html")).read()


def test_iusti_grid_currency_comes_from_cells():
    tiers = parse_pricing_tables(IUSTI, default_currency="")
    assert tiers and all(t["currency"] == "EUR" for t in tiers)


def test_iusti_grid_expands_every_column_with_labels_and_early_bird():
    tiers = parse_pricing_tables(IUSTI, default_currency="")
    member = [t for t in tiers if t["tier_label"].startswith("Registration Fees · IUSTI Member ·")]
    assert [(t["tier_label"].split(" · ")[-1], t["price_gbp"]) for t in member] == [
        ("Early Registration", 550.0), ("Regular Registration", 600.0), ("Late/On-Site Registration", 700.0)]
    assert member[0]["is_early_bird"] and member[0]["early_bird_deadline"] == "2026-06-15"
    assert not member[1]["is_early_bird"] and member[1]["early_bird_deadline"] is None


def test_single_price_column_keeps_last_cell_behaviour():
    html = ("<h3>Registration Fees</h3><table><tr><th>Category</th><th>Rate</th></tr>"
            "<tr><td>Member</td><td>£120</td></tr><tr><td>Non-member</td><td>£180</td></tr></table>")
    tiers = parse_pricing_tables(html, default_currency="")
    assert [(t["tier_label"], t["price_gbp"], t["currency"]) for t in tiers] == [
        ("Registration Fees · Member", 120.0, "GBP"), ("Registration Fees · Non-member", 180.0, "GBP")]


def test_non_fee_extra_columns_do_not_expand():
    html = ("<h3>Course fees</h3><table><tr><th>Item</th><th>Net</th><th>VAT</th><th>Total</th></tr>"
            "<tr><td>Course</td><td>100</td><td>20</td><td>120</td></tr></table>")
    tiers = parse_pricing_tables(html, default_currency="GBP")
    assert [(t["price_gbp"]) for t in tiers] == [120.0]


def test_heading_currency_still_wins_over_cells():
    html = ("<h3>Registration fees (USD)</h3><table><tr><td>Delegate</td><td>500</td></tr></table>")
    assert parse_pricing_tables(html, default_currency="")[0]["currency"] == "USD"


def test_cells_currency_vote():
    assert _cells_currency(["550 EUR", "600 EUR", "£5 booking fee"]) == "EUR"
    assert _cells_currency(["$1,295", "$1,495"]) == "USD"
    assert _cells_currency(["500", "600"]) is None


def test_comma_thousands_without_decimals():
    from extractors.pricing_tables import _parse_price
    assert _parse_price("EUR 1,125") == 1125.0
    assert _parse_price("12,500") == 12500.0
    assert _parse_price("1200,50") == 1200.5
    assert _parse_price("1 200,00") == 1200.0
    assert _parse_price("1.130 EUR") == 1130.0


# ── R2 HIGH bugs (2026-10-27): EU decimals, prefixed dollars, named currencies ─────────

def test_eu_decimal_with_symbol_prefix_is_not_one_and_a_half():
    from extractors.pricing_tables import _parse_price
    assert _parse_price("€ 1.500,00") == 1500.0


def _one_col(head, cell, default=""):
    html = (f"<h3>{head}</h3><table><tr><td>Member</td><td>{cell}</td></tr>"
            f"<tr><td>Student</td><td>{cell}</td></tr></table>")
    return [(t["price_gbp"], t["currency"]) for t in parse_pricing_tables(html, default_currency=default)]


def test_prefixed_dollar_symbols_are_not_usd():
    assert _one_col("Registration fees (S$)", "465")[:1] == [(465.0, "SGD")]     # old: USD
    assert _one_col("Registration fees", "S$465")[:1] == [(465.0, "SGD")]
    assert _one_col("Registration fees (A$)", "250")[:1] == [(250.0, "AUD")]
    assert _one_col("Registration fees", "HK$1,280")[:1] == [(1280.0, "HKD")]


def test_currency_named_in_heading_beyond_the_old_whitelist():
    assert _one_col("Fees in CAD", "400", default="GBP")[:1] == [(400.0, "CAD")]
    assert _one_col("Registration fees (SEK)", "2 500")[:1] == [(2500.0, "SEK")]


def test_no_detectable_currency_drops_the_tiers_instead_of_defaulting_to_gbp():
    assert _one_col("Registration fees", "350") == []
    assert _one_col("Registration fees", "350", default="GBP")[:1] == [(350.0, "GBP")]   # explicit default still honoured
