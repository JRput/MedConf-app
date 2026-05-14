#!/usr/bin/env python3
"""Test script to verify all fixes are working correctly."""

import sys
from validator import validate_conference
from logger import logger

def test_cpd_points_conversion():
    """Test that cpd_points is correctly converted to integer."""
    logger.info("Testing cpd_points conversion...")
    
    test_cases = [
        ("4.5", 5),  # Should round up
        ("4.4", 4),  # Should round down
        ("4", 4),    # Already integer
        (4.5, 5),    # Float
        (4, 4),      # Integer
        ("invalid", None),  # Invalid should become None
    ]
    
    all_passed = True
    for input_val, expected in test_cases:
        test_conf = {
            "conference_name": "Test Conference",
            "source_url": "http://test.com/test",
            "cpd_points": input_val
        }
        result = validate_conference(test_conf)
        actual = result["data"]["cpd_points"]
        
        if actual != expected:
            logger.error(f"  ✗ Failed: {input_val} -> {actual} (expected {expected})")
            all_passed = False
        else:
            logger.info(f"  ✓ Passed: {input_val} -> {actual}")
    
    return all_passed

def test_required_fields():
    """Test that required fields are enforced."""
    logger.info("\nTesting required fields...")
    
    # Missing conference_name
    test1 = {"source_url": "http://test.com"}
    result1 = validate_conference(test1)
    if result1["valid"]:
        logger.error("  ✗ Should reject missing conference_name")
        return False
    logger.info("  ✓ Correctly rejects missing conference_name")
    
    # Missing source_url
    test2 = {"conference_name": "Test"}
    result2 = validate_conference(test2)
    if result2["valid"]:
        logger.error("  ✗ Should reject missing source_url")
        return False
    logger.info("  ✓ Correctly rejects missing source_url")
    
    # Both present
    test3 = {"conference_name": "Test", "source_url": "http://test.com"}
    result3 = validate_conference(test3)
    if not result3["valid"]:
        logger.error("  ✗ Should accept valid conference")
        return False
    logger.info("  ✓ Correctly accepts valid conference")
    
    return True

def test_data_types():
    """Test that data types are correct."""
    logger.info("\nTesting data types...")
    
    test_conf = {
        "conference_name": "Test Conference",
        "source_url": "http://test.com/test",
        "cpd_accredited": "true",  # String
        "abstract_open": 1,  # Integer
        "archived": False,
        "cpd_points": "4.5"
    }
    
    result = validate_conference(test_conf)
    data = result["data"]
    
    # Check booleans
    if not isinstance(data["cpd_accredited"], bool):
        logger.error(f"  ✗ cpd_accredited should be bool, got {type(data['cpd_accredited'])}")
        return False
    logger.info("  ✓ cpd_accredited is boolean")
    
    if not isinstance(data["abstract_open"], bool):
        logger.error(f"  ✗ abstract_open should be bool, got {type(data['abstract_open'])}")
        return False
    logger.info("  ✓ abstract_open is boolean")
    
    if not isinstance(data["archived"], bool):
        logger.error(f"  ✗ archived should be bool, got {type(data['archived'])}")
        return False
    logger.info("  ✓ archived is boolean")
    
    # Check cpd_points is int or None
    if data["cpd_points"] is not None and not isinstance(data["cpd_points"], int):
        logger.error(f"  ✗ cpd_points should be int or None, got {type(data['cpd_points'])}")
        return False
    logger.info(f"  ✓ cpd_points is {type(data['cpd_points']).__name__}")
    
    return True

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Testing Scraper Fixes")
    logger.info("=" * 60)
    
    all_tests_passed = True
    
    all_tests_passed &= test_cpd_points_conversion()
    all_tests_passed &= test_required_fields()
    all_tests_passed &= test_data_types()
    
    logger.info("\n" + "=" * 60)
    if all_tests_passed:
        logger.info("✓ ALL TESTS PASSED")
    else:
        logger.error("✗ SOME TESTS FAILED")
    logger.info("=" * 60)
    
    sys.exit(0 if all_tests_passed else 1)


