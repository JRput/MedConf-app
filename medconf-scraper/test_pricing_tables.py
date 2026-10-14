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
