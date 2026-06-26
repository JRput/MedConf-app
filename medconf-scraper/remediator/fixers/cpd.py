"""CPD points fixer."""

from __future__ import annotations
import re
from typing import Callable, Optional, Tuple


def fix_cpd_points(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[int], Optional[str]]:
    if not page_text:
        return None, None
    # Pattern bank — most-specific first
    patterns = [
        r"(\d{1,3})\s*CPD\s*(?:credits?|points?)\b",
        r"(\d{1,3})[- ]CPD\s*(?:credits?|points?)\b",
        r"accredited\s+for\s+(\d{1,3})\s*(?:CPD\s*)?(?:credits?|points?)",
        r"earn\s+(?:up\s+to\s+)?(\d{1,3})\s*CPD",
        r"(\d{1,3})\+\s*CPD",
    ]
    for pat in patterns:
        m = re.search(pat, page_text, re.I)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 200:
                    return n, "heuristic_regex"
            except ValueError:
                continue
    return None, None
