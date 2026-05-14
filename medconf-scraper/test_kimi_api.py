#!/usr/bin/env python3
"""Quick test to verify Kimi K2.5 API connection and response format."""

import sys
from openai import OpenAI
from config import KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL
from logger import logger

def test_kimi_api():
    """Test basic API connection and JSON response parsing."""
    if not KIMI_API_KEY:
        logger.error("KIMI_API_KEY not set")
        return False
    
    logger.info(f"Testing Kimi K2.5 API connection...")
    logger.info(f"Model: {KIMI_MODEL}")
    logger.info(f"Base URL: {KIMI_BASE_URL}")
    
    client = OpenAI(
        api_key=KIMI_API_KEY,
        base_url=KIMI_BASE_URL
    )
    
    # Simple test prompt that should return JSON
    test_prompt = """You are a web scraping agent. Based on this page content, decide your next action.

CURRENT PAGE CONTENT:
This is a test page with sample conference information:
- Conference: Medical Innovation Summit 2024
- Dates: 2024-03-15 to 2024-03-17
- Location: London, UK

Respond ONLY with valid JSON in this exact structure:
{
    "action": "extract",
    "data": [{
        "conference_name": "Medical Innovation Summit 2024",
        "start_date": "2024-03-15",
        "end_date": "2024-03-17",
        "city": "London",
        "region": "UK"
    }],
    "reasoning": "Found conference data on page"
}"""
    
    try:
        logger.info("Sending test request to Kimi K2.5...")
        response = client.chat.completions.create(
            model=KIMI_MODEL,
            max_tokens=1000,
            temperature=0.7,
            messages=[{"role": "user", "content": test_prompt}],
            extra_body={"chat_template_kwargs": {"thinking": False}}
        )
        
        message = response.choices[0].message
        content = message.content
        
        logger.info("✓ API request successful!")
        logger.info(f"Response type: {type(content)}")
        logger.info(f"Response length: {len(content) if content else 0}")
        
        if content:
            logger.info(f"Response preview (first 200 chars): {content[:200]}")
            
            # Try to parse as JSON
            import json
            try:
                # Strip markdown code fences if present
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    parts = cleaned.split("```")
                    if len(parts) >= 2:
                        cleaned = parts[1]
                        if cleaned.startswith("json"):
                            cleaned = cleaned[4:].strip()
                
                # Find JSON object
                if not cleaned.startswith("{"):
                    start = cleaned.find("{")
                    end = cleaned.rfind("}") + 1
                    if start != -1 and end > start:
                        cleaned = cleaned[start:end]
                
                parsed = json.loads(cleaned)
                logger.info("✓ JSON parsing successful!")
                logger.info(f"Parsed JSON: {json.dumps(parsed, indent=2)}")
                return True
            except json.JSONDecodeError as e:
                logger.warning(f"⚠ JSON parsing failed: {e}")
                logger.warning(f"Raw content: {content}")
                return False
        else:
            logger.error("✗ No content in response")
            # Check for reasoning content
            if hasattr(message, 'model_extra') and message.model_extra:
                logger.info(f"model_extra keys: {list(message.model_extra.keys())}")
            return False
            
    except Exception as e:
        logger.error(f"✗ API request failed: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_kimi_api()
    sys.exit(0 if success else 1)


