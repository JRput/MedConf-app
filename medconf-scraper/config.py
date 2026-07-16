# config.py
"""Configuration module - loads environment variables and exposes them as constants."""

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys - Kimi K2.5 via NVIDIA API
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Scraper configuration
SCRAPER_MAX_STEPS = int(os.getenv("SCRAPER_MAX_STEPS", "30"))
SCRAPER_DELAY_SECS = int(os.getenv("SCRAPER_DELAY_SECONDS", "2"))
# Default Playwright page.goto / locator timeout. Raised 10 s → 30 s
# after RCEM's on-demand listing timed out on 2 of 4 daily scrapes in
# July 2026 — the site occasionally takes 15-20 s to render at 05:00 UTC.
SCRAPER_TIMEOUT_MS = int(os.getenv("SCRAPER_TIMEOUT_MS", "30000"))

# Validate required configuration
def validate_config():
    """Check that all required configuration is present."""
    missing = []
    if not KIMI_API_KEY:
        missing.append("KIMI_API_KEY")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
