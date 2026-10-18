"""
fire_moderation_digest.py

Runs daily (09:00 UTC) via GitHub Actions. For community contributions:
  1. expires pending items whose event has passed (expire_stale_contributions RPC)
  2. counts items awaiting review (pending / needs_info)
  3. gives every admin exactly one unread 'moderation' notification
     (any older unread one is replaced, so notices never stack)
  4. logs the email that would go to the moderators

Idempotent per day: re-running replaces the unread notice instead of adding one.
With nothing pending, notifications are left untouched.

Usage: python fire_moderation_digest.py [--dry-run]
"""

import os
import sys

from dotenv import load_dotenv

DEFAULT_EMAIL = "moderation@medconf.example"
PENDING_STATUSES = ["pending", "needs_info"]


def _supabase():
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]  # service-role; bypasses RLS
    return create_client(url, key)


def notify_moderators(pending: int, breakdown: str) -> None:
    """Placeholder moderator email.

    No email provider is configured yet, so this only prints what would be
    sent. Wire Resend (or similar) here later: send to MODERATION_NOTIFY_EMAIL
    with the same subject and the breakdown as the body.
    """
    addr = os.environ.get("MODERATION_NOTIFY_EMAIL") or DEFAULT_EMAIL
    subject = f"{pending} contribution(s) awaiting review"
    print(f"EMAIL (not sent — no provider configured) to {addr}: {subject}")


def _count(sb, **filters) -> int:
    q = sb.table("community_contributions").select("id", count="exact")
    q = q.in_("status", PENDING_STATUSES)
    for k, v in filters.items():
        q = q.eq(k, v)
    resp = q.execute()
    if getattr(resp, "count", None) is not None:
        return resp.count
    return len(resp.data or [])


def build_breakdown(sb) -> tuple[int, str]:
    pending = _count(sb)
    new_events = _count(sb, kind="new_event")
    add_info = _count(sb, kind="add_info")
    waiting = _count(sb, enrichment_status="waiting")
    enriched = _count(sb, enrichment_status="fetched")
    breakdown = (
        f"{new_events} new event(s), {add_info} added info; "
        f"{enriched} enriched, {waiting} waiting for enrichment."
    )
    return pending, breakdown


def run(sb, dry_run: bool = False) -> dict:
    if dry_run:
        print("DRY RUN: would expire stale contributions (RPC skipped)")
        expired = 0
    else:
        resp = sb.rpc("expire_stale_contributions").execute()
        expired = resp.data if isinstance(resp.data, int) else 0
        print(f"Expired {expired} stale contribution(s)")

    pending, breakdown = build_breakdown(sb)
    print(f"Pending review: {pending} ({breakdown})")

    notified = 0
    if pending > 0:
        title = f"{pending} contribution(s) awaiting review"
        admins = sb.table("user_profiles").select("id").eq("is_admin", True).execute().data or []
        for admin in admins:
            uid = admin["id"]
            if dry_run:
                print(f"DRY RUN: would replace unread moderation notice for admin {uid}: {title}")
                continue
            (
                sb.table("notifications")
                .delete()
                .eq("user_id", uid)
                .eq("type", "moderation")
                .is_("read_at", "null")
                .execute()
            )
            sb.table("notifications").insert(
                {
                    "user_id": uid,
                    "type": "moderation",
                    "title": title,
                    "body": breakdown,
                    "conference_id": None,
                }
            ).execute()
            notified += 1
        print(f"Notified {notified} admin(s)" if not dry_run else f"Would notify {len(admins)} admin(s)")
        notify_moderators(pending, breakdown)
    else:
        print("Nothing pending; notifications untouched")

    return {"expired": expired, "pending": pending, "notified": notified}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_dotenv()
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        print("Missing SUPABASE_URL / SUPABASE_KEY")
        return 1
    run(_supabase(), dry_run="--dry-run" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
