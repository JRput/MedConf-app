"""Shared helpers for the community-contributions E2E suite.

Needs: dev server on E2E_BASE (default http://localhost:3000), the two throwaway test accounts
(test_submitter.json / test_moderator.json in E2E_CREDS_DIR), service key in medconf-scraper/.env,
anon key in medconf-website/.env.local. Never prints secrets.
"""
import json, os, re, sys, time
from dotenv import load_dotenv
from supabase import create_client

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
load_dotenv(os.path.join(ROOT, "medconf-scraper", ".env"))
load_dotenv(os.path.join(ROOT, "medconf-website", ".env.local"))

DEFAULT_CREDS = "/private/tmp/claude-501/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/8face73c-ff7d-4fb3-8d1a-4e08bcb06f52/scratchpad"
CREDS_DIR = os.environ.get("E2E_CREDS_DIR", DEFAULT_CREDS)
BASE = os.environ.get("E2E_BASE", "http://localhost:3000")
SHOTS = os.path.join(HERE, "screenshots")
RUN_TS = time.strftime("%Y%m%d%H%M%S")


def creds(who):
    return json.load(open(os.path.join(CREDS_DIR, f"test_{who}.json")))


def service():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def anon():
    return create_client(os.environ["NEXT_PUBLIC_SUPABASE_URL"], os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"])


def user_client(who):
    c = anon(); c.auth.sign_in_with_password({"email": creds(who)["email"], "password": creds(who)["password"]}); return c


class Results:
    def __init__(self, name):
        self.name, self.ok, self.rows = name, True, []

    def check(self, cond, msg):
        print(("PASS " if cond else "FAIL ") + msg); self.rows.append((bool(cond), msg)); self.ok = self.ok and bool(cond)
        return bool(cond)

    def finish(self):
        print(f"RESULT[{self.name}]:", "ALL PASS" if self.ok else "FAILURES"); return 0 if self.ok else 1


def login(pg, who):
    c = creds(who)
    pg.context.clear_cookies(); pg.goto(f"{BASE}/auth/login")
    pg.get_by_label("Email address").fill(c["email"]); pg.get_by_label("Password").fill(c["password"])
    pg.get_by_role("button", name=re.compile("sign in", re.I)).click()
    pg.wait_for_url(re.compile(r"/(dashboard|onboarding|conferences)"), timeout=20000)


def expand(pg, name_re):
    """Click a collapsed section header (button) on the page if present and not yet expanded."""
    h = pg.get_by_role("button", name=re.compile(name_re))
    if h.count() and h.first.get_attribute("aria-expanded") != "true":
        h.first.click(); pg.wait_for_timeout(300)


def clean_user(svc, who):
    """Idempotency: remove the test user's contributions (facts/tiers cascade) and leftover e2e community events."""
    uid = creds(who)["user_id"]
    svc.table("community_contributions").delete().eq("user_id", uid).execute()
    svc.table("conferences").delete().eq("source_id", 1000).like("source_url", "https://example.org/e2e%").execute()
    svc.table("notifications").delete().eq("user_id", uid).eq("type", "contribution_update").execute()


def rpc_err(fn):
    """Return error text if the call raises, else None."""
    try:
        fn(); return None
    except Exception as e:
        return str(e)
