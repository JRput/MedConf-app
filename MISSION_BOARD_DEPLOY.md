# Mission: Deploy the MedConf website to Vercel (first production deployment)

**Opened:** 2026-10-24 · **Owner approval:** "lets move to setting up deployment on vercel … activate hq and foreman to plan and deploy the build to vercel successfully. ensure the github repo is up to date with the latest updates for the site." · **Protocol:** HQ foreman (session plans on Opus; no Fable/Astra consult requested), proof-check before close.

## Brief
Take `medconf-website/` (Next.js 16.1.6 / React 19 / Tailwind v4, Supabase anon client, middleware route guard) from localhost-only to a live Vercel deployment connected to the GitHub repo `JRput/MedConf-app` (monorepo; site in the `medconf-website` subdirectory), with production env vars, a green production build, a smoke test of the public and auth routes, and the Supabase auth redirect settings pointed at the new origin. Custom domain and real SMTP (Resend) are follow-ups, not this mission.

## Facts established (2026-10-24)
- Repo: `main` = `origin/main` at `8d1f4f5`; `git status -- medconf-website` clean → the site on GitHub IS the latest. Uncommitted: CLAUDE.md + the safe-fetch follow-up board (docs) — committed with this mission's docs.
- Site env contract: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable key, RLS-gated) + optional `NEXT_PUBLIC_DIRECTORY_FIXTURE` (test fixture — must stay UNSET in production). No server-side secret in the site. `.gitignore` excludes `.env*` except `.env.example`.
- Vercel: team `jaikishrajput-gmailcoms-projects` (`team_677DwCROWb1yOHEL4uka1AFg`); no existing project; GitHub namespace `JRput` connected (installation 80234621, unrestricted). `next.config.ts` empty; no `vercel.json`.
- Supabase project `zcpszfbmvfylicpxgsfc` (eu-west-1). Auth email links go to `/auth/callback`; Site URL / redirect allowlist currently localhost (EMAIL_SETUP_GUIDE.md). SMTP still the Supabase default sender (Resend is a follow-up).

## Task graph
```
T0 preflight `vercel-preflight` (sonnet) — local `next build`, vitest, eslint, check:societies, Vercel-readiness greps, recommended settings
T1 Commander — create Vercel project `medconf` linked to JRput/MedConf-app, rootDirectory=medconf-website, framework nextjs, deploy=false
T2 Commander — env vars (production + preview): NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY (plain; publishable values)
T3 Commander — trigger production deployment from main (create_deployment gitSource) → watch build → READY; on build error: fix ticket (sonnet) → commit → redeploy
T4 Commander/agent — smoke test on the deployment URL: `/`, `/conferences`, `/conferences/<id>`, `/societies`, `/calendar` (redirect to login), `/auth/login`, `/auth/signup`, `/dashboard` (redirect), 404 page; response codes + no server errors in runtime logs
T5 Supabase auth: Site URL + redirect allowlist for the Vercel origin (automate via Management API if a token exists; else owner step with exact values)
T6 proof-check (hq-security-reviewer, opus) on the deployment config + any code fixes; CRITICAL/HIGH stop
T7 docs: CLAUDE.md production-state ("Not yet deployed" → URL), this board CLOSED, memory; commit (explicit pathspecs) + push (also triggers Vercel's Git auto-deploy — verify it stays green)
```

## Write sets
- T0: `medconf-website/src/**` lint one-liners only; `medconf-website/next.config.ts` only if a remotePatterns entry is strictly required.
- Fix tickets (if any): named per ticket, inside `medconf-website/`.
- Commander: Vercel project/env/deployment via MCP; docs files.

## Model routing · cost
Sonnet preflight/fix builders; Opus reviewer; Commander verifies. Vercel Hobby tier (free). No new credentials: the Vercel MCP connection is the owner's; env values are the publishable Supabase URL/anon key already in `.env.local`.

