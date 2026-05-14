#!/usr/bin/env python3
"""Run scraper on the first active source from database."""

import sys
from database import get_active_sources
from scraper import scrape_source
from logger import logger
from config import validate_config

def run_first_source():
    """Run scraper on the first active source."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        return False
    
    # Get first active source
    sources = get_active_sources()
    if not sources:
        logger.error("No active sources found in database")
        return False
    
    source = sources[0]
    
    logger.info("=" * 60)
    logger.info("RUNNING SCRAPER ON FIRST SOURCE")
    logger.info("=" * 60)
    logger.info(f"Source ID: {source['id']}")
    logger.info(f"Source Name: {source['source_name']}")
    logger.info(f"URL: {source['base_url']}")
    logger.info("=" * 60)
    logger.info("Starting scraper with fixes applied...")
    logger.info("")
    
    # Run the scraper
    summary = scrape_source(source)
    
    # Print results
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPER RESULTS")
    logger.info("=" * 60)
    logger.info(f"Status: {summary['status']}")
    logger.info(f"Conferences Found: {summary['conferences_found']}")
    logger.info(f"Conferences Inserted: {summary['conferences_inserted']}")
    logger.info(f"Conferences Updated: {summary['conferences_updated']}")
    logger.info(f"Errors Encountered: {summary['errors_encountered']}")
    
    if summary.get('error_details'):
        logger.warning(f"Error Details: {summary['error_details'][:500]}")
    
    logger.info("=" * 60)
    
    # Comparison with previous run
    logger.info("")
    logger.info("=" * 60)
    logger.info("COMPARISON WITH PREVIOUS RUN")
    logger.info("=" * 60)
    logger.info("Previous Run:")
    logger.info("  - Found: 270 conferences")
    logger.info("  - Inserted: 1 conference")
    logger.info("  - Updated: 4 conferences")
    logger.info("  - Issue: cpd_points type error + navigation hanging")
    logger.info("")
    logger.info("Current Run:")
    logger.info(f"  - Found: {summary['conferences_found']} conferences")
    logger.info(f"  - Inserted: {summary['conferences_inserted']} conferences")
    logger.info(f"  - Updated: {summary['conferences_updated']} conferences")
    logger.info("")
    
    # Calculate improvement
    total_saved = summary['conferences_inserted'] + summary['conferences_updated']
    previous_saved = 1 + 4  # 5 total
    
    if total_saved > previous_saved:
        improvement = total_saved - previous_saved
        logger.info(f"✓ IMPROVEMENT: {improvement} more conferences saved!")
        logger.info(f"  Previous: {previous_saved} saved, Current: {total_saved} saved")
    elif total_saved == previous_saved:
        logger.warning("⚠ Same number of conferences saved as before")
    else:
        logger.warning(f"⚠ Fewer conferences saved: {total_saved} vs {previous_saved}")
    
    logger.info("=" * 60)
    
    return summary['status'] in ['success', 'partial']

if __name__ == "__main__":
    success = run_first_source()
    sys.exit(0 if success else 1)

