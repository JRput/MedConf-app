"""Wave access gate: can the SCRAPER read each candidate domain from wherever
this runs? Run it on a GitHub runner via .github/workflows/probe-cloud-access.yml
BEFORE spending a build agent (RCoA cleared from a home IP but not from runner
IPs; HQ LESSON #96: on 2026-11-09 a browser-only probe cleared ehaweb.org and
esgedays.org, but production's httpx-first fetch got 403 on the runner).

Each candidate URL is therefore fetched through the PRODUCTION path,
`extractors.http_fetch.fetch_html(url, browser=<BrowserController>)`, and a
domain is "cleared" only when one URL returns a real page that way. The old
browser-only navigation is still recorded next to it, for comparison.

  python probe_cloud_access.py <candidates.json> [out.json]

Needs the scraper's imports (httpx, supabase, playwright, python-dotenv, ...):
run `pip install -r requirements.txt` first. No API keys or Supabase access
are used; dummy values are set only so the module imports succeed.

Results JSON, per domain: {"domain", "cleared", "verdict", "cleared_url",
"browser_cleared", "results": [...]}. Per URL (old keys unchanged): url,
cleared (= browser-only navigation verdict), secs, title, len, reason, marker
or error; NEW per URL: production_fetch = {ok, length, challenge, blocked,
unreachable, elapsed_ms}. Top-level "cleared" is now the production verdict.
"""
import json
import os
import re
import sys
import time

os.environ.setdefault("SUPABASE_URL", "https://probe.invalid")
os.environ.setdefault("SUPABASE_KEY", "x")
os.environ.setdefault("KIMI_API_KEY", "x")

try:
    from browser import BrowserController, looks_like_challenge, has_content_shape
    from extractors import http_fetch
except ImportError as e:  # fail loudly: a probe that cannot use the production path must not run
    sys.exit(f"probe_cloud_access: missing dependency for the production fetch path ({e}). "
             "Run `pip install -r requirements.txt` (httpx, supabase, playwright, python-dotenv, ...) "
             "and `python -m playwright install chromium` first.")

_MARKER_RE = re.compile(r"(?i)(just a moment|attention required|verif\w+ (?:you are )?human|security verification|access denied|cf-chl|challenge-platform|turnstile|captcha)")


def production_probe(url, browser, fetch=None, reset=None, problems=None):
    """Fetch `url` the way the scraper does and describe the outcome.

    ok = a body came back, it carries no challenge marker and links to more
    than one place. blocked / unreachable come from http_fetch's problem
    registry (reset before the call)."""
    fetch = fetch or http_fetch.fetch_html
    reset = reset or http_fetch.reset_blocks
    problems = problems if problems is not None else http_fetch.last_fetch_problem
    reset()
    t = time.time()
    try:
        body = fetch(url, browser=browser)
    except Exception:  # fetch_html never raises; a fake or a bug must not kill the probe
        body = None
    elapsed = int((time.time() - t) * 1000)
    body = body or ""
    challenge = bool(body) and bool(looks_like_challenge(body, 200))
    ok = bool(body) and not challenge and bool(has_content_shape(body))
    return {"ok": ok, "length": len(body), "challenge": challenge,
            "blocked": bool(problems.get("blocked")) or challenge,
            "unreachable": bool(problems.get("unreachable")) and not problems.get("blocked"),
            "elapsed_ms": elapsed}


def browser_probe(url, browser):
    """The old probe: navigate with the shared BrowserController."""
    t = time.time()
    try:
        browser.navigate(url)
        html = browser.page.content()
        why = ("challenge" if looks_like_challenge(html, 200) else "no-content-shape" if not has_content_shape(html)
               else "too-short" if len(html) <= 5000 else "")
        m = _MARKER_RE.search(html)
        return {"url": url, "cleared": not why, "secs": round(time.time() - t, 1), "title": browser.page.title()[:60],
                "len": len(html), "reason": why, "marker": html[max(0, m.start() - 80): m.end() + 80] if m else ""}
    except Exception as e:
        return {"url": url, "cleared": False, "secs": round(time.time() - t, 1), "error": str(e)[:100]}


def domain_verdict(results):
    """(verdict, cleared_url) from per-URL records: the first URL whose
    production fetch is ok clears the domain; else any blocked/challenged URL
    makes it 'challenged'; else 'unreachable'."""
    for r in results:
        if r["production_fetch"]["ok"]:
            return "cleared", r["url"]
    if any(r["production_fetch"]["blocked"] or r["production_fetch"]["challenge"] for r in results):
        return "challenged", None
    return "unreachable", None


def probe_domain(cand, browser, prod=production_probe, brow=browser_probe):
    results = []
    for url in cand["candidate_urls"]:
        rec = brow(url, browser)
        rec["production_fetch"] = prod(url, browser)
        results.append(rec)
        if rec["production_fetch"]["ok"]:
            break
    verdict, url = domain_verdict(results)
    return {"domain": cand["domain"], "cleared": verdict == "cleared", "verdict": verdict, "cleared_url": url,
            "browser_cleared": any(r["cleared"] for r in results), "results": results}


def main(argv):
    cands = json.load(open(argv[1]))
    out_path = argv[2] if len(argv) > 2 else "probe_cloud_access_results.json"
    out = []
    b = BrowserController()
    b.launch()
    try:
        for c in cands:
            rec = probe_domain(c, b)
            last = rec["results"][-1]
            print(f"{rec['verdict'].upper():11} {c['domain']:36} {last['production_fetch']['elapsed_ms']}ms "
                  f"browser_only={'cleared' if rec['browser_cleared'] else 'no'} url={rec['cleared_url'] or '-'}", flush=True)
            out.append(rec)
    finally:
        b.close()
    print("SUMMARY (production fetch path):")
    for label in ("cleared", "challenged", "unreachable"):
        names = [f"{r['domain']} ({r['cleared_url']})" if label == "cleared" else r["domain"] for r in out if r["verdict"] == label]
        print(f"  {label}: {', '.join(names) if names else '-'}")
    print(f"SUMMARY: {sum(r['cleared'] for r in out)}/{len(out)} cleared")
    json.dump(out, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv)
