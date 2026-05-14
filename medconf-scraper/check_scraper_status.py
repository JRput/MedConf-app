#!/usr/bin/env python3
"""Check what the scraper found and if it's making progress."""

import sys
from database import supabase
from logger import logger
from datetime import datetime, timedelta

def check_scraper_status():
    """Check scraper logs and database status."""
    logger.info("=" * 60)
    logger.info("Checking Scraper Status")
    logger.info("=" * 60)
    
    # Check latest scraper log
    logger.info("\n1. Latest Scraper Run:")
    logs = supabase.table("scraper_logs").select("*").order("run_started_at", desc=True).limit(1).execute()
    
    if logs.data:
        log = logs.data[0]
        logger.info(f"   Started: {log.get('run_started_at')}")
        logger.info(f"   Ended: {log.get('run_ended_at', 'Still running...')}")
        logger.info(f"   Status: {log.get('status')}")
        logger.info(f"   Found: {log.get('conferences_found', 0)}")
        logger.info(f"   Inserted: {log.get('conferences_inserted', 0)}")
        logger.info(f"   Updated: {log.get('conferences_updated', 0)}")
        logger.info(f"   Errors: {log.get('errors_encountered', 0)}")
        if log.get('error_details'):
            logger.info(f"   Error: {log['error_details'][:200]}")
    else:
        logger.info("   No scraper logs found")
    
    # Check total conferences
    logger.info("\n2. Database Status:")
    result = supabase.table("conferences").select("id", count="exact").eq("archived", False).execute()
    total = result.count if hasattr(result, 'count') else len(result.data)
    logger.info(f"   Total active conferences: {total}")
    
    # Check recent conferences
    recent = datetime.utcnow() - timedelta(hours=1)
    recent_result = supabase.table("conferences").select("id", count="exact").eq("archived", False).gte("created_at", recent.isoformat()).execute()
    recent_count = recent_result.count if hasattr(recent_result, 'count') else len(recent_result.data)
    logger.info(f"   Created in last hour: {recent_count}")
    
    # Check if scraper is likely stuck
    if logs.data:
        log = logs.data[0]
        if log.get('run_ended_at') is None:
            # Still running
            started = datetime.fromisoformat(log['run_started_at'].replace('Z', '+00:00'))
            now = datetime.now(started.tzinfo)
            duration = (now - started).total_seconds() / 60  # minutes
            logger.info(f"\n3. Run Duration: {duration:.1f} minutes")
            
            if duration > 30:
                logger.warning(f"   ⚠ Scraper has been running for {duration:.1f} minutes")
                logger.warning(f"   This is longer than expected. It may be stuck.")
                logger.warning(f"   Max steps limit: 30 (each step takes 1-2 minutes)")
                logger.warning(f"   Consider killing the process if no progress is being made.")
    
    logger.info("\n" + "=" * 60)
    
if __name__ == "__main__":
    check_scraper_status()


