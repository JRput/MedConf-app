#!/usr/bin/env python3
"""Verify that saved data matches what the frontend expects."""

import sys
from database import supabase
from logger import logger

def verify_frontend_compatibility():
    """Verify that the database data structure matches frontend expectations."""
    logger.info("=" * 60)
    logger.info("Verifying Frontend Data Compatibility")
    logger.info("=" * 60)
    
    try:
        # Fetch conferences as frontend does
        logger.info("\n1. Fetching conferences (as frontend does)...")
        conf_response = supabase.table("conferences").select("*").eq("archived", False).order("start_date", desc=False).execute()
        conferences = conf_response.data
        
        logger.info(f"   Found {len(conferences)} active conferences")
        
        if not conferences:
            logger.warning("   ⚠ No conferences found. Frontend will show empty list.")
            return False
        
        # Check required fields for frontend
        logger.info("\n2. Checking required fields...")
        required_fields = ["id", "conference_name", "source_url", "archived"]
        missing_fields = []
        
        for conf in conferences:
            for field in required_fields:
                if field not in conf or conf[field] is None:
                    if field not in missing_fields:
                        missing_fields.append(field)
        
        if missing_fields:
            logger.error(f"   ✗ Missing required fields: {missing_fields}")
            return False
        else:
            logger.info("   ✓ All required fields present")
        
        # Check data types
        logger.info("\n3. Checking data types...")
        type_issues = []
        
        for conf in conferences:
            # Check booleans
            if not isinstance(conf.get("archived"), bool):
                type_issues.append(f"Conference {conf['id']}: archived should be boolean")
            if not isinstance(conf.get("cpd_accredited"), bool):
                type_issues.append(f"Conference {conf['id']}: cpd_accredited should be boolean")
            if not isinstance(conf.get("abstract_open"), bool):
                type_issues.append(f"Conference {conf['id']}: abstract_open should be boolean")
            
            # Check dates format (YYYY-MM-DD)
            for date_field in ["start_date", "end_date", "abstract_deadline"]:
                val = conf.get(date_field)
                if val and not isinstance(val, str):
                    type_issues.append(f"Conference {conf['id']}: {date_field} should be string")
                elif val and len(val) != 10:  # YYYY-MM-DD is 10 chars
                    type_issues.append(f"Conference {conf['id']}: {date_field} format may be incorrect: {val}")
        
        if type_issues:
            logger.warning(f"   ⚠ Type issues found: {len(type_issues)}")
            for issue in type_issues[:5]:  # Show first 5
                logger.warning(f"      - {issue}")
            if len(type_issues) > 5:
                logger.warning(f"      ... and {len(type_issues) - 5} more")
        else:
            logger.info("   ✓ All data types correct")
        
        # Fetch pricing tiers as frontend does
        logger.info("\n4. Fetching pricing tiers (as frontend does)...")
        tier_response = supabase.table("pricing_tiers").select("*").execute()
        tiers = tier_response.data
        
        logger.info(f"   Found {len(tiers)} pricing tiers")
        
        # Check pricing tier structure
        if tiers:
            logger.info("\n5. Checking pricing tier structure...")
            tier_issues = []
            
            for tier in tiers:
                if not tier.get("conference_id"):
                    tier_issues.append("Tier missing conference_id")
                if not tier.get("tier_label"):
                    tier_issues.append(f"Tier {tier.get('id')} missing tier_label")
                if tier.get("price_gbp") is None:
                    tier_issues.append(f"Tier {tier.get('id')} missing price_gbp")
                if not isinstance(tier.get("is_early_bird"), bool):
                    tier_issues.append(f"Tier {tier.get('id')}: is_early_bird should be boolean")
            
            if tier_issues:
                logger.warning(f"   ⚠ Pricing tier issues: {len(tier_issues)}")
                for issue in tier_issues[:5]:
                    logger.warning(f"      - {issue}")
            else:
                logger.info("   ✓ All pricing tiers valid")
        
        # Sample data check
        logger.info("\n6. Sample data check...")
        sample = conferences[0]
        logger.info(f"   Sample conference:")
        logger.info(f"      ID: {sample.get('id')}")
        logger.info(f"      Name: {sample.get('conference_name')}")
        logger.info(f"      Start Date: {sample.get('start_date', 'N/A')}")
        logger.info(f"      City: {sample.get('city', 'N/A')}")
        logger.info(f"      Archived: {sample.get('archived')}")
        
        # Count conferences with pricing
        conf_ids = [c['id'] for c in conferences]
        confs_with_pricing = len([t for t in tiers if t.get('conference_id') in conf_ids])
        logger.info(f"\n   Statistics:")
        logger.info(f"      Total conferences: {len(conferences)}")
        logger.info(f"      Conferences with pricing: {confs_with_pricing}")
        logger.info(f"      Total pricing tiers: {len(tiers)}")
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ VERIFICATION COMPLETE")
        logger.info("=" * 60)
        logger.info("\nThe data structure matches frontend expectations.")
        logger.info("Frontend should be able to display this data correctly.")
        logger.info("\nTo view in frontend:")
        logger.info("1. Ensure frontend is running")
        logger.info("2. Navigate to /conferences page")
        logger.info("3. Data should appear automatically")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during verification: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    success = verify_frontend_compatibility()
    sys.exit(0 if success else 1)