## Risk flags
- First deploy before env vars exist would fail or bake empty Supabase config into static pages → create with `deploy=false`, set env, then deploy.
- Monorepo root directory must be `medconf-website` or the build runs at the repo root (Python scraper) and fails.
- Auth flows on the Vercel origin need Supabase Site URL / redirect allowlist updated, or email links point at localhost.
- Vercel Deployment Protection (Vercel Authentication) is on by default for preview URLs on some plans — production URL must be public for the directory; verify the production alias is reachable unauthenticated.
- `middleware.ts` on Next 16: deprecated in favour of `proxy.ts` — a warning is acceptable, an error is a fix ticket.

## Acceptance
Production deployment READY on `https://medconf-<team>.vercel.app` (or `medconf.vercel.app`); smoke routes return the expected codes with the live Supabase data; runtime logs free of 5xx; Supabase redirect settings updated (or exact owner steps recorded); reviewer 0 CRITICAL/HIGH; docs + board pushed; the push itself produced a green Git-triggered deployment.

## Ticket ledger
| id | tier | status/verdict | evidence |
|---|---|---|---|
| T0 vercel-preflight | sonnet | DONE_WITH_CONCERNS | `next build` green (Turbopack, 23 static pages; dynamic: /admin/moderation/[id], /api/directory, /auth/callback, /conferences, /conferences/[id], /societies; / revalidates hourly); vitest 317 passed; check:societies OK (130 codes); `npm ci --dry-run` OK; lint: 1 pre-existing error (ReminderPanel setState-in-effect, known debt, not run by `next build`) + 2 warnings; only build warning = `middleware` → `proxy` deprecation (still runs). No hard-coded origins (callback/middleware use `request.url`; useAuth uses `window.location.origin`). next 16.1.6 needs Node ≥20.9 → pin 22.x. Finding to fix before prod: public `?fixture=1` switch + silent fixture fallback in `src/lib/directory-source.ts` → fix ticket T0b |
| T0b fixture gate | sonnet (vercel-preflight) | DONE → committed `32d6a5d`, pushed | `fixtureAllowed()` gate (also covers getSocietyNextDates); vitest 322 passed; Commander sabotage on old source: 4/5 new tests red; build green |
| T1–T3 | Commander | DONE | project `prj_G2p5tZiJLnUu82yoBz4Ch1dfMr0f`; deployment `dpl_8aAZeTSsvehdyKmjTQpTGLZg7wmz` (main@8d1f4f5) READY+PROMOTED → aliases `medconf.vercel.app`, `medconf-jaikishrajput-gmailcoms-projects.vercel.app`, `medconf-git-main-…`; Git auto-deploy proven: push of 32d6a5d → `dpl_J3chsVTpSHVx3FoVm6zDu9ArybxY` READY production |
| T4 smoke | Commander | DONE on `https://medconf.vercel.app` | public routes 200 (/, /conferences, /conferences/548, /societies, /auth/login|signup|forgot-password, /api/directory); protected 307 → /auth/login (/calendar, /dashboard, /saved, /settings, /submit, /admin/moderation); unknown → 404; API returns live rows |
| T6 deploy-review | opus (hq-security-reviewer) | PASS_WITH_NOTES (0 CRITICAL/HIGH · 1 MEDIUM · 6 LOW) | MEDIUM: uncapped `pageSize`/`page` on public `/api/directory` + `/conferences` SSR (cache-bypassable). LOW: PostgREST `.or()` interpolation of dateFrom/dateTo/q; raw PostgREST error echoed by the API 500; no security headers; fixture flag "true" vs "1" drift; two silent degrade paths; no explicit outbound timeouts. Solid: single fixture chokepoint, fail-closed throw, safeNextPath (no open redirect), cookie-on-redirect callback, DB-enforced admin (is_admin RPC/RLS/trigger), JSON-LD escaping, URL CHECK constraint. Supabase allowlist missing = broken UX (localhost links), nothing fails open |
| T6b hardening wave | sonnet (vercel-preflight) | DONE → committed `bc6175b`, pushed, auto-deployed `dpl_CsszR8waN97tvqfTjsNxqx9r4jVv` READY (production) | vitest 329 passed; build green; Commander diff read (6 items, nothing else). Live re-smoke on https://medconf.vercel.app: 5 security headers present; `pageSize=100000` → 100 rows; `dateFrom=2026-01-01,or(id.gt.0)` dropped (total unchanged 2129); routes 200/307/404 as before |
| T6c re-review | opus (deploy-review) | PASS_WITH_NOTES (0 CRITICAL/HIGH/MEDIUM · 4 LOW hygiene → HQ backlog) | no caller sends pageSize > 20 through the parser (home page passes 100 directly = cap); UI emits YYYY-MM-DD only; sanitiser removes every structural char; headers break nothing; API error contract preserved. Live headers verified by Commander curl |
| T7 docs | Commander | DONE | CLAUDE.md production state → DEPLOYED paragraph; memory updated; this board CLOSED |

