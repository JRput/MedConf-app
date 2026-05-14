# logger.py
"""Logging module - writes run summaries to console and Supabase."""

import logging
from database import insert_scraper_log, update_source_status
from typing import Dict, Any

# Configure console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger("medconf-scraper")


def log_scrape_run(summary: Dict[str, Any]) -> None:
    """Log a completed scrape run to console and Supabase."""
    source_id = summary["source_id"]
    status = summary["status"]

    # Console output
    logger.info(
        f"Source {source_id} | Status: {status} | "
        f"Found: {summary['conferences_found']} | "
        f"Inserted: {summary['conferences_inserted']} | "
        f"Updated: {summary['conferences_updated']} | "
        f"Errors: {summary['errors_encountered']}"
    )

    if summary["error_details"]:
        logger.warning(f"Source {source_id} | Error: {summary['error_details']}")

    # Write to Supabase
    insert_scraper_log(summary)

    # Update the source's last_scraped_at and last_status
    update_source_status(source_id, status)


