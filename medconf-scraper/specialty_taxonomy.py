"""
specialty_taxonomy.py

Python side of the specialty taxonomy that medconf-website/src/lib/taxonomy/
specialties.ts defines. TS stays the SOURCE OF TRUTH (W2a's taxonomy work);
`npm run taxonomy:export` (medconf-website/scripts/export-taxonomy.ts)
generates specialties.json alongside it, and this module just reads that
JSON rather than hand-maintaining a second copy of the map in Python.

Why this exists: W6 onboarding now stores the canonical PARENT SLUG (e.g.
"oncology") in user_profiles.specialty instead of a raw conferences.specialty
string. fire_specialty_alerts.py was still doing
`.ilike("specialty", profile_specialty)` directly against the raw DB column
— a slug like "oncology" happens to still substring-match the raw value
"Oncology" (ilike is case-insensitive), but a multi-word parent like
"general-practice" or "msk-trauma-orthopaedics" never matches ANY raw value
("General Practice" has a space, not a hyphen) and would silently stop
firing alerts for those users. This module expands a slug (or a legacy raw
label from before W6, for users who onboarded before this change) into
every raw value that should match, for use with `.in_(...)` instead of
`.ilike(...)`.
"""

import json
import os
from functools import lru_cache
from typing import Optional

_JSON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "medconf-website",
    "src",
    "lib",
    "taxonomy",
    "specialties.json",
)


class TaxonomyLoadError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load + cache specialties.json for the lifetime of the process.

    Raises TaxonomyLoadError rather than letting a bare FileNotFoundError/
    JSONDecodeError propagate, so callers get one clear error message
    pointing at the fix (re-run the export script) instead of a confusing
    traceback deep in a cron job.
    """
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise TaxonomyLoadError(
            f"specialties.json not found at {_JSON_PATH}. "
            "Run `npm run taxonomy:export` in medconf-website/ to generate it."
        )
    except json.JSONDecodeError as e:
        raise TaxonomyLoadError(f"specialties.json at {_JSON_PATH} is not valid JSON: {e}")

    if "rawToCanonical" not in data or "parents" not in data:
        raise TaxonomyLoadError(
            f"specialties.json at {_JSON_PATH} is missing expected keys "
            "(rawToCanonical/parents) — re-run `npm run taxonomy:export`."
        )
    return data


def _raw_to_canonical() -> dict:
    return _load()["rawToCanonical"]


@lru_cache(maxsize=1)
def _raw_to_canonical_lower() -> dict:
    """Case-insensitive view, mirroring canonicalSpecialty()'s fallback in
    specialties.ts — a stray casing difference should never silently fall
    through to "no match" here any more than it does on the website."""
    return {k.lower(): v for k, v in _raw_to_canonical().items()}


@lru_cache(maxsize=1)
def _parent_slugs() -> set:
    return {p["slug"] for p in _load()["parents"]}


def canonical_parent(value: Optional[str]) -> Optional[str]:
    """Resolve `value` (a parent slug OR a legacy raw label) to a parent slug.

    Order of precedence:
      1. Already a valid parent slug -> itself.
      2. A raw label (case-insensitive) that maps to a parent -> that parent.
      3. Unrecognised -> None.
    """
    if not value:
        return None
    if value in _parent_slugs():
        return value
    mapped = _raw_to_canonical_lower().get(value.lower())
    return mapped


def raw_values_for(parent_slug: str) -> list:
    """Every raw conferences.specialty value that canonicalises to `parent_slug`."""
    return [raw for raw, parent in _raw_to_canonical().items() if parent == parent_slug]


def raw_values_for_profile_specialty(value: Optional[str]) -> list:
    """Expand a `user_profiles.specialty` value — slug (post-W6) or legacy raw
    label (pre-W6) — into the full list of raw conferences.specialty values
    to match against, by `.in_(...)`.

    Legacy raw labels get mapped to their parent FIRST (per the team lead's
    instruction), so a user still stored as "Medical Leadership" matches
    every raw value under that parent (including its sibling "Leadership &
    Management"), not just its own literal string — consistent with how a
    slug-stored user would match.

    Returns [] when `value` is unmapped/unrecognised (e.g. "other", None,
    or empty) — callers should treat an empty list as "no matches", not
    fall back to matching everything.
    """
    parent = canonical_parent(value)
    if not parent or parent == "other":
        return []
    return raw_values_for(parent)
