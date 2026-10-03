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
from typing import List, Optional, Tuple


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


# ---------------------------------------------------------------------------
# Submission programmes that are not literally "abstracts" (added 2026-10-04,
# Mission P4 — BSH International Pathology Day poster competition).
# ---------------------------------------------------------------------------
_PROGRAMME_PATTERNS = [
    (r"poster\s+competitions?", "Poster competition"),
    (r"submit\s+(?:\w+\s+){0,2}?posters?\b", "Poster submissions"),
    (r"posters?\s+submissions?", "Poster submissions"),
    (r"case[\s-]+reports?\s+(?:competition|prize|submissions?)", "Case report competition"),
    (r"call\s+for\s+cases", "Call for cases"),
    (r"trainee\s+prize[^.\n]{0,160}?\bsubmi(?:t|ssion)", "Trainee prize"),
    (r"submi(?:t|ssion)[^.\n]{0,160}?\btrainee\s+prize", "Trainee prize"),
]
_PROGRAMME_RE = [(re.compile(p, re.IGNORECASE), label) for p, label in _PROGRAMME_PATTERNS]

# Deadline phrasings, applied only inside a window around a programme mention
# (so "no later than" about registration elsewhere on the page is ignored).
_PROGRAMME_DEADLINE_PATTERNS = [
    r"(?:competition|submissions?|entries|posters?|abstracts?|case\s+reports?)\s+(?:will\s+)?clos(?:es|e|ing)\b([^.\n]{4,100})",
    r"deadline\s+for\s+(?:\w+\s+){0,2}?(?:submissions?|entries|abstracts?|posters?)\s*(?:is|:|-|\u2013)?\s*([^.\n]{4,100})",
    r"(?:closing\s+date|deadline)\s*(?:for\s+(?:\w+\s+){0,2}?)?(?:is|:|-|\u2013)\s*([^.\n]{4,100})",
    r"submi(?:t|tted|ssions?)\s+(?:\w+\s+){0,5}?by\s+([^.\n]{4,100})",
    r"entries\s+(?:must\s+be\s+)?(?:received\s+|submitted\s+)?by\s+([^.\n]{4,100})",
    r"no\s+later\s+than\s+([^.\n]{4,100})",
]
_PROGRAMME_DEADLINE_RE = [re.compile(p, re.IGNORECASE) for p in _PROGRAMME_DEADLINE_PATTERNS]

_PROGRAMME_OPEN_RE = re.compile(
    r"(?:submissions?|entries|competition|call\s+for\s+\w+)\s+(?:is\s+|are\s+)?(?:now\s+)?open\b"
    r"|now\s+open\s+for\s+(?:\w+\s+){0,2}?(?:submissions?|entries)"
    r"|open\s+for\s+(?:\w+\s+){0,2}?(?:submissions?|entries)",
    re.IGNORECASE,
)

_MONTH_ALT = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
              r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
# Year-less: "7th November" / "7 of November" / "November 7th"
_DAY_MONTH_NOYEAR_RE = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_ALT + r"\b(?!\s*,?\s*\d{4})",
    re.IGNORECASE)
_MONTH_DAY_NOYEAR_RE = re.compile(
    r"\b" + _MONTH_ALT + r"\s+(\d{1,2})\s*(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})(?!:)",
    re.IGNORECASE)


def _resolve_yearless(mon: int, day: int, today: date,
                      event_start: Optional[date]) -> Optional[date]:
    """Next occurrence of mon/day on or after today; if that lands after the
    event starts, the deadline must be the occurrence before the event."""
    try:
        cand = date(today.year, mon, day)
        if cand < today:
            cand = date(today.year + 1, mon, day)
        if event_start and cand > event_start:
            cand = date(event_start.year, mon, day)
            if cand > event_start:
                cand = date(event_start.year - 1, mon, day)
        return cand
    except ValueError:
        return None


def _parse_date_phrase_flex(phrase: str, today: date,
                            event_start: Optional[date]) -> Optional[date]:
    d = _parse_date_phrase(phrase)
    if d:
        return d
    for rx, mi, di in ((_DAY_MONTH_NOYEAR_RE, 2, 1), (_MONTH_DAY_NOYEAR_RE, 1, 2)):
        m = rx.search(phrase)
        if not m:
            continue
        mon_txt = m.group(mi)
        if mon_txt.lower() == "may" and mon_txt != "May" and rx is _MONTH_DAY_NOYEAR_RE:
            continue  # lowercase "may 5 posters" is a verb, not a month
        mon = _MONTHS.get(mon_txt.lower())
        if mon:
            return _resolve_yearless(mon, int(m.group(di)), today, event_start)
    return None


def _find_programme(page_text: str) -> Tuple[Optional[str], List[str]]:
    """Return (label of first programme matched, text windows around matches)."""
    label: Optional[str] = None
    windows: List[str] = []
    for rx, lab in _PROGRAMME_RE:
        for m in rx.finditer(page_text):
            label = label or lab
            windows.append(page_text[max(0, m.start() - 200): m.end() + 900])
    return label, windows


def classify_submission(
    page_text: str,
    today: Optional[date] = None,
    event_start: Optional[date] = None,
) -> Tuple[bool, Optional[date], Optional[str]]:
    """Full classifier: (abstract_open, abstract_deadline, abstract_deadline_note).

    Covers abstracts plus poster / case-report / trainee-prize programmes.
    Conservative: open=True needs a future deadline or explicit "open" wording
    for a programme. A programme with no date yields open=False plus a short
    curator note, never an invented date.
    """
    if not page_text:
        return False, None, None
    today = today or date.today()
    prog_label, prog_windows = _find_programme(page_text)
    # Guard (see 2026-08-16 note): pages with no abstract/poster/programme wording
    # cannot have a submission window (application-deadline false positives).
    if not prog_label and not re.search(r"abstract|poster|call for papers", page_text, re.I):
        return False, None, None

    is_explicitly_closed = any(rx.search(page_text) for rx in _CLOSED_RE)

    deadline: Optional[date] = None
    for rx in _DEADLINE_CAPTURE_RE:
        m = rx.search(page_text)
        if m:
            parsed = _parse_date_phrase(m.group(1))
            if parsed:
                deadline = parsed
                break
    if deadline is None and prog_windows:
        for w in prog_windows:
            for rx in _PROGRAMME_DEADLINE_RE:
                for m in rx.finditer(w):
                    parsed = _parse_date_phrase_flex(m.group(1), today, event_start)
                    if parsed:
                        deadline = parsed
                        break
                if deadline:
                    break
            if deadline:
                break

    if is_explicitly_closed:
        return False, deadline, None
    if deadline and deadline < today:
        return False, deadline, None
    if deadline:
        return True, deadline, None
    if prog_label:
        explicit_open = any(_PROGRAMME_OPEN_RE.search(w) for w in prog_windows)
        note = f"{prog_label} \u2014 see page for submission date"
        return explicit_open, None, note
    return False, None, None


def extract_abstract_info(
    page_text: str,
    today: Optional[date] = None,
) -> Tuple[bool, Optional[date]]:
    """Classify abstract submission status (2-tuple API used by most extractors)."""
    is_open, deadline, _note = classify_submission(page_text, today)
    return is_open, deadline
