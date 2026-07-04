"""Full-field audit gate.

Mandatory pre-Live check for every scraped source. Unlike the fixer path
(which tries to patch missing fields), this AUDITS every row against
every schema field and cross-references the source page. A source cannot
be signed off until every row is either COMPLETE or GENUINELY_ABSENT
with source-page evidence.

Field states per row:
  OK              — DB value is populated and matches the source page
  MISSING         — DB value is null but the source page HAS the info
                    (i.e. the extractor/remediator failed to catch it)
  SUSPECT         — DB value is populated but looks wrong
                    (e.g. specialty=General Practice on a thoracic society)
  GENUINELY_ABSENT — DB value is null AND the source page confirms it
                    doesn't publish that field

Any MISSING or SUSPECT verdict blocks source sign-off.

Run:
  python -m remediator.audit --source N
  python -m remediator.audit --source N --report-only   (no auto-fix attempt)
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Society → expected specialty. Any conference from this society whose
# specialty doesn't match (case-insensitive) is flagged SUSPECT.
SOCIETY_EXPECTED_SPECIALTY = {
    "RCGP": ["General Practice"],
    "RCP": ["Internal Medicine", "General Medicine"],
    "RCPE": ["Internal Medicine"],
    "RCSEng": ["Surgery"],
    "RCS": ["Surgery"],
    "RSM": None,  # Multi-specialty
    "RCEM": ["Emergency Medicine"],
    "RCOG": ["Obstetrics & Gynaecology"],
    "RCR": ["Radiology", "Clinical Oncology"],
    "BOPA": ["Oncology"],
    "BTOG": ["Oncology"],
    "ASCO": ["Oncology", "Clinical Oncology"],
    "ESMO": ["Oncology", "Medical Oncology"],
    "ASTRO": ["Radiation Oncology", "Oncology"],
}

# Suspicious specialty defaults — if a specialty appears here on a source
# whose society doesn't match, it's almost certainly the classifier's
# fallback rather than the real specialty.
SUSPECT_DEFAULT_SPECIALTIES = ("General Practice", "Internal Medicine")


@dataclass
class FieldVerdict:
    field: str
    status: str  # OK, MISSING, SUSPECT, GENUINELY_ABSENT, NOT_APPLICABLE
    db_value: Any = None
    page_evidence: Optional[str] = None
    reason: str = ""


@dataclass
class RowAudit:
    conference_id: int
    conference_name: str
    event_type: str
    source_url: str
    fields: list = field(default_factory=list)  # FieldVerdict[]
    completeness_score: float = 0.0
    total_checked: int = 0
    total_ok: int = 0
    total_missing: int = 0
    total_suspect: int = 0
    total_absent: int = 0

    def add(self, v: FieldVerdict) -> None:
        self.fields.append(v)

    def finalize(self) -> None:
        self.total_checked = len(
            [f for f in self.fields if f.status != "NOT_APPLICABLE"]
        )
        self.total_ok = len([f for f in self.fields if f.status == "OK"])
        self.total_missing = len([f for f in self.fields if f.status == "MISSING"])
        self.total_suspect = len([f for f in self.fields if f.status == "SUSPECT"])
        self.total_absent = len([f for f in self.fields if f.status == "GENUINELY_ABSENT"])
        if self.total_checked > 0:
            # OK and GENUINELY_ABSENT both count as "resolved"
            self.completeness_score = round(
                100 * (self.total_ok + self.total_absent) / self.total_checked, 1
            )
        else:
            self.completeness_score = 0.0

    def passes(self) -> bool:
        return self.total_missing == 0 and self.total_suspect == 0


# ---------------------------------------------------------------- #
# Per-field checks — one function per field.
# Signature: check(row, page_text, page_html, source) → FieldVerdict
# ---------------------------------------------------------------- #

def _page_has(page_text: str, terms: list) -> bool:
    tl = (page_text or "").lower()
    return any(t.lower() in tl for t in terms)


def _has_evidence_of(page_text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, page_text or "", re.I)
    if m:
        s = max(0, m.start() - 40)
        e = min(len(page_text), m.end() + 120)
        return page_text[s:e]
    return None


def check_description(row, page_text, page_html, source) -> FieldVerdict:
    v = (row.get("description") or "").strip()
    if v and 50 <= len(v) <= 700:
        if any(bad in v.lower() for bad in ("register now", "login", "menu",
                                              "cookie policy", "javascript is required")):
            return FieldVerdict("description", "SUSPECT", v[:80],
                                reason="Contains nav-leak phrases")
        # Title-relevance check: description should share ≥1 distinctive
        # token with the event title. Prevents ambient meta descriptions
        # (about a different event on the same site) from being accepted.
        title = (row.get("conference_name") or "").lower()
        STOPWORDS = {"the","a","an","of","and","or","to","for","in","on","at",
                     "with","by","from","as","annual","meeting","conference",
                     "congress","event","symposium","summit","workshop","2024",
                     "2025","2026","2027","2028"}
        title_tokens = {t for t in re.findall(r"[a-z]{4,}", title)
                        if t not in STOPWORDS}
        if title_tokens:
            v_lower = v.lower()
            matched = [t for t in title_tokens if t in v_lower]
            if not matched:
                return FieldVerdict("description", "SUSPECT", v[:100],
                    reason=f"Description shares no distinctive token with "
                           f"event title (tokens sought: {sorted(title_tokens)[:4]})")
        return FieldVerdict("description", "OK", v[:80])
    if v and len(v) < 50:
        return FieldVerdict("description", "SUSPECT", v[:80],
                            reason=f"Too short ({len(v)} chars)")
    if v and len(v) > 700:
        return FieldVerdict("description", "SUSPECT", v[:80],
                            reason=f"Too long ({len(v)} chars)")
    if page_text and len(page_text) > 500:
        return FieldVerdict("description", "MISSING",
                            reason="Page has text but description not extracted")
    return FieldVerdict("description", "GENUINELY_ABSENT",
                        reason="Page has no readable body text")


def check_start_date(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("start_date")
    if v:
        return FieldVerdict("start_date", "OK", v)
    # Look for date patterns on page
    m = re.search(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{4}\b",
        page_text or "",
    )
    if m:
        return FieldVerdict("start_date", "MISSING", None,
                            page_evidence=m.group(0),
                            reason="Page contains a UK-format date not captured")
    return FieldVerdict("start_date", "GENUINELY_ABSENT",
                        reason="Page contains no obvious date")


def check_end_date(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("end_date")
    start = row.get("start_date")
    if v:
        return FieldVerdict("end_date", "OK", v)
    if not start:
        return FieldVerdict("end_date", "NOT_APPLICABLE",
                            reason="No start_date so end_date irrelevant")
    # Check page for a date range
    m = re.search(
        r"\d{1,2}(?:st|nd|rd|th)?\s*(?:[-–]|to)\s*\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{4}",
        page_text or "", re.I,
    )
    if m:
        return FieldVerdict("end_date", "MISSING", None,
                            page_evidence=m.group(0),
                            reason="Page has date RANGE but end_date null")
    return FieldVerdict("end_date", "OK", start,
                        reason="Single-day event; end_date = start_date implicit")


def check_venue_name(row, page_text, page_html, source) -> FieldVerdict:
    v = (row.get("venue_name") or "").strip()
    fmt = (row.get("event_format") or "").lower()
    if fmt == "online":
        return FieldVerdict("venue_name", "NOT_APPLICABLE" if not v else "OK",
                            v or None, reason="Online event")
    if v:
        if not re.search(r"[A-Za-z]", v) or len(v) < 4:
            return FieldVerdict("venue_name", "SUSPECT", v,
                                reason="Too short or non-alpha")
        # Over-long venues almost always contain trailing prose
        # (dates, descriptions) that leaked past the extractor's
        # boundary trimming
        if len(v) > 100:
            return FieldVerdict("venue_name", "SUSPECT", v[:100],
                                reason=f"Suspiciously long ({len(v)} chars) — "
                                       f"likely contains trailing prose")
        # Reject values that contain sentence-shaped content
        if re.search(r"\b(?:from|on|between|will\s+be)\b", v, re.I):
            return FieldVerdict("venue_name", "SUSPECT", v,
                                reason="Contains sentence-shaped content "
                                       "(date/prose leaked past boundary)")
        return FieldVerdict("venue_name", "OK", v)
    # Missing — look for venue anchors
    ev = _has_evidence_of(page_text,
        r"(?:will\s+be\s+held\s+at|held\s+at|hosted\s+at|takes?\s+place\s+at|"
        r"venue[:\s])[\s\w'&,\-.]{5,80}")
    if ev:
        return FieldVerdict("venue_name", "MISSING", None, page_evidence=ev,
                            reason="Page mentions venue but venue_name null")
    return FieldVerdict("venue_name", "GENUINELY_ABSENT",
                        reason="No venue-anchor phrases on page")


def check_city(row, page_text, page_html, source) -> FieldVerdict:
    v = (row.get("city") or "").strip()
    fmt = (row.get("event_format") or "").lower()
    if fmt == "online":
        return FieldVerdict("city", "NOT_APPLICABLE" if not v else "OK", v or None)
    if v:
        return FieldVerdict("city", "OK", v)
    return FieldVerdict("city", "MISSING",
                        reason="In-person event with no city set")


def check_event_format(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("event_format")
    if v not in ("online", "in_person", "hybrid"):
        return FieldVerdict("event_format", "MISSING", v,
                            reason="event_format must be online|in_person|hybrid")
    # Cross-check: if title names a city, event shouldn't be online
    title = (row.get("conference_name") or "")
    known_cities = ("Lugano", "Madrid", "Zurich", "Munich", "Singapore",
                    "Barcelona", "Vienna", "Berlin", "Paris", "Milan",
                    "London", "Chicago", "Edinburgh", "Sheffield",
                    "Manchester", "Boston", "Kuala Lumpur", "Melbourne",
                    "Amsterdam", "Geneva", "Basel", "Brussels", "Dublin",
                    "Lisbon")
    city_in_title = any(c in title for c in known_cities)
    if city_in_title and v == "online":
        return FieldVerdict("event_format", "SUSPECT", v,
            reason=f"Title names a city, but event_format=online")
    return FieldVerdict("event_format", "OK", v)


def check_event_type(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("event_type")
    if v in ("conference", "course", "workshop"):
        return FieldVerdict("event_type", "OK", v)
    return FieldVerdict("event_type", "MISSING", v,
                        reason="event_type must be conference|course|workshop")


def check_specialty(row, page_text, page_html, source) -> FieldVerdict:
    v = (row.get("specialty") or "").strip()
    society = (source.get("society") or "").upper()
    expected = SOCIETY_EXPECTED_SPECIALTY.get(society)
    if not v:
        return FieldVerdict("specialty", "MISSING",
                            reason="No specialty set")
    if expected and not any(v.lower() == e.lower() for e in expected):
        # Off-society specialty is suspect UNLESS it's a legitimately
        # cross-specialty event
        if v in SUSPECT_DEFAULT_SPECIALTIES:
            return FieldVerdict("specialty", "SUSPECT", v,
                reason=f"Society {society} expects one of {expected}, got '{v}' — "
                       f"likely a classifier default")
    return FieldVerdict("specialty", "OK", v)


def check_is_flagship(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("is_flagship")
    title = (row.get("conference_name") or "").lower()
    # Heuristic: if title contains "annual conference" / "annual congress" /
    # "world congress" and is_flagship != True, that's a MISS
    flagship_indicators = ("annual conference", "annual congress",
                           "world congress", "global conference")
    is_probable_flagship = any(k in title for k in flagship_indicators)
    if is_probable_flagship and not v:
        return FieldVerdict("is_flagship", "MISSING", v,
            reason=f"Title contains flagship indicator, but is_flagship=False")
    if v and not is_probable_flagship:
        # Could be a per-source forced flag — check but don't flag as suspect
        # unless clearly non-flagship (e.g. drop-in clinic)
        if any(k in title for k in ("drop-in", "webinar", "webcast",
                                     "training session")):
            return FieldVerdict("is_flagship", "SUSPECT", v,
                reason="Marked flagship but title suggests small event")
    return FieldVerdict("is_flagship", "OK", v)


def check_cpd_points(row, page_text, page_html, source) -> FieldVerdict:
    v = row.get("cpd_points")
    if v is not None and v > 0:
        return FieldVerdict("cpd_points", "OK", v)
    # Look for CPD digits on page
    m = re.search(r"(\d{1,3})\s*CPD\s*(?:credits?|points?|hours?)", page_text or "", re.I)
    if m:
        return FieldVerdict("cpd_points", "MISSING", v,
                            page_evidence=m.group(0),
                            reason=f"Page mentions '{m.group(0)}' but cpd_points null")
    # No CPD mention at all
    if not re.search(r"\bCPD\b", page_text or "", re.I):
        return FieldVerdict("cpd_points", "GENUINELY_ABSENT", v,
                            reason="No CPD mention on page")
    return FieldVerdict("cpd_points", "GENUINELY_ABSENT", v,
                        reason="CPD mentioned but no number to extract")


def check_abstract_status(row, page_text, page_html, source) -> FieldVerdict:
    ao = row.get("abstract_open")
    ad = row.get("abstract_deadline")
    an = row.get("abstract_deadline_note")
    et = row.get("event_type")

    if et != "conference":
        # Non-conferences rarely have abstracts
        return FieldVerdict("abstract_status", "NOT_APPLICABLE",
                            reason=f"event_type={et} — abstracts uncommon")

    tl = (page_text or "").lower()

    # Look for genuine abstract mentions (not just banner filenames)
    has_abstract_content = (
        re.search(r"(?:call\s+for\s+abstracts?|abstract\s+submissions?|"
                  r"submit\s+(?:your\s+)?abstract|abstract\s+deadline)",
                  tl) is not None
    )

    if not has_abstract_content:
        # Genuinely no abstracts advertised
        if ao is True:
            return FieldVerdict("abstract_status", "SUSPECT",
                f"open={ao} deadline={ad}",
                reason="No abstract programme on page but abstract_open=True")
        return FieldVerdict("abstract_status", "GENUINELY_ABSENT",
                            reason="No abstract programme on page")

    # Page has abstract content — verify DB reflects it
    # Check for a closing date pattern that's specifically abstract-context
    # (not a registration deadline that happens to say "deadline")
    close_date = re.search(
        r"(?:abstract\s+submissions?\s+(?:close|deadline|end)|"
        r"abstract\s+(?:submission\s+)?deadline|"
        r"deadline\s+for\s+(?:abstract\s+)?submissions?|"
        r"submit\s+(?:your\s+)?abstract\s+by|"
        r"abstract\s+submission\s+deadline\s+(?:of|is|on|:))"
        r"[:\s\w]{0,40}"
        r"(\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{4})",
        page_text or "", re.I,
    )
    if close_date and not ad:
        return FieldVerdict("abstract_status", "MISSING",
                            f"open={ao} deadline={ad}",
                            page_evidence=f"Page: '{close_date.group(0)}'",
                            reason="Page has abstract deadline date but abstract_deadline null")
    if not (ao is not None or ad or an):
        return FieldVerdict("abstract_status", "MISSING",
                            f"open={ao} deadline={ad}",
                            page_evidence="Page has abstract content",
                            reason="Page has abstract programme but nothing set in DB")
    return FieldVerdict("abstract_status", "OK",
                        f"open={ao} deadline={ad} note={an}")


def check_pricing(row, page_text, page_html, source, pricing_tiers) -> FieldVerdict:
    n = len(pricing_tiers or [])
    tl = (page_text or "").lower()
    is_free = re.search(r"(?:free\s+(?:to\s+attend|of\s+charge|event|admission)|"
                        r"complimentary|no\s+(?:cost|charge|fee))", tl)
    has_prices = bool(re.search(r"[£$€]\s*\d+", page_text or ""))

    if n > 0:
        return FieldVerdict("pricing_tiers", "OK", f"{n} tiers")
    if is_free:
        return FieldVerdict("pricing_tiers", "GENUINELY_ABSENT", "0 tiers",
                            reason="Page indicates free event")
    if has_prices:
        # Filter out no-show penalties
        penalty_context = re.search(
            r"(?:do\s+not\s+attend|charged\s+a\s+fee\s+of|"
            r"cancellation\s+fee|no-show)",
            tl,
        )
        if not penalty_context or re.search(r"[£$€]\s*\d+\s+(?:member|non|early|standard|full|conference|registration)",
                                             tl):
            return FieldVerdict("pricing_tiers", "MISSING", "0 tiers",
                                page_evidence="Page has £ amounts",
                                reason="Prices on page but no tiers in DB")
    return FieldVerdict("pricing_tiers", "GENUINELY_ABSENT", "0 tiers",
                        reason="No pricing content on page")


CHECKS = [
    check_description, check_start_date, check_end_date,
    check_venue_name, check_city, check_event_format, check_event_type,
    check_specialty, check_is_flagship, check_cpd_points,
    check_abstract_status,
]


# ---------------------------------------------------------------- #
# Runner
# ---------------------------------------------------------------- #

def audit_row(row: dict, page_text: str, page_html: Optional[str],
              source: dict, pricing_tiers: list) -> RowAudit:
    audit = RowAudit(
        conference_id=row["id"],
        conference_name=row.get("conference_name") or "",
        event_type=row.get("event_type") or "?",
        source_url=row.get("source_url") or "",
    )
    for check in CHECKS:
        try:
            v = check(row, page_text, page_html, source)
        except Exception as e:
            v = FieldVerdict(check.__name__.replace("check_", ""),
                             "SUSPECT", None, reason=f"Check crashed: {e}")
        audit.add(v)
    # Pricing needs the tier list explicitly
    try:
        v = check_pricing(row, page_text, page_html, source, pricing_tiers)
        audit.add(v)
    except Exception as e:
        audit.add(FieldVerdict("pricing_tiers", "SUSPECT", None,
                               reason=f"Check crashed: {e}"))
    audit.finalize()
    return audit


def _get_supabase():
    from database import supabase
    return supabase


def audit_source(source_id: int) -> dict:
    from .fetcher import PageCache
    sb = _get_supabase()
    source_rows = sb.table("scraper_sources").select("*").eq("id", source_id).execute().data
    if not source_rows:
        raise RuntimeError(f"source {source_id} not found")
    source = source_rows[0]

    conferences = sb.table("conferences").select("*").eq(
        "source_id", source_id).eq("archived", False).execute().data
    conf_ids = [c["id"] for c in conferences]
    tiers = sb.table("pricing_tiers").select("*").in_(
        "conference_id", conf_ids).execute().data if conf_ids else []
    from collections import defaultdict
    tiers_by_conf: dict = defaultdict(list)
    for t in tiers:
        tiers_by_conf[t["conference_id"]].append(t)

    audits: list = []
    with PageCache() as cache:
        for row in conferences:
            url = row.get("source_url")
            page_text = cache.get(url) if url else ""
            page_html = cache.get_html(url) if url else None
            a = audit_row(row, page_text or "", page_html, source,
                          tiers_by_conf.get(row["id"], []))
            audits.append(a)

    # Aggregate stats
    total_rows = len(audits)
    passing_rows = sum(1 for a in audits if a.passes())
    total_missing = sum(a.total_missing for a in audits)
    total_suspect = sum(a.total_suspect for a in audits)
    avg_score = round(
        sum(a.completeness_score for a in audits) / max(1, total_rows), 1
    )

    result = {
        "source_id": source_id,
        "source_name": source.get("source_name"),
        "rows": total_rows,
        "passing_rows": passing_rows,
        "failing_rows": total_rows - passing_rows,
        "total_missing_fields": total_missing,
        "total_suspect_fields": total_suspect,
        "avg_completeness": avg_score,
        "verdict": "PASS" if total_missing == 0 and total_suspect == 0 else "FAIL",
        "audits": [asdict(a) for a in audits],
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write report
    repo_root = Path(__file__).resolve().parent.parent.parent
    out_dir = repo_root / "reports" / "audit" / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"source-{source_id}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    _print_summary(result)
    return result


def _print_summary(result: dict) -> None:
    verdict_line = "✅ PASS" if result["verdict"] == "PASS" else "❌ FAIL — BLOCKS SIGN-OFF"
    b = "─" * 60
    print(b)
    print(f"Source {result['source_id']}: {result['source_name']}")
    print(b)
    print(f"  Rows checked:        {result['rows']}")
    print(f"  Rows passing:        {result['passing_rows']}/{result['rows']}")
    print(f"  Total MISSING:       {result['total_missing_fields']}")
    print(f"  Total SUSPECT:       {result['total_suspect_fields']}")
    print(f"  Avg completeness:    {result['avg_completeness']}%")
    print(f"  Verdict:             {verdict_line}")
    print()
    for a in result["audits"]:
        if a["total_missing"] > 0 or a["total_suspect"] > 0:
            print(f"  [{a['conference_id']}] {a['conference_name'][:55]}"
                  f"  ({a['completeness_score']}%)")
            for f in a["fields"]:
                if f["status"] in ("MISSING", "SUSPECT"):
                    icon = "!" if f["status"] == "MISSING" else "?"
                    print(f"    {icon} {f['field']:22} — {f['status']:8} — {f['reason']}")
                    if f.get("page_evidence"):
                        print(f"      evidence: {f['page_evidence'][:100]}")
    print(b)


def main() -> int:
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    p = argparse.ArgumentParser(description="Full-field audit of a source")
    p.add_argument("--source", type=int, required=True)
    args = p.parse_args()
    result = audit_source(args.source)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
