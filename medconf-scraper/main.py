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


def run_source_group(source_ids: list[int]) -> int:
    """Scrape several sources sequentially in one process (one CI job).

    Added 2026-09-26 for the grouped matrix: at 38+ sources a job-per-source
    matrix exceeds GitHub's free-tier concurrency (20) and just queues.
    Each source is isolated — an exception or failure in one never stops
    the rest — and the exit code is 1 if ANY source failed, so the job
    still goes red and names the culprits.
    """
    failed: list[int] = []
    for sid in source_ids:
        try:
            rc = run_single_source(sid)
        except Exception as e:  # never let one source kill the group
            logger.error(f"Source {sid} crashed: {e}")
            rc = 1
        if rc != 0:
            failed.append(sid)
    if failed:
        logger.error(f"Group finished with failures in source(s): {failed}")
        return 1
    logger.info(f"Group finished: all {len(source_ids)} source(s) succeeded")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MedConf scraper")
    parser.add_argument("--run-now", action="store_true",
                        help="Run a scrape immediately instead of starting the scheduler")
    parser.add_argument("--source", type=int, metavar="ID",
                        help="When used with --run-now, scrape only the source with this id")
    parser.add_argument("--sources", type=str, metavar="ID,ID,...",
                        help="When used with --run-now, scrape these sources sequentially "
                             "(one CI job per group; exit 1 if any fails)")
    args = parser.parse_args()

    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    if args.run_now:
        if args.source is not None:
            return run_single_source(args.source)
        if args.sources:
            ids = [int(x) for x in args.sources.split(",") if x.strip()]
            return run_source_group(ids)
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
