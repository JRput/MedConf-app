"""BAPRAS (British Association of Plastic, Reconstructive and Aesthetic Surgeons) events: WordPress-family subclass.

The site is Sitefinity (not WordPress) but the listing is a plain card-per-event page: <section class="search-news__result">
with a title link, a <date> line ("28<sup>th</sup> - 30<sup>th</sup> October 2026") and a category button. Pages are /page/N.
A few cards link straight to an external registration site (Cvent), so external links are accepted.
"""
import html as _html
import re
from urllib.parse import urlparse

from .tribe_events import html_to_lines
from .wordpress_generic import _COUNTRIES, _VENUE_KW_RE, WordPressGenericExtractor, dedupe_consecutive, find_dates, pick_event_dates

_CHROME_RE = re.compile(r"(?is)<(script|style|svg|noscript|nav|footer|aside|template)\b.*?</\1\s*>")
_FEE_LABEL_RE = re.compile(r"^(registration (?:fees?|rates?)|course fees?|fees?|cost)\s*:?\s*(.*)$", re.I)
_BLOCK_END_RE = re.compile(
    r"^(?:find out more|to find out|register\b|link to book|applications? |email\b|tel\b|target audience|faculty|course dinner|cpd\b|"
    r"event (?:information|description|details)|abstract|for further|other topics|special features|topics covered|course (?:director|organiser|convenors?))", re.I)
_MONEY_RE = re.compile(r"£\s?(\d[\d,]*(?:\.\d{1,2})?)")
_EB_PAIR_RE = re.compile(r"£\s?(\d[\d,]*)\s*\(\s*early[\s-]?bird\s+(?:before|until|by)\s+([^,)]+?)\s*,?\s*£\s?(\d[\d,]*)\s+thereafter\s*\)", re.I)
_CONNECTOR_RE = re.compile(r"^(?:from|to|and|or|then|only)$", re.I)
_UK_POSTCODE_RE = re.compile(r"\s*\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b\s*$")
_LINK_RE = re.compile(r"""(?is)<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a\s*>""")
_REG_LINK_TEXT_RE = re.compile(r"(?i)find out more|register|book|click here|more information|^https?://")


class BaprasExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.bapras.org.uk/professionals/training-and-education/courses-meetings-and-events"
    SOCIETY = "BAPRAS"
    DEFAULT_SPECIALTY = "Plastic Surgery"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    PAGINATION = "path"
    EXTERNAL_LINKS = True
    # with the image <figure> removed the first link of every card is its title link (internal page or external site)
    EVENT_LINK_RE = re.compile(r"^/(?!professionals/training-and-education/courses-meetings-and-events/page/)[^?#]+$")
    CARD_SPLIT_RE = re.compile(r'<section class="search-news__result"')

    def parse_listing(self, html, url):
        html = re.sub(r"(?is)<figure class=\"search-news__image\">.*?</figure>", "", html or "")   # image-only link
        html = re.sub(r"(?i)<sup>\s*(?:st|nd|rd|th)\s*</sup>", "", html)                             # "28<sup>th</sup>" -> "28"
        html = re.sub(r'(?is)<button class="filter-button">(.*?)</button>', r'<span class="category">\1</span>', html)
        return super().parse_listing(html, url)

    def list_shells_override(self):
        shells = super().list_shells_override()
        if not shells:
            return shells
        # the congress is listed twice: its own page and a Cvent registration link ("... - 80th Anniversary") with the same dates
        internal = [s for s in shells if "bapras.org.uk" in s["booking_url"]]

        def dup(s):
            if "bapras.org.uk" in s["booking_url"]:
                return False
            t = s["title"].lower()
            return any(i["start_date"] == s["start_date"] and i["end_date"] == s["end_date"] and t.startswith(i["title"].lower()) for i in internal)
        return [s for s in shells if not dup(s)]

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html, shell, llm_call):
        # Sitefinity wraps the whole page in one ASP.NET <form id="aspnetForm">; the base strips <form> blocks as chrome
        html = re.sub(r"(?i)<form\b", "<div", html or "")
        html = re.sub(r"(?i)</form\s*>", "</div>", html)
        out = super().detail_from_html(html, shell, llm_call)
        m = re.search(r"(?is)<main\b.*?</main\s*>", html)
        body = m.group(0) if m else html
        lines = dedupe_consecutive(html_to_lines(_CHROME_RE.sub(" ", body)))
        # the page ends with a site-wide "Upcoming courses and events" teaser: not part of this event
        if "Upcoming courses and events" in lines:
            lines = lines[:lines.index("Upcoming courses and events")]

        if out.get("region") and re.match(r"^[A-Z]{2}\d$", out["region"]):     # Cvent microsite JSON-LD: country code "GB1"
            out["region"] = "United Kingdom" if out["region"] == "GB1" else None

        loc = next((re.sub(r"^location\s*:\s*", "", l, flags=re.I) for l in lines if re.match(r"^location\s*:\s*\S", l, re.I)), None)
        if loc:
            venue, city, country = self._location(loc)
            for k, v in (("venue_name", venue), ("city", city), ("region", country)):
                if v:
                    out[k] = v
                else:
                    out.pop(k, None) if k != "region" else None
            out["event_format"] = "in_person"
        elif any(re.match(r"^(?:virtual|online)\b", l, re.I) for l in lines[:6]):
            out["event_format"] = "online"
            for k in ("venue_name", "city", "region"):
                out.pop(k, None)

        tiers = self._fees(lines)
        if tiers:
            out["pricing_tiers"] = tiers

        cpd = next((re.search(r"CPD(?:\s+points?)?(?:\s+offered)?\s*:?\s*(\d+(?:\.\d+)?)\s*(?:points?)?", l, re.I) for l in lines if re.search(r"CPD[^.]*\d", l)), None)
        if cpd and not out.get("cpd_points"):
            out["cpd_points"] = float(cpd.group(1))
            out["cpd_accredited"] = True

        desc = self._description(lines)
        if desc:
            out["description"] = desc

        d = out.get("description") or ""
        if re.match(r"(?i)event date|.{0,80}overview more about event", d) or "Add to Calendar" in d:     # Cvent microsite chrome
            d = next((l for l in lines if len(l) >= 80 and not re.search(r"(?i)register|rates|secure your|cookie|sold out|waiting list", l)), "")
            out["description"] = d[:600] if d else None
            if not d:
                out.pop("description")
        if out.get("event_type") == "conference" and not re.search(r"(?i)conference|congress|meeting|symposium|summit|day\b", shell.get("title") or "") \
                and re.search(r"(?i)\bcourse\b", out.get("description") or ""):
            out["event_type"] = "course"
        if re.search(r"(?i)melanoma|skin cancer", shell.get("title") or ""):
            out["specialty"] = "Oncology"
        cut = body.find("Upcoming courses and events")        # site-wide teaser + footer links follow the event content
        ext = self._register_link(body[:cut] if cut > 0 else body)
        if ext:
            out["organiser_url"] = ext
        return out

    @staticmethod
    def _location(raw):
        """'Venue, [street,] City[ POSTCODE]' / 'City, Country' -> (venue, city, country). Free text, so conservative."""
        parts = [_UK_POSTCODE_RE.sub("", p).strip(" .") for p in re.split(r",", raw)]
        parts = [p for p in parts if p and not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}", p)]
        country = None
        if len(parts) >= 2 and parts[-1] in _COUNTRIES:
            country = parts.pop()
            if country == "UK":
                country = "United Kingdom"
        if not parts:
            return None, None, country
        if len(parts) == 1:
            if country:                                    # "Lahore, Pakistan"
                return None, parts[0], country
            return parts[0], None, None
        if _VENUE_KW_RE.search(parts[-1]):                  # "RVI Culture Centre, Video Conferencing Suite, Peacock Hall": all venue, no town
            return ", ".join(parts[:3]), None, country
        # "Engineers’ House, The Promenade, Clifton Down, Clifton, Avon, Bristol": name first, town last
        return parts[0], parts[-1], country

    def _fees(self, lines):
        start = next((i for i, l in enumerate(lines) if _FEE_LABEL_RE.match(l) and not re.search(r"£\s?\d", l.split(":")[0] if ":" in l else "")), None)
        if start is None:
            return []
        head = _FEE_LABEL_RE.match(lines[start])
        section = {"cost": "Cost"}.get(head.group(1).lower(), head.group(1).title())
        if section.lower().startswith("fee"):
            section = "Fees"
        chunk = [head.group(2)] if head.group(2) else []
        for l in lines[start + 1:start + 9]:
            if _BLOCK_END_RE.match(l) or (l.endswith(":") and not _MONEY_RE.search(l)) or l.startswith(("http", "[")):
                break
            chunk.append(l)
        text = " | ".join(chunk)
        if re.match(r"^free\b", text, re.I):
            return [self._tier(section, "Free", 0.0)]
        tiers, seen = [], set()

        def add(label, amount, early=False, deadline=None):
            key = (label, amount)
            if key not in seen:
                seen.add(key)
                tiers.append(self._tier(section, label, amount, early, deadline))

        m = _EB_PAIR_RE.search(text)                         # "£500 (Early Bird before 5 May 2027, £550 thereafter)"
        if m:
            d = pick_event_dates(m.group(2) + " 2000") if False else None
            dd = find_dates(m.group(2))
            lab = re.sub(r"\s*:?\s*$", "", text[:m.start()].split("|")[-1]).strip(" -\u2013:") or "Standard"
            lab = re.sub(r"\b(?:19|20)\d\d\s+Course$", "Course", lab) if False else lab
            add(f"{lab} \u00b7 Early bird", float(m.group(1).replace(",", "")), True, dd[0]["start"] if dd else None)
            add(f"{lab} \u00b7 After early bird", float(m.group(3).replace(",", "")))
            return tiers
        pos = 0
        for am in _MONEY_RE.finditer(text):
            if am.start() < pos:
                continue
            before = text[pos:am.start()].split("|")[-1]        # a label sits on the amount's own line
            after = text[am.end():]
            label = re.sub(r"^[\s|,;:\-\u2013\u2014]+|[\s|,;:\-\u2013\u2014]+$", "", before)
            words = label.split()
            while words and _CONNECTOR_RE.match(words[-1]):
                words.pop()
            while words and _CONNECTOR_RE.match(words[0]):
                words.pop(0)
            label = " ".join(words)
            pm = re.match(r"\s*\(([^)]*)\)", after)
            end = am.end()
            paren = None
            if pm:
                paren = pm.group(1).strip()
                if not re.match(r"(?i)inc|excl|plus|vat|ex\b", paren) and len(paren) <= 45:
                    end += pm.end()
                else:
                    paren = None
            if not label and paren:
                label = paren
            elif label and paren and not re.match(r"(?i)inc|excl|plus|vat", paren):
                label = f"{label} ({paren})"
            early = bool(re.search(r"early[\s-]?bird", label, re.I))
            deadline = None
            if early:
                dd = find_dates(re.split(r"\|", after, 1)[0], None)
                if not dd:
                    dm = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\s+(\d{4})", after)
                    dd = find_dates(" ".join(dm.groups())) if dm else []
                deadline = dd[0]["start"] if dd else None
            label = re.sub(r"\s+", " ", label).strip()
            label = (label[:1].upper() + label[1:]) if label else "Standard"
            label = re.sub(r"\s*[-\u2013\u2014]\s*(early bird)\)?$", r" (\1)", label, flags=re.I) if label.endswith(("early bird", "Early bird")) else label
            add(label[:80], float(am.group(1).replace(",", "")), early, deadline)
            pos = end
        return tiers

    def _tier(self, section, label, amount, early=False, deadline=None):
        return {"tier_label": f"{section} \u00b7 {label}", "price_gbp": amount, "currency": "GBP",
                "is_early_bird": early, "early_bird_deadline": deadline}

    @staticmethod
    def _description(lines):
        for i, l in enumerate(lines):
            if re.match(r"^(?:event (?:information|description|details))\s*:?\s*(.*)$", l, re.I):
                rest = re.sub(r"^event (?:information|description|details)\s*:?\s*", "", l, flags=re.I)
                buf = [rest] if rest else []
                for n in lines[i + 1:i + 6]:
                    if re.match(r"^(?:target audience|registration|course fees?|faculty|course dinner|other topics|special features|topics covered|find out)", n, re.I) or n.endswith(":"):
                        break
                    buf.append(n)
                text = re.sub(r"\s+", " ", " ".join(buf)).strip()
                if len(text) >= 40:
                    return text[:600]
        return None

    @staticmethod
    def _register_link(body):
        """The event's own site / registration page (fees often live there), not the site-wide teaser, tutor homepages or maps.
        A link scores 2 when the words just before it say register / find out more / book, 1 when its own text does."""
        best, best_score = None, 0
        for m in _LINK_RE.finditer(body):
            href = _html.unescape(m.group(1)).strip()
            text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
            if not href.startswith("http") or "bapras.org.uk" in href or href.endswith("/summary"):
                continue
            if re.search(r"maps\.app|reservation-highway|eventbrite.*aff=ebds", href):
                continue
            ctx = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", body[max(0, m.start() - 160):m.start()])))
            score = 2 if re.search(r"(?i)register|find out more|to find out|book|apply", ctx[-110:]) else (1 if _REG_LINK_TEXT_RE.search(text) and not re.match(r"^https?://", text) else 0)
            if score > best_score:
                # a link whose visible text is itself a URL: the visible URL is what the page promises
                best, best_score = (text if re.match(r"^https?://\S+$", text) else href), score
        return best
