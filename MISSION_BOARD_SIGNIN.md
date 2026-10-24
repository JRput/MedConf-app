# Mission: Sign-in sweep + first-time user verification journey + auth emails

**Opened:** 2026-10-24 · **Owner brief:** "proceed with sweeping the sign in flows. plan thoroughly the sign in and verification process for a first time user and generate and set up emails accordingly. activate hq command centre and foreman" · **Protocol:** HQ foreman (plan on Opus; no Fable/Astra consult requested); proof-check on any auth code change.

## Context
- Live: https://medconf.vercel.app (Vercel project `medconf`, Git auto-deploy on push to main). Registration gate LIVE (MISSION_BOARD_ACCESS_GATE.md CLOSED). Supabase project `zcpszfbmvfylicpxgsfc`; owner has set Auth Site URL + redirect allowlist for the Vercel origin (2026-10-24).
- Auth surface in repo: `medconf-website/src/app/auth/{login,signup,verify,callback,forgot-password,reset-password}`, `/onboarding`, `useAuth` (signUp carries `next` into `emailRedirectTo=/auth/callback?next=`), `safeNextPath`, `auth-errors.ts`. E2E suite `tests/e2e/` (Python, scraper venv; `e2e_password_reset.py`, helpers, two example.com test accounts — recreate via service role if lost). Existing templates: `supabase/templates/{confirm_signup,recovery}.{html,txt}` + `supabase/config.toml` `[auth.email.template.*]` (local dev only — production templates live in the Supabase dashboard). EMAIL_SETUP_GUIDE.md (Resend recommended).
- Known constraint to verify: Supabase's default email service delivers only to project team members (since 2024); public users need custom SMTP (Resend) + a verified sending domain — the owner has no custom domain yet.

## Baseline snapshot (2026-10-24)
- HEAD `180d30a` = origin/main. `git status --porcelain`: the two pre-existing `M` files only. Dev server on :3000 still running. principles_block arm=OFF for signin-T1/T2/T3.

## Task graph
```
T1 explorer (sonnet, read-only) — map the auth code paths, screens, states, error handling, config, tests
T2 qa-signin (sonnet) — live sweep on medconf.vercel.app with a fresh test account: signup → verify (admin generateLink, no mailbox) → onboarding → directory (next) → logout → login (next) → forgot/reset → login; negative cases; evidence; defects list
T3 auth-emails (sonnet) — email set as files (confirm signup, reset password, change email, magic link, reauthentication; html+txt), subjects, brand-consistent, variables correct; EMAIL_TEMPLATES.md (dashboard paste steps, Resend/domain setup, local config.toml mapping)
   │
   ▼
Commander: first-time-user journey plan (from T1+T2), triage defects → fix tickets (sonnet) → proof-check (opus) for any auth change → set what can be set → owner steps for the dashboard (templates/SMTP) → report
```

## Write sets
- T1: none (read-only). T2: `tests/e2e/**` (adapt base URL / add `e2e_signin.py`), scratchpad evidence; NO website code. T3: `supabase/templates/**`, `supabase/config.toml` (`[auth.email.template.*]` only), `EMAIL_TEMPLATES.md` (new).

## Risk flags
- Test accounts on the LIVE database: use clearly-marked `qa+<stamp>@medconf-test.invalid`-style addresses only if Supabase accepts them (invalid TLDs may be rejected) — otherwise `+tag` addresses on the owner's domain are NOT ours to use; T2 decides and records; delete/disable test users at the end via service role.
- Service-role key stays local (scraper `.env`); never in website code, never printed.
- Rate limits: Supabase auth email rate limits (default 2/hour on built-in SMTP per address and project-wide caps) — T2 must use admin link generation for verification and reset, not repeated real sends.

