"""ESICM (European Society of Intensive Care Medicine) events: WordPress-family subclass.

/congresses-events/ has a "Next events" grid followed by a "Past events" grid that is filled by infinite scroll
(admin-ajax). Only the first grid is upcoming, so the page is cut at the "Past events" heading and no pagination
is followed. Detail pages open with "[LIVES, ]Month DD-DD, YYYY, City[ (Venue)]" (+ a venue line); the congress
page has real fee grids (member / non-member rows x early / standard / late / one-day columns), parsed here.
"""
import html as _html
import re
from datetime import date

from .tribe_events import html_to_lines
from .wordpress_generic import (_COUNTRIES, WordPressGenericExtractor, dedupe_consecutive, _DETAIL_CHROME_RE)

_HEADER_RE = re.compile(
    r"^(?:[A-Z][A-Za-z&\- ]{1,30},\s+)?(?P<mon>[A-Z][a-z]+)\s+\d{1,2}(?:\s*[-&]\s*\d{1,2})?,\s+(?P<y>\d{4}),\s+(?P<city>[^()]+?)\s*(?:\((?P<venue>[^)]*)\))?\s*$")
_PRICE_RE = re.compile(r"^\s*(?:€\s*)?(\d[\d,.]*)\s*(?:€|EUR)?\s*$")
_MON = {m: i + 1 for i, m in enumerate("January February March April May June July August September October November December".split())}
_BOILER_RE = re.compile(r"(?i)^fraud alert|^the official (?:email|provider)|^official email|beware of email|^registrations? details|^call for abstracts")


