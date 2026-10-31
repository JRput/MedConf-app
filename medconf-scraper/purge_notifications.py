"""
purge_notifications.py

Retention job: deletes rows from `notifications` older than 12 months.
Runs as an extra step of the daily fire-reminders workflow.

  python purge_notifications.py            # delete in batches of 1000
  python purge_notifications.py --dry-run  # count only, no delete

Exit 0 on success, 1 on any error. Never prints secrets.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

BATCH_SIZE = 1000
RETENTION_MONTHS = 12


def cutoff_iso(now: Optional[datetime] = None) -> str:
    """UTC ISO timestamp exactly 12 calendar months before `now`."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    year, month = now.year, now.month - RETENTION_MONTHS
    if month < 1:
        month += 12
        year -= 1
    # clamp the day (e.g. 29 Feb -> 28 Feb)
    day = now.day
    while True:
        try:
            cut = now.replace(year=year, month=month, day=day)
            break
        except ValueError:
            day -= 1
    return cut.isoformat()


def _supabase():
    from supabase import create_client

    # The reminders workflow has no KIMI_API_KEY, so config.validate_config()
    # (which requires it) cannot be used; check the two vars this job needs.
    load_dotenv()
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY") if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def count_old(sb, cutoff: str) -> int:
    res = sb.table("notifications").select("id", count="exact").lt("created_at", cutoff).limit(1).execute()
    return res.count or 0


def purge(sb, cutoff: str, dry_run: bool = False) -> int:
    if dry_run:
        return count_old(sb, cutoff)
    total = 0
    while True:
        rows = (
            sb.table("notifications").select("id").lt("created_at", cutoff)
            .order("created_at").limit(BATCH_SIZE).execute().data
        )
        if not rows:
            return total
        ids = [r["id"] for r in rows]
        sb.table("notifications").delete().in_("id", ids).execute()
        total += len(ids)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the count only; delete nothing")
    args = ap.parse_args(argv)
    try:
        sb = _supabase()
        cutoff = cutoff_iso()
        n = purge(sb, cutoff, dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001 - report type only, never secrets
        print(f"purge_notifications failed: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1
    verb = "would delete" if args.dry_run else "deleted"
    print(f"{verb} {n} notifications older than {cutoff}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
