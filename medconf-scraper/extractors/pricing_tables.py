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

import money
from logger import logger


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


# Currency detection / amount parsing live in money.py (ticket A1, 2026-10-27).
# Nothing in this module defaults a currency: a table whose currency cannot be
# detected from its heading / table text / price cells is DROPPED with a warning
# unless the caller passes an explicit non-empty `default_currency`.


def _clean(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


_CELL_LEFTOVER_RE = re.compile(
    r"(?i)[\s*+\u2020\u2021]*(?:\(?\s*(?:\+|plus|excl\.?|incl\.?|ex\.?|inc\.?)?\s*(?:vat|tax)\s*\)?)?[\s*+\u2020\u2021]*")


def _cell_money(cell: str) -> Optional[money.Money]:
    """The single price a table cell holds ('1 200,00', '550.00', '1.500 EUR', '£1,234.50',
    'S$465') or None. Ranges, labels with prose, zero and implausible amounts are not prices."""
    if not cell:
        return None
    m = money.parse_amount(cell)
    if m is None or m.high is not None:
        return None
    leftover = cell[:m.span[0]] + cell[m.span[1]:]
    if not _CELL_LEFTOVER_RE.fullmatch(leftover):
        return None
    if not (m.amount > 0 and money.plausible(m.amount, m.currency)):
        return None
    return m


def _parse_price(cell: str) -> Optional[float]:
    """Parse "1 200,00", "550.00", "1.500 EUR", "50", "£1,234.50" -> float (None if not a price)."""
    m = _cell_money(cell)
    return m.amount if m else None


def _detect_currency(context: str, default: str = "") -> str:
    """Given a section heading + nearby text, the currency it EVIDENCES, else `default`
    (which is empty unless the caller passes one deliberately)."""
    return _currency_hint(context) or default


def _currency_hint(context: str) -> Optional[str]:
    return money.detect_currency(context)


def _cells_currency(cell_texts: List[str]) -> Optional[str]:
    """Currency written in the price cells themselves ('550 EUR', '£120',
    '$1,295', 'S$465'), by majority. IUSTI 2026 (2026-10-14): the only EUR marker on
    the page was the cell suffix, beyond the heading/first-800-chars window,
    so the remediator dropped a complete 16-tier grid as 'unknown currency'."""
    votes: Dict[str, int] = {}
    for t in cell_texts:
        if not t:
            continue
        m = money.parse_amount(t)
        if m is None or not m.currency or m.high is not None:
            continue
        votes[m.currency] = votes.get(m.currency, 0) + 1
    if not votes:
        return None
    return max(votes, key=votes.get)


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


_COL_HEADER_RE = re.compile(
    r"(?i)\b(?:early|regular|standard|late|on-?site|advance|member|non-?member|until|from|before|after|"
    r"deadline|student|resident|trainee|delegate|bird|rate|fee|price|virtual|in-?person|online|day)\b")
_MONTH_NAME_RE = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
                  r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_COL_DEADLINE_RE = re.compile(
    rf"(?i)(?:until|by|before|through|up to|ends?|closes?)\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME_RE})\.?,?\s+(20\d\d)"
    rf"|(?:until|by|before|through|up to|ends?|closes?)\s+({_MONTH_NAME_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)")
_MONTH_NUM = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _fee_columns(row_cells: List[List[str]]) -> Dict[int, Dict[str, Any]]:
    """{cell_index: {name, early, deadline}} when the first row is a header of
    >= 2 fee-timeframe / category columns and no price; else {}."""
    if not row_cells:
        return {}
    header = row_cells[0]
    if len(header) < 3 or any(_parse_price(c) is not None for c in header[1:] if c):
        return {}
    cols: Dict[int, Dict[str, Any]] = {}
    for k, text in enumerate(header):
        if k == 0 or not text or not _COL_HEADER_RE.search(text):
            continue
        name = re.split(r"(?i)\s+(?:until|from|by|before|through|up to|after|starting)\b", text, 1)[0]
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip(" :-–")[:40] or text[:40]
        deadline = None
        m = _COL_DEADLINE_RE.search(text)
        if m:
            try:
                if m.group(1):
                    deadline = f"{int(m.group(3))}-{_MONTH_NUM[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
                else:
                    deadline = f"{int(m.group(6))}-{_MONTH_NUM[m.group(4)[:3].lower()]:02d}-{int(m.group(5)):02d}"
            except (KeyError, ValueError):
                deadline = None
        cols[k] = {"name": name.title() if name.isupper() else name,
                   "early": bool(re.search(r"(?i)early|advance", text)), "deadline": deadline}
    return cols if len(cols) >= 2 else {}


def parse_pricing_tables(
    html: str,
    *,
    default_currency: str = "",
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
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        row_cells = [[_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)] for row in rows]

        # Detect currency from heading + first 800 chars of table (may
        # contain "(EUR)" after column header), else from the cells.
        currency_ctx = (heading or "") + " " + table_html[:800]
        currency = (_currency_hint(currency_ctx)
                    or _cells_currency([c for cells in row_cells for c in cells[1:]])
                    or default_currency)
        if not currency:
            logger.warning(
                f"pricing_tables: fee table under {heading!r} has no detectable currency "
                f"(no code/symbol in heading, table text or price cells) - dropped, not defaulted")
            continue

        # Column headers of a fee GRID (Early / Regular / Late, Member /
        # Non-member ...): one tier per price cell, labelled with its column,
        # early-bird flag + deadline from the column text. A table with a
        # single price column keeps the old last-cell behaviour.
        columns = _fee_columns(row_cells)

        for cells in row_cells:
            if len(cells) < 2:
                continue
            label = cells[0]
            if not label:
                continue
            # Skip label-only rows (header row is: "Category | Rate")
            if label.lower() in {"category", "type", "rate", "amount",
                                  "price", "cost", "fee"}:
                continue
            section = f"{heading} · {label}"[:120] if heading else label[:120]
            if columns:
                for k, col in columns.items():
                    if k >= len(cells):
                        continue
                    p = _parse_price(cells[k]) if cells[k] else None
                    if p is None:
                        continue
                    tiers.append({
                        "tier_label": f"{section} · {col['name']}"[:120],
                        "price_gbp": p,
                        "currency": currency,
                        "is_early_bird": col["early"] or bool(re.search(r"(?i)early[- ]?bird|super early", label)),
                        "early_bird_deadline": col["deadline"],
                    })
                continue
            # Try LAST cell first (typical price column), then walk left
            price: Optional[float] = None
            for cell_text in reversed(cells[1:]):
                if not cell_text:
                    continue
                p = _parse_price(cell_text)
                if p is not None:
                    price = p
                    break
            if price is None:
                continue
            tiers.append({
                "tier_label": section,
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
