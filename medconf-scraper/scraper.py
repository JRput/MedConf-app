# scraper.py
"""Main scraper function — ties together the agent, validator, DB.

Implements the Phase-6 incremental architecture:
  1. Walk listing pages (paginated, deterministic — no LLM).
  2. For each shell, compute a listing-content hash.
  3. If an existing conference row has the same hash, skip detail extraction
     entirely (just bump last_seen_at). Otherwise navigate to the detail page
     and run the per-source extractor.

This keeps weekly cycles cheap: typically ~10–30 of ~425 events change
between runs, so we save ~95% of LLM calls compared to a full re-fetch.
"""

import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

from llm_agent import AgentLoop
from validator import validate_conference
from database import (
    get_conference_by_source_url,
    insert_conference,
    update_conference,
    insert_pricing_tiers,
    delete_pricing_tiers,
    bump_last_seen,
)
from logger import logger


def _compute_listing_hash(shell: Dict[str, Any]) -> str:
    """
    SHA-256 of the listing-level fields that signal "something might have
    changed and we should re-fetch detail". Order matters — keep it stable.
    """
    parts = [
        str(shell.get("title") or ""),
        str(shell.get("start_date") or ""),
        str(shell.get("start_time") or ""),
        "1" if shell.get("is_sold_out") else "0",
        str(shell.get("location_hint") or ""),
        # Description text changes signal listing-level updates worth re-reading
        (shell.get("description_hint") or "")[:300],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _synthesise_source_url(source: Dict[str, Any], conf: Dict[str, Any]) -> str:
    """Fallback when an extracted conference has no booking/source URL."""
    name = conf.get("conference_name") or "unknown"
    start = conf.get("start_date") or ""
    city = conf.get("city") or ""
    venue = conf.get("venue_name") or ""
    h = hashlib.md5(f"{name}|{start}|{city}|{venue}".encode()).hexdigest()[:8]
    slug = name.lower().replace(" ", "-").replace("/", "-")[:40].strip("-")
    return f"{source['base_url']}#{slug}-{h}"


def scrape_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase-6 multi-page incremental scrape for a single source.

    Returns a summary dict for logging.
    """
    summary = {
        "source_id": source["id"],
        "run_started_at": datetime.utcnow().isoformat(),
        "run_ended_at": None,
        "status": "pending",
        "conferences_found": 0,
        "conferences_inserted": 0,
        "conferences_updated": 0,
        "errors_encountered": 0,
        "error_details": None,
    }
    # Tracked locally for visibility — not stored in scraper_logs schema
    skipped_unchanged = 0
    seen_bumped = 0

    agent = AgentLoop(source)

    try:
        agent.open_browser()

        # --- Phase A: walk all listing pages ---
        shells = agent.list_shells()
        summary["conferences_found"] = len(shells)

        if not shells:
            summary["status"] = "failed"
            summary["error_details"] = "No event cards extracted from listing"
            summary["run_ended_at"] = datetime.utcnow().isoformat()
            return summary

        logger.info(f"Source {source['id']}: starting incremental processing of {len(shells)} shells")

        # --- Phase B: for each shell, decide skip-or-extract ---
        for i, shell in enumerate(shells, start=1):
            if i % 25 == 0:
                logger.info(f"  Progress: {i}/{len(shells)} (skipped unchanged: {skipped_unchanged}, "
                            f"inserted: {summary['conferences_inserted']}, updated: {summary['conferences_updated']})")

            booking_url = shell.get("booking_url") or _synthesise_source_url(source, shell)
            new_hash = _compute_listing_hash(shell)

            try:
                existing = get_conference_by_source_url(booking_url)
            except Exception as e:
                logger.warning(f"  Lookup failed for {booking_url[:60]}: {e}")
                existing = None

            # Fast path: nothing changed at the listing level → just confirm
            # presence. BUT: the listing hash is computed from listing-card
            # fields only, so when a source later publishes details on the
            # event detail page (e.g. RCGP filling in the Primary venue
            # closer to the event date), the hash stays the same and the row
            # would never get re-extracted. To make incremental scrapes
            # SELF-HEALING for late-published detail data, force a re-fetch
            # whenever key detail-page fields are still pending:
            #   - event_format unknown (couldn't determine in-person vs online)
            #   - in-person event but venue or city not yet known
            # Online events with venue/city deliberately null fast-skip as
            # before — those nulls are correct, not pending.
            fmt = (existing or {}).get("event_format") if existing else None
            needs_refresh_for_pending_fields = bool(existing) and (
                fmt is None
                or (fmt == "in_person" and not (existing.get("venue_name") and existing.get("city")))
            )
            if existing and existing.get("listing_hash") == new_hash and not needs_refresh_for_pending_fields:
                try:
                    bump_last_seen(existing["id"])
                    seen_bumped += 1
                    skipped_unchanged += 1
                except Exception as e:
                    logger.warning(f"  bump_last_seen failed for id={existing['id']}: {e}")
                continue

            # Slow path: new event OR listing changed → fetch detail page and re-extract
            merged = agent.extract_detail_for_shell(shell)

            # Detect whether the SOFT (LLM-dependent) fields succeeded. We use
            # these as the proxy for "the LLM call worked" — they're the parts
            # most likely to fail under rate-limit pressure. If they're both
            # null, leave listing_hash NULL so the next scrape retries. Other
            # fields like pricing/format come from deterministic HTML parsing
            # and don't tell us anything about LLM health.
            detail_succeeded = bool(
                merged.get("description")
                or merged.get("specialty")
            )

            # Stamp the row with source_id, hash (only if detail succeeded),
            # timestamps, and a canonical source_url
            merged["source_id"] = source["id"]
            merged["listing_hash"] = new_hash if detail_succeeded else None
            now_iso = datetime.utcnow().isoformat()
            merged["last_seen_at"] = now_iso
            merged["last_detail_at"] = now_iso if detail_succeeded else None
            if not merged.get("source_url"):
                merged["source_url"] = booking_url

            # Validate before insert/update
            validation = validate_conference(merged)
            if not validation["valid"]:
                summary["errors_encountered"] += 1
                msg = f"Validation failed for '{merged.get('conference_name', '?')}': {validation.get('warnings')}"
                logger.warning(msg)
                if not summary["error_details"]:
                    summary["error_details"] = msg
                continue

            cleaned = validation["data"]
            tiers = cleaned.pop("pricing_tiers", []) or []

            try:
                if existing:
                    # Update only changed fields (cheaper, less log noise)
                    changes = {k: v for k, v in cleaned.items() if existing.get(k) != v}
                    if changes:
                        update_conference(existing["id"], changes)
                    # Refresh pricing tiers wholesale when we re-fetched detail
                    delete_pricing_tiers(existing["id"])
                    if tiers:
                        insert_pricing_tiers(existing["id"], tiers)
                    summary["conferences_updated"] += 1
                else:
                    new_id = insert_conference(cleaned)
                    if tiers:
                        insert_pricing_tiers(new_id, tiers)
                    summary["conferences_inserted"] += 1
            except Exception as db_error:
                summary["errors_encountered"] += 1
                msg = f"DB error for '{cleaned.get('conference_name', '?')}': {db_error}"
                logger.warning(msg)
                if not summary["error_details"]:
                    summary["error_details"] = msg

        # Status determination
        produced = (summary["conferences_inserted"]
                    + summary["conferences_updated"]
                    + skipped_unchanged)
        if produced > 0:
            summary["status"] = "success" if summary["errors_encountered"] == 0 else "partial"
        else:
            summary["status"] = "failed" if summary["errors_encountered"] > 0 else "partial"

        logger.info(
            f"Source {source['id']}: status={summary['status']}, found={summary['conferences_found']}, "
            f"inserted={summary['conferences_inserted']}, updated={summary['conferences_updated']}, "
            f"skipped (unchanged)={skipped_unchanged}, errors={summary['errors_encountered']}"
        )

    except Exception as e:
        summary["status"] = "failed"
        summary["error_details"] = str(e)
        summary["errors_encountered"] += 1
        logger.exception(f"Source {source['id']}: scrape_source crashed")
    finally:
        agent.close_browser()

    summary["run_ended_at"] = datetime.utcnow().isoformat()
    return summary

