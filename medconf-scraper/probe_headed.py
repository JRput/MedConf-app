"""Spike (2026-09-26): can a HEADED Chromium clear Cloudflare's managed
challenge where headless cannot? ~18 masterlist domains (RCoA, FICM, ASTRO,
ARVO, AHA, ABN, ...) reject headless Chromium with a 403 "Just a moment"
page but serve a headed browser. Runs both modes against a fixed URL set
and prints a table. No project imports on purpose — this must not depend
on browser.py so the result reflects Playwright alone.

  python probe_headed.py            # both modes
  python probe_headed.py --headless # one mode only
Under CI use `xvfb-run -a python probe_headed.py` for the headed mode.
"""
import re, sys, time, json
from playwright.sync_api import sync_playwright

URLS = [
    "https://www.rcoa.ac.uk/events",
    "https://www.ficm.ac.uk/events",
    "https://www.astro.org/meetings-and-education/",
    "https://www.arvo.org/annual-meeting/",
    "https://professional.heart.org/en/meetings",
    "https://theabn.org/events",
    "https://www.himss.org/events",
    "https://www.rcpsych.ac.uk/events/conferences",   # control: known-good
]
# Only the interstitial itself — real pages embed Turnstile scripts (cf-chl) too.
CHAL = re.compile(r"<title>\s*(?:just a moment|attention required)", re.I)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def probe(headless: bool, wait_s: int = 25, ua: bool = True):
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(**({"user_agent": UA} if ua else {}), viewport={"width": 1366, "height": 850}, locale="en-GB")
        page = ctx.new_page()
        for url in URLS:
            t0 = time.time(); status = None; cleared = False; first = None
            try:
                resp = page.goto(url, wait_until="load", timeout=30000)
                status = resp.status if resp else None
                first = bool(CHAL.search(page.content()))
                while time.time() - t0 < wait_s:
                    if not CHAL.search(page.content()):
                        cleared = True; break
                    page.wait_for_timeout(1000)
                title = page.title()[:40]
            except Exception as e:
                title = f"ERR {str(e)[:40]}"
            out.append({"url": url, "headless": headless, "custom_ua": ua, "status": status, "challenge_first": first,
                        "cleared": cleared, "secs": round(time.time() - t0, 1), "title": title})
            print(f"{'headless' if headless else 'HEADED  '} {'chromeUA ' if ua else 'defaultUA'} {status} first_challenge={first!s:5} cleared={cleared!s:5} {out[-1]['secs']:5}s {title!r:42} {url}", flush=True)
        browser.close()
    return out


if __name__ == "__main__":
    if "--headless" in sys.argv: combos = [(True, False), (True, True)]
    elif "--headed" in sys.argv: combos = [(False, True)]
    else: combos = [(True, False), (True, True), (False, True)]
    results = [r for h, u in combos for r in probe(h, ua=u)]
    for h, u in combos:
        n = sum(1 for r in results if r["headless"] == h and r["custom_ua"] == u and r["cleared"])
        print(f"SUMMARY {'headless' if h else 'headed'} {'chromeUA' if u else 'defaultUA'}: cleared {n}/{len(URLS)}")
    json.dump(results, open("probe_headed_results.json", "w"), indent=1)
