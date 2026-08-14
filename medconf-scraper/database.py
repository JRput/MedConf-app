# database.py
"""Database layer - all Supabase read/write operations."""

import logging
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

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
    """Insert pricing tier rows for a conference.

    Each tier may carry a `session_id` (UUID string) to scope it to one
    course_sessions row. Pass it through if present; conference-flat tiers
    leave it null."""
    rows = []
    for t in tiers:
        row = {
            "conference_id": conference_id,
            "tier_label": t["tier_label"],
            "price_gbp": t["price_gbp"],
            "currency": t.get("currency", "GBP"),
            "is_early_bird": t.get("is_early_bird", False),
            "early_bird_deadline": t.get("early_bird_deadline"),
        }
        if t.get("session_id"):
            row["session_id"] = t["session_id"]
        rows.append(row)

    if rows:
        supabase.table("pricing_tiers").insert(rows).execute()


def delete_course_sessions(course_id: int) -> None:
    """Remove all course_sessions rows for a course before re-inserting."""
    supabase.table("course_sessions").delete().eq("course_id", course_id).execute()


def insert_course_sessions(course_id: int, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Insert course_sessions rows for a course. Returns the inserted rows so
    the caller can map per-session pricing back to the new UUIDs.

    Strips extractor-private keys (those starting with '_') before insert.
    """
    if not sessions:
        return []
    rows = []
    for s in sessions:
        rows.append({
            "course_id": course_id,
            "start_date": s["start_date"],
            "end_date": s.get("end_date"),
            "start_time": s.get("start_time"),
            "duration_text": s.get("duration_text"),
            "availability_status": s.get("availability_status", "unknown"),
            "spots_left": s.get("spots_left"),
            "booking_url": s.get("booking_url"),
            "venue_name": s.get("venue_name"),
            "city": s.get("city"),
            "region": s.get("region"),
            "notes": s.get("notes"),
        })
    response = supabase.table("course_sessions").insert(rows).execute()
    return response.data or []


def delete_pricing_tiers(conference_id: int) -> None:
    """Remove all pricing tiers for a conference before re-inserting updated ones."""
    supabase.table("pricing_tiers").delete().eq("conference_id", conference_id).execute()


def archive_expired_conferences() -> None:
    """Mark conferences whose end_date has passed as archived.

    On-demand rows are excluded — their start_date IS the access deadline,
    so the archival logic for is_on_demand rows uses start_date instead of
    end_date and is handled in archive_undated_past_conferences below.
    """
    today = date.today().isoformat()
    supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).lt("end_date", today).eq("archived", False).eq("is_on_demand", False).execute()
    # On-demand rows expire when their start_date (= access deadline) passes
    supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).lt("start_date", today).eq("archived", False).eq("is_on_demand", True).execute()


def archive_stale_conferences(stale_days: int = 14) -> int:
    """
    Archive events that have not been confirmed by a recent scrape (i.e. their
    listing has disappeared from the source). Implements the L3 staleness
    rule from HQ LESSONS #2.

    SOURCE-HEALTH GUARD: only archive rows whose source has completed at
    least one SUCCESSFUL scrape in the stale window. Without this guard, a
    source that fails 14 days straight (e.g. network flakes on rcem.ac.uk,
    Cloudflare-challenged host, matrix job crash) would silently vaporise
    its entire catalogue on day 14 — the stale-detection would fire on
    every row it stopped stamping last_seen_at on.

    Returns the number of rows archived.
    """
    threshold = (datetime.utcnow() - timedelta(days=stale_days)).isoformat()

    # Identify sources with at least one successful scrape in the window.
    healthy_logs = (
        supabase.table("scraper_logs")
        .select("source_id")
        .eq("status", "success")
        .gte("run_started_at", threshold)
        .execute()
        .data
        or []
    )
    healthy_source_ids = {row["source_id"] for row in healthy_logs}

    if not healthy_source_ids:
        logger.warning(
            "archive_stale_conferences: NO sources have a successful "
            f"scrape in the last {stale_days} days — skipping archival "
            "sweep entirely to avoid mass-vaporising the catalogue"
        )
        return 0

    unhealthy_all = supabase.table("scraper_sources").select("id").execute().data or []
    unhealthy_source_ids = [
        r["id"] for r in unhealthy_all if r["id"] not in healthy_source_ids
    ]
    if unhealthy_source_ids:
        logger.warning(
            f"archive_stale_conferences: {len(unhealthy_source_ids)} source(s) "
            f"had no success in {stale_days} days — their rows will NOT be "
            f"archived: {sorted(unhealthy_source_ids)}"
        )

    # Only archive rows whose source is healthy AND the row itself is stale
    response = (
        supabase.table("conferences")
        .update({
            "archived": True,
            "updated_at": datetime.utcnow().isoformat(),
        })
        .lt("last_seen_at", threshold)
        .eq("archived", False)
        .in_("source_id", sorted(healthy_source_ids))
        .execute()
    )
    return len(response.data) if response.data else 0


def archive_undated_past_conferences() -> int:
    """Events with no end_date but a start_date that has already passed → archive.

    Excludes on-demand rows whose start_date is the access deadline — those
    are handled by archive_expired_conferences above so we don't get
    duplicate archive sweeps over the same row.
    """
    today = date.today().isoformat()
    response = supabase.table("conferences").update({
        "archived": True,
        "updated_at": datetime.utcnow().isoformat()
    }).is_("end_date", "null").lt("start_date", today).eq("archived", False).eq("is_on_demand", False).execute()
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


