"""HIMSS Global Health Conference & Exhibition (himssconference.com): single-congress family subclass.

The congress microsite only (Informa-operated). Nothing on himss.org is ever fetched (blocked on the runner).
Hooks (each proven by the harness / test_himss_conference.py):
  * the home header reads "April 5-8, 2027 | McCormick Place Convention Center | Chicago, IL"; the family accepts the
    first segment after the dates (the venue) and stops, so the city/state segment is read here;
  * /register/ is an Elementor price list (raven-price-list): pass cards (h2) with rows "title / $price / Advance Pricing:
    $price". The shown price is the early-bird rate; "Advance Pricing goes into effect December 21, 2026" is the switch.
    Market Supplier rows (vendor company staff), the free Press pass and any row without a price are skipped;
  * the og:description still describes HIMSS26 in Las Vegas, so the plain meta description (HIMSS27, Chicago) is the description;
  * /call-for-posters/ is the call for proposals: the family's key-date reader found nothing there, so the closing date
    ("... closed as of 5:00 PM EST on Sunday, October 11, 2026") is read here.
"""
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines
from .wordpress_generic import _meta

_MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_TOKEN_RE = re.compile(
    r'(?is)<h2[^>]*elementor-heading-title[^>]*>(?P<h2>.*?)</h2>'
    r'|<h6[^>]*elementor-heading-title[^>]*>(?P<h6>.*?)</h6>'
    r'|raven-price-list-title">(?P<title>.*?)</span>\s*<span[^>]*separator[^>]*></span>\s*<span[^>]*raven-price-list-price">(?P<price>.*?)</span>'
    r'(?:\s*</div>\s*<p[^>]*raven-price-list-description">(?P<desc>.*?)</p>)?')
_ADV_RE = re.compile(rf"Advance Pricing goes into effect\s+({_MON}) (\d{{1,2}}), (20\d\d)", re.I)
_HEADER_RE = re.compile(r"\|\s*([^|]+?)\s*\|\s*([A-Z][A-Za-z .]+?),\s*([A-Z]{2})\s*$")
_CLOSED_RE = re.compile(rf"\b(?:closed|closes?|deadline)\b[^.]*?\b({_MON}) (\d{{1,2}}), (20\d\d)", re.I)
_AUDIENCE_RE = re.compile(r"\b(?:providers?|general admission|students?|government|members?)\b", re.I)


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).replace("&amp;", "&").strip()


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


class HimssConferenceExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.himssconference.com/"
    SOCIETY = "HIMSS"
    EVENT_NAME = "HIMSS Global Health Conference & Exhibition"
    DEFAULT_SPECIALTY = "Digital Health"
    DEFAULT_CURRENCY = "USD"
    REG_URLS = ("https://www.himssconference.com/register/",)
    ABSTRACT_URLS = ("https://www.himssconference.com/call-for-posters/",)
    VENUE_URLS = ("https://www.himssconference.com/about-the-venue/",)
    MAX_AUX_PAGES = 1

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        if not out.get("city"):
            for l in html_lines(html)[:80]:
                m = _HEADER_RE.search(l)
                if m and (not out.get("venue_name") or m.group(1) in out["venue_name"] or out["venue_name"] in m.group(1)):
                    out["city"], out["region"] = m.group(2).strip(), "United States"
                    out["venue_name"] = out.get("venue_name") or m.group(1).strip()
                    out["event_format"] = "in_person"
                    break
        md = _meta(html, "description")       # the og:description is a stale HIMSS26 / Las Vegas text; the plain description is current
        yy = str(shell.get("edition_year") or (shell.get("start_date") or "")[:4])[-2:]
        if md and len(md) >= 50 and yy.isdigit() and f"HIMSS{yy}" in md:
            out["description"] = re.sub(r"\s+", " ", md).strip()[:600]
        return out

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            if "register" not in url:
                continue
            am = _ADV_RE.search(_txt(html))
            adv = datetime.strptime(f"{am.group(1)} {am.group(2)} {am.group(3)}", "%B %d %Y").date() if am else None
            early_dl = adv - timedelta(days=1) if adv else None
            tiers: List[Dict[str, Any]] = []
            pass_name = audience = None
            for m in _TOKEN_RE.finditer(html):
                if m.group("h2") is not None:
                    pass_name, audience = _txt(m.group("h2")), None
                    continue
                if m.group("h6") is not None:           # eligibility subtitle ("Qualified Providers") joins the label; marketing/schedule subtitles do not
                    sub = _txt(m.group("h6"))
                    audience = sub if _AUDIENCE_RE.search(sub) else None
                    continue
                title, price = _txt(m.group("title")), _txt(m.group("price"))
                if not pass_name or re.search(r"market suppliers?|press", title, re.I):
                    continue
                amt = float(re.sub(r"[^\d.]", "", price)) if re.search(r"\$\s?\d", price) else None
                if amt is None:
                    continue
                cat = title.rstrip("* ").strip()
                label = " · ".join([pass_name] + ([audience] if audience else []) + ([] if cat.lower() == pass_name.lower() else [cat]))
                desc = _txt(m.group("desc") or "")
                dm = re.search(r"\$\s?([\d,]+(?:\.\d\d)?)", desc)
                if dm and early_dl:
                    tiers.append({"tier_label": f"{label} · Early bird (until {_fmt(early_dl)})", "price_gbp": amt, "currency": "USD",
                                  "is_early_bird": True, "early_bird_deadline": early_dl.isoformat()})
                    tiers.append({"tier_label": f"{label} · Advance (from {_fmt(adv)})", "price_gbp": float(dm.group(1).replace(",", "")),
                                  "currency": "USD", "is_early_bird": False, "early_bird_deadline": None})
                else:
                    # no switch date: the early price is dead, so an Advance price (when shown) is the one that applies
                    if dm:
                        amt = float(dm.group(1).replace(",", ""))
                    tiers.append({"tier_label": f"{label} · Standard", "price_gbp": amt, "currency": "USD",
                                  "is_early_bird": False, "early_bird_deadline": None})
            if tiers:
                return tiers
        return []

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        try:
            start = date.fromisoformat(shell["start_date"])
        except (KeyError, ValueError, TypeError):
            start = None
        for html in pages.values():
            t = _txt(html)
            if "call for posters" not in t.lower() or not self._mentions_edition(t, shell):
                continue
            m = _CLOSED_RE.search(t)
            if m:
                dl = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
                if start and dl >= start:               # a "deadline" on/after the congress itself is a misparse
                    continue
                out["abstract_open"] = dl >= today
                out["abstract_deadline"] = dl.isoformat()
                return
        super().apply_abstracts(out, pages, shell)
