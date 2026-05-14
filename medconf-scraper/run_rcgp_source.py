#!/usr/bin/env python3
"""Run scraper on RCGP Events source to test fixes."""

import sys
from database import get_active_sources
from scraper import scrape_source
from logger import logger
from config import validate_config

def run_rcgp_source():
    """Run scraper on RCGP Events source."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        return False
    
    # Get RCGP source
    sources = get_active_sources()
    rcgp_source = None
    for source in sources:
        if 'RCGP' in source['source_name']:
            rcgp_source = source
            break
    
    if not rcgp_source:
        logger.error("RCGP Events source not found in database")
        return False
    
    logger.info("=" * 60)
    logger.info("RUNNING SCRAPER ON RCGP EVENTS SOURCE")
    logger.info("=" * 60)
    logger.info(f"Source ID: {rcgp_source['id']}")
    logger.info(f"Source Name: {rcgp_source['source_name']}")
    logger.info(f"URL: {rcgp_source['base_url']}")
    logger.info("=" * 60)
    logger.info("Previous Run Results:")
    logger.info("  - Found: 270 conferences")
    logger.info("  - Inserted: 1 conference")
    logger.info("  - Updated: 4 conferences")
    logger.info("  - Issues: cpd_points type error + navigation hanging")
    logger.info("")
    logger.info("Fixes Applied:")
    logger.info("  ✓ cpd_points conversion (float -> int)")
    logger.info("  ✓ Navigation timeout handling (networkidle -> load)")
    logger.info("  ✓ Better error handling and logging")
    logger.info("")
    logger.info("Starting scraper...")
    logger.info("=" * 60)
    logger.info("")
    
    # Run the scraper
    summary = scrape_source(rcgp_source)
    
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
    logger.info("  - Total Saved: 5 conferences")
    logger.info("")
    logger.info("Current Run:")
    logger.info(f"  - Found: {summary['conferences_found']} conferences")
    logger.info(f"  - Inserted: {summary['conferences_inserted']} conferences")
    logger.info(f"  - Updated: {summary['conferences_updated']} conferences")
    total_saved = summary['conferences_inserted'] + summary['conferences_updated']
    logger.info(f"  - Total Saved: {total_saved} conferences")
    logger.info("")
    
    # Calculate improvement
    previous_saved = 1 + 4  # 5 total
    
    if total_saved > previous_saved:
        improvement = total_saved - previous_saved
        improvement_pct = (improvement / previous_saved) * 100
        logger.info(f"✓ IMPROVEMENT: {improvement} more conferences saved ({improvement_pct:.1f}% increase)!")
        logger.info(f"  Previous: {previous_saved} saved")
        logger.info(f"  Current: {total_saved} saved")
        logger.info(f"  Improvement: +{improvement} conferences")
    elif total_saved == previous_saved:
        logger.warning("⚠ Same number of conferences saved as before")
        logger.warning("  This suggests the fixes may not have resolved all issues")
    else:
        logger.warning(f"⚠ Fewer conferences saved: {total_saved} vs {previous_saved}")
        logger.warning("  This may indicate a different issue")
    
    # Success rate
    if summary['conferences_found'] > 0:
        success_rate = (total_saved / summary['conferences_found']) * 100
        logger.info("")
        logger.info(f"Success Rate: {success_rate:.1f}% ({total_saved}/{summary['conferences_found']} conferences saved)")
        
        if success_rate > 50:
            logger.info("✓ Good success rate!")
        elif success_rate > 10:
            logger.warning("⚠ Moderate success rate - some conferences may have validation issues")
        else:
            logger.warning("⚠ Low success rate - many conferences failing validation or database insertion")
    
    logger.info("=" * 60)
    
    return summary['status'] in ['success', 'partial']

if __name__ == "__main__":
    success = run_rcgp_source()
    sys.exit(0 if success else 1)

