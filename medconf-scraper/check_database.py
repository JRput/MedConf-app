#!/usr/bin/env python3
"""Check what data is in the Supabase database."""

import sys
from database import supabase
from config import SUPABASE_URL
from logger import logger

def check_database():
    """Check what's in the database."""
    logger.info("=" * 60)
    logger.info("Checking Supabase Database")
    logger.info("=" * 60)
    logger.info(f"Supabase URL: {SUPABASE_URL}")
    logger.info("=" * 60)
    
    try:
        # Check scraper_sources
        logger.info("\n1. SCRAPER SOURCES:")
        sources = supabase.table("scraper_sources").select("*").execute()
        logger.info(f"   Total sources: {len(sources.data)}")
        for source in sources.data[:5]:  # Show first 5
            logger.info(f"   - ID {source['id']}: {source['source_name']} ({'active' if source.get('active') else 'inactive'})")
        
        # Check conferences
        logger.info("\n2. CONFERENCES:")
        conferences = supabase.table("conferences").select("*").order("created_at", desc=True).limit(10).execute()
        logger.info(f"   Total conferences (showing latest 10): {len(conferences.data)}")
        for conf in conferences.data:
            logger.info(f"   - ID {conf['id']}: {conf.get('conference_name', 'N/A')}")
            logger.info(f"     Created: {conf.get('created_at', 'N/A')}")
            logger.info(f"     Source URL: {conf.get('source_url', 'N/A')[:60]}...")
        
        # Check scraper_logs
        logger.info("\n3. SCRAPER LOGS:")
        logs = supabase.table("scraper_logs").select("*").order("run_started_at", desc=True).limit(5).execute()
        logger.info(f"   Recent runs (showing latest 5): {len(logs.data)}")
        for log in logs.data:
            logger.info(f"   - Source ID {log['source_id']}: {log['status']}")
            logger.info(f"     Found: {log.get('conferences_found', 0)}, Inserted: {log.get('conferences_inserted', 0)}, Updated: {log.get('conferences_updated', 0)}")
            logger.info(f"     Started: {log.get('run_started_at', 'N/A')}")
        
        # Check pricing_tiers
        logger.info("\n4. PRICING TIERS:")
        tiers = supabase.table("pricing_tiers").select("*").limit(10).execute()
        logger.info(f"   Total pricing tiers (showing first 10): {len(tiers.data)}")
        for tier in tiers.data:
            logger.info(f"   - Conference ID {tier['conference_id']}: {tier.get('tier_label', 'N/A')} - £{tier.get('price_gbp', 0)}")
        
        logger.info("\n" + "=" * 60)
        logger.info("Database check complete!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}", exc_info=True)
        return False
    
    return True

if __name__ == "__main__":
    success = check_database()
    sys.exit(0 if success else 1)


