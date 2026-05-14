#!/usr/bin/env python3
"""Query and display conferences from Supabase database."""

import sys
from database import supabase
from config import SUPABASE_URL
from logger import logger
from datetime import datetime

def query_conferences(limit=20, show_archived=False):
    """Query and display conferences from the database."""
    logger.info("=" * 60)
    logger.info("Querying Conferences from Supabase")
    logger.info("=" * 60)
    logger.info(f"Supabase URL: {SUPABASE_URL}")
    logger.info("=" * 60)
    
    try:
        # Build query
        query = supabase.table("conferences").select("*")
        
        if not show_archived:
            query = query.eq("archived", False)
        
        # Order by start_date (ascending - upcoming first)
        query = query.order("start_date", desc=False)
        
        # Limit results
        if limit:
            query = query.limit(limit)
        
        # Execute query
        response = query.execute()
        conferences = response.data
        
        logger.info(f"\nFound {len(conferences)} conference(s)")
        logger.info("=" * 60)
        
        if not conferences:
            logger.info("No conferences found in database.")
            logger.info("Run the scraper to populate data.")
            return
        
        # Display each conference
        for i, conf in enumerate(conferences, 1):
            logger.info(f"\n[{i}] {conf.get('conference_name', 'N/A')}")
            logger.info(f"    ID: {conf.get('id')}")
            logger.info(f"    Specialty: {conf.get('specialty', 'N/A')}")
            
            # Dates
            start = conf.get('start_date')
            end = conf.get('end_date')
            if start:
                logger.info(f"    Dates: {start}" + (f" to {end}" if end else ""))
            else:
                logger.info(f"    Dates: Not specified")
            
            # Location
            city = conf.get('city')
            region = conf.get('region')
            venue = conf.get('venue_name')
            if city or region:
                location = f"{city or ''}{', ' if city and region else ''}{region or ''}"
                logger.info(f"    Location: {location}")
            if venue:
                logger.info(f"    Venue: {venue}")
            
            # CPD
            if conf.get('cpd_accredited'):
                points = conf.get('cpd_points')
                logger.info(f"    CPD: Accredited" + (f" ({points} points)" if points else ""))
            
            # Abstract
            if conf.get('abstract_open'):
                deadline = conf.get('abstract_deadline')
                logger.info(f"    Abstract: Open" + (f" (deadline: {deadline})" if deadline else ""))
            
            # URLs
            if conf.get('organiser_url'):
                logger.info(f"    Organiser URL: {conf['organiser_url']}")
            logger.info(f"    Source URL: {conf.get('source_url', 'N/A')}")
            
            # Get pricing tiers
            tiers_response = supabase.table("pricing_tiers").select("*").eq("conference_id", conf['id']).execute()
            tiers = tiers_response.data
            if tiers:
                logger.info(f"    Pricing Tiers ({len(tiers)}):")
                for tier in tiers:
                    early_bird = " (Early Bird)" if tier.get('is_early_bird') else ""
                    deadline = f" (deadline: {tier.get('early_bird_deadline')})" if tier.get('early_bird_deadline') else ""
                    logger.info(f"      - {tier.get('tier_label', 'N/A')}: £{tier.get('price_gbp', 0)}{early_bird}{deadline}")
            
            # Metadata
            created = conf.get('created_at')
            updated = conf.get('updated_at')
            if created:
                logger.info(f"    Created: {created}")
            if updated and updated != created:
                logger.info(f"    Updated: {updated}")
            
            logger.info("-" * 60)
        
        logger.info("\n" + "=" * 60)
        logger.info("Query complete!")
        logger.info("=" * 60)
        
        # Summary stats
        total_response = supabase.table("conferences").select("id", count="exact").eq("archived", False).execute()
        total_count = total_response.count if hasattr(total_response, 'count') else len(conferences)
        
        logger.info(f"\nSummary:")
        logger.info(f"  - Total active conferences: {total_count}")
        logger.info(f"  - Displayed: {len(conferences)}")
        
    except Exception as e:
        logger.error(f"Error querying database: {str(e)}", exc_info=True)
        return False
    
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Query conferences from Supabase")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of conferences to display")
    parser.add_argument("--archived", action="store_true", help="Include archived conferences")
    args = parser.parse_args()
    
    success = query_conferences(limit=args.limit, show_archived=args.archived)
    sys.exit(0 if success else 1)


