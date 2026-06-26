"""Abstract submission status fixer.

Strategy:
  1. Search the WHOLE page text for deadline-anchor phrases ("deadline for
     submissions", "submission deadline", "abstract deadline", "closing
     date", "submissions close on", "submit your abstract by")
  2. In a small window around each anchor, parse a date — supporting:
       - ordinals: "7th July", "14th September"
       - full date: "26 March 2026", "March 26, 2026"
       - DD/MM/YYYY: "26/03/2026"
       - year-less: assume current year, roll to next if past
  3. Also check for explicit closed wording across the whole text
  4. Validate the parsed deadline against today
"""

from __future__ import annotations
import re
from datetime import date
from typing import Callable, Optional, Tuple

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# "(?:st|nd|rd|th)" handles "1st", "2nd", "3rd", "7th"
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(20\d{2}))?\b",
    re.I,
)
_MONTH_DAY_RE = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b",
    re.I,
)
_DMY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")

_DEADLINE_ANCHORS = (
    r"deadline\s+for\s+(?:abstract\s+)?submissions?",
    r"(?:abstract\s+)?submissions?\s+deadline",
    r"abstract\s+deadline",
    r"closing\s+date\s+for\s+(?:abstract\s+)?submissions?",
    r"submissions?\s+close\s+on",
    r"submit\s+your\s+abstract\s+by",
    r"abstract\s+submission\s+closes?\s+on",
    r"submissions?\s+(?:are\s+)?(?:now\s+)?open\s+until",
)

_CLOSED_PATTERNS = (
    r"submissions?\s+(?:are\s+)?(?:now\s+)?closed",
    r"closing\s+date\s+has\s+passed",
    r"submission\s+(?:period\s+)?(?:has\s+)?ended",
    r"no\s+longer\s+accepting\s+(?:abstracts?|submissions?)",
    r"abstract\s+submissions?\s+(?:are\s+|is\s+)?closed",
)

_OPEN_PATTERNS = (
    r"submissions?\s+(?:are\s+)?(?:now\s+)?open",
    r"(?:we\s+are\s+)?(?:now\s+)?accepting\s+abstracts",
    r"abstract\s+submissions?\s+(?:are\s+|is\s+)?(?:now\s+)?open",
    r"call\s+for\s+abstracts\s+(?:is\s+|are\s+)?(?:now\s+)?open",
)


def _parse_date_in_window(window: str, today_year: int) -> Optional[str]:
    """Find the closest plausible date in the window. Year-less dates get
    the current year, or next year if that would land in the past."""
    # Try DD/MM/YYYY
    m = _DMY_RE.search(window)
    if m:
        try:
            return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        except ValueError:
            pass
    # Try DD [ordinal] Month [Year]
    for m in _DAY_MONTH_RE.finditer(window):
        day_str = m.group(1)
        month_str = m.group(2).lower()
        year_str = m.group(3)
        mon = _MONTHS.get(month_str) or _MONTHS.get(month_str[:3])
        if not mon:
            continue
        try:
            d = int(day_str)
        except ValueError:
            continue
        if not (1 <= d <= 31):
            continue
        year = int(year_str) if year_str else today_year
        iso = f"{year:04d}-{mon:02d}-{d:02d}"
        # If year was inferred and the resulting date is well in the past,
        # try next year (handles "Tuesday 7th July" written in June)
        if not year_str and iso < date.today().isoformat():
            iso = f"{year + 1:04d}-{mon:02d}-{d:02d}"
        return iso
    # Try Month [ordinal] Day [Year]
    for m in _MONTH_DAY_RE.finditer(window):
        month_str = m.group(1).lower()
        day_str = m.group(2)
        year_str = m.group(3)
        mon = _MONTHS.get(month_str) or _MONTHS.get(month_str[:3])
        if not mon:
            continue
        try:
            d = int(day_str)
        except ValueError:
            continue
        if not (1 <= d <= 31):
            continue
        year = int(year_str) if year_str else today_year
        iso = f"{year:04d}-{mon:02d}-{d:02d}"
        if not year_str and iso < date.today().isoformat():
            iso = f"{year + 1:04d}-{mon:02d}-{d:02d}"
        return iso
    return None


def fix_abstract_status(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[dict], Optional[str]]:
    """Return dict of fields to patch (subset of: abstract_open,
    abstract_deadline, abstract_deadline_note) or (None, None)."""
    if not page_text:
        return None, None

    text_l = page_text.lower()

    # No abstract mention at all → confirm closed
    if "abstract" not in text_l:
        return {"abstract_open": False}, "no_abstract_mention"

    # 1. Explicit-closed wording wins outright
    for pat in _CLOSED_PATTERNS:
        m = re.search(pat, text_l)
        if m:
            # Take a window around the match for date parsing
            window = page_text[max(0, m.start() - 100): m.end() + 300]
            deadline = _parse_date_in_window(window, date.today().year)
            result = {"abstract_open": False}
            if deadline:
                result["abstract_deadline"] = deadline
            return result, "explicit_closed"

    # 2. Look for deadline anchors and parse the date in a small window
    today_year = date.today().year
    best_deadline: Optional[str] = None
    best_method: str = ""
    for pat in _DEADLINE_ANCHORS:
        for m in re.finditer(pat, text_l):
            # Look in BOTH directions — sometimes the date precedes the anchor
            # ("Tuesday 7th July - Deadline for submissions").
            window = page_text[max(0, m.start() - 150): m.end() + 300]
            d = _parse_date_in_window(window, today_year)
            if d:
                best_deadline = d
                best_method = "deadline_anchor"
                break
        if best_deadline:
            break

    if best_deadline:
        if best_deadline < date.today().isoformat():
            return {"abstract_open": False, "abstract_deadline": best_deadline}, "past_deadline"
        return {"abstract_open": True, "abstract_deadline": best_deadline}, "future_deadline"

    # 3. Open wording without a date — curator note
    for pat in _OPEN_PATTERNS:
        if re.search(pat, text_l):
            return {
                "abstract_open": True,
                "abstract_deadline_note": "see event page for details",
            }, "open_no_date"

    return None, None
