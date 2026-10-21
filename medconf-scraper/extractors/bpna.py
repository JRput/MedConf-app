"""BPNA Annual Conference (bpna.org.uk): single-congress family subclass.

Hooks: place sits in an address block under "...will take place on 6-8 January 2027 as a hybrid event at:",
and the fee page ("Booking Details", contentid=N) has per-section tables (full / day / social / virtual) whose
rows read "category, MEMBER|NON-MEMBER, early, standard, late" one cell per line.
"""
import re
from datetime import date
from typing import Any, Dict, List

from .single_congress import SingleCongressExtractor, html_lines

_AMT_RE = re.compile(r"^£\s?([\d,]+(?:\.\d{2})?)$")
_TABLE_START_RE = re.compile(r"^(Conference full attendance|Conference day attendance|Social Events|Virtual conference attendance)\b", re.I)
_SECTIONS = [(re.compile(r"^FULL CONFERENCE ATTENDANCE", re.I), "In person (full conference)"),
             (re.compile(r"^DAY RATES", re.I), "In person (day rate)"),
             (re.compile(r"^SOCIAL EVENT TICKETS", re.I), "Social event"),
             (re.compile(r"^VIRTUAL CONFERENCE RATES", re.I), "Virtual")]
_ENGLISH = {"birmingham", "london", "manchester", "leeds", "liverpool", "bristol", "sheffield", "newcastle", "nottingham", "oxford", "cambridge", "leicester", "southampton", "brighton"}


class BpnaExtractor(SingleCongressExtractor):
    HOME_URL = "https://bpna.org.uk/conference/2027/"
    SOCIETY = "BPNA"
    EVENT_NAME = "BPNA Conference"
    DEFAULT_SPECIALTY = "Paediatric Neurology"
    DEFAULT_CURRENCY = "GBP"
    EDITION_URLS = ("https://bpna.org.uk/?page=courses-conferences",)    # lists next year's "BPNA Annual Conference 20NN"

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            lines = html_lines(self._get(shells[0]["booking_url"]) or "")
            i = next((k for k, l in enumerate(lines[:30]) if re.search(r"as a hybrid event at:?$|will take place[^.]*\bat:?$", l)), None)
            if i is not None and i + 4 < len(lines):
                venue, city = lines[i + 1], next((x for x in lines[i + 2:i + 5] if re.match(r"^[A-Z][a-z]+$", x)), None)
                if city:
                    nation = "England" if city.lower() in _ENGLISH else "United Kingdom"
                    shells[0]["venue_raw"] = f"{venue}, {city}, {nation}"
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def detail_from_html(self, html, url, shell, llm_call):
        # nav link "Booking Details" -> ../2027/index.php?contentid=N (the id changes every year)
        from urllib.parse import urljoin
        m = re.search(r'(?is)<a [^>]*href="([^"]+)"[^>]*>\s*Booking Details\s*</a>', html)
        if m:
            self.REG_URLS = (urljoin(url, m.group(1)),)
        out = super().detail_from_html(html, url, shell, llm_call)
        if out.get("cpd_points") is None and self.REG_URLS:
            bt = " ".join(html_lines(self._get(self.REG_URLS[0]) or ""))
            m = re.search(r"FULL CONFERENCE ATTENDANCE[^()]*\((\d{1,3}) CPD POINTS\)", bt, re.I)
            if m:
                out["cpd_points"], out["cpd_accredited"] = float(m.group(1)), True
        lines = html_lines(html)
        # the family description picks the "A warm welcome from <city>" blurb; a fact line is safer
        intro = next((l for l in lines[:12] if re.search(r"Annual Conference will take place", l)), None)
        if intro:
            where = " ".join(x for x in (out.get("venue_name"), out.get("city")) if x)
            out["description"] = intro.rstrip(" :.") + (f" ({where})." if where else ".")
        return out

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for html in pages.values():
            lines = html_lines(html)
            if not any(_SECTIONS[0][0].match(l) for l in lines):
                continue
            eb = None
            for l in lines:
                m = re.match(r"^Early bird rate applies until:\s*(\d{1,2}) (\w+) (20\d\d)", l)
                if m:
                    try:
                        from datetime import datetime
                        eb = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date().isoformat()
                    except ValueError:
                        eb = None
            section, cols, cat, mem, emitted, active = None, [], [], None, False, False
            amts: List[str] = []

            def flush():
                nonlocal amts, emitted
                if amts and section and cols:
                    cat_l = [re.sub(r"\s*(?:\([^)]*\))?\s*[-–—]\s*\(.*\)$", "", c).strip() for c in cat]
                    label_cat = cat[0] if len(cat) == 1 and not cat[0].startswith("•") else "/".join(c.lstrip("• ").split(" (")[0].rstrip(";") for c in cat) or None
                    for k, (col, a) in enumerate(zip(cols, amts)):
                        parts = [section, label_cat, mem, col]
                        tiers.append({"tier_label": " · ".join(p for p in parts if p), "price_gbp": float(a.replace(",", "")), "currency": "GBP",
                                      "is_early_bird": k == 0 and "early" in col.lower(), "early_bird_deadline": eb if k == 0 and "early" in col.lower() else None})
                    emitted = True
                amts = []

            for l in lines:
                sec = next((nm for rx, nm in _SECTIONS if rx.match(l)), None)
                if sec:
                    flush()
                    section, cols, cat, mem, emitted, active = sec, [], [], None, False, False
                    continue
                if section is None:
                    continue
                if _TABLE_START_RE.match(l):
                    flush()
                    active, cols, cat, mem, emitted = True, [], [], None, False
                    continue
                if not active:
                    continue
                m = _AMT_RE.match(l)
                if m:
                    amts.append(m.group(1))
                    continue
                flush()
                if re.match(r"^(Early bird|Early bird rate|Standard rate|Late rate)$", l, re.I):
                    cols.append(re.sub(r"(?i) rate$", "", l.strip()).capitalize() + " rate")
                    continue
                pm = re.match(r"^\((until|from) (.+)\)$", l, re.I)
                if pm and cols and not re.search(r"\b(until|from)\b", cols[-1]):
                    cols[-1] = f"{cols[-1]} {pm.group(1).lower()} {pm.group(2)}"
                    continue
                if re.match(r"^(MEMBER|NON-MEMBER)$", l):
                    mem = "Member" if l == "MEMBER" else "Non-member"
                    continue
                if emitted:
                    cat, mem, emitted = [], None, False
                if len(l) < 140 and not re.match(r"^(Birmingham \| Physical|.*\|.*)$", l):
                    cat.append(l if l.startswith("•") else re.sub(r"\s*\(includes[^)]*\)", "", l))
                    if section == "Social event" and len(cat) > 1:
                        cat = cat[:1]
            flush()
            break
        return tiers
