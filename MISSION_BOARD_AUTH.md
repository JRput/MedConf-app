# Mission board — Password reset flow (auth)

Opened 2026-10-20 by the Commander. **Status: DELIVERED 2026-10-20** (commits 3346420, 83e59f6; E2E ada1503, ce2fa5b). Owner request: "add a password reset flow into the login, this is an important feature for login."

## 1. Design (fixed)

- `/auth/forgot-password` — email form. Always shows the same "If an account exists… we've sent a link" state (no account enumeration). Reads `?error=expired` from the callback.
- Supabase `resetPasswordForEmail(email, { redirectTo: <origin>/auth/callback?next=/auth/reset-password })`.
- `/auth/callback` — now handles both `code` (PKCE) and `token_hash`+`type` (Supabase server-side template flow), validates `next` (relative path only), and **writes the session cookies onto the redirect response** (pre-existing bug: cookies were set on the request object only, so verified sign-ups were never actually signed in).
- `/auth/reset-password` — needs the recovery session. No session → "link expired" state with a path back to forgot-password. With session → new password + confirm (≥ 8 chars, mirrors signup), `auth.updateUser({ password })`, then success state → dashboard.
- Login page gets a "Forgot password?" link beside the Password label and surfaces `?error=` from the callback (it was being set but never shown).
- Middleware: `/auth/forgot-password` and `/auth/reset-password` stay outside PROTECTED_PATHS and AUTH_PATHS (reachable signed-out; `/auth/*` already skips the profile gate).
- Branded `supabase/templates/recovery.{html,txt}` + `[auth.email.template.recovery]` in config.toml (local stack; the hosted template is pasted by the owner).

## 2. Owner-side steps (dashboard, cannot be automated from here)

1. Authentication → URL Configuration → Redirect URLs: add `http://localhost:3000/**` (an exact `/auth/callback` entry does not match the `?next=` query string; GoTrue globs the whole URL). Add the production origin the same way when deployed.
2. Optional: paste `supabase/templates/recovery.html` into Authentication → Email Templates → Reset Password.
3. Built-in email sender is rate-limited (a few per hour) until SMTP (Resend) is configured — see EMAIL_SETUP_GUIDE.md.

## 3. Ownership

| Phase | Agent | Scope |
|---|---|---|
| P1 build | `auth-p1-build` (sonnet) | pages, callback fix, useAuth, AuthField labelAction, lib/auth/password.ts + vitest, templates, docs |
| P2 QA | `auth-p2-qa` (sonnet) | tsc/lint/vitest gate; Playwright E2E via service-role `generate_link(type=recovery)` → token_hash path; signup token_hash verifies and lands signed-in on /onboarding; negative cases; screenshots 375/1024 |
| Commander | — | verify gate, commit/push, CLAUDE.md, memory |

## 4. Ledger

- 2026-10-20 — board opened; scoping found the callback cookie bug and the allowlist query-string constraint.
- 2026-10-20 — P1 build shipped in 3346420: forgot/reset pages, callback (code + token_hash, safe next, cookie fix), useAuth methods, AuthField labelAction, login link + ?error, recovery templates, docs. tsc/lint(0 new)/vitest 262 pass.
- 2026-10-20 — automated security review on `3346420`: (a) reflected free-text `?error=` on /auth/login → FIX queued (callback emits short codes, login maps known codes to fixed copy); (b) "login CSRF / session fixation" via the `token_hash` path → ACCEPTED: inherent to email-link auth and Supabase's documented SSR pattern; a nonce cookie would break cross-device reset; reset page shows the signed-in email. Mitigation: OTP type allowlist trimmed to signup/email/recovery/email_change (no magiclink/invite side door). Code change held until P2 QA finishes to avoid a hot-reload clash.
- 2026-10-20 — P2 QA (auth-p2-qa): tests/e2e/e2e_password_reset.py ALL PASS (gates tsc/lint 1 known error/vitest 262; pages, forgot no-enumeration, token_hash recovery + validation, replay -> expired, 3 open-redirect fallbacks, signup verify -> /onboarding, allowlist accepts ?next). Screenshots 375/1024/dark reviewed: no visual defects. Review notes (non-blocking) in QA report.
- 2026-10-20 — review fixes in 83e59f6: callback emits error codes only (verify_failed/expired) mapped by lib/auth/errors.ts; OTP types trimmed to signup/email/recovery/email_change. 269 tests pass.
- 2026-10-20 — P2 QA rerun after 83e59f6: e2e_password_reset ALL PASS incl. 6 new error-code/OTP-allowlist checks; vitest 269, tsc clean, lint only known ReminderPanel error. Existing-account forgot submit hit Supabase email rate limit (INFO, expected after repeated runs).
- 2026-10-20 — Commander close-out: gate re-run (tsc clean, vitest 269/269, lint only the known ReminderPanel.tsx:88), board + CLAUDE.md committed, pushed main. Owner steps in §2 remain; localhost allowlist already accepts the callback with ?next (QA probe), so step 1 is only needed for the production origin. Built-in mailer rate limit was hit during QA — reset emails may say "too many" for up to an hour.
