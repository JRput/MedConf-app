"""Specialty fixer.

Strategy:
  1. Per-society constraint set — if the society has a single canonical
     specialty (RCEM → Emergency Medicine, RCOG → Obstetrics & Gynaecology),
     use it without question
  2. Existing classify_specialty() heuristic on title + page text
  3. LLM with constrained allowed-specialty list as a final attempt
"""

from __future__ import annotations
from typing import Callable, Optional, Tuple

SOCIETY_DEFAULT_SPECIALTY = {
    "RCEM": "Emergency Medicine",
    "RCOG": "Obstetrics & Gynaecology",
    "RCR": "Radiology",
    "RCPCH": "Paediatrics",
    "RCPsych": "Psychiatry",
    "RCoA": "Anaesthesia",
    "RCPath": "Pathology",
    "RCOphth": "Ophthalmology",
}

# Multi-discipline societies — known set of allowed values
SOCIETY_ALLOWED_SPECIALTIES = {
    "RCGP": {"General Practice", "GP Training"},
    "RCSEng": {"General Surgery", "Cardiothoracic Surgery",
               "Orthopaedic Surgery", "ENT", "Plastic Surgery",
               "Urology", "Vascular Surgery", "Paediatric Surgery",
               "Neurosurgery", "Trauma & Orthopaedics"},
    "RSM": None,  # too broad — many specialties
    "RCP": None,  # broad
}


def fix_specialty(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
    *,
    society: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    # 1. Society default — single-discipline colleges
    if society and society in SOCIETY_DEFAULT_SPECIALTY:
        return SOCIETY_DEFAULT_SPECIALTY[society], "society_default"

    title = row.get("conference_name") or ""
    if not page_text and not title:
        return None, None

    # 2. Existing classifier on title + page
    try:
        from extractors.specialty_classifier import classify_specialty
        guess = classify_specialty(title, page_text)
        if guess:
            return guess, "title_classifier"
    except Exception:
        pass

    # 3. LLM with strict constraint
    allowed = SOCIETY_ALLOWED_SPECIALTIES.get(society) if society else None
    constraint = (
        f"Pick ONE specialty from this allowed set: {sorted(allowed)}"
        if allowed
        else "Return a single canonical medical specialty (e.g. Cardiology, Emergency Medicine)"
    )
    prompt = f"""Identify the primary clinical specialty for this event.

TITLE: {title}
PAGE TEXT (excerpt):
{(page_text or '')[:2500]}

{constraint}

Respond with ONLY the specialty name. If you cannot tell, respond: null"""

    raw = llm_call(prompt)
    if not raw or raw.strip().lower() in ("null", "none", "n/a", "unknown"):
        return None, None
    candidate = raw.strip().strip("`\"'").strip()
    if not candidate or len(candidate) > 80:
        return None, None
    if allowed and candidate not in allowed:
        return None, None
    return candidate, "llm_constrained"
