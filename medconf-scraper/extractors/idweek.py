# extractors/idweek.py
"""
IDWeek (IDSA / SHEA / HIVMA / PIDS / SIDP) — annual meeting extractor.

Wave 2b source 55. idweek.org is ONE annual meeting. The ~100 "events" seen
in recon are programme sessions (listed on an EventScribe site behind
Cloudflare), so this extractor emits exactly ONE conference shell, like
arvo.py / sitc.py do for flagships.

Site shape (server-rendered, plain httpx works; fetch_html falls back to
the browser if a runner is blocked):
  /               hero "Oct. 21-24, 2026 | Washington, D.C." + venue prose
  /registration/  <table class="idsa-table"> rows = registration category,
                  columns = Advance / Regular / Onsite, each followed by a
                  "Discounted Registration" column (hotel-block $50 off).
  /abstracts/     "Abstract Timeline" with Regular Abstracts Closes <date>.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

BASE_URL = "https://www.idweek.org"
HOME_URL = BASE_URL + "/"
REG_URL = BASE_URL + "/registration/"
ABSTRACTS_URL = BASE_URL + "/abstracts/"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"


def _flatten(fragment: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html_lib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


class IdweekExtractor(BaseExtractor):

    def _fetch(self, url: str) -> Optional[str]:
        for attempt in range(3):
            html = fetch_html(url, browser=getattr(self, "browser", None))
            if html:
                return html
            logger.warning(f"IDWeek: fetch of {url} failed (attempt {attempt + 1}/3)")
            time.sleep(1.5)
        return None

    # ------------------------------------------------------------ listing
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(HOME_URL)
        if not html:
            logger.warning("IDWeek: homepage unavailable - no shells")
            return []
        text = _flatten(html)
        m = re.search(
            rf"{_MON}\s+(\d{{1,2}})\s*[-–]\s*(?:{_MON}\s+)?(\d{{1,2}}),\s*(20\d\d)\s*\|\s*([A-Za-z .]+?),?\s*(D\.C\.|[A-Z]{{2}})(?=\s|$)",
            text,
        )
        if not m:
            logger.warning("IDWeek: could not parse date line on homepage - no shells")
            return []
        mon1, d1, mon2, d2, year, city, st = m.groups()
        try:
            start = date(int(year), _MONTHS[mon1.lower()[:3]], int(d1))
            end = date(int(year), _MONTHS[(mon2 or mon1).lower()[:3]], int(d2))
        except (ValueError, KeyError):
            return []
        if end < date.today():
            logger.info(f"IDWeek: {year} meeting already over - no shells")
            return []
        city = city.strip().rstrip(",")
        shell = {
            "title": f"IDWeek {year}",
            "booking_url": REG_URL,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "city": city,
            "region": "USA",
            "category": "conference",
        }
        return [shell]

    # ------------------------------------------------------------- detail
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        home = self._fetch(HOME_URL) or ""
        reg = self._fetch(REG_URL) or ""
        abstracts = self._fetch(ABSTRACTS_URL) or ""
        home_text = _flatten(home)

        result: Dict[str, Any] = {
            "event_type": "conference",
            "is_flagship": True,
            "organiser_url": HOME_URL,
            "pricing_tiers": self._rate_table(reg),
            "venue_name": self._venue(home_text),
            "event_format": "hybrid" if re.search(r"(?i)attend virtually|virtual rates|in-person and virtual", home_text + _flatten(reg)) else "in_person",
            "city": shell.get("city"),
            "region": shell.get("region"),
        }
        result.update(self._abstract_info(abstracts))
        if re.search(r"(?i)CME|continuing (medical )?education", reg):
            result["cpd_accredited"] = True
        result.update(self._soft_fields(shell.get("title"), home, llm_call))
        return {k: v for k, v in result.items() if v is not None}

    @staticmethod
    def _venue(text: str) -> Optional[str]:
        m = re.search(r"(?:at|in) the ((?:[A-Z][\w.&'-]*\s+){1,6}(?:Convention Center|Conference Center|Centre|Center|Hotel))", text)
        return m.group(1).strip() if m else None

    @staticmethod
    def _usd(cell: str) -> Optional[float]:
        m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", cell)
        return float(m.group(1).replace(",", "")) if m else None

    def _rate_table(self, html: str) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for tbl in re.findall(r"(?is)<table[^>]*>(.*?)</table>", html):
            rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbl)
            if len(rows) < 2:
                continue
            head = [_flatten(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rows[0])]
            if not head or not re.search(r"(?i)registration type", head[0]):
                continue
            # Build per-column timeframe; "Discounted Registration" columns
            # inherit the preceding timeframe.
            frames: List[str] = []
            last = ""
            for h in head[1:]:
                if re.search(r"(?i)discounted", h) and last:
                    frames.append(f"{last} · Hotel-block discount")
                else:
                    last = h
                    frames.append(h)
            for row in rows[1:]:
                cells = [_flatten(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)]
                if len(cells) < 2:
                    continue
                cat = cells[0].rstrip("*").strip()
                for fr, cell in zip(frames, cells[1:]):
                    price = self._usd(cell)
                    if price is None:
                        continue
                    early = bool(re.match(r"(?i)advance", fr))
                    tiers.append({
                        "tier_label": f"Registration · {cat} · {fr}"[:160],
                        "price_gbp": price,
                        "currency": "USD",
                        "is_early_bird": early,
                        "early_bird_deadline": None,
                    })
        seen, out = set(), []
        for t in tiers:
            k = (t["tier_label"], t["price_gbp"])
            if k not in seen:
                seen.add(k)
                out.append(t)
        return out

    @staticmethod
    def _abstract_info(html: str) -> Dict[str, Any]:
        if not html:
            return {}
        text = _flatten(html)
        m = re.search(rf"Regular Abstracts? Closes\s+(?:[A-Za-z]+day,\s+)?{_MON}\s+(\d{{1,2}}),\s*(20\d\d)", text)
        if not m:
            return {}
        try:
            d = date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        except (ValueError, KeyError):
            return {}
        # Late-breaker window may still be open even if regular closed.
        lb = re.search(rf"Late[- ]Breaker Abstract Closes\s+(?:[A-Za-z]+day,\s+)?{_MON}\s+(\d{{1,2}}),\s*(20\d\d)", text)
        deadline = d
        if lb:
            try:
                ld = date(int(lb.group(3)), _MONTHS[lb.group(1).lower()[:3]], int(lb.group(2)))
                if ld >= date.today() > d:
                    deadline = ld
            except (ValueError, KeyError):
                pass
        return {"abstract_open": deadline >= date.today(), "abstract_deadline": deadline.isoformat()}

    def _soft_fields(self, title, home_html: str, llm_call) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        mm = re.search(r'<meta name="description" content="([^"]+)"', home_html)
        meta = html_lib.unescape(mm.group(1)).strip() if mm else None
        text = _flatten(home_html)
        i = text.find("Oct.")
        body = text[i:i + 1500] if i >= 0 else text[:1500]
        raw = llm_call(
            f"Summarise this conference homepage. Event: {title}\n\n{body}\n\n"
            'Reply with JSON only: {"description": "30-50 word summary from the text" or null, '
            '"specialty": "primary clinical area" or null}'
        )
        if raw:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    p = json.loads(m.group(0))
                    out["description"] = p.get("description") or None
                    out["specialty"] = p.get("specialty") or None
                except Exception as e:
                    logger.warning(f"IDWeek soft-fields parse failed: {e}")
        if not out.get("description"):
            out["description"] = meta
        if not out.get("specialty"):
            out["specialty"] = classify_specialty(title, "infectious diseases HIV") or "Infectious Diseases"
        return out
