"""Flow 3: moderation UI (approve, request info, override for unchecked URL) + member resubmit loop."""
import re, sys
from playwright.sync_api import sync_playwright
from helpers import *

R = Results("moderation"); svc = service(); mod, sub = creds("moderator"), creds("submitter")
clean_user(svc, "submitter")
SEED = {}
def seed_add_info(fields, conf=819):
    return svc.table("community_contributions").insert({"user_id": sub["user_id"], "kind": "add_info", "conference_id": conf, "payload": {"fields": fields}}).execute().data[0]
note_item = seed_add_info({"note": "Parking is free on site and the venue has step-free access."})
other_item = seed_add_info({"city": "Leeds"})
new_item = svc.table("community_contributions").insert({"user_id": sub["user_id"], "kind": "new_event", "payload": {
    "conference_name": f"E2E Override Meeting {RUN_TS}", "event_type": "conference", "event_format": "in_person", "start_date": "2027-04-10",
    "country": "United Kingdom", "region": "England", "city": "Leeds", "specialty": "Oncology", "organiser_url": f"https://example.org/e2e/{RUN_TS}-override",
    "cpd_accredited": False, "abstract_open": False, "description": "Override path test."}}).execute().data[0]
R.check(new_item["enrichment_status"] == "waiting", "seeded new_event is waiting (unchecked)")

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 1000})
    login(pg, "moderator")
    pg.goto(f"{BASE}/admin/moderation"); pg.wait_for_load_state("networkidle")
    R.check(pg.url.endswith("/admin/moderation"), f"moderator reaches the queue ({pg.url})")
    R.check(pg.get_by_role("row").count() >= 4, f"queue lists pending items ({pg.get_by_role('row').count()} rows incl header)")
    R.check(sub["email"] in pg.content() or sub["email"].split("@")[0] in pg.content(), "submitter email visible to admin")
    nav_text = re.sub(r"\s+", " ", pg.locator("nav").inner_text())[:200]
    R.check(re.search(r"Moderation\s*\d+", nav_text) is not None, "nav shows Moderation with pending badge: " + nav_text)

    # approve note item through the UI (waiting enrichment -> may require the override flow)
    pg.goto(f"{BASE}/admin/moderation/{note_item['id']}"); pg.wait_for_load_state("networkidle")
    R.check(pg.get_by_label("Field review").count() == 1, "field review table rendered")
    anyway = pg.get_by_role("button", name=re.compile(r"Approve anyway", re.I))
    plain = pg.get_by_role("button", name=re.compile(r"^Approve$"))
    print("buttons: approve-anyway=%d plain-approve=%d" % (anyway.count(), plain.count()))
    R.check(anyway.count() > 0, "item with enrichment_status 'waiting' offers 'Approve anyway...'")
    (anyway if anyway.count() else pg.get_by_role("button", name=re.compile(r"^Approve"))).first.click(); pg.wait_for_timeout(800)
    dlg = pg.get_by_role("dialog")
    if dlg.count():
        R.check(True, "override confirm dialog appeared: " + re.sub(r"\s+", " ", dlg.first.inner_text())[:120])
        dlg.get_by_role("button", name=re.compile(r"(approve|confirm|publish)", re.I)).last.click()
    else:
        R.check(False, "override confirm dialog appeared")
    pg.wait_for_timeout(2500)
    st = svc.table("community_contributions").select("status,moderator_id").eq("id", note_item["id"]).execute().data[0]
    R.check(st["status"] == "published" and st["moderator_id"] == mod["user_id"], f"UI approve via override -> {st}")
    facts = svc.table("community_facts").select("field,is_published").eq("contribution_id", note_item["id"]).execute().data
    R.check(any(f["field"] == "note" and f["is_published"] for f in facts), f"note fact published: {facts}")

    # new_event through the override path
    pg.goto(f"{BASE}/admin/moderation/{new_item['id']}"); pg.wait_for_load_state("networkidle")
    a2 = pg.get_by_role("button", name=re.compile(r"Approve anyway", re.I))
    R.check(a2.count() > 0, "new_event waiting -> 'Approve anyway...' offered")
    if a2.count():
        a2.first.click(); pg.wait_for_timeout(800)
        d2 = pg.get_by_role("dialog")
        if d2.count(): d2.get_by_role("button", name=re.compile(r"(approve|confirm|publish)", re.I)).last.click()
        pg.wait_for_timeout(2500)
    st = svc.table("community_contributions").select("status,conference_id").eq("id", new_item["id"]).execute().data[0]
    R.check(st["status"] == "published" and st["conference_id"], f"new_event published via override -> {st}")
    if st.get("conference_id"):
        svc.table("conferences").update({"archived": True}).eq("id", st["conference_id"]).eq("source_id", 1000).execute()

    # request info (UI)
    pg.goto(f"{BASE}/admin/moderation/{other_item['id']}"); pg.wait_for_load_state("networkidle")
    pg.get_by_role("button", name=re.compile(r"Request info", re.I)).first.click()
    ta = pg.locator("#mod-reason"); ta.wait_for(timeout=5000); ta.fill("Please add the venue name as well as the city.")
    pg.get_by_role("dialog").get_by_role("button", name=re.compile(r"^(Send|Request|Confirm|Submit)", re.I)).first.click(); pg.wait_for_timeout(2500)
    st2 = svc.table("community_contributions").select("status,moderator_note").eq("id", other_item["id"]).execute().data[0]
    R.check(st2["status"] == "needs_info" and "venue" in (st2["moderator_note"] or ""), f"UI request-info -> {st2}")
    notif = svc.table("notifications").select("title").eq("user_id", sub["user_id"]).eq("type", "contribution_update").order("created_at", desc=True).limit(1).execute().data
    R.check(bool(notif) and "more information" in notif[0]["title"].lower(), f"submitter notified: {notif}")

    # member: edit and resubmit
    login(pg, "submitter"); pg.goto(f"{BASE}/dashboard/contributions"); pg.wait_for_load_state("networkidle")
    R.check("Please add the venue" in pg.content(), "moderator note shown to the member")
    pg.get_by_role("button", name=re.compile("Edit and resubmit")).first.click()
    d = pg.get_by_role("dialog"); d.wait_for(timeout=8000)
    d.get_by_role("button", name=re.compile(r"Resubmit for review")).first.click(); pg.wait_for_timeout(2500)
    st3 = svc.table("community_contributions").select("status,enrichment_status,moderator_note").eq("id", other_item["id"]).execute().data[0]
    R.check(st3["status"] == "pending" and st3["enrichment_status"] == "waiting", f"resubmit -> pending + enrichment reset: {st3}")
    pg.context.clear_cookies(); pg.goto(f"{BASE}/conferences/819"); pg.wait_for_load_state("networkidle")
    R.check("Parking is free" in pg.content(), "published community note renders on the public page")
    b.close()
sys.exit(R.finish())
