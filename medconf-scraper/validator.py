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
    for date_field in ["start_date", "end_date", "abstract_deadline"]:
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
    for bool_field in ["cpd_accredited", "abstract_open", "is_sold_out"]:
        cleaned[bool_field] = bool(cleaned.get(bool_field, False))

    # Ensure archived is False by default (so frontend can see new conferences)
    cleaned["archived"] = bool(cleaned.get("archived", False))

    # Validate event_format — must be one of the allowed values or null
    fmt = cleaned.get("event_format")
    if fmt is not None and fmt not in ("in_person", "online", "hybrid"):
        warnings.append(f"Invalid event_format '{fmt}' — set to null")
        cleaned["event_format"] = None

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

