"""ATACC Group (Anaesthesia, Trauma and Critical Care course) : family subclass, course + sessions.

`/product-category/atacc-course/` is a WooCommerce (Avada) product grid: one product per dated course
("24th-26th September 2027 – ATACC Course", "17-19th June 2027 – ATACC Ireland"), each with the price
(GBP 1,450 inc. VAT) and an `instock` / `outofstock` class. The product pages carry nothing else (no venue), so the
shared course description, venue ("LOCATION: Lincolnshire Fire & Rescue Training Facility | LN5 9FG. START TIME: 08:00")
and CPD ("worth up to a maximum of 23.5 CPD points") come from `/tag-training/atacc/`.

Products are grouped by the suffix after the date ("ATACC Course" vs "ATACC Ireland"): one parent row per group
(event_type='course') with a session per dated product, like alsg.py. The main group's parent URL is the category
page; other groups use `<category>#<group>` so the URL stays stable as individual dates pass. Dates come from the
product TITLE (product slugs are copy-pasted and disagree with it).
"""
import html as _html
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive
from .wordpress_generic import _iso, _mon
from logger import logger

_CATEGORY = "https://www.ataccgroup.com/product-category/atacc-course/"
_INFO_URL = "https://www.ataccgroup.com/tag-training/atacc/"
_PRODUCT_RE = re.compile(r'(?is)<li\b[^>]*class="([^"]*\bproduct\b[^"]*)"[^>]*>(.*?)</li>')
_TITLE_RE = re.compile(r'(?is)<h3\b[^>]*class="[^"]*\bproduct-title\b[^"]*"[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>\s*(.*?)\s*</a>')
_PRICE_RE = re.compile(r'(?is)class="price"[^>]*>.*?(?:&pound;|£)\s*</span>\s*([\d,]+(?:\.\d\d)?)')
_DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:-|–)\s*(\d{1,2})(?:st|nd|rd|th)?\s*(?:-|–|,)?\s*([A-Za-z]{3,9})\s*,?\s*(\d{4})"      # 24th-26th September 2027
    r"|(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s*,?\s*(\d{4})")                                                                    # 24 September 2027


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


class AtaccExtractor(WordPressGenericExtractor):
    LISTING_URL = _CATEGORY
    SOCIETY = "ATACC Group"
    DEFAULT_SPECIALTY = "Emergency Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    DEFAULT_EVENT_TYPE = "course"

    # ---- parsing -----------------------------------------------------------
    @staticmethod
    def parse_products(html: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for m in _PRODUCT_RE.finditer(html or ""):
            cls, body = m.group(1), m.group(2)
            tm = _TITLE_RE.search(body)
            if not tm or tm.group(1) in seen:
                continue
            seen.add(tm.group(1))
            title = _clean(tm.group(2))
            dm = _DATE_RE.search(title)
            if not dm:
                continue
            try:
                if dm.group(1):
                    mon = _mon(dm.group(3))
                    start, end = _iso(int(dm.group(4)), mon, int(dm.group(1))), _iso(int(dm.group(4)), mon, int(dm.group(2)))
                else:
                    start = end = _iso(int(dm.group(7)), _mon(dm.group(6)), int(dm.group(5)))
            except KeyError:
                continue
            if not start:
                continue
            suffix = re.sub(r"^[\s\-–]+|[\s\-–]+$", "", title[dm.end():]) or "ATACC Course"
            pm = _PRICE_RE.search(body)
            out.append({"url": tm.group(1), "title": title, "group": suffix, "start_date": start, "end_date": end or start,
                        "price": float(pm.group(1).replace(",", "")) if pm else None, "sold_out": "outofstock" in cls})
        out.sort(key=lambda p: p["start_date"])
        return out

    @staticmethod
    def _gkey(group: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-")

    @classmethod
    def _parent_url(cls, group: str) -> str:
        k = cls._gkey(group)
        return _CATEGORY if k == "atacc-course" else f"{_CATEGORY}#{k}"

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        today = date.today().isoformat()
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in self.parse_products(html):
            if p["end_date"] >= today:
                groups.setdefault(p["group"], []).append(p)
        shells = []
        for g, prods in groups.items():
            url = self._parent_url(g)
            shells.append({"title": f"ATACC {g.replace('ATACC', '').strip() or 'Course'}".replace("ATACC Course", "ATACC Course")
                           if g.upper() != "ATACC COURSE" else "ATACC (Advanced Trauma and Critical Care) Course",
                           "booking_url": url, "source_url": url, "start_date": prods[0]["start_date"], "end_date": prods[0]["end_date"],
                           "venue_raw": None, "category": "course", "_group": g})
        logger.info(f"{self.SOCIETY}: {len(shells)} course groups, {sum(len(v) for v in groups.values())} dated products")
        return shells or None

    # ---- detail ------------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        if "product-title" not in html:
            html = fetch_html(_CATEGORY, browser=getattr(self, "browser", None)) or ""
        return self.detail_from_html(html, shell, llm_call)

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        today = date.today().isoformat()
        group = shell.get("_group") or "ATACC Course"
        prods = [p for p in self.parse_products(html) if p["group"] == group and p["end_date"] >= today]
        info = fetch_html(_INFO_URL, browser=getattr(self, "browser", None)) or ""
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer|template)\b.*?</\1\s*>", " ", info)))
        text = " ".join(lines)
        is_main = self._gkey(group) == "atacc-course"
        venue = city = region = start_time = None
        lm = re.search(r"LOCATION:\s*([^|.]+?)\s*\|\s*([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\.?\s*(?:START TIME:\s*(\d{1,2}:\d{2}))?", text)
        if is_main and lm:                                           # the info page describes the UK (Lincolnshire) course only
            venue, region = lm.group(1).strip(), "United Kingdom"
            start_time = lm.group(3).zfill(5) if lm.group(3) else None
            cm = re.search(r"just outside of ([A-Z][a-z]+)", text)
            city = cm.group(1) if cm else None
        elif not is_main:
            region = "Ireland" if re.search(r"(?i)ireland", group) else None
        out: Dict[str, Any] = {
            "conference_name": shell.get("title"), "society": self.SOCIETY, "event_type": "course",
            "specialty": self.DEFAULT_SPECIALTY, "event_format": "in_person", "region": region,
            "is_sold_out": bool(prods) and all(p["sold_out"] for p in prods),
        }
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        d = next((l for l in lines if len(l) >= 100 and l.startswith("ATACC")), None)
        if d:
            out["description"] = d[:600]
        cm = re.search(r"maximum of (\d+(?:\.\d+)?) CPD points", text)
        if cm and is_main:                                          # the RCS CPD statement is about the UK course
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        if prods:
            out["start_date"], out["end_date"] = prods[0]["start_date"], prods[0]["end_date"]
            if start_time:
                out["start_time"] = start_time
            out["sessions"] = [{"_idx": i, "start_date": p["start_date"], "end_date": p["end_date"] if p["end_date"] != p["start_date"] else None,
                                "start_time": start_time, "duration_text": None,
                                "availability_status": "sold_out" if p["sold_out"] else "available", "spots_left": None,
                                "booking_url": p["url"], "venue_name": venue, "city": city, "region": region, "notes": None,
                                "_price_gbp": p["price"]} for i, p in enumerate(prods)]
            out["pricing_tiers"] = [{"tier_label": "Course fee (inc. VAT)", "price_gbp": p["price"], "currency": "GBP",
                                     "is_early_bird": False, "early_bird_deadline": None, "_session_idx": i}
                                    for i, p in enumerate(prods) if p["price"] is not None]
        return {k: v for k, v in out.items() if v is not None}
