#!/usr/bin/env python3
"""Full pipeline test that extracts and saves data to Supabase."""

import sys
from config import validate_config, KIMI_API_KEY
from scraper import scrape_source
from logger import logger

# Test source - RCGP Events
TEST_SOURCE = {
    "id": 999,  # Test ID (won't conflict with real sources)
    "source_name": "RCGP Events (Test)",
    "base_url": "https://www.rcgp.org.uk/events",
    "extraction_instructions": "Navigate to the events page. Find all upcoming medical conferences and CPD events. For each event, extract: name, dates, location, CPD points if mentioned, pricing tiers, and registration links. If detail pages exist for individual events, navigate to each one to collect complete information.",
    "active": True
}

def test_full_pipeline():
    """Test the complete pipeline: extraction -> validation -> database save."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please ensure you have a .env file with KIMI_API_KEY, SUPABASE_URL, and SUPABASE_KEY")
        return False
    
    if not KIMI_API_KEY:
        logger.error("KIMI_API_KEY not set")
        return False
    
    logger.info("=" * 60)
    logger.info("FULL PIPELINE TEST - Extracting and Saving to Supabase")
    logger.info("=" * 60)
    logger.info(f"Source: {TEST_SOURCE['source_name']}")
    logger.info(f"URL: {TEST_SOURCE['base_url']}")
    logger.info("=" * 60)
    logger.info("This will:")
    logger.info("1. Launch browser and navigate to the source")
    logger.info("2. Extract conference data using Kimi K2.5")
    logger.info("3. Validate the extracted data")
    logger.info("4. Save to Supabase database")
    logger.info("=" * 60)
    logger.info("Starting... (this may take 2-5 minutes)")
    logger.info("")
    
    try:
        # Run the full scraper pipeline
        summary = scrape_source(TEST_SOURCE)
        
        # Print results
        logger.info("")
        logger.info("=" * 60)
        logger.info("PIPELINE TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {summary['status']}")
        logger.info(f"Conferences Found: {summary['conferences_found']}")
        logger.info(f"Conferences Inserted: {summary['conferences_inserted']}")
        logger.info(f"Conferences Updated: {summary['conferences_updated']}")
        logger.info(f"Errors Encountered: {summary['errors_encountered']}")
        
        if summary.get('error_details'):
            logger.warning(f"Error Details: {summary['error_details']}")
        
        logger.info("=" * 60)
        
        # Check if data was saved
        if summary['conferences_inserted'] > 0 or summary['conferences_updated'] > 0:
            logger.info("✓ SUCCESS - Data has been saved to Supabase!")
            logger.info(f"  - {summary['conferences_inserted']} new conference(s) inserted")
            logger.info(f"  - {summary['conferences_updated']} conference(s) updated")
            logger.info("")
            logger.info("You can now view this data:")
            logger.info("1. Run: python3 check_database.py")
            logger.info("2. Check Supabase dashboard")
            logger.info("3. View on medconf website UI")
            return True
        elif summary['conferences_found'] > 0:
            logger.warning("⚠ Data was extracted but not saved")
            logger.warning("  This might be due to validation errors")
            logger.warning(f"  Found {summary['conferences_found']} conferences but 0 were inserted/updated")
            return False
        else:
            logger.warning("⚠ No conferences were found")
            return False
            
    except Exception as e:
        logger.error(f"✗ PIPELINE FAILED: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_full_pipeline()
    sys.exit(0 if success else 1)


