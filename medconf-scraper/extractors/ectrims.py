"""ECTRIMS (ECTRIMS congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class EctrimsExtractor(SingleCongressExtractor):
    HOME_URL = "https://ectrims.eu/events-ectrims-congress"
    SOCIETY = "ECTRIMS"
    EVENT_NAME = "ECTRIMS"
    DEFAULT_SPECIALTY = "Neurology"
    DEFAULT_CURRENCY = "EUR"

    def edition_title(self, ed):
        # The congress is the joint ACTRIMS-ECTRIMS meeting in 2026: use the edition site's own title ("MSToronto 2026 - 10th Joint ...").
        t = (ed.get("page_title") or "").replace(" – ", ": ").replace(" - ", ": ")
        return t if t and str(ed["year"]) in t else super().edition_title(ed)
