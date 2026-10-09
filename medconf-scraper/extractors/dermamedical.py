"""Derma Medical (UK aesthetic-medicine course provider): WooCommerce course shop, family subclass.

`/all-courses/` links ~25 `/product/<slug>/` pages. Each course is a WooCommerce variable product whose
`<form data-product_variations="[...]">` JSON lists every (location, date) pair
(`attribute_pa_location` / `attribute_pa_date`, `is_in_stock`, `avail_qty`), so a course is ONE parent row
with one `course_sessions` entry per pair. The fee is the product's `p.price` ("£1106.00 (incl. VAT)",
"From: £1730.00" when it varies); the JSON-LD offer is stale and variation prices are 0 inside bundles.
Multi-component packages (more than one date form: Skin Expert, Complete Clinician...) and products with no
dated variation (starter kit, open evening, 1:1 training, thread-lift/ultrasound with no dates) are skipped.
Cloudflare 403s plain httpx and the fresh-context fallback of `http_fetch` receives a challenge page that
carries no marker, so every fetch here uses the browser's own page.
"""
import html as _html
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger
from playwright.sync_api import Page

from .http_fetch import fetch_html
from .wordpress_generic import WordPressGenericExtractor

_ROOT = "https://dermamedical.co.uk"
_PRODUCT_RE = re.compile(r"""href=["'](https://dermamedical\.co\.uk/product/[a-z0-9][a-z0-9-]*/)["']""", re.I)
_SKIP_SLUG_RE = re.compile(r"starter-kit|open-evening|bespoke|^1-1")
_FORM_RE = re.compile(r'data-product_variations="([^"]*)"')
_PRICE_RE = re.compile(r'<p class="price[^"]*">(.*?)</p>', re.S)       # rendered DOM: class="price ec-removed"
_LD_PLACE_RE = re.compile(r'"location":\s*\{\s*"@type":\s*"Place",\s*"name":\s*"([^"]+)",\s*"address":\s*\{[^}]*"addressLocality":\s*"([^"]+)"')
_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_LD_CREDITS_RE = re.compile(r'"numberOfCredits":\s*(\d+(?:\.\d+)?)')


class DermamedicalExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/all-courses/"
    SOCIETY = "Derma Medical"
    DEFAULT_SPECIALTY = "Aesthetic & Cosmetic Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    DEFAULT_EVENT_TYPE = "course"

    def _fetch(self, url: str) -> Optional[str]:
        page = getattr(getattr(self, "browser", None), "page", None)
        if page is None:
            return fetch_html(url, browser=None)
        for attempt in range(3):
            try:
                page.goto(url, wait_until="load", timeout=30000)
                body = page.content()
                if body and len(body) > 100000:               # a real shop page is >500 kB; the challenge page is ~80 kB
                    return body
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Derma Medical fetch attempt {attempt + 1}/3 failed for {url}: {e}")
            time.sleep(2 * (attempt + 1))
        return None

    # ---- parsing ----------------------------------------------------------
    @staticmethod
    def parse_sessions(html: str) -> Optional[List[Dict[str, Any]]]:
        """Upcoming (location, date) sessions of a single-form product; None for packages / no dated form."""
        forms = []
        for m in _FORM_RE.finditer(html):
            try:
                vs = json.loads(_html.unescape(m.group(1)))
            except ValueError:
                continue
            if isinstance(vs, list) and any((v.get("attributes") or {}).get("attribute_pa_date") for v in vs):
                forms.append(vs)
        if len(forms) != 1:
            return None
        today = date.today().isoformat()
        seen, out = set(), []
        for v in forms[0]:
            a = v.get("attributes") or {}
            d, loc = a.get("attribute_pa_date"), a.get("attribute_pa_location") or ""
            if not d or not re.match(r"\d{4}-\d{2}-\d{2}$", d) or d < today or (loc, d) in seen:
                continue
            seen.add((loc, d))
            city = loc.replace("-", " ").title() or None
            qty = v.get("avail_qty")
            in_stock = v.get("is_in_stock", True)
            out.append({"start_date": d, "end_date": None, "start_time": None, "duration_text": None,
                        "availability_status": "sold_out" if not in_stock else "available",
                        "spots_left": qty if isinstance(qty, int) and in_stock and qty > 0 else None,
                        "booking_url": None, "venue_name": None, "city": city, "region": "United Kingdom" if city else None,
                        "notes": None})
        out.sort(key=lambda s: (s["start_date"], s["city"] or ""))
        return out

    @staticmethod
    def parse_price(html: str) -> List[Dict[str, Any]]:
        m = _PRICE_RE.search(html)
        txt = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
        pm = re.search(r"[£]\s*([\d,]+(?:\.\d\d)?)", txt)
        if not pm:
            return []
        label = "Course fee · From" if re.search(r"\bfrom\b", txt, re.I) else "Course fee"
        return [{"tier_label": label, "price_gbp": float(pm.group(1).replace(",", "")), "currency": "GBP",
                 "is_early_bird": False, "early_bird_deadline": None}]

    # ---- listing ----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        listing = self._fetch(self.LISTING_URL)
        if not listing:
            return None
        urls: List[str] = []
        for u in _PRODUCT_RE.findall(listing):
            if u not in urls and not _SKIP_SLUG_RE.search(u.rstrip("/").rsplit("/", 1)[-1]):
                urls.append(u)
        shells: List[Dict[str, Any]] = []
        for u in urls:
            time.sleep(self.REQUEST_GAP_S)
            html = self._fetch(u)
            sessions = self.parse_sessions(html) if html else None
            if not sessions:
                continue
            hm = _H1_RE.search(html)
            title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", hm.group(1)))).strip() if hm else ""
            if not title:
                continue
            shells.append({"title": title, "booking_url": u, "source_url": u, "start_date": sessions[0]["start_date"],
                           "end_date": sessions[0]["start_date"], "start_time": None, "venue_raw": None, "category": None,
                           "is_sold_out": all(s["availability_status"] == "sold_out" for s in sessions)})
        logger.info(f"Derma Medical: {len(shells)} dated course products of {len(urls)} linked")
        return shells or None

    # ---- detail -----------------------------------------------------------
    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        sessions = self.parse_sessions(html) or []
        out["event_type"] = "course"
        out["sessions"] = sessions
        if sessions:
            out["start_date"] = sessions[0]["start_date"]
            out["end_date"] = sessions[0]["start_date"]
            cities = {s["city"] for s in sessions if s.get("city")}
            out["city"] = sessions[0]["city"]                              # the earliest session's city, matching the parent's start_date
            out["venue_name"] = None
            lm = _LD_PLACE_RE.search(html)
            if lm and len(cities) == 1 and lm.group(2).strip().lower() == out["city"].lower():
                out["venue_name"] = lm.group(1).strip()                  # JSON-LD names the clinic ("Derma Medical London")
            out["region"] = "United Kingdom"
            out["event_format"] = "in_person"
            out["is_sold_out"] = all(s["availability_status"] == "sold_out" for s in sessions)
        tiers = self.parse_price(html)
        if tiers:
            out["pricing_tiers"] = tiers
        cm = _LD_CREDITS_RE.search(html)
        if cm:
            out["cpd_points"] = float(cm.group(1))
            out["cpd_accredited"] = True
        elif re.search(r"CPD[- ](?:certified|accredited)", html, re.I):
            out["cpd_accredited"] = True
        return out
