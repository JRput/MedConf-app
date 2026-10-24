#!/usr/bin/env python3
"""Push MedConf auth email templates and custom SMTP settings to Supabase.

Usage:
  python3 scripts/supabase_auth_setup.py templates [--dry-run]
  python3 scripts/supabase_auth_setup.py smtp      [--dry-run]
  python3 scripts/supabase_auth_setup.py show      [--dry-run]

Environment (never put these in a file):
  SUPABASE_ACCESS_TOKEN  personal access token (sbp_...), Account -> Access Tokens
  SUPABASE_PROJECT_REF   default zcpszfbmvfylicpxgsfc
  SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS SMTP_SENDER_EMAIL   (smtp subcommand)
  SMTP_SENDER_NAME       default "MedConf"
  SMTP_RATE_LIMIT_EMAILS_PER_HOUR   optional integer -> rate_limit_email_sent

Endpoint: GET/PATCH https://api.supabase.com/v1/projects/{ref}/config/auth
Field names CONFIRMED on 2026-10-24 against the official OpenAPI spec
(https://api.supabase.com/api/v1-json, operations v1-get-auth-service-config and
v1-update-auth-service-config, schema UpdateAuthConfigBody):
  mailer_subjects_{confirmation,recovery,magic_link,email_change,invite,reauthentication}
  mailer_templates_{confirmation,recovery,magic_link,email_change,invite,reauthentication}_content
  smtp_host, smtp_port (STRING in the schema), smtp_user, smtp_pass,
  smtp_sender_name, smtp_admin_email, rate_limit_email_sent (integer),
  plus read fields site_url, uri_allow_list, mailer_otp_exp.
Nothing is unconfirmed. If a field ever disappears from a GET, `show` prints a warning.

Standard library only. The token and SMTP password are never printed.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "supabase", "templates")
DEFAULT_REF = "zcpszfbmvfylicpxgsfc"
API = "https://api.supabase.com/v1/projects/{ref}/config/auth"

# (api key suffix, template file, subject) - subjects match EMAIL_TEMPLATES.md section 1.
TEMPLATES = [
    ("confirmation", "confirm_signup.html", "Confirm your MedConf account"),
    ("recovery", "recovery.html", "Reset your MedConf password"),
    ("magic_link", "magic_link.html", "Your MedConf sign-in link"),
    ("email_change", "email_change.html", "Confirm your new email for MedConf"),
    ("invite", "invite.html", "You're invited to MedConf"),
    ("reauthentication", "reauthentication.html", "Your MedConf verification code"),
]

SECRET_FIELDS = {"smtp_pass"}


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def need(name):
    v = os.environ.get(name, "").strip()
    if not v:
        die("environment variable %s is required" % name)
    return v


def token():
    return need("SUPABASE_ACCESS_TOKEN")


def ref():
    return os.environ.get("SUPABASE_PROJECT_REF", "").strip() or DEFAULT_REF


def call(method, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API.format(ref=ref()), data=data, method=method,
        headers={
            "Authorization": "Bearer " + token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "medconf-auth-setup/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        # Never echo request data; the response body does not contain our secrets.
        die("Supabase API returned HTTP %s: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        die("could not reach Supabase API: %s" % e.reason)


def build_templates():
    body = {}
    for key, fname, subject in TEMPLATES:
        path = os.path.join(TEMPLATE_DIR, fname)
        if not os.path.isfile(path):
            die("template file missing: " + path)
        with open(path, encoding="utf-8") as f:
            body["mailer_templates_%s_content" % key] = f.read()
        body["mailer_subjects_%s" % key] = subject
    return body


def build_smtp():
    body = {
        "smtp_host": need("SMTP_HOST"),
        "smtp_port": need("SMTP_PORT"),
        "smtp_user": need("SMTP_USER"),
        "smtp_pass": need("SMTP_PASS"),
        "smtp_admin_email": need("SMTP_SENDER_EMAIL"),
        "smtp_sender_name": os.environ.get("SMTP_SENDER_NAME", "").strip() or "MedConf",
    }
    rl = os.environ.get("SMTP_RATE_LIMIT_EMAILS_PER_HOUR", "").strip()
    if rl:
        if not rl.isdigit():
            die("SMTP_RATE_LIMIT_EMAILS_PER_HOUR must be an integer")
        body["rate_limit_email_sent"] = int(rl)
    return body


def build_smtp_dry():
    """Dry run must not need secrets: use placeholders for missing values."""
    body = {}
    for field, env in (("smtp_host", "SMTP_HOST"), ("smtp_port", "SMTP_PORT"),
                       ("smtp_user", "SMTP_USER"), ("smtp_pass", "SMTP_PASS"),
                       ("smtp_admin_email", "SMTP_SENDER_EMAIL")):
        body[field] = os.environ.get(env, "")
    body["smtp_sender_name"] = os.environ.get("SMTP_SENDER_NAME", "").strip() or "MedConf"
    rl = os.environ.get("SMTP_RATE_LIMIT_EMAILS_PER_HOUR", "").strip()
    if rl.isdigit():
        body["rate_limit_email_sent"] = int(rl)
    return body


def describe(body):
    for k in sorted(body):
        v = body[k]
        if k in SECRET_FIELDS:
            print("  %-48s <secret, %s>" % (k, "set" if v else "NOT SET"))
        elif isinstance(v, str):
            print("  %-48s %d chars%s" % (k, len(v), "" if v else "  (NOT SET)"))
        else:
            print("  %-48s %r" % (k, v))


def show(cfg):
    print("project ref: " + ref())
    for k in ("site_url", "uri_allow_list", "mailer_otp_exp", "smtp_host",
              "smtp_port", "smtp_user", "smtp_admin_email", "smtp_sender_name",
              "rate_limit_email_sent"):
        if k not in cfg:
            print("  WARNING: field %s not present in API response" % k)
        else:
            print("  %-24s %s" % (k, cfg[k]))
    print("  smtp_pass                (never shown) %s" % ("set" if cfg.get("smtp_pass") else "not set / hidden"))
    for key, _, _ in TEMPLATES:
        sk, bk = "mailer_subjects_%s" % key, "mailer_templates_%s_content" % key
        body = cfg.get(bk) or ""
        head = " ".join(body.split())[:80]
        print("  [%s]" % key)
        print("    subject: %s" % cfg.get(sk))
        print("    body[:80]: %s" % head)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["templates", "smtp", "show"])
    ap.add_argument("--dry-run", action="store_true",
                    help="print field names and value sizes, send nothing, no token needed")
    a = ap.parse_args()

    if a.command == "show":
        if a.dry_run:
            print("DRY RUN: would GET " + API.format(ref=ref()))
            return
        show(call("GET"))
        return

    if a.dry_run:
        body = build_templates() if a.command == "templates" else build_smtp_dry()
        print("DRY RUN: would PATCH %s with %d fields (nothing sent):" % (API.format(ref=ref()), len(body)))
        describe(body)
        return

    body = build_templates() if a.command == "templates" else build_smtp()
    call("PATCH", body)
    print("PATCH ok (%d fields). Re-reading config:" % len(body))
    show(call("GET"))


if __name__ == "__main__":
    main()
