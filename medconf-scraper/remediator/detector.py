"""Detect rows with missing or inaccurate fields.

Returns a list of (conference_row, list_of_gap_field_names) tuples.

Gap detection is conservative — we DON'T treat the following as gaps:
- city / venue_name on online events (correctly null)
- end_date when start_date is present and the event is single-day
- pricing on events with explicit `pricing_genuinely_missing` markers
"""

from __future__ import annotations
from typing import List, Tuple


# Fields the remediator's fixers target. Order = priority — earlier fields
# usually unlock the later ones (e.g. fixing description helps specialty).
TARGETED_FIELDS = (
    "description",
    "venue_name",
    "city",
    "event_format",
    "cpd_points",
    "specialty",
    "pricing",         # special — checked via pricing_tiers join, not column
    "abstract_status", # special — composite check on abstract_open/deadline
)


def is_online(row: dict) -> bool:
    return (row.get("event_format") or "").lower() == "online"


def detect_gaps(
    row: dict,
    has_pricing: bool,
    *,
    expected_specialties: set | None = None,
) -> List[str]:
    """Return list of field names that are gaps for THIS row.

    Context-aware: doesn't flag city/venue on online events, doesn't flag
    pricing if the row is on-demand (where pricing is checked differently).
    """
    gaps: List[str] = []

    # Description: null OR shorter than 60 chars (likely a stub)
    desc = (row.get("description") or "").strip()
    if not desc or len(desc) < 60:
        gaps.append("description")

    # Venue / city — only if format is in-person/hybrid (or not yet set)
    fmt = (row.get("event_format") or "").lower()
    if fmt in ("in_person", "hybrid", ""):
        if not row.get("venue_name"):
            gaps.append("venue_name")
        if not row.get("city"):
            gaps.append("city")

    # Event format unset entirely
    if not row.get("event_format"):
        gaps.append("event_format")

    # CPD — only if cpd_accredited is True or unknown
    if row.get("cpd_accredited") is not False and row.get("cpd_points") is None:
        gaps.append("cpd_points")

    # Specialty — null OR not in the expected set for this source's society
    spec = (row.get("specialty") or "").strip()
    if not spec:
        gaps.append("specialty")
    elif expected_specialties and spec not in expected_specialties:
        gaps.append("specialty")  # wrong specialty for this society

    # Pricing — if no pricing rows exist and the row isn't free/known-no-pricing
    if not has_pricing and not row.get("is_on_demand"):
        gaps.append("pricing")

    # Abstract status — composite check
    if row.get("abstract_open") and not row.get("abstract_deadline") \
            and not row.get("abstract_deadline_note"):
        gaps.append("abstract_status")

    return gaps


def detect_gaps_for_rows(
    rows: List[dict],
    pricing_by_conf: dict,
    *,
    expected_specialties: set | None = None,
) -> List[Tuple[dict, List[str]]]:
    """Batch wrapper. Returns only rows that have at least one gap."""
    out: List[Tuple[dict, List[str]]] = []
    for r in rows:
        has_pricing = bool(pricing_by_conf.get(r["id"]))
        gaps = detect_gaps(r, has_pricing,
                           expected_specialties=expected_specialties)
        if gaps:
            out.append((r, gaps))
    return out
