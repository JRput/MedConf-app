"""European Society of Pathology (ESP) — Tribe Events family.

The API record has no venue for most events; the description opens with a
header line "<Title> <dates> <City>, <Country>" and sometimes "Venue: ...".
Fees are listed as "Registration Fees / ESP Members* ... / EUR 380" lines.
"""

import re
from .tribe_events import TribeEventsExtractor, city_country_after_year


class EspPathologyExtractor(TribeEventsExtractor):
    API_URL = "https://www.esp-pathology.org/wp-json/tribe/events/v1/events"
    SOCIETY = "ESP"
    DEFAULT_SPECIALTY = "Pathology"
    DEFAULT_CURRENCY = "EUR"
    PREFER_DEFAULT_SPECIALTY = True   # every ESP event is pathology ("Perinatal" etc. must not retag)

    def location_from_text(self, text, shell):
        loc = city_country_after_year(text)
        v = re.search(r"\bVenue:\s*(.+)", text)
        venue = v.group(1) if v else None   # trimmed by clean_prose_venue downstream
        if not (loc or venue):
            return None
        return venue, (loc[0] if loc else None), (loc[1] if loc else None)
