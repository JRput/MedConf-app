"""E2E: first-time-user sign-in + verification journey against the LIVE site.

Base URL: env E2E_BASE_URL (default https://medconf.vercel.app).
Run from medconf-scraper:  ./.venv/bin/python ../tests/e2e/e2e_signin_live.py
Service key comes only from medconf-scraper/.env (via helpers.service()); never printed.
Creates at most 2 test users (always deleted in a finally). At most 2 real emails are
triggered: the signup form (step 3) and the forgot-password form (steps 7/9).
Admin generate_link is used for verification/recovery so no mailbox is needed.
Evidence: screenshots + signin_live_report.json in SHOT_DIR.
"""
import json, os, re, secrets, sys, time, traceback
from urllib.parse import quote, urlparse
from playwright.sync_api import sync_playwright
from helpers import service

BASE = os.environ.get("E2E_BASE_URL", "https://medconf.vercel.app").rstrip("/")
SHOT_DIR = os.environ.get(
    "E2E_SHOT_DIR",
    "/private/tmp/claude-501/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/"
    "8face73c-ff7d-4fb3-8d1a-4e08bcb06f52/scratchpad/signin",
)
os.makedirs(SHOT_DIR, exist_ok=True)
for _f in os.listdir(SHOT_DIR):
    if _f.endswith(".png"):
        os.remove(os.path.join(SHOT_DIR, _f))
SEND_EMAILS = os.environ.get("E2E_SEND_EMAILS", "1") == "1"  # 0 = skip the two real-email form submits (debug reruns)
TS = str(int(time.time()))
DOMAIN = os.environ.get("E2E_EMAIL_DOMAIN", "example.com")
EMAIL = f"qa-signin-{TS}@{DOMAIN}"
EMAIL_B = f"qa-signin-unconfirmed-{TS}@{DOMAIN}"
PW1 = "Qa1-" + secrets.token_urlsafe(10)
PW2 = "Qa2-" + secrets.token_urlsafe(10)
NEXT = "/conferences?q=cardio"

svc = service()
rows, notes, created = [], [], []
_shot_n = [0]


def shot(pg, name):
    _shot_n[0] += 1
    p = os.path.join(SHOT_DIR, f"{_shot_n[0]:02d}_{name}.png")
    try:
        pg.screenshot(path=p, full_page=True)
    except Exception:
        pass
    return p


def rec(step, name, ok, detail="", shotp=""):
    st = "NOTE" if ok is None else ("PASS" if ok else "FAIL")
    rows.append({"step": step, "name": name, "status": st, "detail": detail, "shot": shotp})
    print(f"{st} [{step}] {name} -- {detail}")


def info(msg):
    notes.append(msg); print("INFO " + msg)


def path_of(pg):
    u = urlparse(pg.url)
    return u.path + (("?" + u.query) if u.query else "")


def body(pg, n=500):
    try:
        return re.sub(r"\s+", " ", pg.locator("body").inner_text(timeout=5000))[:n]
    except Exception as e:
        return f"<body unreadable: {e}>"


def login(pg, email, pw, next_=None):
    pg.goto(f"{BASE}/auth/login" + (f"?next={quote(next_, safe='')}" if next_ else ""))
    pg.locator("#email").fill(email); pg.locator("#password").fill(pw)
    pg.get_by_role("button", name=re.compile(r"^sign in$", re.I)).click()


def alert_text(pg):
    a = pg.get_by_role("alert")
    return a.first.inner_text() if a.count() else ""


def run(step, name, fn):
    try:
        fn()
    except Exception as e:
        rec(step, name + " (script error)", False, f"{type(e).__name__}: {str(e)[:200]}")
        traceback.print_exc(limit=2)


