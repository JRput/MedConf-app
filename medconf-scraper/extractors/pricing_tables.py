"""Shared pricing-table parser — plain-number tables under fee-related headings.

The false-negative pattern that keeps biting us: WordPress-style sites
(ESGO courses, some conferences) render pricing as a plain HTML <table>
of `<label> | <numeric price>` rows under a heading like "Registration
Fees" or "Course Package Fee". Prices are just numbers ("550.00",
"1 200,00", "1.500 EUR") with no £/$/€ prefix in every cell — the
currency is declared once in the section header.

Because most extractors regex on `[£$€]\s*\d+`, these tables slip
through the fast-path unnoticed. This helper is a shared fallback:

    tiers = parse_pricing_tables(detail_html, default_currency="EUR")

Extractors call it after their source-specific parser to catch anything
that didn't fit the source's own conventions. The audit gate uses the
same helper to detect false negatives (0 tiers extracted, but plain-
number pricing tables ARE on the page).
"""

from __future__ import annotations
import re
import html as _html
from typing import List, Dict, Any, Optional, Tuple


# Headings that we accept as a pricing-section marker. If a <table>
# sits under a heading matching any of these, we parse it.
FEE_HEADING_TOKENS = (
    "registration fee",
    "registration rates",
    "course package fee",
    "course fee",
    "regular rate",
    "pricing",
    "prices",
    "fees",
    "registration",
    "rate",
    "fee schedule",
    "cost",
)


# Currency hint keywords found in headings / adjacent text.
_CURRENCY_HINTS = (
    ("EUR", "EUR"), ("€", "EUR"), ("Euro", "EUR"), ("euros", "EUR"),
    ("GBP", "GBP"), ("£", "GBP"), ("Pounds", "GBP"), ("Sterling", "GBP"),
    ("USD", "USD"), ("$", "USD"), ("Dollars", "USD"),
    ("CHF", "CHF"), ("Swiss Francs", "CHF"),
    ("SGD", "SGD"), ("Singapore", "SGD"),
    ("HKD", "HKD"), ("Hong Kong Dollars", "HKD"),
    ("BRL", "BRL"), ("Reais", "BRL"),
)


# Price cell patterns — any of these count as a "price" cell.
_PRICE_CELL_RE = re.compile(
    r"""
    ^\s*
    (?:[£$€]\s*)?                # optional prefix currency
    (
        \d{1,3}(?:[ .,]\d{3})*   # thousands separator: space, dot, comma
        (?:[.,]\d{1,2})?         # optional decimal (. or ,)
        |
        \d+(?:[.,]\d{1,2})?      # simpler pattern
    )
    \s*
    (?:[£$€]|EUR|GBP|USD|CHF|SGD|HKD|BRL)?  # optional suffix
    \s*
    (?:[*+†\d]+)?                # trailing footnote marker
    \s*$
    """,
    re.I | re.X,
)


