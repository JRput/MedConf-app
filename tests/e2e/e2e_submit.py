"""Flow 2: /submit new event -> pending -> gate -> approve -> live listing -> duplicate -> merge -> hide.
Leaves one pending new_event (needed by the moderation + digest flows)."""
import re, sys
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from helpers import *

R = Results("submit"); svc, an = service(), anon(); sub = creds("submitter")
clean_user(svc, "submitter")
URL = f"https://example.org/e2e/{RUN_TS}"


def pick(pg, sel, name):
    pg.locator(sel).click(); pg.get_by_role("option", name=re.compile(f"^{re.escape(name)}$")).click()


def fill_form(pg, name, url, start, desc, price):
    pg.goto(f"{BASE}/submit"); pg.wait_for_load_state("networkidle")
    pg.locator("#sub-name").fill(name); pg.locator("#sub-url").fill(url); pg.locator("#sub-url").blur()
    pick(pg, "#sub-type", "Conference"); pick(pg, "#sub-format", "In person")
    pg.locator("#sub-start").fill(start); pg.locator("#sub-start").blur()
    pick(pg, "#sub-country", "United Kingdom")
    try: pick(pg, "#sub-nation", "England")
    except PWTimeout: print("note: nation select not found")
    pg.locator("#sub-city").fill("Manchester"); pg.locator("#sub-venue").fill("Manchester Central")
    grp = pg.locator('[aria-labelledby="sub-specialty-label"]')
    grp.get_by_role("combobox").first.click()
    opt = pg.get_by_role("option", name=re.compile("^Oncology$"))
    if opt.count() == 0: pg.keyboard.type("Oncology")
    pg.get_by_role("option", name=re.compile("^Oncology$")).first.click()
    expand(pg, r"^Fees\b")
    frm = pg.locator('input[id$="-from"]').first; frm.wait_for(timeout=5000); frm.fill(price); frm.blur()
    expand(pg, r"^(\d+\s*)?Description\b")
    pg.locator("textarea#sub-desc").fill(desc)
    pg.locator("#sub-consent").check()
    pg.get_by_role("button", name=re.compile("Submit for review")).click()
    pg.wait_for_timeout(2500)


with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 1000})
    login(pg, "submitter")
    fill_form(pg, f"E2E Oncology Symposium {RUN_TS} (test)", URL, "2027-03-15", "Automated end-to-end test submission. Will be hidden again.", "120")
    h = pg.content(); R.check("Thanks" in h or "review" in h.lower(), "submission success state shown")
    rows = svc.table("community_contributions").select("id,kind,status,payload,enrichment_status").eq("user_id", sub["user_id"]).eq("kind", "new_event").execute().data
    R.check(len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["enrichment_status"] == "waiting", f"new_event row pending+waiting (got {len(rows)})")
    r0 = rows[0]; pl = r0["payload"]
    R.check(pl.get("organiser_url") == URL and pl.get("start_date") == "2027-03-15" and pl.get("region") == "England" and pl.get("specialty") == "Oncology" and "description" in pl,
            f"payload core fields: url={pl.get('organiser_url')} region={pl.get('region')} specialty={pl.get('specialty')}")
    R.check(str((pl.get("fees") or {}).get("from_price")) in ("120", "120.0"), f"fees stored: {pl.get('fees')}")

    err = rpc_err(lambda: svc.rpc("moderate_contribution", {"p_id": r0["id"], "p_action": "approve", "p_note": "no override"}).execute())
    R.check(err and "safety-checked" in err, f"approve WITHOUT approve_unchecked refused while waiting: {(err or 'NOT REFUSED')[:70]}")
    res = svc.rpc("moderate_contribution", {"p_id": r0["id"], "p_action": "approve", "p_note": "e2e approve", "p_final": {**pl, "approve_unchecked": True}}).execute().data
    R.check(res.get("ok") is True and res.get("conference_id"), f"approve -> {res}")
    cid = res["conference_id"]
    conf = an.table("directory_events").select("id,society,price_from,specialty,region").eq("id", cid).execute().data
    R.check(conf and conf[0]["society"] == "Community" and conf[0]["price_from"] == 120, f"anon directory row price_from=120: {conf}")
    pg.goto(f"{BASE}/conferences/{cid}"); pg.wait_for_load_state("networkidle"); h = pg.content()
    R.check(f"E2E Oncology Symposium {RUN_TS}" in h and "Community" in h, "detail page renders event with Community chip")

    dup = svc.table("community_contributions").insert({"user_id": sub["user_id"], "kind": "new_event", "payload": {**pl, "conference_name": "Duplicate attempt"}}).execute().data[0]
    r2 = svc.rpc("moderate_contribution", {"p_id": dup["id"], "p_action": "approve", "p_final": {**pl, "conference_name": "Duplicate attempt", "approve_unchecked": True}}).execute().data
    R.check(r2.get("ok") is False and r2.get("code") == "duplicate" and r2.get("conference_id") == cid, f"duplicate detection -> {r2}")
    r3 = svc.rpc("moderate_contribution", {"p_id": dup["id"], "p_action": "merge", "p_final": {"merge_into_conference_id": cid, "approve_unchecked": True}}).execute().data
    R.check(r3.get("ok") is True and r3.get("status") == "merged", f"merge -> {r3}")
    r4 = svc.rpc("moderate_contribution", {"p_id": r0["id"], "p_action": "hide", "p_note": "e2e cleanup"}).execute().data
    arch = svc.table("conferences").select("archived,source_id").eq("id", cid).execute().data[0]
    R.check(r4.get("status") == "hidden" and arch["archived"] is True and arch["source_id"] == 1000, f"hide archives the community row -> {arch}")
    pg.goto(f"{BASE}/conferences/{cid}"); R.check("not found" in pg.content().lower(), "hidden event no longer served")

    # B) realistic pending submission left for moderation/digest flows
    fill_form(pg, f"Test submission - North West Cancer Research Day {RUN_TS}", f"{URL}-pending", "2027-05-20",
              "Test submission for moderation practice: a one-day regional oncology meeting with trainee abstract prizes.", "95")
    left = svc.table("community_contributions").select("id").eq("user_id", sub["user_id"]).eq("kind", "new_event").eq("status", "pending").execute().data
    R.check(len(left) == 1, f"one pending new_event left (got {len(left)})")
    pg.goto(f"{BASE}/dashboard/contributions"); pg.wait_for_load_state("networkidle"); h = pg.content()
    R.check(pg.url.endswith("/dashboard/contributions") and "Pending" in h, f"/dashboard/contributions renders ({pg.url})")
    pg.goto(f"{BASE}/admin/moderation"); pg.wait_for_load_state("networkidle")
    R.check("/admin" not in pg.url, f"non-admin bounced from /admin/moderation to {pg.url}")
    b.close()
sys.exit(R.finish())