## Ticket ledger
| id | tier | status/verdict | write set | evidence |
|---|---|---|---|---|
| signin-T2 `qa-signin` | sonnet | DISPATCHED | tests/e2e/** | — |
| signin-T1 `signin-explore` | — | DONE (map + 9 journey gaps; see sections below) | — | agent report |
| signin-T3 `auth-emails` | sonnet | DONE (6 templates html+txt, config.toml mapping, EMAIL_TEMPLATES.md; Commander rendered confirm/recovery/reauth light+dark — on brand) | supabase/templates/**, supabase/config.toml, EMAIL_TEMPLATES.md | scratchpad/emails/*.png |
| signin-F1 `auth-fix` | sonnet | DISPATCHED | `src/app/auth/{verify,login,signup,callback}/**` · `src/app/onboarding/page.tsx` · `src/middleware.ts` (onboarding bounce `next`) · `src/hooks/useAuth.ts` · `src/lib/auth/errors.ts` · `src/lib/auth/next-cookie.ts` (new) · `src/components/layout/Navbar.tsx` (sign-out) · vitest files | — |
| signin-T2 `qa-signin` | sonnet | DONE_WITH_CONCERNS (live sweep; 3 defects; signup form untestable: example.com rejected + built-in SMTP rate limit exhausted) | tests/e2e/e2e_signin_live.py (untracked) | scratchpad/signin/ |
| signin-F1 `auth-fix` | sonnet | DONE_WITH_CONCERNS → committed LOCALLY `632f55b` (not pushed) | see F1 row | 472 tests, build green |
| signin-F1b `auth-fix` (sweep defects) | sonnet | DISPATCHED | `src/app/onboarding/page.tsx` · `src/app/auth/callback/route.ts` · tests | — |
| signin-F2 `auth-emails` (token_hash links) | sonnet | DONE (5 link templates on `{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=…`; recovery carries `next=%2Fauth%2Freset-password`; docs updated; no ConfirmationURL/RedirectTo left) | supabase/templates/** · supabase/config.toml · EMAIL_TEMPLATES.md · EMAIL_SETUP_GUIDE.md | — |

## Status log
- 2026-10-24 — board written; wave 1 fan-out announced (3 agents, disjoint); dispatched.
- 2026-10-24 — CONFIRMED from Supabase docs ("Send emails with custom SMTP" / going-into-prod): the default SMTP "sends messages only to pre-authorized addresses" (project team members); other addresses fail with *Email address not authorized*; heavy per-hour rate limit; no SLA. Custom SMTP lifts it (initial 30 msgs/hour, adjustable). ⇒ **Public sign-ups cannot complete email verification until Resend (or another SMTP) + a verified sending domain is configured — hard launch dependency; the owner has no domain yet.** Advisors API not permitted for this connector.
- 2026-10-24 — Live user base (read-only count): 6 accounts — owner (gmail), 3 mailinator test users (2026-10-03), 2 example.com E2E accounts (2026-10-18); 0 unconfirmed; 5 profiles completed. No real public sign-ups yet, so nobody is currently stuck on verification. Supabase logs/advisors not permitted for this connector.

## Explorer map — what a first-time user meets today (T1, file:line in the agent report)
- Signup = email + password (≥8), no confirm field; submit → `/auth/verify` (stateless: no address shown, no resend, says "expires after 24 hours" and "sign in again to send a fresh one" — both false; links to the now-gated directory).
- Emails use `{{ .ConfirmationURL }}` = PKCE `?code=` flow → works only in the browser that signed up; opening the email on another device/webview → `/auth/login?error=verify_failed`. Callback already accepts `token_hash`+`type` (signup/email/recovery/email_change) — the cross-device-safe form.
- Unconfirmed login → raw "Email not confirmed", no resend. `supabase.auth.resend` is never called anywhere.
- `next`: survives signup → callback, then `/onboarding` ignores it and always goes to `/dashboard`; the middleware bounce to `/onboarding` drops it too; "Forgot password?" drops it.
- Sign-out (Navbar) leaves the user on the gated page until they navigate. Settings sign-out goes to `/`.
- Password reset: anti-enumeration "sent" state; recovery → `/auth/reset-password`; no-session → "link expired" + request new; success → dashboard.
- Config (local): confirmations on, double-confirm email change on, secure_password_change off, otp_expiry 3600, min password 6 (client 8), email rate limit 2/h.
- Live users: 6 (owner + 5 test); 0 unconfirmed.

## Target first-time-user journey (plan)
1. Gate → "Create a free account" (next carried) → **Signup** (email, password ≥8) → Supabase sends **confirm_signup** (token_hash link: cross-device safe) → app → `/auth/verify?email=…` showing the address, "Resend email" (60 s cooldown, rate-limit message), "Use a different address", correct expiry (1 hour), "Back to home".
2. Email link → `/auth/callback?token_hash&type=signup` → cookies → `/onboarding` (specialty, grade) → **`next` if known** (same-device: short-lived `mc_next` cookie set at signup; cross-device: dashboard) else `/dashboard`.
3. Returning user: **Login** → `next`; errors mapped ("Email or password is incorrect"; unconfirmed → "Confirm your email first" + Resend button → `/auth/verify?email&reason=unconfirmed`); "Forgot password?" carries `next`.
4. Expired/invalid signup link → `/auth/verify?reason=expired(&email)` with Resend (not the login error).
5. **Reset**: forgot → **recovery** email (token_hash link) → `/auth/reset-password` → success → "Continue" (`next` or dashboard).
6. **Sign out** → `/` with a refreshed tree.
7. Emails: six templates designed (T3). Delivery: built-in sender = team members only → **Resend + verified domain required before public launch** (owner: domain). Dashboard paste steps in EMAIL_TEMPLATES.md.

## Fix plan (dispatch after T2's live results confirm/extend)
- F1 website auth (sonnet): verify page (email, resend, copy), login error mapping + unconfirmed path, signup → verify with email/`next` cookie, callback expired-signup → verify page, onboarding + middleware carry `next`, Navbar sign-out → `/`, tests (vitest + e2e additions). Proof-check (opus) after.
- F2 templates (sonnet): token_hash link form for confirm/recovery/email_change/invite/magic_link (`{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=…`), EMAIL_TEMPLATES.md + config.toml updated, verify-page copy aligned with the 1-hour expiry.
- 2026-10-24 — T1 + T3 DONE. Fix wave fan-out announced (F1 website auth, F2 templates; sonnet; disjoint); dispatched while T2's live sweep continues against the deployed site. principles arm=OFF.
- 2026-10-24 — **CHECKPOINT (owner: approaching max token usage).** Committed + pushed: email set (T3+F2), EMAIL_TEMPLATES.md, EMAIL_SETUP_GUIDE.md fix, config.toml mapping, this board. **IN FLIGHT, NOT committed:** F1 `auth-fix` (verify page + resend, login error mapping, signup `mc_next` cookie, callback expired→verify + magiclink/invite types, onboarding/middleware carry `next`, Navbar sign-out → `/`, tests) — its edits may be partially on disk under `medconf-website/src/app/auth/**`, `src/app/onboarding/page.tsx`, `src/middleware.ts`, `src/hooks/useAuth.ts`, `src/lib/auth/{errors,gate,next-cookie}.ts`, `src/components/layout/Navbar.tsx`, tests; T2 `qa-signin` live sweep (writes `tests/e2e/e2e_signin_live.py` + scratchpad evidence; creates ≤2 test users on the live DB and deletes them at the end — if the session died mid-run, check `auth.users` for `qa-signin-*` accounts and delete via service role).
  **RESUME STEPS:** (1) `git status` → inspect F1's files; run `cd medconf-website && npm test && npm run build`; if F1 reported DONE finish its verification (curl checks in the ticket), else re-dispatch F1 with the same ticket text (board "Fix plan"); (2) read T2's PASS/FAIL table (scratchpad/signin/ or re-run `tests/e2e/e2e_signin_live.py` with `E2E_BASE_URL=https://medconf.vercel.app`); fold defects into an F1b ticket; (3) proof-check (hq-security-reviewer, opus) on the auth diff; (4) commit (explicit paths) + push → auto-deploy → live re-sweep; (5) owner dashboard steps: paste the 6 templates + subjects from EMAIL_TEMPLATES.md (or provide an `sbp_` token for the management-API upload), Resend + domain for public delivery; (6) CLOSE board, memory, HQ lesson (cross-device PKCE links).
- 2026-10-24 — Post-checkpoint: F1 `auth-fix` reported DONE_WITH_CONCERNS (472 tests, build green; only unproven path = a successful callback landing with the `mc_next` cookie, needs a real token). Committed LOCALLY (not pushed) as the commit after 35ab918. Still to do on resume: T2 sweep results → F1b; proof-check (opus) on the auth diff; push; live re-sweep incl. the cookie path; owner dashboard steps.
- 2026-10-24 — **T2 live sweep DONE_WITH_CONCERNS** (script `tests/e2e/e2e_signin_live.py`, untracked; evidence scratchpad/signin/). PASS: gates + next, dialog, signup validation, token_hash verification signs in + confirms, directory/societies/event open when signed in, logout/login/next, recovery → reset → new password, bad/garbled tokens, unconfirmed login. **Defects for F1b (on resume):** (1) HIGH — onboarding "Done" hangs on "Saving…" after successful writes (`onboarding/page.tsx` ~:117 `router.push('/dashboard')`; prefetched /dashboard likely cached as a redirect to /onboarding; `saving` never reset) → use `router.refresh()` + push or `window.location.assign(dest)`; (2) MEDIUM — a verify link carrying `next` lands straight on `/conferences…` with an incomplete profile, skipping onboarding (directory is not profile-gated) → callback: for `type=signup|invite|magiclink` always land on `/onboarding?next=…` (F1 made onboarding honour next); (3) LOW — onboarding drops next (fixed by F1, re-verify). **Concern:** the live signup form could not be submitted validly: `@example.com` rejected as invalid by Supabase, then "email rate limit exceeded"; the reset form hit "Too many reset emails" — the project-wide built-in-SMTP rate limit is exhausted → confirms the Resend dependency; test users were deleted (per ticket).
- 2026-10-24 — RESUMED from checkpoint. Reconciled: HEAD `632f55b` (F1, local) on top of pushed `35ab918`; working tree = this board + T2's untracked script + the two pre-existing M files. F1b dispatched (sonnet). Owner question: Resend needs a domain → recommend a single-sender SMTP provider meanwhile (Brevo free 300/day or Gmail App Password 500/day) — settable by the owner in the dashboard or by me via the Management API with an `sbp_` token + the SMTP credential.
