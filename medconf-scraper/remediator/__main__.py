"""CLI entry — python -m remediator --source N"""

from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

from .runner import remediate_source
from .report import print_summary


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    p = argparse.ArgumentParser(prog="python -m remediator")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--source", type=int, help="Source ID to remediate")
    grp.add_argument("--all", action="store_true",
                     help="Run on every active source")
    args = p.parse_args()

    if args.all:
        from database import supabase
        active = supabase.table("scraper_sources").select("id").eq(
            "active", True
        ).order("id").execute().data or []
        for s in active:
            try:
                summary = remediate_source(s["id"])
                print_summary(Path(summary["report_path"]))
            except Exception as e:
                print(f"Source {s['id']} failed: {e}", file=sys.stderr)
        return 0

    summary = remediate_source(args.source)
    print_summary(Path(summary["report_path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
