"""Null conference.city values written by the remediator's bare known-city heuristic.

Scans remediation reports for city patches with method heuristic_known_city
(or heuristic_postcode_prefix -> Sheffield), fetches the current rows and
nulls the cities the row data does not corroborate.

Dry-run (default): prints a decision table and totals. Never writes.
--apply: PATCH {"city": null, "remediation_attempted_at": null} for "null" decisions.

Run from medconf-scraper/:  ./.venv/bin/python tools/repair_heuristic_city.py [--reports DIR ...]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS = ROOT.parent / "reports" / "remediation"
CHUNK = 150
COLS = "id,source_id,conference_name,city,venue_name,region,event_format,archived,remediation_attempted_at"


def decide(row: dict, written_city: str) -> tuple[str, str]:
    if (row.get("event_format") or "") == "online":
        return "null", "online event"
    pat = re.compile(r"(?<!\w)" + re.escape(written_city.strip()) + r"(?!\w)", re.I)
    for field in ("venue_name", "conference_name", "region"):
        if pat.search(row.get(field) or ""):
            return "keep", f"city in {field}"
    return "null", "uncorroborated heuristic"


def _is_bad(p: dict) -> bool:
    if p.get("field") != "city":
        return False
    m, v = p.get("method"), (p.get("value_after") or "")
    if m == "heuristic_known_city":
        return True
    return m == "heuristic_postcode_prefix" and v == "Sheffield"


def scan(dirs: list[Path]) -> dict[int, tuple[str, str]]:
    """conference_id -> (value_after, date); latest date wins."""
    found: dict[int, tuple[str, str]] = {}
    for d in dirs:
        d = Path(d)
        for f in sorted(d.rglob("source-*.json")):
            date = f.parent.name
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            for p in (data.get("patches_applied") or []) if isinstance(data, dict) else []:
                if not _is_bad(p) or p.get("conference_id") is None:
                    continue
                cid = int(p["conference_id"])
                if cid not in found or date >= found[cid][1]:
                    found[cid] = (p["value_after"], date)
    return found


def _env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY missing (medconf-scraper/.env)")
    return url.rstrip("/"), {"apikey": key, "Authorization": f"Bearer {key}"}


def fetch_rows(ids: list[int]) -> list[dict]:
    url, hdr = _env()
    rows: list[dict] = []
    for i in range(0, len(ids), CHUNK):
        chunk = ",".join(str(x) for x in ids[i:i + CHUNK])
        r = httpx.get(f"{url}/rest/v1/conferences?select={COLS}&id=in.({chunk})", headers=hdr, timeout=60)
        r.raise_for_status()
        rows.extend(r.json())
    return rows


def _t(s, n):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", action="append", type=Path)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    found = scan(a.reports or [DEFAULT_REPORTS])
    rows = fetch_rows(sorted(found))
    cands, archived = [], 0
    for r in rows:
        written = found[r["id"]][0]
        if (r.get("city") or "").strip().lower() != written.strip().lower():
            continue
        if r.get("archived"):
            archived += 1
            continue
        d, why = decide(r, written)
        cands.append((r, d, why))
    for r, d, why in sorted(cands, key=lambda c: c[0]["id"]):
        print(f"{r['id']}\t{r['source_id']}\t{d}\t{why}\t{r['city']}\t{_t(r.get('venue_name'),30)}\t"
              f"{_t(r.get('region'),15)}\t{r.get('event_format')}\t{_t(r.get('conference_name'),50)}")
    nulls = [c for c in cands if c[1] == "null"]
    print(f"\ncandidates={len(cands)} keep={len(cands) - len(nulls)} null={len(nulls)} archived-skipped={archived}")
    if not a.apply:
        return 0
    if not cands:
        sys.exit("refusing to apply: 0 candidates")
    url, hdr = _env()
    hdr = {**hdr, "Content-Type": "application/json", "Prefer": "return=minimal"}
    for r, _, _ in nulls:
        resp = httpx.patch(f"{url}/rest/v1/conferences?id=eq.{r['id']}", headers=hdr, timeout=60,
                           json={"city": None, "remediation_attempted_at": None})
        resp.raise_for_status()
        print(f"patched {r['id']} -> {resp.status_code}")
    print(f"applied {len(nulls)} nulls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
