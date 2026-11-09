"""Digital Health Rewired (digitalhealthrewired.com): single-congress family subclass (ASP.events platform).

Hooks (each proven by the harness):
  * the page's JSON-LD Event carries the venue as {name: "The NEC Birmingham", address: "Birmingham, United Kingdom"}
    (address is a plain string, which the family location reader skips), so venue/city are read from it and the UK
    nation is England; its description sentence is the description (the first prose line of the page is the ad-consent text);
  * /tickets-pricing is a card layout ("Public and third sector / Free", "Private sector / Two-day pass / £789
    +VAT ... Save £210 against the £999 on-the-door price", "Start-up / £199 +VAT"), parsed here;
  * /call-speakers says "Speaker applications closed on Friday 25 September 2026" - a speaker call, recorded as a
    closed submission window.
The Register buttons go to forms.reg.buzz (a registration form, no fees) and are not followed.
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List

from .single_congress import SingleCongressExtractor, html_lines
from .wordpress_generic import json_ld_events

_NATION = {"Birmingham": "England", "London": "England", "Manchester": "England", "Leeds": "England", "Liverpool": "England",
           "Glasgow": "Scotland", "Edinburgh": "Scotland", "Cardiff": "Wales", "Belfast": "Northern Ireland"}


def _gbp(s: str):
    m = re.fullmatch(r"£\s?(\d[\d,]*(?:\.\d\d)?)", (s or "").strip())
    return float(m.group(1).replace(",", "")) if m else None


class RewiredExtractor(SingleCongressExtractor):
    HOME_URL = "https://digitalhealthrewired.com/"
    SOCIETY = "Digital Health Rewired"
    EVENT_NAME = "Digital Health Rewired"
    DEFAULT_SPECIALTY = "Digital Health"
    DEFAULT_CURRENCY = "GBP"
    REG_URLS = ("https://digitalhealthrewired.com/tickets-pricing",)
    ABSTRACT_URLS = ("https://digitalhealthrewired.com/call-speakers",)
    MAX_AUX_PAGES = 1

    def list_shells_override(self):
        shells = super().list_shells_override()
        self._start = date.fromisoformat(shells[0]["start_date"]) if shells else None
        return shells

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        start = getattr(self, "_start", None)
        for url, html in pages.items():
            if "tickets-pricing" not in url:
                continue
            lines = html_lines(html)
            text = " ".join(lines)
            if start and not re.search(rf"\b{start.day} {start.strftime('%B')}\b", text):
                continue                                      # opening times must name this edition's first day
            tiers: List[Dict[str, Any]] = []

            def tier(label, amt, early=False):
                tiers.append({"tier_label": label, "price_gbp": amt, "currency": "GBP", "is_early_bird": early, "early_bird_deadline": None})

            for i, l in enumerate(lines):
                if l == "Public and third sector" and lines[i + 1:i + 2] == ["Free"]:
                    tier("Two-day pass · Public and third sector · Free", 0.0)
                if l == "Two-day pass" and _gbp(lines[i + 1] if i + 1 < len(lines) else "") is not None and "Private sector" in lines[max(0, i - 2):i]:
                    tier("Two-day pass · Private sector · Book ahead (+VAT)", _gbp(lines[i + 1]), True)
                    m = re.search(r"£(\d[\d,]*) on-the-door", " ".join(lines[i + 2:i + 6]))
                    if m:
                        tier("Two-day pass · Private sector · On the door (+VAT)", float(m.group(1).replace(",", "")))
                if l == "Start-up" and _gbp(lines[i + 1] if i + 1 < len(lines) else "") is not None:
                    tier("Two-day pass · Start-up company (+VAT)", _gbp(lines[i + 1]))
            if tiers:
                return tiers
        return []

    def apply_abstracts(self, out, pages, shell):
        for html in pages.values():
            m = re.search(r"Speaker applications closed on (?:[A-Z][a-z]+day )?(\d{1,2} [A-Z][a-z]+ \d{4})", " ".join(html_lines(html)))
            if m:
                d = datetime.strptime(m.group(1), "%d %B %Y").date()
                out["abstract_open"] = d >= date.today()
                out["abstract_deadline"] = d.isoformat()
                out["abstract_deadline_note"] = "Call for speakers"
                return

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        for ev in json_ld_events(html):
            loc = ev.get("location") or {}
            name = (loc.get("name") or "").strip()
            addr = loc.get("address") if isinstance(loc.get("address"), str) else ""
            city = addr.split(",")[0].strip() if addr else ""
            if name and city in _NATION:
                out["venue_name"] = re.sub(r"^The\s+", "", name)
                out["city"], out["region"], out["event_format"] = city, _NATION[city], "in_person"
            d = (ev.get("description") or "").strip()
            if d:
                out["description"] = d[:600]
            break
        return out
