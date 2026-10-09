"""ERA (European Renal Association) events: WordPress-family subclass with four shell sources.

era-online.org has no single event archive, so list_shells_override() merges:
  A. /events/other-events/  - blocks "title / 'Month D - D, YYYY<br>City, Country' / VISIT THE EVENT WEBSITE": third-party
     meetings that ERA endorses. The card links straight to the organiser's own site (booking_url), so Phase B only reads
     that site for a description and fee tables; dates and place come from the block.
  B. ERA Congress pages /events/<city>-<year>/ linked from that page ("Official information about the 64th ERA Congress,
     Rotterdam & Virtual, June 3-6, 2027").
  C. ERA Education Meetings: blocks on /events/era-education-meetings/ whose text says "will take place".
  D. ERA CME courses: /cme-courses/ own pages (IWG, CKD-MBD ...; dd/mm/yyyy range + Venue: + fee lines) and the Registry
     epidemiology course page.
Invitation-only ERA Science Meetings are skipped.
"""
import html as _html
import re
import time
from datetime import date

from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, dedupe_consecutive, find_dates, find_start_time, split_location,
                                _DETAIL_CHROME_RE, _iso, _meta, _mon)
from .http_fetch import fetch_html
from logger import logger

_ROOT = "https://www.era-online.org"
_BLOCK_SPLIT = "<!-- block17 -->"
_DMY_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:-|–|to)\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_TAKES_RE = re.compile(r"will take place (?:on )?([A-Z][a-z]+ \d{1,2}\s*[-–]\s*\d{1,2}(?:,\s*\d{4})?)(?:,?\s*in\s+([A-Z][^.<]+?))?[.<]")


def _text(fragment):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


class EraExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.era-online.org/events/other-events/"
    SOCIETY = "ERA"
    DEFAULT_SPECIALTY = "Nephrology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"

    # ---- listing -----------------------------------------------------------
    def _get(self, url):
        time.sleep(self.REQUEST_GAP_S)
        return fetch_html(url, browser=getattr(self, "browser", None))

    def list_shells_override(self):
        today = date.today().isoformat()
        listing = self._fetch(self.LISTING_URL)
        if listing is None:
            return None
        shells = self._other_events(listing)
        for url in sorted(set(re.findall(r"https://www\.era-online\.org/events/([a-z\-]+-20\d\d)/", listing))):
            sh = self._congress(f"{_ROOT}/events/{url}/")
            if sh:
                shells.append(sh)
        shells += self._education()
        shells += self._cme()
        out, seen = [], set()
        for s in shells:
            if (s["end_date"] or s["start_date"]) < today or s["booking_url"] in seen:
                continue
            if (date.fromisoformat(s["start_date"]) - date.today()).days > self.MAX_FUTURE_DAYS:
                continue
            seen.add(s["booking_url"])
            out.append(s)
        logger.info(f"ERA: {len(out)} shells")
        return out or None

    @staticmethod
    def _shell(title, url, start, end, venue_raw=None, kind="ext", category=None):
        return {"title": title, "booking_url": url, "source_url": url, "start_date": start, "end_date": end or start,
                "start_time": None, "venue_raw": venue_raw, "category": category, "era_kind": kind}

    def _other_events(self, html):
        main = re.search(r"(?is)<main.*?</main>", html)
        out = []
        for b in (main.group(0) if main else html).split(_BLOCK_SPLIT):
            h2 = re.search(r"(?is)<h2[^>]*>(.*?)</h[26]>", b)
            link = re.search(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>\s*VISIT THE EVENT WEBSITE""", b)
            if not h2 or not link:
                continue
            title = _text(h2.group(1))
            para = next((m for m in re.findall(r"(?is)<p>(.*?)</p>", b) if find_dates(_text(m))), None)
            if not para:
                continue
            dline, _, place = re.sub(r"(?i)<br\s*/?>", "\n", para).partition("\n")
            dates = find_dates(_text(dline))
            if not dates:
                continue
            place = _text(place)
            out.append(self._shell(title, _html.unescape(link.group(1)).strip(), dates[0]["start"], dates[0]["end"],
                                   place or None, "ext", "Endorsed event"))
        return out

    def _congress(self, url):
        page = self._get(url)
        if not page:
            return None
        sub = re.search(r"Official information about the (\d+\w+) ERA Congress,\s*([^,]+?),\s*([A-Z][a-z]+ \d{1,2}\s*[-–]\s*\d{1,2},\s*\d{4})", _text(page))
        if not sub:
            return None
        d = find_dates(sub.group(3))
        if not d:
            return None
        city = re.sub(r"\s*&.*$", "", sub.group(2)).strip()
        lines = html_to_lines(_DETAIL_CHROME_RE.sub(" ", page))
        venue = next((lines[i + 1] for i, l in enumerate(lines[:-1]) if re.match(r"^Congress venue \d{4}$", l)), None)
        return self._shell(f"ERA Congress {d[0]['start'][:4]} – {city}", url, d[0]["start"], d[0]["end"],
                           f"{venue}, {city}" if venue else city, "congress", "Congress")

    def _education(self):
        """'The fifth Education Meeting will take place on March 23-24, 2027, in Cairo, Egypt' (past ones say 'took place');
        the detail URL is the era-education-<city>-<year> link with that city in its slug."""
        page = self._get(f"{_ROOT}/events/era-education-meetings/")
        out = []
        if not page:
            return out
        links = re.findall(r"""href=["'](https://www\.era-online\.org/events/era-education-meetings/era-education-[a-z0-9\-]+/)["']""", page)
        txt = _text(page)
        for m in re.finditer(r"will take place on ([A-Z][a-z]+ \d{1,2}\s*[-\u2013]\s*\d{1,2}, \d{4}), in ([A-Z][\w ]+?), ([A-Z][\w ]+?)(?: in collaboration|[.,])", txt):
            d = find_dates(m.group(1))
            url = next((l for l in links if re.sub(r"\W+", "", m.group(2)).lower() in l.replace("-", "")), None)
            if d and url:
                out.append(self._shell(f"ERA Education Meeting \u2013 {m.group(2)} {d[0]['start'][:4]}", url, d[0]["start"], d[0]["end"],
                                       f"{m.group(2)}, {m.group(3)}", "edu", "Education Meeting"))
        return out

    def _cme(self):
        page = self._get(f"{_ROOT}/cme-courses/")
        out = []
        if not page:
            return out
        for m in re.finditer(r"""href=["'](https://www\.era-online\.org/cme-courses/[a-z0-9\-]+/)["']""", page):
            url = m.group(1)
            if any(s["booking_url"] == url for s in out):
                continue
            body = self._get(url)
            if not body:
                continue
            txt = _text(body)
            dm = _DMY_RE.search(txt)
            title = _text(re.search(r"(?is)<h1[^>]*>(.*?)</h1>", body).group(1)) if re.search(r"(?is)<h1", body) else None
            if not (dm and title):
                continue
            s, e = _iso(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))), _iso(int(dm.group(6)), int(dm.group(5)), int(dm.group(4)))
            vm = re.search(r"Venue:\s*([^.]+?)(?:\s{2,}|Scientific|$)", txt)
            lines = html_to_lines(_DETAIL_CHROME_RE.sub(" ", body))
            ti = next((i for i, l in enumerate(lines) if l == title), None)
            sub = next((l for l in lines[ti + 1:ti + 4] if not re.match(r"(?i)register|save the date", l)), None) if ti is not None else None
            out.append(self._shell(f"{title}: {sub}" if sub else title, url, s, e, vm.group(1).strip() if vm else None, "cme", "CME course"))
        # Registry epidemiology course: its own section on the Registry education page
        reg = self._get(f"{_ROOT}/research-education/era-registry/education/")
        if reg:
            t = _text(reg)
            em = re.search(r"The (20\d\d) edition will take place in ([A-Z][\w ]+), ([A-Z][\w ]+), on ([A-Z][a-z]+ \d{1,2}\s*[-–]\s*\d{1,2})", t)
            if em:
                d = find_dates(f"{em.group(4)}, {em.group(1)}")
                if d:
                    out.append(self._shell(f"{em.group(1)} CME “Introductory Course on Epidemiology” by the ERA Registry",
                                           f"{_ROOT}/research-education/era-registry/education/", d[0]["start"], d[0]["end"],
                                           f"{em.group(2)}, {em.group(3)}", "reg", "CME course"))
        return out

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html, shell, llm_call):
        kind = shell.get("era_kind", "ext")
        if kind == "ext":
            return self._external(html, shell)
        out = super().detail_from_html(html, shell, llm_call)
        out["society"] = self.SOCIETY
        if kind == "congress":
            out["event_type"] = "conference"
            out["event_format"] = "hybrid"                # "both virtual and live in Rotterdam"
        elif kind in ("cme", "reg"):
            out["event_type"] = "course"
        elif kind == "edu":
            out["event_type"] = "conference"
        out["start_date"], out["end_date"] = shell["start_date"], shell["end_date"]
        if kind == "congress":
            parts = [p.strip() for p in (shell.get("venue_raw") or "").split(",")]
            if len(parts) == 2:
                out["venue_name"], out["city"] = parts
        txt = _text(html)
        main = re.search(r"(?is)<main\b.*?</main\s*>", html)
        mlines = dedupe_consecutive(html_to_lines(_DETAIL_CHROME_RE.sub(" ", main.group(0) if main else html)))
        d = next((l for l in mlines if len(l) >= 70 and not re.search(r"(?i)summary report|^official information about|^home\b|avoid scammers|fake e-?mails|email-protection|cookie", l)), None)
        if kind == "reg":                                  # the page opens with the Registry's own blurb; the course paragraph follows
            d = next((l for l in mlines if re.search(r"epidemiology course|Many nephrologists", l)), d)
        out["description"] = d[:600] if d else None
        if not d:
            out.pop("description")
        if kind == "reg":
            out["pricing_tiers"] = [{"tier_label": "Registration · ERA members only", "price_gbp": 0.0, "currency": "EUR",
                                     "is_early_bird": False, "early_bird_deadline": None}] if re.search(r"Registration is free", txt) else []
            out["event_format"] = "in_person"
            if not out["pricing_tiers"]:
                out.pop("pricing_tiers")
        if kind == "cme":
            m = re.search(r"has been accredited by the European Accreditation Council[^.]*?with (\d+(?:\.\d+)?) European CME credits?", txt)
            if m:
                out["cpd_points"], out["cpd_accredited"] = float(m.group(1)), True
            loc = re.search(r"Course[^,]*?,\s*([A-Z][\w ’']+?),\s*([A-Z][a-z]+)\s+\d{2}/\d{2}/\d{4}", txt)    # "... CME Course: ..., Mestre, Italy 30/10/2026"
            if loc:
                out["city"], out["region"] = loc.group(1).strip(), loc.group(2)
            vn = re.search(r"Venue:\s*([^,]+?)(?:\s+Via\b|,)", txt)
            if vn:
                out["venue_name"] = vn.group(1).strip()
            reg = re.search(r"""href=["'](https?://(?!www\.era-online\.org)[^"']+)["'][^>]*>\s*REGISTER NOW""", html, re.I)
            if reg:
                out["organiser_url"] = _html.unescape(reg.group(1))
        if kind == "edu":
            m = re.search(r"The meeting will take place at the ([^.]+?)\.", txt)
            if m:
                out["venue_name"] = m.group(1).split(" by ")[0].strip()
            c = split_location(shell.get("venue_raw"))
            out["city"], out["region"] = c[1] or (shell.get("venue_raw") or "").split(",")[0].strip(), c[2]
            out["event_format"] = "in_person"
        return out

    def _external(self, html, shell):
        """Third-party site: dates and place are the ERA listing's; the site only supplies a description and (if present) fee tables."""
        out = {"society": self.SOCIETY, "event_type": "conference", "specialty": self.DEFAULT_SPECIALTY,
               "start_date": shell["start_date"], "end_date": shell["end_date"]}
        title = shell["title"]
        if re.search(r"(?i)\b(course|masterclass|update)\b", title):
            out["event_type"] = "course"
        raw = shell.get("venue_raw") or ""
        online = bool(re.search(r"(?i)virtual", raw))
        raw = re.sub(r"(?i)\s*&\s*virtual\s*$", "", raw).strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            out["city"] = parts[0]
            if len(parts) > 1:
                out["region"] = "United States" if parts[-1] in ("USA", "US") else parts[-1]
        out["event_format"] = "hybrid" if online and parts else ("online" if online else ("in_person" if parts else None))
        if not out["event_format"]:
            out.pop("event_format")
        md = _meta(html, "og:description") or _meta(html, "description")
        yr = shell["start_date"][:4]
        if md and len(md) >= 50 and not re.search(r"(?i)cookie|javascript", md) and not (re.search(r"20\d\d", md) and yr not in md):
            out["description"] = md[:600]               # a description naming another year is last edition's page
        # fees: not scraped here. These are other organisers' sites (often last year's page, e.g. MIRCIM still shows 2026 fees),
        # so organiser_url hands the site to the explorer, which applies the registration-link / sub-page / PDF logic.
        out["organiser_url"] = shell["booking_url"]
        return out
