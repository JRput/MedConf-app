"""E2E: password reset flow, callback cookie fix, open-redirect guard, signup verification.

Needs the dev server, the submitter test account, service key and anon key (see README).
Side effects: temporarily changes the submitter's password (always restored in a finally),
creates one throwaway signup user (always deleted). Never prints tokens or passwords.
Run from medconf-scraper:  ./.venv/bin/python ../tests/e2e/e2e_password_reset.py
"""
import os, re, secrets, subprocess, sys, time
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from helpers import BASE, ROOT, SHOTS, Results, anon, creds, service

R = Results("password_reset")
WEB = os.path.join(ROOT, "medconf-website")
os.makedirs(SHOTS, exist_ok=True)
TS = str(int(time.time()))
info_lines, owner_actions = [], []


def info(msg):
    print("INFO " + msg); info_lines.append(msg)


def owner_action(msg):
    print("OWNER-ACTION " + msg); owner_actions.append(msg)


# ---------------------------------------------------------------- 1. static gates
def gate(cmd, label, allow_lint=False):
    p = subprocess.run(cmd.split(), cwd=WEB, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip().splitlines()
    print(f"--- {label} (last lines)"); print("\n".join(out[-4:]))
    return p.returncode, "\n".join(out)


rc, _ = gate("npx tsc --noEmit", "tsc")
R.check(rc == 0, "tsc --noEmit clean")
rc, out = gate("npm run lint", "lint")
errs = re.findall(r"^\s*\d+:\d+\s+error\s", out, re.M)
files_with_err = [l for l in out.splitlines() if "ReminderPanel.tsx" in l]
other = len(errs) - 1
R.check(len(errs) <= 1 and (not errs or files_with_err), f"lint: only the known ReminderPanel error ({len(errs)} error(s) total)")
rc, out = gate("npx vitest run", "vitest")
m = re.search(r"Tests\s+(\d+) passed", out)
R.check(rc == 0 and m and int(m.group(1)) >= 262, f"vitest passes ({m.group(1) if m else '?'} tests)")

# ---------------------------------------------------------------- helpers
svc, sub = service(), creds("submitter")
EMAIL, UID, OLDPW = sub["email"], sub["user_id"], sub["password"]


def recovery_hash():
    r = svc.auth.admin.generate_link({"type": "recovery", "email": EMAIL})
    return r.properties.hashed_token


def cb(token, typ="recovery", next_=None):
    u = f"{BASE}/auth/callback?token_hash={token}&type={typ}"
    if next_ is not None:
        u += f"&next={next_}"
    return u


def fresh(browser, vw=None):
    kw = {"viewport": {"width": vw[0], "height": vw[1]}} if vw else {}
    return browser.new_context(**kw)


def shot(pg, name):
    pg.screenshot(path=os.path.join(SHOTS, f"pwreset_{name}.png"), full_page=True)


def reset_to_form(pg, token_next="/auth/reset-password"):
    pg.goto(cb(recovery_hash(), "recovery", token_next))
    pg.wait_for_url(re.compile(r"/auth/(reset-password|forgot-password)"), timeout=20000)
    pg.get_by_label("New password", exact=True).or_(pg.get_by_role("heading", name="This link has expired")).wait_for(timeout=15000)


def new_pw(pg, a, b):
    pg.get_by_label("New password", exact=True).fill(a)
    pg.get_by_label("Confirm new password", exact=True).fill(b)
    pg.get_by_role("button", name="Update password").click()


NEWPW = "E2e-" + secrets.token_urlsafe(12)

with sync_playwright() as pw:
    br = pw.chromium.launch()
    try:
        # ------------------------------------------------------------ 2. pages signed out
        ctx = fresh(br); pg = ctx.new_page()
        resp = pg.goto(f"{BASE}/auth/forgot-password")
        R.check(resp.status == 200, "GET /auth/forgot-password -> 200")
        R.check(pg.get_by_label("Email address").count() == 1 and pg.get_by_role("button", name="Send reset link").count() == 1,
                "forgot-password has email field and Send reset link button")
        pg.goto(f"{BASE}/auth/reset-password")
        ok = pg.get_by_role("heading", name="This link has expired").count() or pg.get_by_role("heading", name="This link has expired").wait_for(timeout=10000) is None
        link = pg.get_by_role("link", name=re.compile("Request a new link"))
        R.check(ok and link.count() == 1 and link.get_attribute("href") == "/auth/forgot-password",
                "reset-password signed out shows expired state linking to /auth/forgot-password")
        pg.goto(f"{BASE}/auth/login")
        fl = pg.get_by_role("link", name="Forgot password?")
        R.check(fl.count() == 1 and fl.get_attribute("href") == "/auth/forgot-password", "login shows Forgot password? -> /auth/forgot-password")
        ctx.close()

        # ------------------------------------------------------------ 3. forgot form
        ctx = fresh(br); pg = ctx.new_page()
        pg.goto(f"{BASE}/auth/forgot-password")
        pg.get_by_label("Email address").fill(EMAIL)
        pg.get_by_role("button", name="Send reset link").click()
        pg.wait_for_timeout(4000)
        if pg.get_by_role("alert").count() and re.search("Too many", pg.get_by_role("alert").first.inner_text()):
            info("existing-account submit hit the email rate limit (alert shown); sent-state check skipped for the real account")
        else:
            R.check(pg.get_by_role("heading", name="Check your email").count() == 1 and EMAIL in pg.locator("body").inner_text(),
                    "existing-account submit -> 'Check your email' mentioning the email")
        ghost = f"nobody+{TS}@example.com"
        pg.goto(f"{BASE}/auth/forgot-password")
        pg.get_by_label("Email address").fill(ghost)
        pg.get_by_role("button", name="Send reset link").click()
        pg.wait_for_timeout(4000)
        if pg.get_by_role("alert").count() and re.search("Too many", pg.get_by_role("alert").first.inner_text()):
            info("unknown-account submit hit the email rate limit; enumeration check inconclusive")
        else:
            R.check(pg.get_by_role("heading", name="Check your email").count() == 1 and ghost in pg.locator("body").inner_text(),
                    "unknown-account submit -> identical sent state (no enumeration)")
        pg.goto(f"{BASE}/auth/forgot-password?error=expired")
        pg.get_by_role("alert").first.wait_for(timeout=10000)
        R.check("expired" in pg.get_by_role("alert").first.inner_text().lower(), "?error=expired shows expired-link error above form")
        ctx.close()

        # ------------------------------------------------------------ 4/5. recovery + replay (password restored in finally)
        used_token = None
        try:
            used_token = recovery_hash()
            ctx = fresh(br); pg = ctx.new_page()
            pg.goto(cb(used_token, "recovery", "/auth/reset-password"))
            pg.wait_for_url(re.compile(r"/auth/reset-password"), timeout=20000)
            pg.get_by_label("New password", exact=True).wait_for(timeout=15000)
            R.check(True, "token_hash callback lands on /auth/reset-password with the form (session cookie written)")
            R.check(EMAIL in pg.locator("body").inner_text(), "reset form shows the signed-in email")
            new_pw(pg, "Abcdefgh1", "Different1")
            pg.wait_for_timeout(500)
            R.check("Passwords do not match" in pg.locator("body").inner_text(), "mismatched passwords -> 'Passwords do not match'")
            new_pw(pg, "abc12", "abc12")
            pg.wait_for_timeout(500)
            R.check("at least 8" in pg.locator("body").inner_text().lower(), "5-char password -> min-length error")
            new_pw(pg, OLDPW, OLDPW)
            pg.wait_for_timeout(3000)
            al = pg.get_by_role("alert")
            txt = al.first.inner_text().lower() if al.count() else ""
            if "different" in txt or "same" in txt:
                R.check(True, "same-as-current password rejected with Supabase message")
            elif pg.get_by_role("heading", name="Password updated").count():
                info("Supabase did not enforce 'different from old password' on this project (update accepted)")
            else:
                R.check(False, f"same-password attempt gave unexpected state: alert={txt[:80]!r}")
            if pg.get_by_role("heading", name="Choose a new password").count():
                new_pw(pg, NEWPW, NEWPW)
            pg.get_by_role("heading", name="Password updated").wait_for(timeout=15000)
            R.check(pg.get_by_role("button", name="Continue to dashboard").count() == 1, "valid new password -> 'Password updated' + Continue to dashboard")
            pg.get_by_role("button", name="Continue to dashboard").click()
            pg.wait_for_url(re.compile(r"/(dashboard|onboarding)"), timeout=20000)
            R.check(True, f"Continue lands on {urlparse(pg.url).path}")
            ctx.close()

            c2 = anon()
            try:
                c2.auth.sign_in_with_password({"email": EMAIL, "password": NEWPW}); R.check(True, "sign-in with NEW password works")
            except Exception as e:
                R.check(False, f"sign-in with NEW password failed: {type(e).__name__}")
            try:
                anon().auth.sign_in_with_password({"email": EMAIL, "password": OLDPW}); R.check(False, "OLD password still works")
            except Exception:
                R.check(True, "OLD password rejected")

            # 5. replay
            ctx = fresh(br); pg = ctx.new_page()
            pg.goto(cb(used_token, "recovery", "/auth/reset-password"))
            pg.wait_for_url(re.compile(r"/auth/(forgot-password|reset-password)"), timeout=20000)
            pg.wait_for_timeout(1500)
            u = urlparse(pg.url)
            R.check(u.path == "/auth/forgot-password" and parse_qs(u.query).get("error") == ["expired"], "replayed token -> /auth/forgot-password?error=expired")
            ctx.close()
        finally:
            try:
                svc.auth.admin.update_user_by_id(UID, {"password": OLDPW})
                anon().auth.sign_in_with_password({"email": EMAIL, "password": OLDPW})
                print("INFO submitter password restored and verified")
            except Exception as e:
                R.check(False, f"FAILED to restore submitter password: {type(e).__name__}")

        # ------------------------------------------------------------ 6. open redirect
        for label, nxt in [("absolute URL", "https://example.com/evil"), ("protocol-relative", "//example.com"), ("scheme-in-path", "/javascript:alert(1)")]:
            ctx = fresh(br); pg = ctx.new_page()
            pg.goto(cb(recovery_hash(), "recovery", nxt))
            pg.wait_for_url(re.compile(r"/auth/"), timeout=20000)
            pg.wait_for_timeout(1000)
            u = urlparse(pg.url)
            R.check(u.netloc == urlparse(BASE).netloc and u.path == "/auth/reset-password", f"open redirect next={label} -> fallback /auth/reset-password on own host")
            ctx.close()

        # ------------------------------------------------------------ 7. signup verification
        sup_email, sup_id = f"e2e.signup.{TS}@example.com", None
        try:
            r = svc.auth.admin.generate_link({"type": "signup", "email": sup_email, "password": secrets.token_urlsafe(12)})
            sup_id = r.user.id
            ctx = fresh(br); pg = ctx.new_page()
            pg.goto(cb(r.properties.hashed_token, "signup"))
            pg.wait_for_url(re.compile(r"/(onboarding|auth/login|dashboard)"), timeout=20000)
            pg.wait_for_timeout(1500)
            R.check(urlparse(pg.url).path.startswith("/onboarding"), f"signup token_hash verifies and lands signed-in on /onboarding (got {urlparse(pg.url).path})")
            ctx.close()
        finally:
            if sup_id:
                try:
                    svc.auth.admin.delete_user(sup_id); print("INFO throwaway signup user deleted")
                except Exception as e:
                    R.check(False, f"failed to delete throwaway user: {type(e).__name__}")

        # ------------------------------------------------------------ 8. allowlist probe
        want = f"{BASE}/auth/callback?next=/auth/reset-password"
        r = svc.auth.admin.generate_link({"type": "recovery", "email": EMAIL, "options": {"redirect_to": want}})
        got = r.properties.redirect_to or parse_qs(urlparse(r.properties.action_link).query).get("redirect_to", [""])[0]
        if got == want:
            R.check(True, "allowlist accepts the callback URL with ?next")
        else:
            g = urlparse(got)
            owner_action(f"redirect allowlist rewrote requested callback to host={g.netloc!r} path={g.path!r}: add http://localhost:3000/** in Authentication -> URL Configuration")

        # ------------------------------------------------------------ 9. screenshots
        def shots(vw, tag, dark=False):
            def prep(ctx):
                pg = ctx.new_page(); return pg
            ctx = fresh(br, vw)
            if dark:
                ctx.close(); ctx = br.new_context(viewport={"width": vw[0], "height": vw[1]}, color_scheme="dark")
            pg = ctx.new_page()

            def dk():
                if dark:
                    pg.evaluate("document.documentElement.setAttribute('data-theme','dark')"); pg.wait_for_timeout(200)
            if not dark:
                pg.goto(f"{BASE}/auth/login"); pg.wait_for_timeout(800); shot(pg, f"login_{tag}")
            pg.goto(f"{BASE}/auth/forgot-password"); pg.wait_for_timeout(800); dk(); shot(pg, f"forgot_form_{tag}")
            if not dark:
                pg.get_by_label("Email address").fill(f"nobody+{TS}@example.com")
                pg.get_by_role("button", name="Send reset link").click(); pg.wait_for_timeout(3500); shot(pg, f"forgot_sent_{tag}")
                pg.goto(f"{BASE}/auth/reset-password"); pg.wait_for_timeout(1500); shot(pg, f"reset_expired_{tag}")
            reset_to_form(pg); dk(); shot(pg, f"reset_form_{tag}")
            if not dark:
                pw2 = NEWPW + tag
                new_pw(pg, pw2, pw2)
                pg.get_by_role("heading", name="Password updated").wait_for(timeout=15000); shot(pg, f"reset_success_{tag}")
            ctx.close()

        try:
            shots((375, 800), "375")
            shots((1024, 768), "1024")
            shots((1024, 768), "1024_dark", dark=True)
            print("INFO screenshots written to tests/e2e/screenshots/pwreset_*.png")
        except Exception as e:
            R.check(False, f"screenshot pass failed: {type(e).__name__}: {str(e)[:120]}")
        finally:
            try:
                svc.auth.admin.update_user_by_id(UID, {"password": OLDPW})
                anon().auth.sign_in_with_password({"email": EMAIL, "password": OLDPW})
                print("INFO submitter password restored after screenshots")
            except Exception as e:
                R.check(False, f"FAILED to restore submitter password after screenshots: {type(e).__name__}")
    finally:
        br.close()

print(f"SUMMARY info={len(info_lines)} owner_actions={len(owner_actions)}")
sys.exit(R.finish())