def _clean(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_price(cell: str) -> Optional[float]:
    """Parse "1 200,00", "550.00", "1.500 EUR", "50", "£1,234.50" → float."""
    if not cell:
        return None
    s = cell.strip()
    # Strip currency suffixes + prefixes + trailing footnote markers
    s = re.sub(
        r"\s*(?:EUR|GBP|USD|CHF|SGD|HKD|BRL|€|£|\$)\s*", "", s, flags=re.I
    )
    s = re.sub(r"[*+†]+\s*$", "", s).strip()
    if not s:
        return None
    # Detect number format
    if "," in s and "." in s:
        # Both — US style with thousands (1,200.50)
        s = s.replace(",", "")
    elif "," in s:
        # European decimal (1 200,00 or 1200,50)
        s = s.replace(" ", "").replace(",", ".")
    elif re.match(r"^\d{1,3}(?:\.\d{3})+$", s):
        # 1.500 (European thousand-sep, no decimal)
        s = s.replace(".", "")
    else:
        s = s.replace(" ", "")
    try:
        val = float(s)
    except ValueError:
        return None
    # Reasonable price range guard: 1 to 50,000
    if 0.0 < val <= 50000.0:
        return val
    return None


def _detect_currency(context: str, default: str = "GBP") -> str:
    """Given a section heading + nearby text, guess the currency."""
    if not context:
        return default
    ctx_lower = context.lower()
    for hint, curr in _CURRENCY_HINTS:
        # Case-insensitive match, but require word-ish boundary
        if re.search(rf"\b{re.escape(hint.lower())}\b", ctx_lower) or hint in context:
            return curr
    return default


def _preceding_heading(html: str, table_start: int) -> Optional[str]:
    """Return the LAST <h2>/<h3>/<h4> BEFORE table_start whose text
    contains a fee-related keyword. CTA-style headings ("register
    HERE") are skipped so extractors don't use them as tier prefixes.
    """
    head_slice = html[max(0, table_start - 4000):table_start]
    matches = list(re.finditer(
        r"<h[234][^>]*>(.*?)</h[234]>", head_slice, re.DOTALL | re.I,
    ))
    for m in reversed(matches):
        c = _clean(m.group(1))
        if any(tok in c.lower() for tok in FEE_HEADING_TOKENS):
            return c
    return None


def _table_has_fee_header_row(table_html: str) -> bool:
    """Some tables don't have a preceding H2/H3 — the fee header lives
    inside row 1 ("Registration Fees | Regular Rate (EUR)")."""
    return bool(re.search(
        r"(?i)(registration\s+fees?|regular\s+rate|course\s+package|"
        r"fee\s+schedule|pricing\s+category)",
        table_html,
    ))


def parse_pricing_tables(
    html: str,
    *,
    default_currency: str = "GBP",
    max_tiers: int = 60,
) -> List[Dict[str, Any]]:
    """Extract pricing tiers from any HTML page that renders fees as
    <table> rows under a fee-related heading.

    Composite labels: "<Heading> · <Category>" so the frontend's tabbed
    PricingTable can group by section (Registration / Course Package
    Fee / etc.).

    Returns a list of dicts ready for pricing_tiers insertion:
        {tier_label, price_gbp, currency, is_early_bird, early_bird_deadline}
    """
    if not html:
        return []
    tiers: List[Dict[str, Any]] = []
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        table_html = m.group(1)
        heading = _preceding_heading(html, m.start())
        if not heading and not _table_has_fee_header_row(table_html):
            continue
        # Detect currency from heading + first 500 chars of table (may
        # contain "(EUR)" after column header)
        currency_ctx = (heading or "") + " " + table_html[:800]
        currency = _detect_currency(currency_ctx, default_currency)

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(cells) < 2:
                continue
            label = _clean(cells[0])
            if not label:
                continue
            # Try LAST cell first (typical price column), then walk left
            price: Optional[float] = None
            for cell_html in reversed(cells[1:]):
                cell_text = _clean(cell_html)
                if not cell_text:
                    continue
                p = _parse_price(cell_text)
                if p is not None:
                    price = p
                    break
            if price is None:
                continue
            # Skip label-only rows (header row is: "Category | Rate")
            if label.lower() in {"category", "type", "rate", "amount",
                                  "price", "cost", "fee"}:
                continue
            tier_label = f"{heading} · {label}"[:120] if heading else label[:120]
            tiers.append({
                "tier_label": tier_label,
                "price_gbp": price,
                "currency": currency,
                "is_early_bird": bool(re.search(
                    r"(?i)early[- ]?bird|super early", label
                )),
                "early_bird_deadline": None,
            })
        if len(tiers) >= max_tiers:
            break
    # Dedupe by (label, price)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in tiers:
        key = (t["tier_label"], t["price_gbp"])
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def html_has_pricing_tables(html: str) -> bool:
    """Cheap check for the audit: does this HTML contain at least one
    plain-number table under a fee-related heading? Returns True if
    at least 2 tiers WOULD be parsed. Used to escalate a MISSING
    verdict when the extractor emitted 0 tiers."""
    return len(parse_pricing_tables(html, max_tiers=3)) >= 2
