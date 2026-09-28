"""Wave 1d access gate (2026-09-28): can the PRODUCTION browser
(BrowserController.navigate, with its Cloudflare profile rotation) read each
candidate domain from wherever this runs? Run it on a GitHub runner via
.github/workflows/probe-cloud-access.yml BEFORE spending a build agent —
RCoA cleared from a home IP but not from runner IPs.

  python probe_cloud_access.py <candidates.json> [out.json]
Needs only Playwright (no API keys, no Supabase).
"""
import json, re, sys, time, os
os.environ.setdefault("SUPABASE_URL", "x"); os.environ.setdefault("SUPABASE_KEY", "x"); os.environ.setdefault("KIMI_API_KEY", "x")
from browser import BrowserController

CHAL = re.compile(r"<title>\s*(?:just a moment|attention required|checking your browser|403|access denied|forbidden)", re.I)
cands = json.load(open(sys.argv[1]))
out = []
b = BrowserController(); b.launch()
for c in cands:
    rec = {"domain": c["domain"], "results": []}
    for url in c["candidate_urls"][:2]:
        t = time.time()
        try:
            b.navigate(url)
            html = b.page.content()
            ok = not CHAL.search(html[:2000]) and len(html) > 5000
            rec["results"].append({"url": url, "cleared": ok, "secs": round(time.time() - t, 1), "title": b.page.title()[:60], "len": len(html)})
        except Exception as e:
            rec["results"].append({"url": url, "cleared": False, "secs": round(time.time() - t, 1), "error": str(e)[:100]})
        if rec["results"][-1]["cleared"]:
            break
    rec["cleared"] = any(r["cleared"] for r in rec["results"])
    print(f"{'CLEARED' if rec['cleared'] else 'BLOCKED'} {c['domain']:36} {rec['results'][-1].get('secs')}s {rec['results'][-1].get('title', rec['results'][-1].get('error'))!r}", flush=True)
    out.append(rec)
b.close()
n = sum(r["cleared"] for r in out)
print(f"SUMMARY: {n}/{len(out)} cleared")
json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else "probe_cloud_access_results.json", "w"), indent=1)
