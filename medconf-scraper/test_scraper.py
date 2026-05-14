#!/usr/bin/env python3
"""Test script to run the agentic scraper on a single source using Kimi K2.5."""

import sys
import json
from config import validate_config, KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL
from database import get_active_sources
from scraper import scrape_source
from logger import logger

# Test source - RCGP Events (one of the example sources)
TEST_SOURCE = {
    "id": 999,  # Test ID
    "source_name": "RCGP Events (Test)",
    "base_url": "https://www.rcgp.org.uk/events",
    "extraction_instructions": "Navigate to the events page. Find all upcoming medical conferences and CPD events. For each event, extract: name, dates, location, CPD points if mentioned, pricing tiers, and registration links. If detail pages exist for individual events, navigate to each one to collect complete information.",
    "active": True
}


def test_with_database_source(source_id: int = None):
    """Test scraper using a source from the database."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please ensure you have a .env file with KIMI_API_KEY, SUPABASE_URL, and SUPABASE_KEY")
        sys.exit(1)
    
    # Check API key is set
    if not KIMI_API_KEY:
        logger.error("KIMI_API_KEY not found in environment variables")
        sys.exit(1)
    
    logger.info(f"Using Kimi K2.5 model: {KIMI_MODEL}")
    logger.info(f"API Base URL: {KIMI_BASE_URL}")
    
    # Get sources from database
    sources = get_active_sources()
    
    if not sources:
        logger.warning("No active sources found in database. Using test source instead.")
        source = TEST_SOURCE
    else:
        if source_id:
            # Find specific source by ID
            source = next((s for s in sources if s["id"] == source_id), None)
            if not source:
                logger.error(f"Source with ID {source_id} not found")
                logger.info(f"Available source IDs: {[s['id'] for s in sources]}")
                sys.exit(1)
        else:
            # Use first available source
            source = sources[0]
            logger.info(f"Using first available source: {source['source_name']} (ID: {source['id']})")
    
    logger.info("=" * 60)
    logger.info(f"Testing scraper on: {source['source_name']}")
    logger.info(f"URL: {source['base_url']}")
    logger.info("=" * 60)
    
    # Run the scraper
    try:
        summary = scrape_source(source)
        
        # Print results
        logger.info("\n" + "=" * 60)
        logger.info("SCRAPER TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {summary['status']}")
        logger.info(f"Conferences Found: {summary['conferences_found']}")
        logger.info(f"Conferences Inserted: {summary['conferences_inserted']}")
        logger.info(f"Conferences Updated: {summary['conferences_updated']}")
        logger.info(f"Errors Encountered: {summary['errors_encountered']}")
        
        if summary.get('error_details'):
            logger.error(f"Error Details: {summary['error_details']}")
        
        logger.info("=" * 60)
        
        # Return success if we found or inserted/updated conferences
        if summary['conferences_found'] > 0 or summary['conferences_inserted'] > 0 or summary['conferences_updated'] > 0:
            logger.info("✓ Test completed successfully!")
            return 0
        else:
            logger.warning("⚠ Test completed but no conferences were found/inserted")
            return 1
            
    except Exception as e:
        logger.error(f"Error during scraping: {str(e)}", exc_info=True)
        return 1


def test_with_hardcoded_source():
    """Test scraper using a hardcoded test source (no database required)."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.warning(f"Configuration warning: {e}")
        logger.info("Continuing with test source (database operations will fail)")
    
    # Check API key is set
    if not KIMI_API_KEY:
        logger.error("KIMI_API_KEY not found in environment variables")
        logger.error("Please set KIMI_API_KEY in your .env file")
        sys.exit(1)
    
    logger.info(f"Using Kimi K2.5 model: {KIMI_MODEL}")
    logger.info(f"API Base URL: {KIMI_BASE_URL}")
    logger.info("=" * 60)
    logger.info(f"Testing scraper on: {TEST_SOURCE['source_name']}")
    logger.info(f"URL: {TEST_SOURCE['base_url']}")
    logger.info("=" * 60)
    
    # Run the scraper
    try:
        summary = scrape_source(TEST_SOURCE)
        
        # Print results
        logger.info("\n" + "=" * 60)
        logger.info("SCRAPER TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {summary['status']}")
        logger.info(f"Conferences Found: {summary['conferences_found']}")
        logger.info(f"Conferences Inserted: {summary['conferences_inserted']}")
        logger.info(f"Conferences Updated: {summary['conferences_updated']}")
        logger.info(f"Errors Encountered: {summary['errors_encountered']}")
        
        if summary.get('error_details'):
            logger.error(f"Error Details: {summary['error_details']}")
        
        logger.info("=" * 60)
        
        # Return success if we found conferences (insertion may fail without DB)
        if summary['conferences_found'] > 0:
            logger.info("✓ Test completed successfully! Found conferences.")
            return 0
        else:
            logger.warning("⚠ Test completed but no conferences were found")
            return 1
            
    except Exception as e:
        logger.error(f"Error during scraping: {str(e)}", exc_info=True)
        return 1


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--hardcoded":
            # Use hardcoded test source
            sys.exit(test_with_hardcoded_source())
        elif sys.argv[1].isdigit():
            # Use specific source ID from database
            source_id = int(sys.argv[1])
            sys.exit(test_with_database_source(source_id))
        else:
            logger.error(f"Unknown argument: {sys.argv[1]}")
            logger.info("Usage:")
            logger.info("  python test_scraper.py              # Use first source from database")
            logger.info("  python test_scraper.py <source_id>  # Use specific source ID")
            logger.info("  python test_scraper.py --hardcoded   # Use hardcoded test source")
            sys.exit(1)
    else:
        # Default: use first source from database
        sys.exit(test_with_database_source())


