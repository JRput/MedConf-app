"""Report writer — emits a structured JSON file per remediator run.

Reports live under reports/remediation/YYYY-MM-DD/source-N.json so
multiple runs in the same day for the same source overwrite cleanly.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List


def write_report(
    *,
    source_id: int,
    source_name: str,
    society: str | None,
    events_scraped: int,
    events_with_gaps: int,
    patches_applied: List[dict],
    patches_rejected: List[dict],
    patches_couldnt_fix: List[dict],
    duration_sec: float,
    explorer_trails: List[dict] | None = None,
) -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = repo_root / "reports" / "remediation" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"source-{source_id}.json"
    # Attach the audit trail to each couldnt_fix entry so the verdict is
    # provable. The next session's Claude (or the user) can re-verify by
    # walking the trail.
    trails_by_conf: dict = {}
    for t in (explorer_trails or []):
        trails_by_conf.setdefault(t["conference_id"], []).append(t)
    for entry in patches_couldnt_fix:
        cid = entry["conference_id"]
        trails = trails_by_conf.get(cid, [])
        # Only attach trails for unfixed fields
        unfixed_fields = set(entry.get("fields") or [])
        entry["exploration_evidence"] = [
            {
                "field": t["field"],
                "method": t["method"],
                "places_looked": {
                    "tabs_visited": t["audit_trail"].get("tabs_visited", []),
                    "subpages_fetched": t["audit_trail"].get("subpages_fetched", []),
                    "images_ocred": t["audit_trail"].get("images_ocred", 0),
                    "total_text_chars": t["audit_trail"].get("total_text_chars", 0),
                },
                "llm_reasoning": t["audit_trail"].get("llm_reasoning", ""),
                "notes": t["audit_trail"].get("notes", []),
            }
            for t in trails if t["field"] in unfixed_fields
        ]

    report = {
        "source_id": source_id,
        "source_name": source_name,
        "society": society,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "events_scraped": events_scraped,
        "events_with_gaps_at_first": events_with_gaps,
        "events_fixed": len({p["conference_id"] for p in patches_applied}),
        "events_still_incomplete": len(patches_couldnt_fix),
        "patches_applied": patches_applied,
        "patches_rejected_by_validator": patches_rejected,
        "patches_couldnt_fix": patches_couldnt_fix,
        "explorer_runs": len(explorer_trails or []),
        "explorer_successes": sum(1 for t in (explorer_trails or []) if t.get("found")),
        "duration_sec": round(duration_sec, 1),
    }
    out_path.write_text(json.dumps(report, indent=2, default=str))
    return out_path


def print_summary(report_path: Path) -> None:
    """Pretty-print the report contents to stdout."""
    data = json.loads(report_path.read_text())
    border = "─" * 60
    print(border)
    print(f"Source {data['source_id']}: {data['source_name']}")
    print(border)
    print(f"  {data['events_scraped']} events scraped")
    print(f"  ✓ {data['events_scraped'] - data['events_with_gaps_at_first']} complete on first scrape")
    print(f"  ⚠ {data['events_with_gaps_at_first']} events had gaps")
    print(f"    → {data['events_fixed']} fixed by remediator")
    print(f"    → {data['events_still_incomplete']} still incomplete")
    print()
    if data["patches_applied"]:
        # Group by field
        by_field: dict = {}
        for p in data["patches_applied"]:
            by_field.setdefault(p["field"], 0)
            by_field[p["field"]] += 1
        print("  Patches applied:")
        for f, n in sorted(by_field.items(), key=lambda kv: -kv[1]):
            print(f"    {f:20} ×{n}")
    if data["patches_couldnt_fix"]:
        print()
        print("  Couldn't fix (with audit trail):")
        for p in data["patches_couldnt_fix"][:5]:
            print(f"    [{p['conference_id']}] {p['fields']}")
            for ev in p.get("exploration_evidence", []):
                trail = ev.get("places_looked", {})
                print(f"      ↳ {ev['field']}: looked at "
                      f"{len(trail.get('tabs_visited', []))} tabs, "
                      f"{len(trail.get('subpages_fetched', []))} subpages, "
                      f"{trail.get('images_ocred', 0)} images "
                      f"({trail.get('total_text_chars', 0)} chars total)")
                if ev.get("llm_reasoning"):
                    print(f"        reason: {ev['llm_reasoning'][:120]}")
    if data.get("explorer_runs", 0):
        print()
        print(f"  Explorer Tier 2 escalations: {data['explorer_runs']} runs, "
              f"{data['explorer_successes']} successful")
    print(border)
    print(f"  Report: {report_path}")
    print(f"  Duration: {data['duration_sec']}s")
    print(border)
