"""Offline tests for RCGP engage fee extraction (extractors/rcgp.py).

Fixtures are real rendered captures (document.body.innerText / textContent,
2026-10-27) of engage.rcgp.org.uk event pages. Fees on these pages are free
text inside the organiser's description; there is no structured price field
(the ui-api Event__c record carries only the same rich-text Detail__c).
"""
import json
import pathlib

import pytest

from extractors.rcgp import RCGPExtractor, parse_rcgp_fee_text

FIX = pathlib.Path(__file__).parent / "fixtures"


class FakePage:
    """Minimal stand-in for a Playwright page: serves innerText / textContent."""

    def __init__(self, fx):
        self.inner, self.text = fx["inner"], fx["text"]

    def evaluate(self, js):
        return self.inner if "innerText" in js else self.text


def load(i):
    return json.loads((FIX / f"rcgp_{i}_rendered.json").read_text())


def tiers(i, start="2026-12-01"):
    return RCGPExtractor({"id": 1})._extract_engage_pricing(FakePage(load(i)), start)


def pairs(ts):
    return [(t["tier_label"], t["price_gbp"]) for t in ts]


def test_price_first_members_non_members():
    # "£495 - Members / £595 - Non-members" (was: no tiers)
    ts = tiers(555)
    assert pairs(ts) == [("Member", 495.0), ("Non-Member", 595.0)]
    assert all(t["currency"] == "GBP" and not t["is_early_bird"] for t in ts)


def test_free_member_paid_non_member():
    # "FREE - Member / £18 Non-member (inclusive of VAT)"
    assert pairs(tiers(3069)) == [("Member", 0.0), ("Non-Member", 18.0)]


def test_early_bird_ticket_lines_with_deadline():
    ts = tiers(2044, "2027-03-10")
    assert len(ts) == 4
    assert ("One-day ticket · Trainee · Early Bird", 159.0) in pairs(ts)
    assert all(t["is_early_bird"] and t["early_bird_deadline"] == "2026-12-03" for t in ts)


def test_non_members_charged_sentence():
    # member side is a deposit-only line and must not become a tier
    assert pairs(tiers(3140)) == [("Non-Member", 24.0)]


def test_deposit_only_event_gives_no_tiers():
    assert tiers(3487) == []


def test_existing_label_first_pattern_unchanged():
    # "Pricing:Members - £525Non-member - £625" is handled by the original regex
    ts = tiers(1680)
    assert pairs(ts) == [("Member", 525.0), ("Non-Member", 625.0)]
    assert all("currency" in t for t in ts)


@pytest.mark.parametrize("text,expected", [
    ("Cost: £20 for members, £80 for non-members", [("Member", 20.0), ("Non-Member", 80.0)]),
    ("Tickets: £20 Members | £30 Non-members/Guests", [("Member", 20.0), ("Non-Member", 30.0)]),
    ("£40.00 - All tickets", [("Standard", 40.0)]),
    ("Cost: RCGP Members - FREE\nNon RCGP Members and Guests £25.00", [("Member", 0.0), ("Non-Member", 25.0)]),
    ("Member: Free  Non-Member: Not Available", []),      # wholly free -> nothing
    ("ODE live: exclusive to RCGP members ODE REWIND: free to all", []),
    ("£10 refundable deposit for members | £20 non-members", []),
    ("there will be a £30 non-attendance fee", []),
])
def test_parser_cases(text, expected):
    got = pairs(parse_rcgp_fee_text(text))
    assert got == expected
