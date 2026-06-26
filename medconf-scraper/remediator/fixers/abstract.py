"""Abstract submission status fixer.

The most-common gap is "open with no deadline AND no note" — extractor
hard-coded open=true without verifying. We:
  1. Look for explicit "submissions closed" wording
  2. Parse deadline date if present
  3. Validate against today
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


def _parse_deadline_date(text: str) -> Optional[str]:
    m = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})\b", text,
    )
    if m:
        d = int(m.group(1))
        mon = _MONTHS.get(m.group(2).lower()) or _MONTHS.get(m.group(2)[:3].lower())
        y = int(m.group(3))
        if mon:
            return f"{y:04d}-{mon:02d}-{d:02d}"
    return None


def fix_abstract_status(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[dict], Optional[str]]:
    """Return a dict of fields to patch — could be:
      {"abstract_open": False}
      {"abstract_open": True, "abstract_deadline": "2026-09-01"}
      {"abstract_open": True, "abstract_deadline_note": "..."}
    """
    if not page_text:
        return None, None

    text_l = page_text.lower()

    # Find abstract-relevant section first to avoid matching on unrelated dates
    if "abstract" not in text_l:
        # No abstract content at all → confirm closed (clear inconsistency)
        return {"abstract_open": False}, "no_abstract_mention"

    # Look in a window around the first "abstract" mention
    idx = text_l.find("abstract")
    window = page_text[max(0, idx - 100): idx + 2000]
    window_l = window.lower()

    # 1. Explicit closed wording wins
    if re.search(
        r"submissions?\s+(?:are\s+)?(?:now\s+)?closed|"
        r"closing\s+date\s+has\s+passed|"
        r"submission\s+(?:period\s+)?ended|"
        r"no\s+longer\s+accepting",
        window_l,
    ):
        deadline = _parse_deadline_date(window)
        result = {"abstract_open": False}
        if deadline:
            result["abstract_deadline"] = deadline
        return result, "explicit_closed"

    # 2. Deadline date
    deadline = _parse_deadline_date(window)
    if deadline:
        if deadline < date.today().isoformat():
            return {"abstract_open": False, "abstract_deadline": deadline}, "past_deadline"
        return {"abstract_open": True, "abstract_deadline": deadline}, "future_deadline"

    # 3. Explicit open wording with no date → curator note
    if re.search(
        r"submissions?\s+(?:are\s+)?(?:now\s+)?open|"
        r"(?:we\s+are\s+)?(?:now\s+)?accepting\s+abstracts",
        window_l,
    ):
        return {
            "abstract_open": True,
            "abstract_deadline_note": "see event page for details",
        }, "open_no_date"

    return None, None
