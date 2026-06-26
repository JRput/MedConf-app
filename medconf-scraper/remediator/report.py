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
) -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = repo_root / "reports" / "remediation" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"source-{source_id}.json"
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
        print("  Couldn't fix:")
        for p in data["patches_couldnt_fix"][:5]:
            print(f"    [{p['conference_id']}] {p['fields']} — source genuinely missing")
    print(border)
    print(f"  Report: {report_path}")
    print(f"  Duration: {data['duration_sec']}s")
    print(border)
