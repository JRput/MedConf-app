"""Sanity gates for fixer outputs before they reach Supabase."""

from __future__ import annotations
import logging
import re
from datetime import date as _date
from typing import Any

import money

logger = logging.getLogger(__name__)


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


# Currencies are the shared `money.KNOWN_CODES` table (ISO-4217, 50 codes) and the
# per-currency fee cap is `money.max_amount` (KRW/JPY/INR/IDR... legitimately run to
# 5-9 digits). pricing_tiers.currency is text, so any known code is storable.
_SMALL_AMOUNT = 5.0


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
        # A present-but-null/unknown currency (vision could not read one) is rejected, not defaulted.
        if currency not in money.KNOWN_CODES:
            return False
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0 \
                or price > money.max_amount(currency):
            return False
        if 0 < price < _SMALL_AMOUNT:
            logger.warning("validate pricing: suspiciously small amount %s %s for %r "
                           "(a thousands separator or a page number misread?)", currency, price, label[:60])
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
