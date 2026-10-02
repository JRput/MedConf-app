"""
fire_specialty_alerts.py

Runs daily (03:00 UTC) via GitHub Actions, AFTER the main scrape cron
(02:00 UTC) so it sees any events the scrape just added.

For each opted-in user (notification_preferences.email_new_conferences=true),
finds conferences/courses where:
  - specialty matches the user's specialty
  - created_at > user.last_specialty_alert_at  (the per-user watermark)
  - not archived

Since W6 onboarding, `user_profiles.specialty` stores a canonical PARENT
SLUG from medconf-website/src/lib/taxonomy/specialties.ts (e.g. "oncology"),
not a raw `conferences.specialty` string — a plain `.ilike(specialty)`
against the raw column would silently stop matching for any multi-word
parent (e.g. "general-practice" never substring-matches "General Practice").
specialty_taxonomy.py expands the stored value (slug, or a legacy raw label
for users who onboarded before W6) into every raw value under that parent,
and this module queries with `.in_(...)` against that expanded list. See
specialty_taxonomy.py's module docstring for the full rationale.

If any matches found, inserts ONE batched notification ("3 new Cardiology
events") and advances the watermark to NOW().

In-app only — no emails. The bell icon polls notifications for unread
counts. Clicking the notification deep-links to
/conferences?specialty=<...>&sort=recently_added.

Idempotent in the absence of new data: re-running on the same day with
nothing fresh inserts no notifications.

Usage:
  python fire_specialty_alerts.py                  # normal run (writes)
  python fire_specialty_alerts.py --dry-run         # no inserts/updates, just prints what would happen
  python fire_specialty_alerts.py --explain-specialty oncology   # print the raw values a slug expands to, then exit
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

from specialty_taxonomy import TaxonomyLoadError, raw_values_for_profile_specialty


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


def fire_alerts(sb: Client, dry_run: bool = False) -> dict:
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
            raw_values = raw_values_for_profile_specialty(specialty)
        except TaxonomyLoadError as e:
            # Don't let a missing/stale specialties.json take down the whole
            # cron run for every user — fall back to the pre-W2a behaviour
            # for this user and keep going.
            print(f"  user {u['id']}: taxonomy unavailable ({e}); falling back to raw ilike match")
            raw_values = []

        try:
            q = sb.table("conferences") \
                .select("id, conference_name, event_type, created_at") \
                .eq("archived", False) \
                .order("created_at", desc=True)
            if raw_values:
                # specialty is a canonical slug (or a legacy raw label that
                # mapped to one) — match every raw value under that parent,
                # e.g. "oncology" -> ["Oncology","Clinical Oncology",...].
                q = q.in_("specialty", raw_values)
            else:
                # Unmapped value — not a known slug and not in the
                # raw->canonical map (e.g. a brand-new raw specialty the
                # scraper just introduced, before specialties.ts has been
                # updated for it). Fall back to the original substring
                # match rather than silently matching nothing.
                q = q.ilike("specialty", specialty)
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

        if dry_run:
            alerts_fired += 1
            print(f"  [dry-run] user {u['id']}: would fire \"{title}\" ({len(matches)} match(es); raw_values={raw_values or '[ilike fallback]'})")
            continue

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


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query and print what would be fired, but insert no notifications and advance no watermark.",
    )
    parser.add_argument(
        "--explain-specialty",
        metavar="SLUG_OR_LABEL",
        help="Print the raw conferences.specialty values a slug (or legacy raw label) expands to, then exit without touching the DB.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.explain_specialty:
        raw_values = raw_values_for_profile_specialty(args.explain_specialty)
        if not raw_values:
            print(f"{args.explain_specialty!r} did not resolve to a known parent slug or raw label.")
            sys.exit(1)
        print(f"{args.explain_specialty!r} expands to {len(raw_values)} raw value(s):")
        for v in sorted(raw_values):
            print(f"  - {v}")
        sys.exit(0)

    sb = _supabase()
    summary = fire_alerts(sb, dry_run=args.dry_run)
    sys.exit(1 if summary["errors"] > 0 else 0)