## Status log
- 2026-10-24 — board written after discovery (team, GitHub link, env contract, repo clean); T0 dispatched.
- 2026-10-24 — BLOCKED on owner input: Vercel MCP connector returns 403 "You don't have permission to create a project" on create_git_project, create_project (v11) and create_deployment (v13) for team_677DwCROWb1yOHEL4uka1AFg (reads work: list_teams, list_projects, git_namespaces). Vercel CLI 48.1.6 is installed but has no credentials. Unblock = owner runs `vercel login` once (or re-authorizes the Vercel connector with project-create scope). Prepared for the CLI route: scratchpad `vercel_project.json` (project + Git link + both env vars) and `vercel_deploy.json` (production deploy from main). T0 preflight continues meanwhile.
- 2026-10-24 — UNBLOCKED: owner ran `vercel login` (CLI user jaikishrajput-5643). MCP writes still 403, so the Vercel REST API was called with the CLI's stored token (never printed). T1 DONE: project `medconf` `prj_G2p5tZiJLnUu82yoBz4Ch1dfMr0f`, framework nextjs, rootDirectory `medconf-website`, Git link github JRput/MedConf-app (repoId 1155725089, productionBranch main). T2 DONE: NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY on production+preview (plain; publishable values). Node pinned 22.x (default was 24.x). T3 started: production deployment `dpl_8aAZeTSsvehdyKmjTQpTGLZg7wmz` from main@8d1f4f5 → aliases `medconf-jaikishrajput-gmailcoms-projects.vercel.app` (production) and `medconf-git-main-…vercel.app`; watcher running.
- 2026-10-24 — First production deployment READY (PROMOTED) and public at https://medconf.vercel.app; fixture gate committed `32d6a5d` and auto-deployed by the Git link; smoke green; proof-check dispatched. Pending: Supabase Site URL/redirect allowlist (owner), docs, CLOSE.
- 2026-10-24 — Proof-check PASS_WITH_NOTES; Commander decision (Level 2): the MEDIUM and the cheap LOWs are hardening of a now-public surface → one batched fix wave, re-review of the hunks, then push (auto-deploy) + re-smoke. Deferred to HQ backlog: silent degrade-path logs, explicit outbound timeouts, scraper-side `javascript:` scheme filter check, Supabase max-rows verification.
- 2026-10-24 — Hardening wave live (`bc6175b`); third Git-triggered production deployment READY; re-smoke green incl. headers and clamps. Awaiting re-review verdict; then docs + CLOSE.
- 2026-10-24 — **CLOSED.** Production live at https://medconf.vercel.app (aliases `medconf-jaikishrajput-gmailcoms-projects.vercel.app`, `medconf-git-main-…`). Three production deployments: `8d1f4f5` (first, API-triggered), `32d6a5d` fixture gate and `bc6175b` hardening (both Git auto-deploys). Smoke + re-smoke green; no runtime errors. Reviews: PASS_WITH_NOTES → hardening wave → PASS_WITH_NOTES (4 LOW → HQ backlog). Project setting `enableAffectedProjectsDeployments=true` (docs-only pushes do not rebuild). **Owner steps open:** Supabase Auth → Site URL `https://medconf.vercel.app`; Redirect URLs `https://medconf.vercel.app/**` and `https://medconf-*-jaikishrajput-gmailcoms-projects.vercel.app/**`; later: custom domain, Resend SMTP. HQ LESSONS #85 (connector write scope).
