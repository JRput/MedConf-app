# scheduler.py
"""Scheduler module - defines weekly schedule and triggers scraper runs."""

from apscheduler.schedulers.blocking import BlockingScheduler
from database import (
    get_active_sources,
    archive_expired_conferences,
    archive_stale_conferences,
    archive_undated_past_conferences,
    close_passed_abstract_deadlines,
    update_source_last_full_walk,
)
from scraper import scrape_source
from logger import log_scrape_run, logger


def run_all_sources() -> None:
    """Fetch all active sources and scrape each one."""
    logger.info("=== Scraper run started ===")

    sources = get_active_sources()
    logger.info(f"Found {len(sources)} active source(s)")

    for source in sources:
        logger.info(f"Starting scrape for source {source['id']}: {source['source_name']}")
        summary = scrape_source(source)
        log_scrape_run(summary)
        if summary["status"] in ("success", "partial"):
            try:
                update_source_last_full_walk(source["id"])
            except Exception as e:
                logger.warning(f"Failed to update last_full_walk_at for source {source['id']}: {e}")

    # ---- Multi-rule archival sweep (Phase-6 staleness) ----
    expired = archive_expired_conferences()
    undated_past = archive_undated_past_conferences()
    stale = archive_stale_conferences(stale_days=14)
    closed_abstracts = close_passed_abstract_deadlines()
    logger.info(
        f"Archival sweep: end_date<today archived, "
        f"{undated_past or 0} undated-past archived, "
        f"{stale or 0} unseen-14d archived, "
        f"{closed_abstracts or 0} stale abstract_open flipped"
    )

    logger.info("=== Scraper run complete ===")


def start_scheduler() -> None:
    """Start the APScheduler with a weekly cron job."""
    scheduler = BlockingScheduler()
    
    # Runs every Sunday at 02:00 AM
    scheduler.add_job(
        run_all_sources,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0
    )
    
    logger.info("Scheduler started. Next scrape run: Sunday at 02:00")
    scheduler.start()


