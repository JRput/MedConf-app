"""money.py — the shared amount / currency parser (ticket A1, 2026-10-27)."""
import pytest

import money
from money import (CURRENCIES, KNOWN_CODES, Money, detect_currency, find_amounts, normalize_currency,
                   parse_amount, parse_number, plausible)


@pytest.mark.parametrize("text,amount,currency", [
    ("£1,250.00", 1250.0, "GBP"),
    ("€ 1.500,00", 1500.0, "EUR"),
    ("1.500,00 €", 1500.0, "EUR"),
    ("1 200,50 €", 1200.5, "EUR"),
    ("1500 EUR", 1500.0, "EUR"),
    ("EUR1500", 1500.0, "EUR"),
    ("EUR 350 (excl. VAT)", 350.0, "EUR"),
    ("from 350 EUR", 350.0, "EUR"),
    ("500 eur", 500.0, "EUR"),
    ("CHF 1'200", 1200.0, "CHF"),
    ("CHF 1 200.–", 1200.0, "CHF"),
    ("Fr. 1'200", 1200.0, "CHF"),
    ("USD $350", 350.0, "USD"),
    ("US$350", 350.0, "USD"),
    ("$1,395.50", 1395.5, "USD"),
    ("A$250", 250.0, "AUD"),
    ("C$300", 300.0, "CAD"),
    ("NZ$275", 275.0, "NZD"),
    ("S$465.00", 465.0, "SGD"),
    ("HK$1,280", 1280.0, "HKD"),
    ("R$ 900", 900.0, "BRL"),
    ("¥50,000", 50000.0, "JPY"),
    ("₩300,000", 300000.0, "KRW"),
    ("₹25,000", 25000.0, "INR"),
    ("350 PLN", 350.0, "PLN"),
    ("zł 350", 350.0, "PLN"),
    ("1 200 zł", 1200.0, "PLN"),
    ("CZK 5 000", 5000.0, "CZK"),
    ("12 500 Kč", 12500.0, "CZK"),
    ("SEK 2 500", 2500.0, "SEK"),
    ("£0.00 shipping", 0.0, "GBP"),                     # amount 0 is returned; the caller decides
    (" € 1 500", 1500.0, "EUR"),          # NBSP / narrow NBSP tolerant
])
def test_amount_and_currency(text, amount, currency):
    m = parse_amount(text)
    assert m is not None and (m.amount, m.currency) == (amount, currency)


def test_range_has_low_and_high():
    for t in ("€350–€500", "350–500 EUR", "EUR 350 - 500", "€350 to €500"):
        m = parse_amount(t)
        assert (m.amount, m.high, m.currency) == (350.0, 500.0, "EUR"), t
    assert parse_amount("£350 - 2027").high is None          # a year is not an upper bound
    assert parse_amount("£350 - 15 March").high is None


@pytest.mark.parametrize("text", ["Free", "TBC", "Complimentary", "", "Member"])
def test_no_amount_is_none(text):
    assert parse_amount(text) is None


def test_kr_needs_context():
    assert parse_amount("kr 2,500").currency is None
    assert parse_amount("kr 2,500").amount == 2500.0
    assert parse_amount("kr 2,500", context="Fees in SEK").currency == "SEK"
    assert parse_amount("2 500 kr", context="Norwegian kroner; NOK").currency == "NOK"
    assert parse_amount("kr 2,500", context="SEK or NOK").currency is None          # two candidates: not guessed


def test_dollar_and_yen_ambiguity():
    assert parse_amount("$300").currency == "USD"
    assert parse_amount("$300", context="Fees in AUD").currency == "AUD"
    assert parse_amount("$300", context="Australian dollars").currency == "AUD"
    assert parse_amount("$300", context="USD and AUD").currency == "USD"
    assert parse_amount("¥300").currency == "JPY"
    assert parse_amount("¥300", context="RMB").currency == "CNY"
    assert parse_amount("300元").currency == "CNY"
    assert parse_amount("300 円").currency == "JPY"


