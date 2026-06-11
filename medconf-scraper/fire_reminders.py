"""
fire_reminders.py

Runs daily (08:00 UTC) via GitHub Actions. Finds user_reminders rows
whose scheduled_for date has arrived, creates an in-app notification
row for each, and marks the reminder as sent.

In-app only — there's no email send. The /dashboard notification bell
polls notifications for unread counts.

Idempotent: if the workflow is run twice on the same day, the second
run finds nothing because the first marked everything as 'sent'.
"""

import os
import sys
from datetime import date, datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client


def _supabase() -> Client:
    load_dotenv()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]  # service-role; bypasses RLS to write notifications
    return create_client(url, key)


def _build_title(reminder_type: str, lead_days: int, conf_name: str) -> str:
    label = {
        "abstract_deadline": "Abstract deadline",
        "conference_start": "Conference start",
        "registration_deadline": "Registration deadline",
    }.get(reminder_type, "Reminder")
    if lead_days == 0:
        when = "today"
    elif lead_days == 1:
        when = "in 1 day"
    else:
        when = f"in {lead_days} days"
    return f"{conf_name}: {label.lower()} {when}"


def _build_body(reminder_type: str, target_date: str) -> str:
    label = {
        "abstract_deadline": "Abstract submissions close",
        "conference_start": "Conference starts",
        "registration_deadline": "Registration closes",
    }.get(reminder_type, "Event")
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    pretty = target.strftime("%A %d %B %Y")
    return f"{label} on {pretty}."


def fire_due_reminders(sb: Client, today: Optional[date] = None) -> dict:
    today = today or date.today()
    today_iso = today.isoformat()

    # Find due, still-scheduled reminders
    due = sb.table("user_reminders") \
        .select("id, user_id, conference_id, reminder_type, lead_time_days, target_date, scheduled_for") \
        .eq("status", "scheduled") \
        .lte("scheduled_for", today_iso) \
        .execute()

    rows = due.data or []
    if not rows:
        print(f"[{today_iso}] No reminders due.")
        return {"due": 0, "fired": 0, "skipped_archived": 0, "errors": 0}

    print(f"[{today_iso}] Found {len(rows)} due reminder(s).")

    # Batch-fetch the conferences referenced (so we have names for the
    # notification title without an N+1 query)
    conference_ids = list({r["conference_id"] for r in rows})
    conf_resp = sb.table("conferences") \
        .select("id, conference_name, archived") \
        .in_("id", conference_ids) \
        .execute()
    conf_by_id = {c["id"]: c for c in (conf_resp.data or [])}

    fired = 0
    skipped_archived = 0
    errors = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for r in rows:
        conf = conf_by_id.get(r["conference_id"])
        if not conf:
            print(f"  - reminder {r['id']}: conference {r['conference_id']} missing; cancelling.")
            try:
                sb.table("user_reminders") \
                    .update({"status": "cancelled", "updated_at": now_iso}) \
                    .eq("id", r["id"]) \
                    .execute()
            except Exception as e:
                print(f"    error cancelling: {e}")
                errors += 1
            continue

        if conf.get("archived"):
            # Don't surface notifications for archived events
            try:
                sb.table("user_reminders") \
                    .update({"status": "cancelled", "updated_at": now_iso}) \
                    .eq("id", r["id"]) \
                    .execute()
                skipped_archived += 1
            except Exception as e:
                print(f"    error cancelling archived: {e}")
                errors += 1
            continue

        title = _build_title(r["reminder_type"], r["lead_time_days"], conf["conference_name"])
        body = _build_body(r["reminder_type"], r["target_date"])

        try:
            sb.table("notifications").insert({
                "user_id": r["user_id"],
                "type": "reminder",
                "title": title,
                "body": body,
                "conference_id": r["conference_id"],
                "reminder_id": r["id"],
            }).execute()

            sb.table("user_reminders") \
                .update({"status": "sent", "sent_at": now_iso, "updated_at": now_iso}) \
                .eq("id", r["id"]) \
                .execute()
            fired += 1
        except Exception as e:
            print(f"  - reminder {r['id']}: failed to fire ({e})")
            errors += 1

    summary = {"due": len(rows), "fired": fired, "skipped_archived": skipped_archived, "errors": errors}
    print(f"[{today_iso}] Done: {summary}")
    return summary


if __name__ == "__main__":
    sb = _supabase()
    summary = fire_due_reminders(sb)
    # Exit non-zero on errors so the workflow fails loudly
    sys.exit(1 if summary["errors"] > 0 else 0)
