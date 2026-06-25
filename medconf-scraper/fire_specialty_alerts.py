"""
fire_specialty_alerts.py

Runs daily (03:00 UTC) via GitHub Actions, AFTER the main scrape cron
(02:00 UTC) so it sees any events the scrape just added.

For each opted-in user (notification_preferences.email_new_conferences=true),
finds conferences/courses where:
  - specialty matches the user's specialty (exact, case-insensitive)
  - created_at > user.last_specialty_alert_at  (the per-user watermark)
  - not archived

If any matches found, inserts ONE batched notification ("3 new Cardiology
events") and advances the watermark to NOW().

In-app only — no emails. The bell icon polls notifications for unread
counts. Clicking the notification deep-links to
/conferences?specialty=<...>&sort=recently_added.

Idempotent in the absence of new data: re-running on the same day with
nothing fresh inserts no notifications.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client


def _supabase() -> Client:
    load_dotenv()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]  # service role bypasses RLS to write notifications
    return create_client(url, key)


def _format_title(count: int, specialty: str, kinds: set) -> str:
    """Title shown in the bell + notifications list.

    `kinds` is the set of event_type values present in the matched rows
    ({'conference','course','workshop'} subset). Pure batches use the
    specific noun; mixed batches collapse to 'events'.
    """
    if len(kinds) == 1:
        kind = next(iter(kinds))
        if kind == "course":
            noun = "course" if count == 1 else "courses"
        elif kind == "workshop":
            noun = "workshop" if count == 1 else "workshops"
        else:
            noun = "conference" if count == 1 else "conferences"
    else:
        noun = "event" if count == 1 else "events"

    return f"{count} new {specialty} {noun}"


def _format_body(rows: list, specialty: str) -> str:
    """Small subtitle that shows up under the title in the bell row.

    Lists up to 3 names; appends '+N more' beyond that so the row stays compact.
    """
    names = [r["conference_name"] for r in rows[:3]]
    head = ", ".join(names)
    if len(rows) > 3:
        head += f" + {len(rows) - 3} more"
    return head


def fire_alerts(sb: Client) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()

    # Load opted-in users joined with their specialty + watermark
    users_resp = sb.table("notification_preferences") \
        .select("id, email_new_conferences") \
        .eq("email_new_conferences", True) \
        .execute()

    user_ids = [u["id"] for u in (users_resp.data or [])]
    if not user_ids:
        print("No opted-in users.")
        return {"users": 0, "alerts": 0, "matches": 0, "errors": 0}

    profiles_resp = sb.table("user_profiles") \
        .select("id, specialty, last_specialty_alert_at") \
        .in_("id", user_ids) \
        .execute()

    users = [
        u for u in (profiles_resp.data or [])
        if u.get("specialty") and u["specialty"].strip() and u["specialty"].lower() != "other"
    ]
    print(f"Considering {len(users)} opted-in user(s) with a specialty set.")

    alerts_fired = 0
    matches_total = 0
    errors = 0

    for u in users:
        specialty = u["specialty"]
        watermark = u.get("last_specialty_alert_at")

        try:
            # Find specialty matches created after the watermark
            q = sb.table("conferences") \
                .select("id, conference_name, event_type, created_at") \
                .eq("archived", False) \
                .ilike("specialty", specialty) \
                .order("created_at", desc=True)
            if watermark:
                q = q.gt("created_at", watermark)
            # Cap at 50 — beyond that the user gets one rolled-up notification
            # anyway; we just don't need every single id for the body summary.
            resp = q.limit(50).execute()
            matches = resp.data or []
        except Exception as e:
            print(f"  user {u['id']}: query failed ({e})")
            errors += 1
            continue

        if not matches:
            continue

        matches_total += len(matches)
        kinds = {m.get("event_type") or "conference" for m in matches}

        title = _format_title(len(matches), specialty, kinds)
        body = _format_body(matches, specialty)

        try:
            sb.table("notifications").insert({
                "user_id": u["id"],
                "type": "new_in_specialty",
                "title": title,
                "body": body,
                # No conference_id on a batched alert — link lives in the
                # NotificationBell click handler (deep-links to the
                # specialty-filtered directory).
                "conference_id": None,
            }).execute()

            sb.table("user_profiles") \
                .update({"last_specialty_alert_at": now_iso}) \
                .eq("id", u["id"]) \
                .execute()

            alerts_fired += 1
            print(f"  user {u['id']}: {title}")
        except Exception as e:
            print(f"  user {u['id']}: insert failed ({e})")
            errors += 1

    summary = {
        "users": len(users),
        "alerts": alerts_fired,
        "matches": matches_total,
        "errors": errors,
    }
    print(f"Done: {summary}")
    return summary


if __name__ == "__main__":
    sb = _supabase()
    summary = fire_alerts(sb)
    sys.exit(1 if summary["errors"] > 0 else 0)
