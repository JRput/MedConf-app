"""ERS (European Respiratory Society) events: constants-only WordPress family subclass."""
import re

from .wordpress_generic import _COUNTRIES, WordPressGenericExtractor


class ErsnetExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.ersnet.org/events/"
    SOCIETY = "ERS"
    DEFAULT_SPECIALTY = "Respiratory Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    # the card grid also links to channel.ersnet.org: /event-NNN-... (conferences) and /media-NNN-... (webinars)
    EVENT_LINK_RE = re.compile(r"^/(?:events/(?!page/)[^/?#]+|event-\d+[^/?#]*|media-\d+[^/?#]*)/?$")

    def venue_from_lines(self, lines, shell):
        """Venue panel: either a second 'Venue' heading (the first is the tab) followed by the address lines,
        or an unheaded block right before 'Cancellation policy'. Both end with the country line."""
        heads = [i for i, l in enumerate(lines) if l == "Venue"]
        if len(heads) >= 2:
            block = []
            for ln in lines[heads[1] + 1:heads[1] + 9]:
                if re.match(r"(?i)tel\b|phone|e-?mail|website", ln):
                    continue
                block.append(ln)
                if ln in _COUNTRIES:
                    return ", ".join(block)
            return None
        if "Cancellation policy" not in lines:
            return None
        block = []
        for ln in reversed(lines[:lines.index("Cancellation policy")]):
            if len(ln) > 60 or re.search(r"[\u20ac\u00a3$]|member|fee", ln, re.I) or len(block) >= 6:
                break
            block.append(ln)
        block.reverse()
        return ", ".join(block) if block and block[-1] in _COUNTRIES else None
