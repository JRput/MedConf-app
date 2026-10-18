"""Flow 1: add-info dialog on a listed event -> pending -> approve -> renders with Community tag."""
import re, sys, os
from playwright.sync_api import sync_playwright
from helpers import *

R = Results("add_info"); svc, an = service(), anon(); sub = creds("submitter")
CONF = int(sys.argv[1]) if len(sys.argv) > 1 else 819
clean_user(svc, "submitter")

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 900})
    login(pg, "submitter"); R.check("/auth/login" not in pg.url, f"login ok ({pg.url})")

    def open_dialog():
        pg.goto(f"{BASE}/conferences/{CONF}"); pg.wait_for_load_state("networkidle")
        pg.get_by_role("button", name="Add missing info").first.click()
        d = pg.get_by_role("dialog"); d.wait_for(timeout=10000); return d

    def submit(d):
        btn = d.get_by_role("button", name=re.compile(r"^(submit|send|add info|save|share)", re.I))
        (btn if btn.count() else d.locator("button[type=submit]")).first.click()

    d = open_dialog(); d.get_by_role("button", name=re.compile(r"^Fees$")).click()
    frm = d.locator('input[id$="-from"]'); frm.wait_for(timeout=5000); frm.fill("150"); frm.blur()
    submit(d); pg.wait_for_timeout(1500)
    R.check(pg.get_by_text(re.compile("Thanks", re.I)).count() > 0 or pg.get_by_role("dialog").count() == 0, "fees submission acknowledged")

    d = open_dialog(); d.get_by_role("button", name=re.compile(r"^Note$")).click()
    ta = d.locator("textarea").first; ta.wait_for(timeout=5000); ta.fill("Parking is free on site and the venue has step-free access.")
    submit(d); pg.wait_for_timeout(1500)

    rows = svc.table("community_contributions").select("id,kind,status,payload,enrichment_status").eq("user_id", sub["user_id"]).eq("conference_id", CONF).order("created_at").execute().data
    R.check(len(rows) == 2, f"two contributions stored (got {len(rows)})")
    fees = next((r for r in rows if "fees" in (r["payload"] or {})), None)
    R.check(fees is not None and str((fees["payload"]["fees"] or {}).get("from_price")) in ("150", "150.0", "150.00"), f"fees payload stored: {fees and fees['payload'].get('fees')}")
    R.check(all(r["status"] == "pending" and r["enrichment_status"] == "waiting" for r in rows), "both pending + waiting enrichment")

    err = rpc_err(lambda: svc.rpc("moderate_contribution", {"p_id": fees["id"], "p_action": "approve", "p_note": "no override"}).execute())
    R.check(err and "safety-checked" in err, f"approve WITHOUT approve_unchecked refused while waiting: {(err or 'NOT REFUSED')[:80]}")
    st = svc.table("community_contributions").select("status").eq("id", fees["id"]).execute().data[0]["status"]
    R.check(st == "pending", f"refused approve left the row pending ({st})")

    res = svc.rpc("moderate_contribution", {"p_id": fees["id"], "p_action": "approve", "p_note": "e2e approve", "p_final": {**fees["payload"], "approve_unchecked": True}}).execute().data
    R.check(isinstance(res, dict) and res.get("ok") is True and res.get("status") == "published", f"approve with override -> {res}")
    tiers = an.table("community_tiers").select("tier_label,price,currency,is_published").eq("conference_id", CONF).execute().data
    R.check(any(float(t["price"]) == 150.0 and t["is_published"] for t in tiers), f"anon sees published community tier: {tiers}")
    notes = svc.table("notifications").select("type,title").eq("user_id", sub["user_id"]).eq("type", "contribution_update").execute().data
    R.check(len(notes) >= 1, f"submitter notified: {[n['title'] for n in notes]}")

    pg.goto(f"{BASE}/conferences/{CONF}"); pg.wait_for_load_state("networkidle"); html = pg.content()
    R.check("Community" in html, "page shows Community tag"); R.check("150" in html, "page shows the 150 fee")
    b.close()

user = user_client("submitter")
err = rpc_err(lambda: user.table("community_contributions").insert({"kind": "add_info", "conference_id": CONF, "payload": {"fields": {"booking_url": "javascript:alert(1)"}}}).execute())
R.check(err and "http" in err, f"javascript: URL rejected server-side: {(err or 'ACCEPTED')[:90]}")
err = rpc_err(lambda: user.table("community_contributions").insert({"kind": "add_info", "conference_id": CONF, "payload": {"fields": {"city": "Leeds"}}, "status": "published"}).execute())
row = svc.table("community_contributions").select("status").eq("user_id", sub["user_id"]).eq("conference_id", CONF).order("created_at", desc=True).limit(1).execute().data[0]
R.check(err is None and row["status"] == "pending", f"client-set status forced back to pending (got {row['status']}, err={err})")
sys.exit(R.finish())
