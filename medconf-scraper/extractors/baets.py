"""British Association of Endocrine and Thyroid Surgeons (BAETS) — Tribe Events family."""

from .tribe_events import TribeEventsExtractor


class BaetsExtractor(TribeEventsExtractor):
    API_URL = "https://www.baets.org.uk/wp-json/tribe/events/v1/events"
    SOCIETY = "BAETS"
    DEFAULT_SPECIALTY = "Surgery (General)"
    DEFAULT_CURRENCY = "GBP"