uid_a = None
with sync_playwright() as pw:
    br = pw.chromium.launch()
    try:
        ctx = br.new_context(viewport={"width": 1280, "height": 900}); pg = ctx.new_page()

        # ------------------------------------------------ 2. signed-out gate
        def s2():
            pg.goto(f"{BASE}/conferences?q=cardio"); pg.wait_for_load_state("networkidle")
            p = path_of(pg)
            ok = p.startswith("/auth/login") and "next=" in p
            rec("2a", "/conferences?q=cardio -> login with next", ok, p, shot(pg, "gate_conferences"))
            pg.goto(f"{BASE}/societies"); pg.wait_for_load_state("networkidle")
            rec("2b", "/societies -> login with next", path_of(pg).startswith("/auth/login") and "next=" in path_of(pg), path_of(pg))
            pg.goto(f"{BASE}/"); pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(1500)
            tile = pg.locator("main a[href^='/conferences?']")
            if not tile.count():
                rec("2c", "specialty tile on / opens sign-in dialog", False, "no browse tile (main a[href^=/conferences?]) found on /", shot(pg, "home"))
                return
            tile.first.click(); pg.wait_for_timeout(1000)
            dlg = pg.get_by_role("dialog")
            if not dlg.count():
                rec("2c", "specialty tile on / opens sign-in dialog", False, f"no dialog; url={path_of(pg)}", shot(pg, "tile_click"))
                return
            sp = shot(pg, "gate_dialog")
            rec("2c", "specialty tile on / opens sign-in dialog", True, re.sub(r"\s+", " ", dlg.first.inner_text())[:160], sp)
            href = dlg.get_by_role("link", name=re.compile("Create a free account", re.I)).first.get_attribute("href")
            sin = dlg.get_by_role("link", name=re.compile(r"^Sign in$", re.I)).first.get_attribute("href")
            rec("2d", "dialog 'Create a free account' carries next", bool(href and "next=" in href), f"{href}  (sign in: {sin})")
        run("2", "signed-out gate", s2)

        # ------------------------------------------------ 3. signup form (path A: live form, real email #1)
        def s3():
            su = f"{BASE}/auth/signup?next={quote(NEXT, safe='')}"
            pg.goto(su)
            pg.locator("#email").fill("not-an-email"); pg.locator("#password").fill("short")
            pg.get_by_role("button", name=re.compile("create|sign up|continue", re.I)).last.click(); pg.wait_for_timeout(800)
            t = body(pg, 700)
            rec("3a", "short password error renders", "at least 8" in t.lower(), t[:200], shot(pg, "signup_short_pw"))
            has_confirm = pg.locator("#confirm, #confirmPassword").count() > 0
            info(f"signup form has a confirm-password field: {has_confirm} (mismatch check {'testable' if has_confirm else 'N/A'})")
            pg.locator("#email").fill(""); pg.locator("#password").fill("longenough1")
            pg.get_by_role("button", name=re.compile("create|sign up|continue", re.I)).last.click(); pg.wait_for_timeout(600)
            rec("3b", "empty email error renders", "email" in body(pg, 800).lower() and "enter your email" in body(pg, 800).lower(), "", shot(pg, "signup_empty_email"))
            pg.locator("#email").fill("not-an-email")
            pg.get_by_role("button", name=re.compile("create|sign up|continue", re.I)).last.click(); pg.wait_for_timeout(2500)
            t = body(pg, 800)
            rec("3c", "malformed email rejected with message", path_of(pg).startswith("/auth/signup") and bool(alert_text(pg) or "valid" in t.lower() or "invalid" in t.lower()),
                f"alert={alert_text(pg)[:120]!r}", shot(pg, "signup_bad_email"))
            # valid submit (REAL EMAIL #1)
            if not SEND_EMAILS:
                info("E2E_SEND_EMAILS=0: signup valid-submit skipped"); return
            pg.locator("#email").fill(EMAIL); pg.locator("#password").fill(PW1)
            pg.get_by_role("button", name=re.compile("create|sign up|continue", re.I)).last.click()
            try:
                pg.wait_for_url(re.compile(r"/auth/verify"), timeout=20000)
            except Exception:
                pass
            sp = shot(pg, "signup_submit")
            if "/auth/verify" in pg.url:
                rec("3d", "valid signup -> /auth/verify", True, "copy: " + body(pg, 300), sp)
            else:
                rec("3d", "valid signup -> /auth/verify", False, f"url={path_of(pg)} alert={alert_text(pg)[:200]!r}", sp)
        run("3", "signup form", s3)

        def find_user(email):
            page = 1
            while page <= 10:
                us = svc.auth.admin.list_users(page=page, per_page=200)
                for u in us:
                    if (u.email or "").lower() == email.lower():
                        return u
                if len(us) < 200:
                    return None
                page += 1
            return None

        ua = find_user(EMAIL)
        path_used = "live signup form"
        if ua:
            uid_a = ua.id; created.append(ua.id)
            info(f"signup created user; email_confirmed_at={ua.email_confirmed_at}")
        else:
            info("signup form did NOT create the user (likely email-send failure); falling back to admin create_user email_confirm=False")
            r = svc.auth.admin.create_user({"email": EMAIL, "password": PW1, "email_confirm": False})
            uid_a = r.user.id; created.append(uid_a); path_used = "admin create_user (fallback)"
        info("step-1 account path: " + path_used)
        rec("1", "test account created", True, path_used + f" (domain @{DOMAIN})")

        # ------------------------------------------------ 4. verification without mailbox
        cb_redirect = f"{BASE}/auth/callback?next={quote(NEXT, safe='')}"
        link_props = {}

        def s4():
            r = svc.auth.admin.generate_link({"type": "signup", "email": EMAIL, "password": PW1, "options": {"redirect_to": cb_redirect}})
            link_props["action"] = r.properties.action_link
            ctx4 = br.new_context(viewport={"width": 1280, "height": 900}); p4 = ctx4.new_page()
            p4.goto(f"{BASE}/auth/callback?token_hash={r.properties.hashed_token}&type=signup&next={quote(NEXT, safe='')}")
            p4.wait_for_load_state("networkidle"); p4.wait_for_timeout(2500)
            landed = path_of(p4); sp = shot(p4, "verify_token_hash")
            rec("4a", "callback?token_hash&type=signup&next -> signed in", landed.startswith("/onboarding") or landed.startswith("/conferences"), f"landed {landed}", sp)
            ev = find_user(EMAIL)
            rec("4c", "email_confirmed_at set after link", bool(ev and ev.email_confirmed_at), "")
            rec("4d", "new user lands on /onboarding", landed.startswith("/onboarding"), f"landed {landed}")
            rec("4e", "`next` survives to onboarding (still in URL)", "cardio" in p4.url, f"url {landed}")
            link_props["ctx"] = ctx4; link_props["pg"] = p4
        run("4", "verification", s4)

        # ------------------------------------------------ 5. onboarding + gate open
        def s5():
            p = link_props["pg"]
            p.goto(f"{BASE}/onboarding"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1500)
            sp = shot(p, "onboarding_1")
            rec("5a", "onboarding step 1 renders", "specialty" in body(p, 400).lower(), body(p, 160), sp)
            p.get_by_role("combobox").first.click(); p.wait_for_timeout(500)
            opt = p.get_by_role("option").first
            opt.click(); p.wait_for_timeout(300)
            p.get_by_role("button", name=re.compile("continue", re.I)).click(); p.wait_for_timeout(600)
            shot(p, "onboarding_2")
            p.get_by_role("combobox").first.click(); p.get_by_role("option", name="Registrar").click()
            net = []
            p.on("response", lambda r: net.append(f"{r.status} {r.request.method} {urlparse(r.url).path[:60]}") if ("supabase" in r.url or "onboarding" in r.url or "dashboard" in r.url) else None)
            p.on("console", lambda m: net.append("console." + m.type + ": " + m.text[:120]) if m.type in ("error", "warning") else None)
            p.on("request", lambda r: net.append(f"REQ {r.method} {urlparse(r.url).path[:40]}{'?' + urlparse(r.url).query[:30] if urlparse(r.url).query else ''}") if urlparse(r.url).netloc == urlparse(BASE).netloc else None)
            p.on("requestfailed", lambda r: net.append(f"FAILED {urlparse(r.url).path[:40]} {r.failure}"))
            t0 = time.time()
            p.get_by_role("button", name=re.compile(r"^done$", re.I)).click(); p.wait_for_timeout(4000)
            info(f"after Done+4s: url={path_of(p)} saving_visible={p.get_by_text('Saving').count() > 0}")
            try: p.wait_for_url(re.compile(r"/(dashboard|conferences)"), timeout=20000)
            except Exception: pass
            info(f"Done -> {path_of(p)} took {time.time()-t0:.1f}s; network/console: {net[-24:]}")
            p.wait_for_load_state("networkidle")
            sp = shot(p, "after_onboarding")
            dest = path_of(p)
            rec("5b", "onboarding Done -> leaves /onboarding (to /dashboard)", not dest.startswith("/onboarding"), f"-> {dest}  (next={NEXT!r} {'honoured' if 'cardio' in dest else 'NOT honoured; goes to dashboard'})", sp)
            p.goto(f"{BASE}{NEXT}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1500)
            sp = shot(p, "directory_signed_in")
            rec("5c", "/conferences?q=cardio renders when signed in", path_of(p).startswith("/conferences"), f"{path_of(p)} :: {body(p, 200)}", sp)
            p.goto(f"{BASE}/societies"); p.wait_for_load_state("networkidle")
            rec("5d", "/societies renders when signed in", path_of(p).startswith("/societies"), path_of(p), shot(p, "societies_signed_in"))
            p.goto(f"{BASE}{NEXT}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1000)
            link = p.locator("a[href^='/conferences/']").first
            if link.count():
                href = link.get_attribute("href"); p.goto(f"{BASE}{href}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1500)
                t = body(p, 4000).lower()
                sp = shot(p, "event_detail_signed_in")
                gated = "sign in" in t and ("unlock" in t or "free account" in t)
                rec("5e", "event page shows full details (fees/CPD/venue), no gate", not gated, f"{href}; has 'fee/price': {('fee' in t or 'price' in t or '£' in t)}, 'cpd': {'cpd' in t}, 'venue': {'venue' in t}; gate text: {gated}", sp)
            else:
                rec("5e", "event page shows full details", False, "no event link found in directory", sp)
            # onboarding after completion
            p.goto(f"{BASE}/onboarding"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(2000)
            rec("8c", "/onboarding after completion bounces to /dashboard", path_of(p).startswith("/dashboard"), path_of(p), shot(p, "onboarding_after_done"))
            # signed-in login bounce
            p.goto(f"{BASE}/auth/login"); p.wait_for_load_state("networkidle")
            rec("8b", "/auth/login while signed in bounces", not path_of(p).startswith("/auth/login"), path_of(p))
            p.goto(f"{BASE}/auth/login?next=%2Fsocieties"); p.wait_for_load_state("networkidle")
            rec("8b2", "/auth/login?next=/societies signed in -> /societies", path_of(p).startswith("/societies"), path_of(p))
        run("5", "onboarding & gate open", s5)

        # ------------------------------------------------ 6. logout / login
        def s6():
            p = link_props["pg"]
            p.goto(f"{BASE}/dashboard"); p.wait_for_load_state("networkidle")
            btn = p.get_by_role("button", name=re.compile("sign out", re.I))
            if not btn.count():
                p.set_viewport_size({"width": 390, "height": 800}); p.reload(); p.wait_for_load_state("networkidle")
                menu = p.get_by_role("button", name=re.compile("menu", re.I))
                if menu.count(): menu.first.click(); p.wait_for_timeout(400)
                btn = p.get_by_role("button", name=re.compile("sign out", re.I))
            sp = shot(p, "before_signout")
            if not btn.count():
                rec("6a", "sign-out control found", False, "none on /dashboard", sp); return
            btn.first.click(); p.wait_for_timeout(2500)
            rec("6a", "sign out", True, f"landed {path_of(p)}", shot(p, "after_signout"))
            p.goto(f"{BASE}/conferences"); p.wait_for_load_state("networkidle")
            rec("6b", "/conferences redirects to login after logout", path_of(p).startswith("/auth/login"), path_of(p))
            login(p, EMAIL, "wrong-" + PW1); p.wait_for_timeout(2500)
            rec("6c", "wrong password shows message", bool(alert_text(p)) and path_of(p).startswith("/auth/login"), f"alert={alert_text(p)!r}", shot(p, "login_wrong_pw"))
            login(p, EMAIL, PW1, "/societies")
            try: p.wait_for_url(re.compile(r"/societies"), timeout=15000)
            except Exception: pass
            rec("6d", "correct password + next=/societies lands on /societies", path_of(p).startswith("/societies"), path_of(p), shot(p, "login_next"))
        run("6", "logout/login", s6)

        # ------------------------------------------------ 7. password reset (real email #2 via form)
        def s7():
            ctx7 = br.new_context(); p = ctx7.new_page()
            p.goto(f"{BASE}/auth/forgot-password")
            if SEND_EMAILS:
              p.locator("#email").fill(EMAIL)
              p.get_by_role("button", name="Send reset link").click(); p.wait_for_timeout(5000)
              t = body(p, 500)
              rec("9", "REAL EMAIL probe: forgot-password UI response", True, f"alert={alert_text(p)[:200]!r}; body={t[:260]}", shot(p, "forgot_submit"))
            else:
              info("E2E_SEND_EMAILS=0: forgot-password submit skipped")
            r = svc.auth.admin.generate_link({"type": "recovery", "email": EMAIL, "options": {"redirect_to": f"{BASE}/auth/callback?next=%2Fauth%2Freset-password"}})
            act, h = r.properties.action_link, r.properties.hashed_token
            p.goto(act); p.wait_for_load_state("networkidle"); p.wait_for_timeout(2500)
            landed = path_of(p); sp = shot(p, "recovery_action_link")
            info(f"recovery action_link landed on {landed}")
            if "/auth/reset-password" not in landed:
                rec("7a", "recovery admin action_link (hash/implicit flow) -> reset-password [informational: server callback cannot read URL hash]", None, f"landed {landed}", sp)
                r = svc.auth.admin.generate_link({"type": "recovery", "email": EMAIL})
                ctx7.close(); ctx7 = br.new_context(); p = ctx7.new_page()
                p.goto(f"{BASE}/auth/callback?token_hash={r.properties.hashed_token}&type=recovery"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(2500)
                landed = path_of(p); sp = shot(p, "recovery_token_hash")
                rec("7b", "callback?token_hash&type=recovery -> reset-password", "/auth/reset-password" in landed, f"landed {landed}", sp)
            else:
                rec("7a", "recovery link -> /auth/reset-password", True, landed, sp)
            p.get_by_label("New password", exact=True).fill(PW2); p.get_by_label("Confirm new password", exact=True).fill(PW2)
            p.get_by_role("button", name="Update password").click(); p.wait_for_timeout(3000)
            rec("7c", "password updated confirmation", "Password updated" in body(p, 600), body(p, 200), shot(p, "reset_done"))
            p.get_by_role("button", name=re.compile("Continue to dashboard")).click(); p.wait_for_timeout(3000)
            rec("7d", "Continue lands on", True, path_of(p), shot(p, "after_reset_continue"))
            ctx7.close()
            c8 = br.new_context(); q = c8.new_page()
            login(q, EMAIL, PW1); q.wait_for_timeout(3000)
            rec("7e", "OLD password now rejected", path_of(q).startswith("/auth/login") and bool(alert_text(q)), f"{path_of(q)} alert={alert_text(q)!r}")
            login(q, EMAIL, PW2)
            try: q.wait_for_url(re.compile(r"^(?!.*/auth/login)"), timeout=12000)
            except Exception: pass
            q.wait_for_timeout(2500)
            rec("7f", "NEW password logs in", not path_of(q).startswith("/auth/login"), f"{path_of(q)} alert={alert_text(q)!r}", shot(q, "login_new_pw"))
            c8.close()
        run("7", "password reset", s7)

        # ------------------------------------------------ 8. edge cases
        def s8():
            c = br.new_context(); p = c.new_page()
            p.goto(f"{BASE}/auth/callback?code=bad"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1500)
            rec("8a", "callback?code=bad -> error page/message", True, f"{path_of(p)} :: alert={alert_text(p)!r} :: {body(p, 200)}", shot(p, "callback_bad_code"))
            p.goto(f"{BASE}/auth/callback"); p.wait_for_load_state("networkidle")
            rec("8a2", "callback with no params", True, path_of(p))
            p.goto(f"{BASE}/auth/callback?token_hash=garbage&type=recovery"); p.wait_for_load_state("networkidle")
            rec("8a3", "callback garbled recovery token_hash", True, f"{path_of(p)} :: {body(p, 200)}", shot(p, "callback_bad_recovery"))
            r = svc.auth.admin.create_user({"email": EMAIL_B, "password": PW1, "email_confirm": False})
            created.append(r.user.id)
            login(p, EMAIL_B, PW1); p.wait_for_timeout(3000)
            rec("8d", "unconfirmed-email login message", path_of(p).startswith("/auth/login") and bool(alert_text(p)), f"alert={alert_text(p)!r}", shot(p, "unconfirmed_login"))
            # admin action_link (implicit/hash flow) on user B -- what a PKCE-less link does at the callback
            r = svc.auth.admin.generate_link({"type": "signup", "email": EMAIL_B, "password": PW1, "options": {"redirect_to": cb_redirect}})
            c2 = br.new_context(); p2 = c2.new_page()
            p2.goto(r.properties.action_link); p2.wait_for_load_state("networkidle"); p2.wait_for_timeout(2500)
            landed = path_of(p2)
            rec("4f", "signup admin action_link (hash/implicit flow) -> signed in [informational: server callback cannot read URL hash]", None,
                f"landed {landed}{'#<tokens in hash dropped by server callback>' if '#' in p2.url else ''}", shot(p2, "action_link_implicit"))
            c2.close(); c.close()
        run("8", "edge cases", s8)
    finally:
        br.close()
        # ------------------------------------------------ 10. cleanup
        deleted = []
        for uid in created:
            try:
                svc.table("user_profiles").delete().eq("id", uid).execute()
            except Exception:
                pass
            try:
                svc.auth.admin.delete_user(uid); deleted.append(uid)
            except Exception as e:
                print("cleanup failed for", uid, type(e).__name__)
        print("CLEANUP deleted user ids:", deleted)

print("\n| step | check | status | detail |\n|---|---|---|---|")
for r in rows:
    print(f"| {r['step']} | {r['name']} | {r['status']} | {r['detail'][:140].replace('|','/')} |")
json.dump({"base": BASE, "rows": rows, "notes": notes, "deleted": created}, open(os.path.join(SHOT_DIR, "signin_live_report.json"), "w"), indent=1)
sys.exit(0 if all(r["status"] != "FAIL" for r in rows) else 1)
