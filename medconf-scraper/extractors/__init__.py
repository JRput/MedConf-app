# extractors/__init__.py
"""
Per-source detail-page extractors.

Each source (RCGP, RCSEng, RSM, future sources) gets its own extractor module
that knows the HTML structure of that source's event detail pages. A registry
maps source_id (or source_name) to the matching extractor.

Architecture:
- Listing-page extraction (browser.get_event_cards) is GENERIC across sources.
- Detail-page extraction is PER-SOURCE because event detail pages have
  highly varied markup for pricing, venue, dates, etc.
- If no extractor is registered for a source, the FallbackExtractor uses the
  generic LLM-only extraction path (the previous default behaviour).

To onboard a new source:
1. Inspect a few of its event detail pages.
2. Create extractors/<source_slug>.py with a class implementing extract_detail().
3. Register it in EXTRACTOR_REGISTRY below.
"""

from typing import Dict, Any, Optional

from .base import BaseExtractor
from .fallback import FallbackExtractor
from .rsm import RSMExtractor
from .rcseng import RCSEngExtractor
from .rcgp import RCGPExtractor
from .rcp import RCPExtractor

# source_id → extractor class
# IDs come from the scraper_sources table (see Supabase).
EXTRACTOR_REGISTRY: Dict[int, type[BaseExtractor]] = {
    1: RCGPExtractor,                   # Royal College of General Practitioners
    2: RCSEngExtractor,                 # Royal College of Surgeons of England
    3: RSMExtractor,                    # Royal Society of Medicine
    4: RCPExtractor,                    # Royal College of Physicians
}


def get_extractor(source: Dict[str, Any]) -> BaseExtractor:
    """
    Return the registered extractor for a source, or the fallback if none.

    `source` is the row from scraper_sources (must include 'id').
    """
    cls = EXTRACTOR_REGISTRY.get(source["id"], FallbackExtractor)
    return cls(source)


__all__ = ["get_extractor", "BaseExtractor", "FallbackExtractor", "RSMExtractor"]
