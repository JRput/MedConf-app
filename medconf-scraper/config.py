# config.py
"""Configuration module - loads environment variables and exposes them as constants."""

import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# API Keys - Kimi K2.5 via NVIDIA API
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")


def _parse_chain(env_value: Optional[str], default_list: List[str], override: Optional[str]) -> List[str]:
    """Build a model fallback chain: KIMI_MODEL(_VISION) override goes first
    (dedupe), then the comma-separated KIMI_MODEL(_VISION)_CHAIN env var if
    set, else the hardcoded default list."""
    chain = [m.strip() for m in env_value.split(",") if m.strip()] if env_value else list(default_list)
    if override:
        chain = [override] + [m for m in chain if m != override]
    # dedupe while preserving order
    seen = set()
    out = []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


# 2026-08-26: NVIDIA killed meta/llama-3.3-70b-instruct (our post-07-31
# replacement for the moonshotai/kimi-k2.* family) and its backup with no
# warning — every text call had been silently failing since (heuristics
# backstopped the soft fields, so CI stayed green). Probed live 2026-09-20
# with valid JSON output: nemotron-3-super-120b-a12b (fastest, ~4s),
# muse-glimmer-30b (~2s, needs max_tokens>=1024, see llm_client.py),
# gpt-oss-20b (reasoning model — burns tokens on <thinking>, needs a
# higher max_tokens floor too). llm_client.chat_completion() walks this
# chain and advances past any model that 404s/410s.
_KIMI_MODEL_CHAIN_DEFAULT = [
    "nvidia/nemotron-3-super-120b-a12b",
    "meta/muse-glimmer-30b",
    "openai/gpt-oss-20b",
]
KIMI_MODEL_CHAIN = _parse_chain(os.getenv("KIMI_MODEL_CHAIN"), _KIMI_MODEL_CHAIN_DEFAULT, os.getenv("KIMI_MODEL"))
# Kept for backward compat with any code/log message that still reads a
# single model name — always the first (current-best) model in the chain.
KIMI_MODEL = KIMI_MODEL_CHAIN[0]

# Vision model chain. Both entries confirmed live and multimodal as of
# 2026-09-20 — see vision.py's rotation log for the multi-column
# fee-table evaluation (synthetic table only; muse-glimmer-30b was
# faster and doesn't carry 11b's known column-collapse history).
_KIMI_VISION_MODEL_CHAIN_DEFAULT = [
    "meta/muse-glimmer-30b",
    "meta/llama-3.2-11b-vision-instruct",
]
KIMI_VISION_MODEL_CHAIN = _parse_chain(
    os.getenv("KIMI_VISION_MODEL_CHAIN"), _KIMI_VISION_MODEL_CHAIN_DEFAULT, os.getenv("KIMI_VISION_MODEL")
)
KIMI_VISION_MODEL = KIMI_VISION_MODEL_CHAIN[0]

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
