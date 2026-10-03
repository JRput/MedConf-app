"""American Association of Neurological Surgeons (AANS) — Tribe Events family."""

from .tribe_events import TribeEventsExtractor


class AansExtractor(TribeEventsExtractor):
    API_URL = "https://www.aans.org/wp-json/tribe/events/v1/events"
    SOCIETY = "AANS"
    DEFAULT_SPECIALTY = "Neurology"
    DEFAULT_CURRENCY = "USD"
    PREFER_DEFAULT_SPECIALTY = True   # every AANS event is neurosurgery
