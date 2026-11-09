"""AMWC - Aesthetic & Anti-Aging Medicine World Congress (amwc-conference.com): single-congress family subclass.

Hooks (each proven by the harness):
  * JSON-LD says 2027-04-01..02 while the visible header ("Cannes. 1-3 April 2027") and the compliance line
    ("1-2-3 April 2027") say three days: the header range wins when it starts on the same day;
  * /register/ shows each pass as "<name> / <struck-out original price> / <current price> / Offer ends 14th January"
    (Next.js text, no table), parsed here; the original price is the final rate from 15 January;
  * /faculty/abstract-submission/ lists "Oral presentation - October 31" and "Poster submission - December 31"
    with no year: the year is the edition's year minus one when the date would fall after the congress.
"""
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines

_MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                           "august", "september", "october", "november", "december"])}
_PASSES = ("Scientific Program Passes", "Sponsored Workshops /Exhibition Passes", "Aesthetics New Joiners Pass")
_EUR_RE = re.compile(r"^€\s?(\d[\d,]*)$")


class AmwcExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.amwc-conference.com/"
    SOCIETY = "AMWC"
    EVENT_NAME = "AMWC"
    DEFAULT_SPECIALTY = "Aesthetic Medicine"
    DEFAULT_CURRENCY = "EUR"
    REG_URLS = ("https://www.amwc-conference.com/register/",)
    ABSTRACT_URLS = ("https://www.amwc-conference.com/faculty/abstract-submission/",)
    VENUE_URLS = ("https://www.amwc-conference.com/info/venue/",)
    MAX_AUX_PAGES = 1

    def _edition_from(self, url, html):
        ed = super()._edition_from(url, html)
        if ed and ed.get("source") == "json-ld":
            s = date.fromisoformat(ed["start"])
            for l in (ed.get("lines") or [])[:30]:
                m = re.search(r"(\d{1,2})\s*[–-]\s*(\d{1,2})\s+([A-Z][a-z]+)\s+(20\d\d)", l)
                if m and _MONTHS.get(m.group(3).lower()) == s.month and int(m.group(4)) == s.year and int(m.group(1)) == s.day:
                    e = date(s.year, s.month, int(m.group(2)))
                    if s <= e and (e - s).days <= 10:
                        ed["end"] = e.isoformat()
                        break
        return ed

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            lines = html_lines(html)
            if "register" not in url or not any(str(year) in l for l in lines):
                continue
            tiers: List[Dict[str, Any]] = []
            for i, l in enumerate(lines):
                if l not in _PASSES:
                    continue
                prices, dl = [], None
                for x in lines[i + 1:i + 14]:
                    m = _EUR_RE.match(x)
                    if m and len(prices) < 2:
                        prices.append(float(m.group(1).replace(",", "")))
                    m2 = re.match(r"^Offer ends (\d{1,2})(?:st|nd|rd|th)? ([A-Z][a-z]+)$", x)
                    if m2 and m2.group(2).lower() in _MONTHS:
                        dl = date(year, _MONTHS[m2.group(2).lower()], int(m2.group(1)))
                        break
                if len(prices) == 2 and dl and prices[0] > prices[1]:          # struck original, then current offer
                    name = "Scientific Programme Pass" if l.startswith("Scientific") else "Sponsored Workshops / Exhibition Pass" if l.startswith("Sponsored") else "Aesthetics New Joiners Pass"
                    label = dl.strftime("%d %B %Y").lstrip("0")
                    if dl >= date.today():
                        tiers.append({"tier_label": f"{name} · Early bird · until {label}", "price_gbp": prices[1], "currency": "EUR",
                                      "is_early_bird": True, "early_bird_deadline": dl.isoformat()})
                    tiers.append({"tier_label": f"{name} · Final rate" + (f" · from {(dl + timedelta(days=1)).strftime('%d %B %Y').lstrip('0')}" if dl >= date.today() else ""),
                                  "price_gbp": prices[0], "currency": "EUR", "is_early_bird": False, "early_bird_deadline": None})
            if tiers:
                return tiers
        return []

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        try:
            start = date.fromisoformat(shell["start_date"])
        except (KeyError, ValueError, TypeError):
            return super().apply_abstracts(out, pages, shell)
        for html in pages.values():
            text = " ".join(html_lines(html))
            found = []
            for kind, mon, day in re.findall(r"(Oral presentation|Poster submission)\s*[–-]\s*([A-Z][a-z]+) (\d{1,2})\b", text):
                if mon.lower() not in _MONTHS:
                    continue
                d = date(start.year, _MONTHS[mon.lower()], int(day))
                if d >= start:
                    d = date(start.year - 1, d.month, d.day)
                found.append((kind, d))
            if found:
                fut = sorted(d for _, d in found if d >= today)
                out["abstract_open"] = bool(fut)
                out["abstract_deadline"] = (fut[0] if fut else max(d for _, d in found)).isoformat()
                out["abstract_deadline_note"] = "; ".join(f"{k} {d.strftime('%d %B %Y').lstrip('0')}" for k, d in sorted(found, key=lambda t: t[1]))
                return
