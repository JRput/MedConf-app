"""BOFAS Annual Scientific Meeting (bofas.org.uk): single-congress family subclass.

Hooks: the home page says "BOFAS 2026 will be held in Wales from 4th to 6th of November" (day-first, year in
the previous words), the venue sits on /annual-meeting/venue, and the fee table is a PDF linked from
/annual-meeting/registration ("Registration Rates - Click here"), parsed here via pypdf.
"""
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from .abstract_classifier import _default_fetcher, pdf_bytes_to_text
from .single_congress import SingleCongressExtractor, find_edition, html_lines

_BASE = "https://www.bofas.org.uk"
_ROW_RE = re.compile(r"([A-Za-z][A-Za-z ,\-–*/]+?)\s+£(\d[\d,]*)\s+£(\d[\d,]*)\s+£(\d[\d,]*)")


class BofasExtractor(SingleCongressExtractor):
    HOME_URL = _BASE + "/annual-meeting"
    SOCIETY = "BOFAS"
    EVENT_NAME = "BOFAS Annual Scientific Meeting"
    DEFAULT_SPECIALTY = "Orthopaedics"
    DEFAULT_CURRENCY = "GBP"
    REG_URLS = (_BASE + "/annual-meeting/registration",)
    ABSTRACT_URLS = (_BASE + "/annual-meeting/abstracts",)
    VENUE_URLS = (_BASE + "/annual-meeting/venue",)

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        lines = html_lines(html)
        for l in lines[:20]:
            m = re.search(r"BOFAS (20\d\d) will be held in ([A-Z][A-Za-z ]+?) from (\d{1,2})(?:st|nd|rd|th)? to (\d{1,2})(?:st|nd|rd|th)? of ([A-Z][a-z]+)", l)
            if m:
                syn = f"{m.group(3)}-{m.group(4)} {m.group(5)} {m.group(1)} | {m.group(2)}"
                ed = find_edition(html, [syn] + lines, url)
                if ed:
                    ed.update(url=url, lines=lines)
                    return ed
        return super()._edition_from(url, html)

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            vl = html_lines(self._get(self.VENUE_URLS[0]) or "")
            i = next((k for k, l in enumerate(vl) if re.match(r"^BOFAS 20\d\d\s*-\s*Venue$", l)), None)
            city = next((m.group(1) for l in vl for m in [re.search(r"is located in ([A-Z][a-z]+)", l)] if m), None)
            home_place = next((m.group(1).strip() for l in html_lines(self._get(self.HOME_URL) or "")[:20]
                               for m in [re.search(r"will be held in ([A-Z][A-Za-z ]+?) from", l)] if m), None)
            if i is not None and city and home_place:
                shells[0]["venue_raw"] = f"{vl[i + 1]}, {city}, {home_place}"
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):               # "Venue, City, Nation" (UK nation as region)
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        link = None
        for u, html in pages.items():
            for m in re.finditer(r'(?is)<a [^>]*href="([^"]+\.pdf[^"]*)"', html):
                if re.search(r"registration[\s%20_-]*rates", m.group(1), re.I):
                    link = urljoin(u, m.group(1).replace("&amp;", "&"))
                    break
            if link:
                break
        if not link:
            return []
        got = _default_fetcher(link.replace(" ", "%20"))
        if not got or got[0] != "pdf":
            return []
        text = re.sub(r"\s+", " ", pdf_bytes_to_text(got[1]))
        tiers: List[Dict[str, Any]] = []
        sections = [("3-Day Conference", r"Full 3 Day Conference Fee", r"Daily Rate"), ("Single Day", r"Daily Rate", r"Conference Dinner")]
        for name, start, end in sections:
            m = re.search(start + r"(.*?)" + end, text)
            if not m:
                continue
            seg = m.group(1)
            std = re.search(r"Standard Rate until\s+(\d{1,2}\w{0,2} \w+ 20\d\d)", seg)
            late = re.search(r"Late Rate from\s+(\d{1,2}\w{0,2} \w+)", seg)
            cols = [(f"Standard rate until {std.group(1)}" if std else "Standard rate", True),
                    (f"Late rate from {late.group(1)}" if late else "Late rate", False),
                    ("On the day", False)]
            for row in _ROW_RE.finditer(seg):
                label = re.sub(r"\s*\*+", "", row.group(1)).strip(" -–,")
                label = re.sub(r"^.*?(?=BOFAS Full Member|Non-BOFAS Member|Trainee, AHPs, Retired|Exhibitor)", "", label).replace("Trainee, AHPs, Retired Members", "Trainee, AHPs, Retired Members")
                for (tf, early), amt in zip(cols, row.groups()[1:]):
                    tiers.append({"tier_label": f"{name} · {label} · {tf}", "price_gbp": float(amt.replace(",", "")),
                                  "currency": "GBP", "is_early_bird": early, "early_bird_deadline": None})
            if name == "3-Day Conference" and re.search(r"Trainee, AHPs\s*[-–]\s*Presenting\*+\s*Free of charge", seg):
                tiers.append({"tier_label": "3-Day Conference · Trainee, AHPs - Presenting (code on acceptance) · Free of charge", "price_gbp": 0.0,
                              "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        return tiers

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        lines = html_lines(html)
        intro = next((l for l in lines[:12] if re.search(r"BOFAS 20\d\d will be held", l)), None)
        theme = next((l for l in lines[:12] if l.lower().startswith("the theme of the conference")), None)
        if intro:
            out["description"] = " ".join(x.rstrip(".") + "." for x in (intro, theme) if x)
        return out