@pytest.mark.parametrize("raw,currency,expected", [
    ("1.500,00", None, 1500.0), ("1,500.00", None, 1500.0), ("1.500", None, 1500.0), ("1,500", None, 1500.0),
    ("350,5", None, 350.5), ("350.50", None, 350.5), ("1 200,00", None, 1200.0), ("1'200", None, 1200.0),
    ("1.500.000", None, 1500000.0), ("50.000", "JPY", 50000.0), ("300,000", "KRW", 300000.0),
    ("5 000", "CZK", 5000.0), ("1 200", "HUF", 1200.0), ("2.500", "SEK", 2500.0),
])
def test_decimal_rule(raw, currency, expected):
    assert parse_number(raw, currency) == expected


def test_find_amounts_returns_every_priced_token():
    found = find_amounts("Member £350, Student £200 or 150 EUR; 2027 edition")
    assert [(m.amount, m.currency) for m in found] == [(350.0, "GBP"), (200.0, "GBP"), (150.0, "EUR")]
    assert find_amounts("2027 in 12 days") == []                  # no currency token, no amount
    assert [m.amount for m in find_amounts("Day 1, 350 or 20", require_currency=False)] == [1.0, 350.0, 20.0]


def test_adjacent_symbols_do_not_steal_each_other():
    found = find_amounts("£350 £400")
    assert [(m.amount, m.currency) for m in found] == [(350.0, "GBP"), (400.0, "GBP")]


def test_spans_point_into_the_original_text():
    text = "Members:  £225* only"
    m = parse_amount(text)
    assert text[m.span[0]:m.span[1]] == "£225"


@pytest.mark.parametrize("ctx,url,expected", [
    ("Registration fees (S$)", None, "SGD"),
    ("Fees in CAD", None, "CAD"),
    ("Fees in USD/€", None, "USD"),                          # earliest code wins
    ("Prices in euros", None, "EUR"),
    ("Registration fees (SEK)", None, "SEK"),
    ("Swiss francs", None, "CHF"),
    ("Registration fees", None, None),                       # never defaults
    ("", None, None),
    ("Registration fees", "https://www.rcgp.org.uk/events", "GBP"),
    ("Registration fees", "https://example.com/x", None),
    ("Fees €", "https://example.co.uk", "EUR"),                # text evidence beats the URL
    ("see index.php try 5", None, None),                      # minor codes are upper-case only
])
def test_detect_currency(ctx, url, expected):
    assert detect_currency(ctx, url) == expected


def test_normalize_currency():
    assert normalize_currency("usd") == "USD" and normalize_currency("₩") == "KRW"
    assert normalize_currency("US$") == "USD" and normalize_currency("S$") == "SGD" and normalize_currency("Fr.") == "CHF"
    assert normalize_currency("Euro") == "EUR" and normalize_currency("zł") == "PLN"
    for bad in (None, "", "unknown", "N/A", "kr", "ABC"):
        assert normalize_currency(bad) is None, bad


def test_table_is_complete_and_consistent():
    required = "GBP EUR USD CHF SGD HKD BRL AUD CAD NZD INR JPY KRW CNY SEK NOK DKK PLN CZK TRY ZAR MXN RON HUF AED SAR ILS THB MYR IDR PHP TWD".split()
    assert set(required) <= KNOWN_CODES == set(CURRENCIES)
    for code, row in CURRENCIES.items():
        assert {"symbols", "decimals", "max", "names"} <= set(row), code
    assert CURRENCIES["JPY"]["decimals"] == 0 and CURRENCIES["GBP"]["decimals"] == 2


def test_caps():
    assert plausible(50000, "GBP") and not plausible(50001, "GBP")
    assert plausible(1_500_000, "JPY") and not plausible(25_000_000, "JPY")
    assert plausible(300_000, "KRW")
    assert not plausible(-1, "EUR") and not plausible(None, "EUR")
    assert money.max_amount(None) == 50000.0


def test_money_is_a_value_object():
    assert Money(1.0, "GBP") == Money(1.0, "GBP", None, (0, 0))
    with pytest.raises(Exception):
        Money(1.0, "GBP").amount = 2.0                       # frozen
