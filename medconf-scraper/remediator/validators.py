"""Sanity gates for fixer outputs before they reach Supabase."""

from __future__ import annotations
import re
from datetime import date as _date
from typing import Any


def validate_description(value: str) -> bool:
    if not isinstance(value, str):
        return False
    n = len(value)
    if n < 50 or n > 700:
        return False
    # No nav leak
    if re.search(
        r"(T \+44|Disclaimer:|Cookies:|Skip to|Log in|Register Now|Copyright)",
        value,
    ):
        return False
    return True


def validate_venue_name(value: str) -> bool:
    if not isinstance(value, str):
        return False
    n = len(value)
    if n < 5 or n > 200:
        return False
    if not any(c.isalpha() for c in value):
        return False
    lower = value.lower()
    nav = ("register", "login", "menu", "search", "members", "exams",
           "cookies", "privacy", "terms")
    if any(p in lower for p in nav):
        return False
    return True


def validate_city(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) < 2 or len(value) > 60:
        return False
    return value[0].isalpha()


def validate_event_format(value: str) -> bool:
    return value in ("in_person", "online", "hybrid")


def validate_cpd_points(value: Any) -> bool:
    return isinstance(value, int) and 1 <= value <= 200


def validate_specialty(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return 3 <= len(value) <= 80


# Matches pricing_tiers.currency in production (CLAUDE.md §5) plus KRW and the
# few others already accepted. KRW/JPY/INR prices are routinely 5-6 digits.
_VALID_CURRENCIES = ("GBP", "USD", "EUR", "HKD", "SGD", "CHF", "BRL",
                     "AUD", "CAD", "INR", "JPY", "KRW")
_HIGH_DENOMINATION = ("KRW", "JPY", "INR")
_HIGH_DENOMINATION_CAP = 10_000_000


def validate_pricing_tiers(value: list) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for t in value:
        if not isinstance(t, dict):
            return False
        label = t.get("tier_label")
        price = t.get("price_gbp")
        currency = t.get("currency", "GBP")   # key absent = legacy text path (GBP)
        if not isinstance(label, str) or len(label) < 3 or len(label) > 200:
            return False
        cap = _HIGH_DENOMINATION_CAP if currency in _HIGH_DENOMINATION else 50000
        if not isinstance(price, (int, float)) or price < 0 or price > cap:
            return False
        # A present-but-null/unknown currency (vision could not read one) is rejected, not defaulted.
        if currency not in _VALID_CURRENCIES:
            return False
    return True


def validate_abstract_status(value: dict) -> bool:
    if not isinstance(value, dict):
        return False
    if "abstract_open" not in value:
        return False
    return True


VALIDATORS = {
    "description": validate_description,
    "venue_name": validate_venue_name,
    "city": validate_city,
    "event_format": validate_event_format,
    "cpd_points": validate_cpd_points,
    "specialty": validate_specialty,
    "pricing": validate_pricing_tiers,
    "abstract_status": validate_abstract_status,
}


def validate(field: str, value: Any) -> bool:
    fn = VALIDATORS.get(field)
    if fn is None:
        return False
    try:
        return bool(fn(value))
    except Exception:
        return False
