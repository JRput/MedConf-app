# validator.py
"""Data validation - validates extracted conference data before database insertion."""

from datetime import datetime
from typing import Dict, Any, List

REQUIRED_FIELDS = ["conference_name", "source_url"]


def validate_conference(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates a single conference record.
    
    Returns: { 'valid': bool, 'data': cleaned_data, 'warnings': [str] }
    """
    warnings: List[str] = []
    cleaned = data.copy()

    # Check required fields
    for field in REQUIRED_FIELDS:
        if not cleaned.get(field):
            return {
                "valid": False,
                "data": None,
                "warnings": [f"Missing required field: {field}"]
            }

    # Validate and parse dates
    for date_field in ["start_date", "end_date", "abstract_deadline", "on_demand_original_date"]:
        val = cleaned.get(date_field)
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except (ValueError, TypeError):
                warnings.append(f"Invalid date format for {date_field}: '{val}' — set to null")
                cleaned[date_field] = None

    # Validate pricing tiers
    tiers = cleaned.get("pricing_tiers", [])
    valid_tiers: List[Dict[str, Any]] = []
    
    for t in tiers:
        if t.get("tier_label") and t.get("price_gbp") is not None:
            try:
                t["price_gbp"] = float(t["price_gbp"])
                valid_tiers.append(t)
            except (ValueError, TypeError):
                warnings.append(f"Invalid price for tier '{t.get('tier_label')}' — skipped")
        else:
            warnings.append(f"Incomplete pricing tier — skipped: {t}")
    
    cleaned["pricing_tiers"] = valid_tiers

    # Validate and convert cpd_points to integer (database expects INTEGER, not float)
    if cleaned.get("cpd_points") is not None:
        try:
            # Convert to float first (handles strings like "4.5"), then round to int
            cpd_val = float(cleaned["cpd_points"])
            # Standard rounding: 0.5 and above rounds up
            cleaned["cpd_points"] = int(cpd_val + 0.5) if cpd_val >= 0 else int(cpd_val - 0.5)
        except (ValueError, TypeError):
            warnings.append(f"Invalid cpd_points value: '{cleaned.get('cpd_points')}' — set to null")
            cleaned["cpd_points"] = None
    
    # Ensure booleans are correct type
    for bool_field in ["cpd_accredited", "abstract_open", "is_sold_out", "is_on_demand", "is_flagship"]:
        cleaned[bool_field] = bool(cleaned.get(bool_field, False))

    # Abstract-status consistency check — every extractor's output passes through
    # here, so this is the canonical place to enforce the rule:
    #   abstract_open=True is ONLY valid when EITHER
    #     (a) abstract_deadline is set and today-or-later, OR
    #     (b) abstract_deadline_note is set AND abstract_deadline is null
    #         (curator-confirmed open, no published date)
    # Anything else → force abstract_open=False. This catches:
    #   - extractor sets open=True with a past deadline
    #   - extractor sets open=True with a stale note that no longer applies
    #   - extractor sets open=True without any supporting info
    from datetime import date as _date
    today_iso = _date.today().isoformat()

    # Stale-deadline guard — catches sources that roll a URL forward to
    # next year's event but leave the previous cycle's abstract deadline
    # on the page (observed on ASCO /breakthrough, /quality). If deadline
    # is >240 days before start_date, it can't be for THIS event; drop it
    # so the daily scrape re-picks the real date once the source updates.
    _dl = cleaned.get("abstract_deadline")
    _sd = cleaned.get("start_date")
    if _dl and _sd:
        try:
            _ddl = _date.fromisoformat(_dl)
            _dsd = _date.fromisoformat(_sd)
            if (_dsd - _ddl).days > 240:
                warnings.append(
                    f"abstract_deadline {_dl} is {(_dsd - _ddl).days} days "
                    f"before start_date {_sd} — treating as stale, dropped"
                )
                cleaned["abstract_deadline"] = None
                cleaned["abstract_deadline_note"] = None
                cleaned["abstract_open"] = False
        except ValueError:
            pass

    if cleaned["abstract_open"]:
        deadline = cleaned.get("abstract_deadline")
        note = cleaned.get("abstract_deadline_note")
        if deadline:
            # Deadline takes priority over note. Past → closed.
            if deadline < today_iso:
                warnings.append(
                    f"abstract_open=True but abstract_deadline {deadline} is in the past — forced to False"
                )
                cleaned["abstract_open"] = False
                cleaned["abstract_deadline_note"] = None
        elif note:
            # No deadline + note = curator-confirmed open. Fine.
            pass
        else:
            # No date and no note — extractor shouldn't be claiming open.
            warnings.append(
                "abstract_open=True without abstract_deadline or note — forced to False"
            )
            cleaned["abstract_open"] = False

    # Ensure archived is False by default (so frontend can see new conferences)
    cleaned["archived"] = bool(cleaned.get("archived", False))

    # Validate event_format — must be one of the allowed values or null
    fmt = cleaned.get("event_format")
    if fmt is not None and fmt not in ("in_person", "online", "hybrid"):
        warnings.append(f"Invalid event_format '{fmt}' — set to null")
        cleaned["event_format"] = None

    # Validate event_type — defaults to 'conference' if missing/invalid
    et = cleaned.get("event_type")
    if et not in ("conference", "course", "workshop"):
        if et is not None:
            warnings.append(f"Invalid event_type '{et}' — defaulted to 'conference'")
        cleaned["event_type"] = "conference"

    # course_sessions array is a sidecar payload, not a conferences column.
    # Validate it minimally if present so a malformed row doesn't crash the upsert.
    sessions = cleaned.get("sessions")
    if sessions is not None:
        if not isinstance(sessions, list):
            warnings.append(f"Invalid sessions type {type(sessions).__name__} — dropped")
            cleaned["sessions"] = []
        else:
            valid_sessions = []
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                if not s.get("start_date"):
                    continue
                try:
                    datetime.strptime(s["start_date"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                # Coerce booleans / strings
                status = s.get("availability_status") or "unknown"
                if status not in ("available", "limited", "sold_out", "unknown"):
                    status = "unknown"
                s["availability_status"] = status
                valid_sessions.append(s)
            cleaned["sessions"] = valid_sessions

    # Validate start_time — must be HH:MM or HH:MM:SS or null
    st = cleaned.get("start_time")
    if st:
        try:
            # Accept HH:MM and HH:MM:SS
            if len(st) == 5:
                datetime.strptime(st, "%H:%M")
            else:
                datetime.strptime(st, "%H:%M:%S")
        except (ValueError, TypeError):
            warnings.append(f"Invalid start_time '{st}' — set to null")
            cleaned["start_time"] = None

    # Warn if key optional fields are missing
    for field in ["start_date", "city", "specialty"]:
        if not cleaned.get(field):
            warnings.append(f"Missing optional field: {field}")

    return {
        "valid": True,
        "data": cleaned,
        "warnings": warnings
    }

