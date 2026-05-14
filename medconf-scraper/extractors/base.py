# extractors/base.py
"""Base class for per-source detail-page extractors."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable
from playwright.sync_api import Page


class BaseExtractor(ABC):
    """
    Abstract interface every per-source extractor implements.

    The contract:
      - The Browser has already navigated to a single event's detail URL.
      - extract_detail() reads structured data from that page and returns a
        dict of the conference fields.
      - Soft fields (description, specialty) may use llm_call() for the
        small fraction of work that genuinely needs reasoning.
    """

    def __init__(self, source: Dict[str, Any]):
        self.source = source
        self.source_id = source["id"]
        self.source_name = source.get("source_name", "")

    @abstractmethod
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        """
        Extract all detail-page fields for the event currently loaded in `page`.

        Args:
          page: Playwright Page already navigated to the event detail URL.
          shell: The listing-level shell dict (title, booking_url, dates, etc.)
                 from get_event_cards. Useful for context and as fallback values.
          llm_call: Helper that takes a prompt string and returns the model's
                    raw response text (or None on failure). Use this only for
                    fields that genuinely need reasoning.

        Returns a dict with any subset of the conference fields:
          description, specialty, venue_name, city, region, event_format,
          cpd_points, cpd_accredited, end_date, start_time (if not in shell),
          abstract_open, abstract_deadline, pricing_tiers
        """
        ...

    @staticmethod
    def parse_gbp(price_text: str) -> Optional[float]:
        """Parse a £-prefixed string to a float. Handles £0.00, £1,234.50, etc."""
        if not price_text:
            return None
        import re
        m = re.search(r"£\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", price_text)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
