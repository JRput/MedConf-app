"""American Association of Gynecologic Laparoscopists (AAGL) — Tribe Events family.

aagl.org shows a "Human Verification" interstitial for the HTML listing from
runner IPs, but the Tribe JSON API answers plain HTTP. If the API is ever
challenged too, `fetch_html` falls back to the real browser automatically.
Some congress records have no API venue; their description carries a
"<dates> <year> <City>, <Country>" header that fills city/region.
"""

from .tribe_events import TribeEventsExtractor, city_country_after_year


class AaglExtractor(TribeEventsExtractor):
    API_URL = "https://aagl.org/wp-json/tribe/events/v1/events"
    SOCIETY = "AAGL"
    DEFAULT_SPECIALTY = "Women's Health"
    DEFAULT_CURRENCY = "USD"

    def location_from_text(self, text, shell):
        loc = city_country_after_year(text)
        return (None, loc[0], loc[1]) if loc else None