def _cells(row_html):
    return [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", row_html)]


class EsicmExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.esicm.org/congresses-events/"
    SOCIETY = "ESICM"
    DEFAULT_SPECIALTY = "Intensive Care Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    EVENT_LINK_RE = re.compile(r"^/events/[^/?#]+/?$")
    CARD_SPLIT_RE = re.compile(r'<a class="esicm-news-item"')

    def parse_listing(self, html, url):
        m = re.search(r"(?i)<h2[^>]*>\s*Past events\s*</h2>", html or "")
        return super().parse_listing(html[:m.start()] if m else html, url)

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html, shell, llm_call):
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(_DETAIL_CHROME_RE.sub(" ", html)))
        title = re.sub(r"\W+", "", (shell.get("title") or "").lower())
        ti = next((i for i, l in enumerate(lines) if re.sub(r"\W+", "", l.lower()) == title), None)
        head = lines[ti + 1:ti + 7] if ti is not None else []

        # "LIVES, October 10-14, 2026, Lisbon (CCL, Lisboa Congress Centre)" / "February 04-05, 2027, Milan" + venue line
        city = venue = None
        for k, l in enumerate(head):
            m = _HEADER_RE.match(l)
            if m and m.group("mon") in _MON:
                city = re.sub(r"\s+[a-z]$", "", m.group("city").strip(" ,"))          # "Sao Paulo l" -> "Sao Paulo"
                venue = (m.group("venue") or "").strip() or None
                if venue and "," in venue:
                    first, rest = [x.strip() for x in venue.split(",", 1)]
                    if re.fullmatch(r"[A-Z]{2,5}", first):                                  # "CCL, Lisboa Congress Centre"
                        venue = rest
                if not venue and k + 1 < len(head) and "," in head[k + 1] and not _BOILER_RE.search(head[k + 1]) and len(head[k + 1]) < 160:
                    venue = head[k + 1].split(",")[0].strip()                              # "Humanitas Congress Center, via ... Rozzano"
                    if re.search(r"\d", venue):
                        venue = None
                break
        if city:
            out["city"] = city
            out["event_format"] = "in_person"
        if venue:
            out["venue_name"] = venue
        country = None
        for i, l in enumerate(lines):                                                   # "Venue Address / ... / 1300-307 Lisbon, Portugal"
            if re.match(r"^venue address$", l, re.I):
                for n in lines[i + 1:i + 5]:
                    tail = n.split(",")[-1].strip()
                    if tail in _COUNTRIES or n in _COUNTRIES:
                        country = tail if tail in _COUNTRIES else n
                        break
                break
        if country:
            out["region"] = country

        # event type: these are all conferences / forums; keep the base answer only for obvious teaching formats
        if not re.search(r"(?i)datathon|workshop|webinar|course|masterclass", shell.get("title") or ""):
            out["event_type"] = "conference"

        # cpd: the base reads "November 2026 CME Credits" as 2026 points
        cp = out.get("cpd_points")
        if cp is not None and (cp > 100 or 1990 <= cp <= 2100):
            out.pop("cpd_points", None)
            out.pop("cpd_accredited", None)

        grid = self._fee_grids(html, out.get("start_date") or shell.get("start_date"))
        if grid:
            out["pricing_tiers"] = grid
        elif not out.get("pricing_tiers"):
            for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", html):
                label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
                if re.match(r"(?i)^register(?: now)?$|^individual registration$", label) and "esicm.org" not in m.group(1):
                    out["organiser_url"] = _html.unescape(m.group(1))
                    break

        desc = next((l for l in (lines[ti + 1:] if ti is not None else lines) if len(l) >= 80 and not _BOILER_RE.search(l)), None)
        if desc:
            out["description"] = desc[:600]
        return out

    def _fee_grids(self, html, start_iso):
        """<table> grids: header row = [group, timeframe...], then category rows with one price per timeframe;
        a row with no prices (e.g. NON-MEMBER) switches the group. Section = nearest heading above the table."""
        tiers, seen = [], set()
        yr = int(start_iso[:4]) if start_iso else date.today().year
        for tm in re.finditer(r"(?is)<table\b.*?</table\s*>", html):
            tbl = tm.group(0)
            if "€" not in tbl:
                continue
            hs = re.findall(r"(?is)<h[1-5][^>]*>(.*?)</h[1-5]\s*>", html[:tm.start()])
            section = re.sub(r"\s+[-–]\s+.*$|\s*\(.*$", "", re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", hs[-1]))).strip()) if hs else "Registration"
            section = section.title() if section.isupper() else section
            rows = [_cells(r) for r in re.findall(r"(?is)<tr\b.*?</tr\s*>", tbl)]
            rows = [r for r in rows if r]
            if len(rows) < 2:
                continue
            header = rows[0]
            group = header[0] if header and header[0] and not _PRICE_RE.match(header[0]) else ""
            for r in rows[1:]:
                prices = [(j, _PRICE_RE.match(c)) for j, c in enumerate(r) if j > 0 and _PRICE_RE.match(c)]
                if not prices:
                    if r and r[0]:
                        group = r[0]
                    continue
                cat = re.sub(r"\*+", "", r[0]).strip()
                gname = {"esicm member": "ESICM member", "non-member": "Non-member"}.get(group.lower(), group.title()) if group else ""
                if group and cat.lower() == group.lower():
                    cat = ""
                cat = {"esicm member": "ESICM member", "non-member": "Non-member"}.get(cat.lower(), cat)
                category = " – ".join(x for x in (gname, cat) if x) or "Standard"
                for j, pm in prices:
                    tf = re.sub(r"\s+", " ", re.sub(r"\*+", "", header[j] if j < len(header) else "")).strip() or "Standard"
                    amt = float(pm.group(1).replace(",", ""))
                    early = bool(re.search(r"(?i)\bearly\b|^until", tf)) and not re.search(r"(?i)\bnot\b", tf)
                    dl = None
                    dm = re.search(r"(?i)until\s+(\d{1,2})\s+([A-Z][a-z]+)", tf)
                    if early and dm and dm.group(2) in _MON:
                        try:
                            dl = date(yr, _MON[dm.group(2)], int(dm.group(1))).isoformat()
                        except ValueError:
                            dl = None
                    label = f"{section} · {category} · {tf}"[:150]
                    if (label, amt) in seen:
                        continue
                    seen.add((label, amt))
                    tiers.append({"tier_label": label, "price_gbp": amt, "currency": "EUR", "is_early_bird": early, "early_bird_deadline": dl})
        return tiers
