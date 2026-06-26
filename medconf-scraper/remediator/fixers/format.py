"""Event format fixer — online / in_person / hybrid."""

from __future__ import annotations
import re
from typing import Callable, Optional, Tuple


def fix_event_format(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    if not page_text:
        return None, None
    text = page_text[:8000].lower()
    has_online = bool(re.search(
        r"\b(online|virtual|webinar|live\s*stream|livestream|zoom|teams|remote|on-demand)\b",
        text,
    ))
    has_in_person = bool(re.search(
        r"\b(in[- ]person|on[- ]site|onsite|face[- ]to[- ]face|attend\s+in[- ]person)\b",
        text,
    ))
    has_hybrid = bool(re.search(r"\bhybrid\b", text))

    if has_hybrid or (has_online and has_in_person):
        return "hybrid", "heuristic_keywords"
    if has_online:
        return "online", "heuristic_keywords"
    if has_in_person:
        return "in_person", "heuristic_keywords"

    # Venue presence implies in-person
    if row.get("venue_name") or row.get("city"):
        return "in_person", "heuristic_venue_implies"

    return None, None
