"""ESGE Days (esgedays.org): single-congress family subclass.

The congress's own site only. Nothing on esge.com is ever fetched (its terms forbid automated access).
Hooks (each proven by the harness):
  * the home page lists "April 28, 2027: Pre-courses in Lisbon, Portugal" before "April 29 - May 1, 2027: ESGE Days 2027
    in Lisbon, Portugal"; the family took the one-day pre-course line as the congress. The congress line wins;
  * parse_place strips the "Pre-courses in" / "ESGE Days 2027 in" lead-in from the place text;
  * /registration/register-now is a text grid ("Early Bird (bookable until March 16, 2027) EUR580", virtual
    "(bookable until May 1, 2027) EUR295") under category headings; parsed here. Press (free), Industry
    Representative (exhibitor badge) and percentage discounts carry no clinician price and are skipped;
  * the family key-date reader took "Registration opens December 9, 2026" as the abstract deadline: the abstract
    deadline is read from the "Deadline for abstract submissions" line;
  * the how-to-get page gives "Venue Address : Lisbon Congress Centre, Praca das Industrias 1 ..." (label with a space before the colon);
  * the description is the site's meta description (the first prose line is a banner about abstracts closing soon).
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines, parse_place as _base_parse_place
from .wordpress_generic import _meta

_MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_CONGRESS_RE = re.compile(rf"^({_MON}) (\d{{1,2}})\s*[-–]\s*(?:({_MON}) )?(\d{{1,2}}), (20\d\d):?\s*ESGE Days \d{{4}} in ([A-Z][\w ]+), ([A-Z][a-z]+)")
_AMT_RE = re.compile(r"€\s?(\d[\d,]*(?:\.\d\d)?)(?:\s*\(per course\))?$")
_BOOK_RE = re.compile(rf"\(bookable (until|from) ({_MON} \d{{1,2}}, 20\d\d)\)")
_ABS_DL_RE = re.compile(rf"^({_MON} \d{{1,2}}, 20\d\d):\s*(?:Abstract submission deadline|Deadline for abstract submissions?)\b", re.I)
_LBA_RE = re.compile(rf"^({_MON} \d{{1,2}}, 20\d\d):\s*Late[\s-]breaking (?:abstracts? )?submissions? close", re.I)
_SKIP_CATS = re.compile(r"press|industry", re.I)


def _d(s: str) -> date:
    return datetime.strptime(s, "%B %d, %Y").date()


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


class EsgeDaysExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.esgedays.org/"
    SOCIETY = "ESGE"
    EVENT_NAME = "ESGE Days"
    DEFAULT_SPECIALTY = "Gastroenterology"
    DEFAULT_CURRENCY = "EUR"
    REG_URLS = ("https://esgedays.org/registration/register-now",)
    ABSTRACT_URLS = ("https://esgedays.org/abstracts/abstracts",)
    VENUE_URLS = ("https://esgedays.org/general-information/how-to-get-to-esge-days",)
    MAX_AUX_PAGES = 1

    def _edition_from(self, url, html):
        lines = html_lines(html)
        for i, l in enumerate(lines):
            m = _CONGRESS_RE.match(l)
            if not m:
                continue
            m1, d1, m2, d2, yr = m.group(1), int(m.group(2)), m.group(3) or m.group(1), int(m.group(4)), int(m.group(5))
            s = datetime.strptime(f"{m1} {d1} {yr}", "%B %d %Y").date()
            e = datetime.strptime(f"{m2} {d2} {yr}", "%B %d %Y").date()
            if e >= date.today() and 0 <= (e - s).days <= 10:
                return {"start": s.isoformat(), "end": e.isoformat(), "date_line": l, "idx": i, "source": "header-line",
                        "year": yr, "page_title": None, "seg": l, "url": url, "lines": lines}
        return super()._edition_from(url, html)

    def parse_place(self, raw):
        return _base_parse_place(re.sub(r"^.*?\bin\s+(?=[A-Z])", "", raw or "", count=1))

    def venue_from_lines(self, lines):
        for l in lines:
            m = re.match(r"^Venue Address\s*:\s*([^,]+),", l)
            if m:
                return m.group(1).strip()
        return None

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        md = _meta(html, "description")
        if md and len(md) >= 50 and "ESGE Days" in md:
            out["description"] = re.sub(r"\s+", " ", md).strip()[:600]
        # register-now sells Virtual participation as its own ticket; the family's hybrid
        # rule only scans the home page head, which never says so (review 2026-11-14).
        if out.get("event_format") == "in_person":
            out["event_format"] = "hybrid"
        return out

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            if "register" not in url:
                continue
            lines = html_lines(html)
            try:
                a = next(i for i, l in enumerate(lines) if l.startswith(f"ESGE Days {year} Registration Fees"))
                b = next(i for i in range(a, len(lines)) if lines[i].startswith("Eligibility"))
            except StopIteration:
                continue
            tiers: List[Dict[str, Any]] = []
            section = group = cat = mode = None
            skip_next = False
            for l in lines[a + 1:b]:
                if skip_next:
                    skip_next = False
                    continue
                if l.startswith("i "):
                    skip_next = True
                    continue
                if l.startswith("Core Programme"):
                    section, group, cat = "Core programme", None, None
                elif l.startswith("Add-On Courses"):
                    section, group, cat = "Add-on courses", None, None
                elif l.startswith("Special Fee Categories") or l.startswith("Special Category"):
                    group = None
                elif re.match(r"^(?:Non-Members|Members)\b", l):
                    group = "Non-member" if l.startswith("Non") else "Member"
                elif l in ("In-Person Participation", "Virtual Participation"):
                    mode = "In-person" if l.startswith("In") else "Virtual"
                elif l.startswith(("Early Bird", "Standard", "Late / On-Site", "(bookable")):
                    am = _AMT_RE.search(l)
                    if not (am and section and cat and mode) or _SKIP_CATS.search(cat):
                        continue
                    price = float(am.group(1).replace(",", ""))
                    bm = _BOOK_RE.search(l)
                    dl = _d(bm.group(2)) if bm else None
                    early = l.startswith("Early Bird")
                    if mode == "Virtual":
                        tf = f"until {_fmt(dl)}" if dl else "Standard"
                    elif early and dl:
                        tf = f"Early bird (until {_fmt(dl)})"
                    elif l.startswith("Standard") and bm and bm.group(1) == "from":
                        tf = f"Standard (from {_fmt(dl)})"
                    else:
                        tf = "Late / on-site"
                    name = f"{cat} ({group})" if section == "Add-on courses" and group else cat
                    tiers.append({"tier_label": " · ".join([section, name, mode, tf]), "price_gbp": price, "currency": "EUR",
                                  "is_early_bird": early, "early_bird_deadline": dl.isoformat() if early and dl else None})
                elif len(l) <= 70 and not re.match(r"^(?:Registration Type|Early|Late)", l) and not re.search(r"[.:]$|Not offered|Not applicable|^\(", l):
                    if l in ("Groups of 10 or more", "Group Registration"):
                        cat = None
                    else:
                        cat = l
            if tiers:
                return tiers
        return []

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        found, lba = [], []
        for html in pages.values():
            for l in html_lines(html):
                m = _ABS_DL_RE.match(l)
                if m:
                    found.append(_d(m.group(1)))
                m = _LBA_RE.match(l)
                if m:
                    lba.append(_d(m.group(1)))
        if not found:
            return super().apply_abstracts(out, pages, shell)
        fut = sorted(d for d in found if d >= today)
        dl = fut[0] if fut else max(found)
        out["abstract_open"] = dl >= today
        out["abstract_deadline"] = dl.isoformat()
        if lba:
            out["abstract_deadline_note"] = f"Late-breaking abstracts close {_fmt(max(lba))}"
