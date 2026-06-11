# database.py
"""Database layer - all Supabase read/write operations."""

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_active_sources() -> List[Dict[str, Any]]:
    """Fetch all active sources from the scraper registry."""
    response = supabase.table("scraper_sources").select("*").eq("active", True).execute()
    return response.data


def update_source_status(source_id: int, status: str) -> None:
    """Update a source's last_scraped_at and last_status after a run."""
    supabase.table("scraper_sources").update({
        "last_scraped_at": datetime.utcnow().isoformat(),
        "last_status": status
    }).eq("id", source_id).execute()


def get_conference_by_source_url(source_url: str) -> Optional[Dict[str, Any]]:
    """Check if a conference with this source URL already exists."""
    response = supabase.table("conferences").select("*").eq("source_url", source_url).execute()
    return response.data[0] if response.data else None


def insert_conference(data: Dict[str, Any]) -> int:
    """Insert a new conference record. Returns the new ID."""
    response = supabase.table("conferences").insert(data).execute()
    return response.data[0]["id"]


def update_conference(conference_id: int, data: Dict[str, Any]) -> None:
    """Update an existing conference record with changed fields."""
    data["updated_at"] = datetime.utcnow().isoformat()
    supabase.table("conferences").update(data).eq("id", conference_id).execute()


def insert_pricing_tiers(conference_id: int, tiers: List[Dict[str, Any]]) -> None:
    """Insert pricing tier rows for a conference."""
    rows = [{
        "conference_id": conference_id,
        "tier_label": t["tier_label"],
        "price_gbp": t["price_gbp"],
        "is_early_bird": t.get("is_early_bird", False),
        "early_bird_deadline": t.get("early_bird_deadline")
    } for t in tiers]
    
    if rows:
        supabase.table("pricing_tiers").insert(rows).execute()


def delete_pricing_tiers(conference_id: int) -> None:
    """Remove all pricing tiers for a conference before re-inserting updated ones."""
    supabase.table("pricing_tiers").delete().eq("conference_id", conference_id).execute()


def archive_expired_conferences() -> None:
    """Mark conferences whose end_date has passed as archived."""
    today = date.today().isoformat()
    supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).lt("end_date", today).eq("archived", False).execute()


def archive_stale_conferences(stale_days: int = 14) -> int:
    """
    Archive events that have not been confirmed by a recent scrape (i.e. their
    listing has disappeared from the source). Implements the L3 staleness
    rule from HQ LESSONS #2.

    Returns the number of rows archived.
    """
    threshold = (datetime.utcnow() - timedelta(days=stale_days)).isoformat()
    response = supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).lt("last_seen_at", threshold).eq("archived", False).execute()
    return len(response.data) if response.data else 0


def archive_undated_past_conferences() -> int:
    """Events with no end_date but a start_date that has already passed → archive."""
    today = date.today().isoformat()
    response = supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).is_("end_date", "null").lt("start_date", today).eq("archived", False).execute()
    return len(response.data) if response.data else 0


def close_passed_abstract_deadlines() -> int:
    """
    Flip abstract_open = FALSE on rows whose abstract_deadline has passed.

    The scraper extracts abstract_open from the source page's text ("abstracts
    open" etc.), but the source rarely updates that phrasing the moment the
    deadline passes — so without a cleanup pass the directory keeps showing
    closed submissions as still open. The deadline date is the source of
    truth, so this just enforces consistency between the two fields.

    Returns the number of rows updated.
    """
    today = date.today().isoformat()
    response = supabase.table("conferences").update({
        "abstract_open": False,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("abstract_open", True).lt("abstract_deadline", today).eq("archived", False).execute()
    return len(response.data) if response.data else 0


def bump_last_seen(conference_id: int) -> None:
    """Update last_seen_at for a conference confirmed by the current scrape."""
    supabase.table("conferences").update({
        "last_seen_at": datetime.utcnow().isoformat()
    }).eq("id", conference_id).execute()


def update_source_last_full_walk(source_id: int) -> None:
    """Record that we just completed a full multi-page walk of this source."""
    supabase.table("scraper_sources").update({
        "last_full_walk_at": datetime.utcnow().isoformat()
    }).eq("id", source_id).execute()


def insert_scraper_log(log_data: Dict[str, Any]) -> None:
    """Write a scraper run log entry."""
    supabase.table("scraper_logs").insert(log_data).execute()


