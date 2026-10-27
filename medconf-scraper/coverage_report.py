#!/usr/bin/env python
"""Cross-source data coverage report + regression gate (read-only).

Per ACTIVE source (non-archived events only):
  fees_pct      % of events with at least one pricing tier
  abstracts_pct % of conferences + workshops with an abstract deadline or note
                (courses and on-demand rows excluded; same rule as
                remediator/detector.py)
  venue_pct     % of in-person/hybrid/unset-format events with a venue
  city_pct      % of in-person/hybrid/unset-format events with a city
                (online rows are NOT_APPLICABLE for venue and city)

Writes reports/coverage/<date>.json + .md, prints a GitHub job summary when
GITHUB_STEP_SUMMARY is set, and compares with reports/coverage/baseline.json.

Exit codes: 0 ok (also: DB/transport error -> "coverage check skipped"), 1 regression,
2 config error (missing SUPABASE_URL / SUPABASE_KEY).
Regression (red) = a source with >= MIN_EVENTS events whose metric is more than
MAX_DROP_PP points below the baseline on TWO consecutive daily reports (today's and
the previous report file), OR a source registered in the last RECENT_DAYS days has
no coverage entry (no live events). First run / no previous report: never red.
Sources with fewer than MIN_EVENTS events are advisory only (printed, never red).
--update-baseline rewrites the baseline from the current numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MIN_EVENTS = 25  # below this a single event moves a metric by > MAX_DROP_PP: advisory only
MAX_DROP_PP = 10.0
RECENT_DAYS = 7
METRICS = ("fees_pct", "abstracts_pct", "venue_pct", "city_pct")
PAGE = 1000  # PostgREST row cap (HQ LESSONS #87)

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_DIR = REPO_ROOT / "reports" / "coverage"
BASELINE = COVERAGE_DIR / "baseline.json"


def _pct(n: int, d: int):
    return round(100.0 * n / d, 1) if d else None


def compute_coverage(sources: list[dict], confs: list[dict], tier_conf_ids: set) -> dict:
    """Pure function. sources = active scraper_sources rows; confs = non-archived rows."""
    acc: dict[int, dict] = {}
    for s in sources:
        acc[s["id"]] = {"name": s.get("source_name"), "society": s.get("society"),
                        "events": 0, "fee_ok": 0, "abs_n": 0, "abs_ok": 0,
                        "loc_n": 0, "venue_ok": 0, "city_ok": 0}
    tot = {"events": 0, "fee_ok": 0, "abs_n": 0, "abs_ok": 0,
           "loc_n": 0, "venue_ok": 0, "city_ok": 0}
    for c in confs:
        a = acc.get(c.get("source_id"))
        if a is None:
            continue
        for t in (a, tot):
            t["events"] += 1
            if c["id"] in tier_conf_ids:
                t["fee_ok"] += 1
            if c.get("event_type") in ("conference", "workshop") and not c.get("is_on_demand"):
                t["abs_n"] += 1
                if c.get("abstract_deadline") or c.get("abstract_deadline_note"):
                    t["abs_ok"] += 1
            if (c.get("event_format") or "").lower() in ("in_person", "hybrid", ""):
                t["loc_n"] += 1
                if c.get("venue_name"):
                    t["venue_ok"] += 1
                if c.get("city"):
                    t["city_ok"] += 1

    def fmt(a):
        return {"events": a["events"],
                "fees_pct": _pct(a["fee_ok"], a["events"]),
                "abstracts_pct": _pct(a["abs_ok"], a["abs_n"]), "abstracts_n": a["abs_n"],
                "venue_pct": _pct(a["venue_ok"], a["loc_n"]),
                "city_pct": _pct(a["city_ok"], a["loc_n"]), "location_n": a["loc_n"]}

    out = {}
    for sid, a in acc.items():
        row = fmt(a)
        row["name"], row["society"] = a["name"], a["society"]
        out[str(sid)] = row
    return {"sources": out, "totals": fmt(tot)}


def recent_source_ids(sources: list[dict], now: datetime, days: int = RECENT_DAYS) -> list[int]:
    cutoff = now - timedelta(days=days)
    ids = []
    for s in sources:
        v = s.get("created_at")
        if not v:
            continue
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d >= cutoff:
            ids.append(s["id"])
    return sorted(ids)


def _drops(baseline: dict | None, current: dict, min_events: int | None, max_events: int | None = None):
    """{(sid, metric): (bv, nv, events, name)} for metrics more than MAX_DROP_PP under baseline."""
    out = {}
    base = (baseline or {}).get("sources", {})
    for sid, e in (current or {}).get("sources", {}).items():
        b = base.get(sid)
        n = e.get("events") or 0
        if not b or (min_events is not None and n < min_events) or (max_events is not None and n >= max_events):
            continue
        for m in METRICS:
            nv, bv = e.get(m), b.get(m)
            if nv is None or bv is None:
                continue
            if bv - nv > MAX_DROP_PP:
                out[(sid, m)] = (bv, nv, n, e.get("name"))
    return out


def evaluate(baseline: dict | None, current: dict, recent_ids: list[int],
             previous: dict | None = None) -> tuple[list[str], list[str]]:
    """(regressions, advisories). A regression needs the same drop vs the baseline on
    today's report AND the previous one; a single-day dip, or no previous report,
    is advisory. Small sources (< MIN_EVENTS) are always advisory."""
    problems: list[str] = []
    advisories: list[str] = []
    cur = current["sources"]
    for sid in recent_ids:
        e = cur.get(str(sid))
        if not e or not e["events"]:
            problems.append(f"source {sid}: registered in the last {RECENT_DAYS} days but has no coverage entry (no live events)")
    prev_drops = _drops(baseline, previous, MIN_EVENTS) if previous else None
    for (sid, m), (bv, nv, n, name) in _drops(baseline, current, MIN_EVENTS).items():
        msg = f"source {sid} ({name}): {m} fell {bv:.1f}% -> {nv:.1f}% (-{bv - nv:.1f} pp, {n} events)"
        if prev_drops is not None and (sid, m) in prev_drops:
            problems.append(msg + " on 2 consecutive reports")
        else:
            advisories.append(msg + (" (first day below threshold)" if prev_drops is not None
                                     else " (no previous report to confirm)"))
    for (sid, m), (bv, nv, n, name) in _drops(baseline, current, None, MIN_EVENTS).items():
        advisories.append(f"source {sid} ({name}): {m} fell {bv:.1f}% -> {nv:.1f}% "
                          f"(-{bv - nv:.1f} pp, only {n} events: advisory)")
    return problems, advisories


def compare(baseline: dict | None, current: dict, recent_ids: list[int],
            previous: dict | None = None) -> list[str]:
    """Regression messages only (empty = pass)."""
    return evaluate(baseline, current, recent_ids, previous)[0]


def load_previous(out_dir: Path, day: str) -> dict | None:
    """Latest dated report in out_dir strictly before `day`, or None."""
    best = None
    for p in out_dir.glob("????-??-??.json"):
        if p.stem < day and (best is None or p.stem > best.stem):
            best = p
    if best is None:
        return None
    try:
        return json.loads(best.read_text())
    except (OSError, ValueError):
        return None


def render_markdown(current: dict, problems: list[str], day: str, advisories: list[str] | None = None) -> str:
    def f(v):
        return "n/a" if v is None else f"{v:.0f}%"
    t = current["totals"]
    lines = [f"## Coverage report {day}", "",
             f"Global: {t['events']} events | fees {f(t['fees_pct'])} | abstracts {f(t['abstracts_pct'])} "
             f"| venue {f(t['venue_pct'])} | city {f(t['city_pct'])}", ""]
    lines += ["**Regressions:** " + ("none" if not problems else ""), ""]
    lines += [f"- {p}" for p in problems]
    if advisories:
        lines += ["", "**Advisory (never red):**", ""] + [f"- {a}" for a in advisories]
    lines += ["", "| id | source | events | fees | abstracts | venue | city |", "|---|---|---|---|---|---|---|"]
    for sid, e in sorted(current["sources"].items(), key=lambda kv: int(kv[0])):
        lines.append(f"| {sid} | {e.get('name') or ''} | {e['events']} | {f(e['fees_pct'])} | "
                     f"{f(e['abstracts_pct'])} | {f(e['venue_pct'])} | {f(e['city_pct'])} |")
    return "\n".join(lines) + "\n"


def _fetch_all(client, table: str, cols: str, order: str = "id", **eq) -> list[dict]:
    rows, start = [], 0
    while True:
        q = client.table(table).select(cols).order(order)
        for k, v in eq.items():
            q = q.eq(k, v)
        batch = q.range(start, start + PAGE - 1).execute().data or []
        rows += batch
        if len(batch) < PAGE:
            return rows
        start += PAGE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--out-dir", default=str(COVERAGE_DIR))
    ap.add_argument("--baseline", default=str(BASELINE))
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set", file=sys.stderr)
        return 2
    try:
        from supabase import create_client
        cl = create_client(url, key)
        sources = _fetch_all(cl, "scraper_sources", "id,source_name,society,active,created_at", active=True)
        confs = _fetch_all(cl, "conferences",
                           "id,source_id,event_type,event_format,venue_name,city,abstract_deadline,"
                           "abstract_deadline_note,is_on_demand", archived=False)
        tiers = {r["conference_id"] for r in _fetch_all(cl, "pricing_tiers", "id,conference_id")}
    except Exception as e:
        # A transient DB / network error says nothing about coverage: never red.
        msg = f"coverage check skipped: could not read Supabase ({type(e).__name__}: {str(e)[:200]})"
        print(msg)
        summ = os.getenv("GITHUB_STEP_SUMMARY")
        if summ:
            try:
                with open(summ, "a", encoding="utf-8") as fh:
                    fh.write(msg + "\n")
            except OSError:
                pass
        return 0

    now = datetime.now(timezone.utc)
    day = date.today().isoformat()
    current = compute_coverage(sources, confs, tiers)
    current["date"] = day
    bp = Path(args.baseline)
    baseline = json.loads(bp.read_text()) if bp.exists() else None
    previous = load_previous(Path(args.out_dir), day)
    problems, advisories = evaluate(baseline, current, recent_source_ids(sources, now), previous)
    if baseline is None:
        print("NOTE: no baseline file; regression comparison skipped")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    current["regressions"] = problems
    current["advisories"] = advisories
    (out / f"{day}.json").write_text(json.dumps(current, indent=2))
    md = render_markdown(current, problems, day, advisories)
    (out / f"{day}.md").write_text(md)
    print(md)
    summ = os.getenv("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as fh:
            fh.write(md)
    if args.update_baseline:
        clean = {k: v for k, v in current.items() if k not in ("regressions", "advisories")}
        bp.write_text(json.dumps(clean, indent=2))
        print(f"baseline updated: {bp}")
        return 0
    for p in problems:
        print("REGRESSION", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
