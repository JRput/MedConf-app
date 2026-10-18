"""Flow 4: moderation digest -> exactly one unread 'moderation' notification per admin, no stacking on re-run."""
import os, subprocess, sys
from helpers import *

R = Results("digest"); svc = service(); mod = creds("moderator"); sub = creds("submitter")
pend = svc.table("community_contributions").select("id", count="exact").in_("status", ["pending", "needs_info"]).execute().count
if not pend:
    svc.table("community_contributions").insert({"user_id": sub["user_id"], "kind": "add_info", "conference_id": 819, "payload": {"fields": {"city": "Leeds"}}}).execute()
R.check(True, f"pending/needs_info items before run: {pend or 1}")

def run_digest():
    r = subprocess.run([os.path.join(ROOT, "medconf-scraper", ".venv", "bin", "python"), "fire_moderation_digest.py"],
                       cwd=os.path.join(ROOT, "medconf-scraper"), capture_output=True, text=True)
    print(r.stdout.strip()[-400:]); return r.returncode

def unread(uid):
    return svc.table("notifications").select("id").eq("user_id", uid).eq("type", "moderation").is_("read_at", "null").execute().data

admins = [a["id"] for a in svc.table("user_profiles").select("id").eq("is_admin", True).execute().data]
R.check(mod["user_id"] in admins, f"test moderator is admin; admin count = {len(admins)}")
R.check(run_digest() == 0, "digest run 1 exit 0")
c1 = {a: len(unread(a)) for a in admins}
R.check(all(n == 1 for n in c1.values()), f"exactly one unread moderation notice per admin after run 1: {len(c1)} admins, counts={sorted(set(c1.values()))}")
R.check(run_digest() == 0, "digest run 2 exit 0")
c2 = {a: len(unread(a)) for a in admins}
R.check(all(n == 1 for n in c2.values()), f"still exactly one after run 2 (no stacking): counts={sorted(set(c2.values()))}")
non_admin = svc.table("notifications").select("id").eq("user_id", sub["user_id"]).eq("type", "moderation").execute().data
R.check(not non_admin, "submitter (non-admin) got no moderation notice")
sys.exit(R.finish())
