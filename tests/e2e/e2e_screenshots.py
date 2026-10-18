"""Responsive screenshots at 375x800 and 768x1024 + automatic breakage heuristics (horizontal scroll, clipped elements)."""
import os, re, sys
from playwright.sync_api import sync_playwright
from helpers import *

os.makedirs(SHOTS, exist_ok=True); svc = service(); R = Results("screenshots")
pend = svc.table("community_contributions").select("id").in_("status", ["pending", "needs_info"]).limit(1).execute().data
item_id = pend[0]["id"] if pend else None
VIEWS = {"375": {"width": 375, "height": 800}, "768": {"width": 768, "height": 1024}, "1024": {"width": 1024, "height": 768}, "1280": {"width": 1280, "height": 800}}
JS = """() => { const de = document.documentElement; const out = {hscroll: de.scrollWidth - de.clientWidth, wide: []};
  for (const el of document.querySelectorAll('body *')) { const r = el.getBoundingClientRect(); if (r.width && r.right > de.clientWidth + 1 && getComputedStyle(el).position !== 'fixed') {
    let p = el.parentElement, clipped = false; while (p) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { clipped = true; break; } p = p.parentElement; }
    if (!clipped) out.wide.push((el.tagName + '.' + (el.className||'').toString().slice(0,40)) + ' right=' + Math.round(r.right)); } }
  out.wide = out.wide.slice(0, 5); return out; }"""

def shot(pg, name, size):
    pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(600)
    path = os.path.join(SHOTS, f"{name}-{size}.png"); pg.screenshot(path=path, full_page=True)
    m = pg.evaluate(JS); R.check(m["hscroll"] <= 1 and not m["wide"], f"{name}-{size}: hscroll={m['hscroll']} overflowing={m['wide']}")

with sync_playwright() as p:
    b = p.chromium.launch()
    for size, vp in VIEWS.items():
        ctx = b.new_context(viewport=vp); pg = ctx.new_page(); login(pg, "submitter")
        pg.goto(f"{BASE}/submit"); shot(pg, "submit", size)
        pg.goto(f"{BASE}/dashboard/contributions"); shot(pg, "contributions", size)
        pg.goto(f"{BASE}/conferences/819"); pg.wait_for_load_state("networkidle")
        pg.get_by_role("button", name="Add missing info").first.click(); pg.get_by_role("dialog").wait_for(timeout=8000)
        d = pg.get_by_role("dialog"); box = d.bounding_box()
        R.check(box and box["x"] >= -1 and box["x"] + box["width"] <= vp["width"] + 1, f"add-info dialog fits viewport {size}: {box}")
        shot(pg, "addinfo-dialog", size); ctx.close()
        ctx = b.new_context(viewport=vp); pg = ctx.new_page(); login(pg, "moderator")
        pg.goto(f"{BASE}/admin/moderation"); shot(pg, "moderation-queue", size)
        if item_id: pg.goto(f"{BASE}/admin/moderation/{item_id}"); shot(pg, "moderation-item", size)
        ctx.close()
    b.close()
sys.exit(R.finish())
