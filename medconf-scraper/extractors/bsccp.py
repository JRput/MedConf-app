"""BSCCP (British Society for Colposcopy and Cervical Pathology) events: Craft CMS, family subclass.

`/events` is a server-rendered card list (`li.card-three`: heading, date line, category chips). Page 2 onwards
(`/events/p2`) are archive pages of undated "last three years" lists, so the walk stops at page 1. Event pages are short
prose with a hero "Register" button that points at the real booking site (Eventbrite, medcpduk, the EFC congress site,
the cytology centre), so fees are not on bsccp.org.uk: the button is kept as `organiser_url` for the explorer. The
trainee "Online Colposcopy OSCE" is an exam sitting, not a CPD event, and is skipped; the two "ONLINE ... Colposcopy
Course" cards are undated on-demand courses and drop out through the family's undated-card rule.
"""
import html as _html
import re
from typing import Any, Callable, Dict, List, Optional

from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive

_REGISTER_RE = re.compile(r'(?is)<a\b[^>]*href="(https?://[^"]+)"[^>]*>\s*Register\s*</a>')
_STALE_DESC_RE = re.compile(r"(?i)currently finalising arrangements|^save the date")


class BsccpExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.bsccp.org.uk/events"
    SOCIETY = "BSCCP"
    DEFAULT_SPECIALTY = "Obstetrics & Gynaecology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    MAX_PAGES = 1

    def skip_event(self, shell: Dict[str, Any]) -> bool:
        t = shell.get("title") or ""
        return bool(re.search(r"\bOSCE\b", t) and not re.search(r"(?i)prep", t))        # the exam itself, not a course

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        title = shell.get("title") or ""
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html or "")))
        text = " ".join(lines)
        if not out.get("event_format") and re.search(r"(?i)\b(online|virtual)\b", title):
            out["event_format"] = "online"
        if not (out.get("venue_name") or out.get("city")) and out.get("event_format") != "online":
            m = re.search(r"taking place in ([A-Z][a-z]+)\s*,\s*([A-Z][\w&' .-]{2,40}?) from \d", text)      # "in London , QEII Centre from 19th-21st April 2027"
            if m:
                out["city"], out["venue_name"], out["region"], out["event_format"] = m.group(1), m.group(2).strip(), "United Kingdom", "in_person"
        d = out.get("description") or ""
        if not d or _STALE_DESC_RE.search(d):
            i = next((k for k, l in enumerate(lines) if re.match(r"^The 20\d\d Annual BSCCP Scientific Meeting", l)), None)
            if i is not None:
                out["description"] = " ".join(lines[i:i + 2])[:600]
            else:
                ti = next((k for k, l in enumerate(lines) if l == title), 0)
                alt = next((l for l in lines[ti + 1:ti + 14] if len(l) >= 80 and not _STALE_DESC_RE.search(l)), None)
                if alt:
                    out["description"] = alt[:600]
                else:
                    out.pop("description", None)
        rm = _REGISTER_RE.search(html or "")
        if rm and "bsccp.org.uk" not in rm.group(1):
            out["organiser_url"] = _html.unescape(rm.group(1))
        return out
