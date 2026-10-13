"""The Ultrasound Site (UK MSK ultrasound courses): WooCommerce shop, family subclass.

`/shop/` (9 products a page, `/shop/page/N/`) sells every course date as THREE products: a two-day product titled
"21/22 November 2026 - Advanced MSK ultrasound course" (both days) plus "21st November 2026 - ... Day 1" and
"22nd November 2026 - ... Day 2" single-day products. They are grouped into one event per two-day product (the day
products become extra fee tiers), so a course date is one row. Past dates are listed too and dropped. A product page
carries a FooEvents "Event Details" tab (Date = first day, Start/End time) and a meta description; the venue is only
named for the cadaveric injection course (Queen Mary University, London). Prices are GBP, VAT inclusive.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .wordpress_generic import WordPressGenericExtractor, _iso, _mon, next_page_url, _meta

_ITEM_RE = re.compile(r'(?is)<li\b[^>]*class="([^"]*\bproduct\b[^"]*)"[^>]*>\s*<a href="(https://theultrasoundsite\.co\.uk/product/[^"]+)".*?'
                      r'woocommerce-loop-product__title">(.*?)</h2>.*?<bdi>.*?</span>\s*([\d,]+(?:\.\d\d)?)</bdi>')
_RANGE_RE = re.compile(r"^(\d{1,2})\s*/\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*[-–]\s*(.+)$")
_SINGLE_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\s*[-–]\s*(.+)$")
_DAY_RE = re.compile(r"\s*[-–(]*\s*\(?\bDay\s*([12])\b(?:\s*only)?\s*(?:[-–]\s*)?\(?([^)]*)\)?\s*$", re.I)
_TXT = lambda s: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()   # noqa: E731


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]+", "", re.sub(r"(?i)\bintroduct(?:ory|ion)(?:\s+to)?\b", "intro", name).lower())


class TheUltrasoundSiteExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://theultrasoundsite.co.uk/shop/"
    SOCIETY = "The Ultrasound Site"
    DEFAULT_SPECIALTY = "Radiology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    DEFAULT_EVENT_TYPE = "course"

    # ---- listing -----------------------------------------------------------
    def _products(self) -> List[Dict[str, Any]]:
        out, seen = [], set()
        url = self.LISTING_URL
        for pg in range(1, self.MAX_PAGES + 1):
            html = self._fetch(url)
            if not html:
                break
            items = _ITEM_RE.findall(html)
            new = [i for i in items if i[1] not in seen]
            if not new:
                break
            for cls, href, title, price in new:
                seen.add(href)
                out.append({"url": href, "title": _TXT(title), "price": float(price.replace(",", "")), "soldout": "outofstock" in cls})
            nxt = next_page_url(html, url, pg, "path")
            if not nxt or nxt == url:
                break
            url = nxt
            time.sleep(self.REQUEST_GAP_S)
        return out

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        both, days = {}, {}
        for p in self._products():
            t = p["title"]
            m = _RANGE_RE.match(t)
            if m:
                d1, d2, mon, yr, name = m.groups()
                s, e = _iso(int(yr), _mon(mon), int(d1)), _iso(int(yr), _mon(mon), int(d2))
                both[(_norm(name), s)] = {**p, "name": name.strip(), "start": s, "end": e}
                continue
            m = _SINGLE_RE.match(t)
            if m:
                d, mon, yr, rest = m.groups()
                s = _iso(int(yr), _mon(mon), int(d))
                dm = _DAY_RE.search(rest)
                name = _DAY_RE.sub("", rest).strip(" -–") if dm else rest.strip()
                days.setdefault((_norm(name), s), []).append({**p, "name": name, "start": s, "day": dm.group(1) if dm else None, "limb": (dm.group(2).strip(" -") if dm else "")})
        shells = []
        for (nk, s), b in both.items():
            if not s or (b["end"] or s) < today:
                continue
            # day-only products of this course date: the same name inside the two-day window
            opts = [d for (k, ds), lst in days.items() if k == nk and ds and s <= ds <= (b["end"] or s) for d in lst]
            shells.append({"title": b["name"], "booking_url": b["url"], "source_url": b["url"], "start_date": s, "end_date": b["end"] or s,
                           "start_time": None, "venue_raw": None, "category": "Course", "price": b["price"], "soldout": b["soldout"],
                           "options": sorted(opts, key=lambda d: d["start"])})
        # one-day products with no two-day sibling
        used = {(k, ds) for (k, s), b in both.items() for (k2, ds), lst in days.items() if k2 == k and ds and s <= ds <= (b["end"] or s)}
        for (nk, s), lst in days.items():
            if (nk, s) in used or not s or s < today:
                continue
            for d in lst:
                shells.append({"title": d["name"], "booking_url": d["url"], "source_url": d["url"], "start_date": s, "end_date": s,
                               "start_time": None, "venue_raw": None, "category": "Course", "price": d["price"], "soldout": d["soldout"], "options": []})
        shells.sort(key=lambda x: x["start_date"])
        logger.info(f"The Ultrasound Site listing: {len(shells)} shells")
        return shells or None

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY, "event_type": "course", "start_date": shell["start_date"], "end_date": shell["end_date"]}
        md = _meta(html, "og:description") or _meta(html, "description") or ""
        md = _html.unescape(md).strip()
        if md:
            out["description"] = md[:600]
        out["specialty"] = "Radiology"
        tm = re.search(r"Start time:\s*</b>\s*(\d{1,2}:\d{2})", html)
        if tm:
            out["start_time"] = tm.group(1).zfill(5)
        vm = re.search(r"\b(?:facilities of|held at|venue:?)\s+([A-Z][\w&' .-]{3,60}?),\s*(London)\b", md)
        if vm:
            out["venue_name"], out["city"], out["region"], out["event_format"] = vm.group(1).strip(), vm.group(2), "United Kingdom", "in_person"
        tiers: List[Dict[str, Any]] = []
        if shell.get("options"):
            tiers.append({"tier_label": "Course fee · Both days", "price_gbp": shell["price"], "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
            for d in shell["options"]:
                lbl = f"Day {d['day']} only" + (f" ({d['limb']})" if d.get("limb") else "") if d.get("day") else "Single day"
                tiers.append({"tier_label": f"Course fee · {lbl}", "price_gbp": d["price"], "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        elif shell.get("price"):
            tiers.append({"tier_label": "Course fee", "price_gbp": shell["price"], "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        if tiers:
            out["pricing_tiers"] = tiers
        if shell.get("soldout") or re.search(r'(?i)class="stock out-of-stock"|>\s*sold out\s*<', html):
            out["is_sold_out"] = True
        return out
