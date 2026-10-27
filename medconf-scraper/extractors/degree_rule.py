"""ONE Python home of the degree-programme title rule.

Must stay IDENTICAL to public.is_degree_title in
supabase/migrations/20261027000000_event_type_degree.sql (Postgres `\\y` == Python
`\\b`, `''` == `'`). test_degree_type.py loads the SQL file and asserts both
patterns are equal, so the two copies cannot drift.
"""
import re
from typing import Optional

INCLUDE_PATTERN = (
    r"(\b(m\.?sc|b\.?sc|mres|mphil|phd|dphil|mba|mph|pgcert|pgdip)\b"
    r"|\bpostgraduate\s+(certificate|diploma)\b"
    r"|\bdiploma\s+in\b"
    r"|\badvanced\s+certificate\s+in\b"
    r"|\bcertificate\s+in\b.*\blevel\s*7\b"
    r"|\bmaster'?s?\s+(of|in)\b"
    r"|\bbachelors?\s+of\b"
    r"|\bdoctorate\s+(in|of)\b)"
)
EXCLUDE_PATTERN = (
    r"(\b(ceremon\w*|graduation|awards?|prepar\w*|revision|exam\w*|mock|osce|symposium|congress|conference|webinar|lecture|open\s+day|viva|workshop|open\s+evening|info(rmation)?\s+(session|evening)|alumni|interview|live\s+20\d\d|networking|taster|masterclass)\b"
    r"|\bfor\s+the\s+diploma\b"
    r"|,\s*(md|do|mph|mba|phd|msc|mres|mphil|dphil|pgcert|pgdip|facs|frcp|frcs|frca|mrcp|mrcs|rn|bds)\b)"
)
_INCLUDE = re.compile(INCLUDE_PATTERN, re.I)
_EXCLUDE = re.compile(EXCLUDE_PATTERN, re.I)


def is_degree_title(title: Optional[str]) -> bool:
    t = title or ""
    return bool(_INCLUDE.search(t)) and not _EXCLUDE.search(t)
