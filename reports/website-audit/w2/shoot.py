import re
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3055"
OUT = "/Users/Sushil/Documents/Documents/IMT2/Side hustle/myTalk_conference app/reports/website-audit/w2"

VIEWPORTS = {
    "390": {"width": 390, "height": 844},
    "768": {"width": 768, "height": 1024},
    "1440": {"width": 1440, "height": 900},
}

def shoot(page, name, full_page=True):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=full_page)
    print("saved", name)

with sync_playwright() as p:
    browser = p.chromium.launch()

    for vp_name, vp in VIEWPORTS.items():
        for theme in ["light", "dark"]:
            ctx = browser.new_context(viewport=vp, color_scheme=theme)
            page = ctx.new_page()
            page.goto(f"{BASE}/conferences", wait_until="networkidle")
            page.wait_for_timeout(400)
            page.screenshot(path=f"{OUT}/conferences-default-{vp_name}-{theme}-viewport.png", full_page=False)
            shoot(page, f"conferences-default-{vp_name}-{theme}")
            ctx.close()

    ctx = browser.new_context(viewport=VIEWPORTS["1440"], color_scheme="light")
    page = ctx.new_page()
    page.goto(f"{BASE}/conferences?specialty=oncology&format=in_person&price=under-300", wait_until="networkidle")
    page.wait_for_timeout(400)
    shoot(page, "conferences-filtered-1440-light")
    ctx.close()

    ctx = browser.new_context(viewport=VIEWPORTS["1440"], color_scheme="light")
    page = ctx.new_page()
    page.goto(f"{BASE}/conferences?q=zzzznomatch9999", wait_until="networkidle")
    page.wait_for_timeout(400)
    shoot(page, "conferences-empty-1440-light")
    ctx.close()

    ctx = browser.new_context(viewport=VIEWPORTS["390"], color_scheme="light")
    page = ctx.new_page()
    page.goto(f"{BASE}/conferences", wait_until="networkidle")
    page.wait_for_timeout(400)
    try:
        page.get_by_role("button", name=re.compile("Filters")).first.click()
        page.wait_for_timeout(400)
    except Exception as e:
        print("sheet click failed", e)
    shoot(page, "conferences-mobile-sheet-390-light", full_page=False)
    ctx.close()

    ctx = browser.new_context(viewport=VIEWPORTS["1440"], color_scheme="light")
    page = ctx.new_page()
    page.goto(f"{BASE}/conferences", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.keyboard.press("Meta+k")
    page.wait_for_timeout(400)
    shoot(page, "conferences-cmdk-1440-light", full_page=False)
    ctx.close()

    for theme in ["light", "dark"]:
        ctx = browser.new_context(viewport=VIEWPORTS["1440"], color_scheme=theme)
        page = ctx.new_page()
        page.goto(f"{BASE}/societies", wait_until="networkidle")
        page.wait_for_timeout(400)
        shoot(page, f"societies-1440-{theme}")
        ctx.close()

    browser.close()
print("done")
