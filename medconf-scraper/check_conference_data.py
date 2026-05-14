#!/usr/bin/env python3
"""Check what conference data was actually saved."""

from database import supabase
from logger import logger

logger.info("=" * 60)
logger.info("Checking Saved Conference Data")
logger.info("=" * 60)

# Get all conferences
result = supabase.table('conferences').select('*').eq('archived', False).order('updated_at', desc=True).execute()
conferences = result.data

logger.info(f"\nTotal conferences in database: {len(conferences)}")

# Group by source_url to see duplicates
from collections import Counter
source_urls = [c['source_url'] for c in conferences]
url_counts = Counter(source_urls)

logger.info(f"\nUnique source URLs: {len(url_counts)}")
logger.info(f"Conferences with duplicate source URLs: {sum(1 for count in url_counts.values() if count > 1)}")

# Show duplicates
logger.info("\nSource URL distribution:")
for url, count in url_counts.most_common(10):
    logger.info(f"  {url[:80]}: {count} conference(s)")

# Check RCGP specifically
rcgp_confs = [c for c in conferences if 'rcgp.org.uk' in c.get('source_url', '')]
logger.info(f"\nRCGP conferences: {len(rcgp_confs)}")
for conf in rcgp_confs[:5]:
    logger.info(f"  ID {conf['id']}: {conf.get('conference_name', 'N/A')[:60]}")
    logger.info(f"    Source URL: {conf.get('source_url', 'N/A')}")
    logger.info(f"    Organiser URL: {conf.get('organiser_url', 'N/A')[:60]}")
    logger.info("")

