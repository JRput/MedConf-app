# extractors/abstract_classifier.py
"""
Deterministic abstract / poster / oral submission classifier.

Scans detail-page text for evidence that an event accepts abstract or poster
submissions, and parses the submission deadline when stated.

Returns (abstract_open: bool, abstract_deadline: Optional[date]).

Decision logic (in order):
  1. If page text contains "Abstract Submissions: Closed" / "Closed for
     submissions" / "Submissions have closed" → (False, None)
  2. If page mentions a deadline phrase ("deadline for submissions is X",
     "submission deadline: X", "submit by X") AND we can parse a date:
       - If the date is already in the past → (False, parsed_date)
       - Otherwise                          → (True,  parsed_date)
  3. If page only mentions abstract/poster/oral submission positively but no
     date can be parsed → (True, None)
  4. Otherwise (no abstract mention at all) → (False, None)
"""

from __future__ import annotations
import re
from datetime import date, datetime
from typing import Optional, Tuple


# Negative phrases — explicit "closed" or "deadline passed" statements
_CLOSED_PATTERNS = [
    r"abstract\s+submissions?\s+(?:are|is)?\s*(?:now\s+)?closed",
    r"submissions?\s+(?:are|is)\s+(?:now\s+)?closed",
    r"closed\s+for\s+submissions?",
    r"submissions?\s+have\s+closed",
    r"submissions?\s+closed",
    r"deadline\s+has\s+passed",
    r"submission\s+deadline\s+has\s+passed",
]
_CLOSED_RE = [re.compile(p, re.IGNORECASE) for p in _CLOSED_PATTERNS]

# Positive phrases — explicit mentions of accepting submissions
_OPEN_PATTERNS = [
    r"open\s+for\s+(?:abstract|poster|oral)?\s*submissions?",
    r"submissions?\s+(?:are|is)\s+(?:now\s+)?open",
    r"call\s+for\s+(?:abstracts?|posters?|papers?)",
    r"submit\s+(?:your|an?)\s+(?:abstract|poster|paper)",
    r"abstract\s+submission",
    r"poster\s+submission",
    r"oral\s+submission",
    r"(?:abstracts?|posters?)\s+(?:are|is|can\s+be)\s+(?:invited|welcomed?|accepted)",
]
_OPEN_RE = [re.compile(p, re.IGNORECASE) for p in _OPEN_PATTERNS]


# Date phrase extraction — look for the date PHRASE near a deadline keyword,
# then parse the phrase into a real date.
# The phrase capture is permissive (up to 60 chars) and we let the date parser
# pull out the actual day/month/year regardless of surrounding fluff.
_DEADLINE_CAPTURE_PATTERNS = [
    r"deadline\s+for\s+(?:submissions?|abstracts?|posters?)\s+is\s+([^.\n]{4,80})",
    r"(?:abstract|poster|submission)\s+(?:submission\s+)?deadline\s*[:\-]\s*([^.\n]{4,80})",
    r"submit\s+(?:your\s+)?(?:abstract|poster|paper)?\s*by\s+([^.\n]{4,80})",
    r"submissions?\s+close\s+(?:on\s+)?([^.\n]{4,80})",
    r"deadline\s*[:\-]\s*([^.\n]{4,80})",  # very generic — last resort
]
_DEADLINE_CAPTURE_RE = [re.compile(p, re.IGNORECASE) for p in _DEADLINE_CAPTURE_PATTERNS]


# Date-token extractor — pulls a "29 May 2026" / "29th May 2026" / "May 29 2026"
# from anywhere inside a phrase. Handles ordinal suffixes and day-of-week prefixes.
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+"
    r"(\d{1,2})\s*(?:st|nd|rd|th)?[,\s]+(\d{4})\b",
    re.IGNORECASE,
)
_NUMERIC_DMY_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b")  # 29/05/2026
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")                  # 2026-05-29


def _parse_date_phrase(phrase: str) -> Optional[date]:
    """Best-effort: parse a free-text fragment that might contain a date."""
    if not phrase:
        return None
    try:
        # 1. "29[th] May 2026" / "29 May 2026"
        m = _DAY_MONTH_YEAR_RE.search(phrase)
        if m:
            day = int(m.group(1))
            mon = _MONTHS.get(m.group(2).lower())
            year = int(m.group(3))
            if mon:
                return date(year, mon, day)
        # 2. "May 29, 2026" / "May 29 2026"
        m = _MONTH_DAY_YEAR_RE.search(phrase)
        if m:
            mon = _MONTHS.get(m.group(1).lower())
            day = int(m.group(2))
            year = int(m.group(3))
            if mon:
                return date(year, mon, day)
        # 3. "29/05/2026" — UK convention day-first
        m = _NUMERIC_DMY_RE.search(phrase)
        if m:
            day = int(m.group(1))
            mon = int(m.group(2))
            year = int(m.group(3))
            if 1 <= mon <= 12 and 1 <= day <= 31:
                return date(year, mon, day)
        # 4. ISO "2026-05-29"
        m = _ISO_RE.search(phrase)
        if m:
            year, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(year, mon, day)
    except (ValueError, TypeError):
        return None
    return None


def extract_abstract_info(
    page_text: str,
    today: Optional[date] = None,
) -> Tuple[bool, Optional[date]]:
    """Classify abstract submission status from a detail-page's text content."""
    if not page_text:
        return False, None
    today = today or date.today()

    # 1. Explicit "closed" wording takes precedence
    is_explicitly_closed = any(rx.search(page_text) for rx in _CLOSED_RE)

    # 2. Extract any deadline date mentioned near a submission keyword
    deadline: Optional[date] = None
    for rx in _DEADLINE_CAPTURE_RE:
        m = rx.search(page_text)
        if m:
            parsed = _parse_date_phrase(m.group(1))
            if parsed:
                deadline = parsed
                break

    # 3. Look for positive open-for-submissions wording
    has_open_signal = any(rx.search(page_text) for rx in _OPEN_RE)

    # 4. Decision
    # 4a. If explicitly closed, honour that regardless of other signals
    if is_explicitly_closed:
        return False, deadline
    # 4b. If a deadline is known and in the past → closed
    if deadline and deadline < today:
        return False, deadline
    # 4c. If a deadline is in the future → open
    if deadline and deadline >= today:
        return True, deadline
    # 4d. Positive language but no parseable date → open with null deadline
    if has_open_signal:
        return True, None
    # 4e. Default → not accepting submissions
    return False, None
