# Mission board — legal pages + privacy commitments (2026-10-31)

Brief: `legal/CLAUDE_CODE_BRIEF.md` (drafts `legal/{terms,privacy,cookies}.md`, brand "MediCon" temporary, contact `hellomedicon@gmail.com` temporary, NOT solicitor-reviewed). Owner: "read the brief and carry out the tasks … report back with any questions".

**Baseline:** main fast-forwarded locally to `feat/google-analytics-consent` (`2f2a2a5`, analytics OFF until `NEXT_PUBLIC_GA_MEASUREMENT_ID` is set). The push itself is blocked for this session by the auto-mode classifier ("production deploy") → one push at the end, owner-run or approved. Workers `model: sonnet`; security reviewer (opus) on the deletion path. PRINCIPLES arm OFF.

## Tickets (parallel, disjoint write sets)
| id | scope | write set |
|---|---|---|
| T1 legal pages | brand constant `src/lib/site.ts`; `/terms` `/privacy` `/cookies` static pages rendering the Markdown at build time (front-matter + HTML comments stripped, `MediCon` → `SITE_NAME`, tables scroll on mobile); `sitemap.ts`; `robots.ts` check; Footer links (privacy/terms/cookies/contact mailto); `AuthTerms` sign-up/login wording; Submit form links; cookie/storage re-audit of the code vs `cookies.md` (report only) | `medconf-website/src/lib/site.ts`, `src/lib/legal.ts`, `src/app/{terms,privacy,cookies}/page.tsx`, `src/app/sitemap.ts`, `src/app/robots.ts`, `src/components/layout/Footer.tsx`, `src/components/auth/AuthCard.tsx`, `src/components/community/submit/SubmitEventForm.tsx`, `package.json` + lockfile (markdown lib), tests |
| T2a deletion + minimisation SQL | migration: `community_contributions.user_id` nullable + `ON DELETE SET NULL`, `moderator_id ON DELETE SET NULL`; `delete_my_account()` SECURITY DEFINER (auth.uid(); unpublished contributions deleted, published/merged anonymised: user_id NULL, note NULL, evidence_url NULL; then `auth.users` row deleted; EXECUTE to `authenticated` only); RLS review for NULL owners; `user_profiles.country` default dropped + `institution/region/country` nulled (or dropped if unread); dry run + rollback + checks; `supabase_schema.sql` | `supabase/migrations/20261101000000_account_deletion.sql` + `_rollback.sql` + `_checks.txt` + `dry_run_20261101.sql`, `supabase_schema.sql` |
| T2b settings UI | "Delete account" section (type DELETE → RPC `delete_my_account` → sign out → `/`); "In-app alerts for new events in my specialty" toggle bound to `notification_preferences.email_new_conferences`; tests | `src/app/settings/page.tsx` (+ small components under `src/components/settings/`), `src/lib/types.ts` if needed, tests |
| T3 retention | `medconf-scraper/purge_notifications.py` (delete `notifications` older than 12 months, service key, dry-run flag) + a step in `.github/workflows/fire-reminders.yml`; test | those two files + test |
| V1 | hq-security-reviewer (opus) on T2a + T2b (deletion path, RLS, no service key client-side) | read-only |

**Foreman:** CLAUDE.md "Legal pages" section + convention rule; memory (brand, email, draft status, standing rule, future-features checklist, inactive-account TODO); owner questions; final push after tests/build.

## Owner questions (blocking placeholders)
1. Brand shown on the live site until the rename: "MedConf" (UI today) or "MediCon" (drafts)?
2. Operator's full legal name (+ company name/number if a company) and a geographic postal address (virtual office fine).
3. ICO registration number (after paying the fee) — or leave the sentence out until then?
4. Organiser response time (default 5 working days unless told otherwise).
5. Supabase plan → backup retention (Pro = 7 days daily backups; Free = none) for `privacy.md` §6.
6. NVIDIA API: confirm prompt retention/training terms, or switch the submission-check provider.
7. Publication date = the day the push goes live (I set `last_updated` then).

## Log
- 2026-10-31 — board created; local ff-merge of the analytics branch; tickets dispatched.
- 2026-10-31 ~14:15 UTC — T1 (legal pages, footer, consent wording, 544 vitest + tsc + build green; audit found `medconf:submit-draft:<user id>` missing from cookies.md → foreman added the row), T2b (Settings delete-account + specialty-alert toggle; NULL-owner handling in moderation), T3 (purge_notifications.py + reminders workflow step) DONE. T2a DONE (FKs SET NULL, `delete_my_account()`, guard + orphan-notification triggers, user_profiles institution/region/country DROPPED after grep; dry run PASSED locally, rolled back). Security review (opus): PASS_WITH_NOTES — MEDIUM: insert race (advisory lock), dashboard deletion path diverges (BEFORE DELETE trigger on auth.users sharing one internal function); LOW: orphan trigger scope + log, guard bypass scoped to the four columns → NULL. FV1 sent to T2a. Then: dry run again → build → backstop commit → apply migration → push (owner).
- 2026-10-31 ~14:25 UTC — FV1 closed; dry run PASSED; website 544 + tsc + build; commit `417423d`; **migration `20261101000000_account_deletion` APPLIED.** Remaining: owner pushes main (classifier blocks the deploy for this session) → Vercel deploys legal pages (analytics still off) → owner sets `NEXT_PUBLIC_GA_MEASUREMENT_ID=G-M2DLMQR888` in Vercel Production + redeploy → fill placeholders when the owner answers (brand, legal name, address, ICO, response time, backup retention, NVIDIA).
