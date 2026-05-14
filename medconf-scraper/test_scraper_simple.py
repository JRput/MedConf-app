#!/usr/bin/env python3
"""Simplified test that just verifies the scraper can launch browser and make one LLM call."""

import sys
from config import validate_config, KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL
from llm_agent import AgentLoop
from logger import logger

# Minimal test source
TEST_SOURCE = {
    "id": 999,
    "source_name": "RCGP Events (Test)",
    "base_url": "https://www.rcgp.org.uk/events",
    "extraction_instructions": "Find all upcoming medical conferences. Extract: name, dates, location, CPD points, pricing tiers.",
    "active": True
}

def test_scraper_basic():
    """Test that the scraper can launch browser and make at least one LLM call."""
    try:
        validate_config()
    except EnvironmentError as e:
        logger.warning(f"Config warning: {e}")
    
    if not KIMI_API_KEY:
        logger.error("KIMI_API_KEY not set")
        return False
    
    logger.info("=" * 60)
    logger.info("Testing Agentic Scraper with Kimi K2.5")
    logger.info("=" * 60)
    logger.info(f"Source: {TEST_SOURCE['source_name']}")
    logger.info(f"URL: {TEST_SOURCE['base_url']}")
    logger.info(f"Model: {KIMI_MODEL}")
    logger.info("=" * 60)
    
    try:
        # Create agent
        agent = AgentLoop(TEST_SOURCE)
        
        # Launch browser
        logger.info("Launching browser...")
        agent.browser.launch()
        logger.info("✓ Browser launched")
        
        # Navigate to page
        logger.info(f"Navigating to {TEST_SOURCE['base_url']}...")
        page_text = agent.browser.navigate(TEST_SOURCE['base_url'])
        logger.info(f"✓ Page loaded ({len(page_text)} characters)")
        
        # Make one LLM decision
        logger.info("Making first LLM decision call...")
        logger.info("(This may take 1-2 minutes...)")
        decision = agent._get_llm_decision(page_text)
        logger.info("✓ LLM decision received!")
        logger.info(f"Action: {decision.get('action')}")
        logger.info(f"Reasoning: {decision.get('reasoning', 'N/A')}")
        
        if decision.get('action') == 'extract':
            data_count = len(decision.get('data', []))
            logger.info(f"Extracted {data_count} conference(s)")
            if data_count > 0:
                logger.info(f"Sample conference: {decision['data'][0].get('conference_name', 'N/A')}")
        
        # Clean up
        agent.browser.close()
        logger.info("✓ Browser closed")
        
        logger.info("=" * 60)
        logger.info("✓ TEST PASSED - Scraper is working!")
        logger.info("=" * 60)
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST FAILED: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_scraper_basic()
    sys.exit(0 if success else 1)


