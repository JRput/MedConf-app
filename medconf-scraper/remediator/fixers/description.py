"""Description fixer — extract 30-50 word summary from source page.

Strategy:
  1. Heuristic: find "Overview" / "About" section and pull the first 2 paragraphs
  2. LLM: ask for a concise summary from the overview content
  3. Validate: 50-500 chars, no nav-leak patterns, no all-caps
"""

from __future__ import annotations
import json
import re
from typing import Callable, Optional, Tuple

_NAV_LEAK_RE = re.compile(
    r"(T \+44|W rcog\.org\.uk|Registered charity|Disclaimer:|Cookies:|"
    r"Join the conversation|Privacy Policy|Skip to main content|Log in / Register|"
    r"Limitations of use|@RC[A-Za-z]+|MyRCR|Copyright)",
)

_OVERVIEW_MARKERS = (
    "overview", "about this", "about the", "summary", "event description",
    "event summary", "key information",
)


def _extract_overview_paragraphs(text: str) -> str:
    """Find the first text chunk after an Overview-like heading."""
    tl = text.lower()
    for marker in _OVERVIEW_MARKERS:
        idx = tl.find(marker)
        if idx == -1:
            continue
        # Take ~1500 chars after the marker; stop at common end markers
        chunk = text[idx + len(marker): idx + len(marker) + 1500].strip()
        # Cut at next major section heading
        for end_marker in (
            "Are you going?", "Booking options", "How to book", "Register",
            "Agenda", "Key reasons to attend", "Acknowledgements", "Fees",
        ):
            ei = chunk.find(end_marker)
            if ei > 100:
                chunk = chunk[:ei]
                break
        return chunk.strip()
    # No overview marker found — return first 1500 chars of body
    return text[:1500]


def fix_description(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    if not page_text:
        return None, None

    chunk = _extract_overview_paragraphs(page_text)
    if not chunk or len(chunk) < 50:
        return None, None

    title = row.get("conference_name") or ""
    prompt = f"""Summarise this medical event in 30-50 words, using ONLY the supplied text.
Plain prose, no markdown, no headings.

EVENT TITLE: {title}

PAGE TEXT:
{chunk[:2500]}

Respond with ONLY the summary, nothing else."""

    raw = llm_call(prompt)
    if not raw:
        # Heuristic fallback: first 320 chars of the chunk
        candidate = chunk[:320].strip()
        if len(candidate) < 50:
            return None, None
        if _NAV_LEAK_RE.search(candidate):
            return None, None
        return candidate, "heuristic_overview"

    candidate = raw.strip().strip("`").strip()
    # Validate
    if len(candidate) < 50 or len(candidate) > 700:
        return None, None
    if _NAV_LEAK_RE.search(candidate):
        return None, None
    alphas = [c for c in candidate if c.isalpha()]
    if alphas and sum(1 for c in alphas if c.isupper()) / len(alphas) > 0.5:
        return None, None
    return candidate, "llm_overview"
