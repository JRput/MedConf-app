#!/usr/bin/env python3
# main.py
"""Entry point for the MedConf scraper.

Usage:
  python main.py                              # start the weekly APScheduler
  python main.py --run-now                    # scrape ALL active sources immediately
  python main.py --run-now --source <id>      # scrape ONE source immediately

The --source flag is what GitHub Actions uses to run each source as its own
isolated cloud worker (one source per worker, all in parallel).
"""

import argparse
import sys

from config import validate_config
from database import (
    get_active_sources,
    archive_expired_conferences,
    archive_stale_conferences,
    archive_undated_past_conferences,
    close_passed_abstract_deadlines,
    update_source_last_full_walk,
)
from logger import logger, log_scrape_run
from scheduler import run_all_sources, start_scheduler
from scraper import scrape_source


def run_single_source(source_id: int) -> int:
    """Scrape exactly one source by id. Returns 0 on success, 1 on failure."""
    sources = get_active_sources()
    target = next((s for s in sources if s["id"] == source_id), None)
    if not target:
        logger.error(f"Source id={source_id} not found among active sources")
        return 1

    logger.info(f"Single-source run: scraping source {target['id']}: {target['source_name']}")
    summary = scrape_source(target)
    log_scrape_run(summary)
    if summary["status"] in ("success", "partial"):
        try:
            update_source_last_full_walk(target["id"])
        except Exception as e:
            logger.warning(f"Failed to update last_full_walk_at: {e}")

    # Archival + housekeeping sweep runs regardless of single/multi-source
    # flow. Cheap and idempotent — better to run too often than miss it.
    try:
        archive_expired_conferences()
        archive_undated_past_conferences()
        archive_stale_conferences(stale_days=14)
        closed = close_passed_abstract_deadlines()
        if closed:
            logger.info(f"Flipped abstract_open=FALSE on {closed} past-deadline rows")
    except Exception as e:
        logger.warning(f"Housekeeping sweep failed: {e}")

    return 0 if summary["status"] in ("success", "partial") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="MedConf scraper")
    parser.add_argument("--run-now", action="store_true",
                        help="Run a scrape immediately instead of starting the scheduler")
    parser.add_argument("--source", type=int, metavar="ID",
                        help="When used with --run-now, scrape only the source with this id")
    args = parser.parse_args()

    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    if args.run_now:
        if args.source is not None:
            return run_single_source(args.source)
        logger.info("Running scraper immediately for ALL active sources")
        run_all_sources()
        return 0

    # No --run-now → start the APScheduler (the legacy local-mode behaviour).
    # In production we use GitHub Actions cron, NOT this in-process scheduler
    # (see HQ LESSON #1 on APScheduler unreliability on macOS).
    start_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())
