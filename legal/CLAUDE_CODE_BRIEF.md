# Legal pages — implementation brief for Claude Code

**Status:** DRAFT legal documents, prepared 31 Oct 2026 from a review of this repo. Not yet reviewed by a solicitor.
**Files in this folder:**

| File | Becomes | Notes |
|---|---|---|
| `terms.md` | `/terms` | Terms of Use |
| `privacy.md` | `/privacy` | Privacy Policy (UK GDPR) |
| `cookies.md` | `/cookies` | Cookie Policy |
| `CLAUDE_CODE_BRIEF.md` | — | This file. Don't publish it |

Each document has YAML front-matter and HTML comments (`<!-- DRAFT NOTES ... -->`, `<!-- FUTURE: ... -->`) that are **notes for you and must not render**. Placeholders look like `[[PLACEHOLDER: ...]]`. `grep -rn "PLACEHOLDER" legal/` lists them all.

---

## 0. Save this to project memory first

Add a short **"Legal pages"** section to `CLAUDE.md`, and a matching entry in the project's auto-memory (`memory/project_pending_work.md`), recording:

1. **Temporary brand name.** The legal pages use **"MediCon"**, but the site will be renamed. The UI currently says "MedConf". Render the brand name in the legal pages from one constant (e.g. `SITE_NAME` in `src/lib/site.ts`) so a rename is a one-line change, and so the UI and legal pages match. Ask the owner which name the live site should show until the rename.
2. **Temporary contact email.** `hellomedicon@gmail.com` is a placeholder until a custom domain exists. When the domain is set up, replace it everywhere (legal pages, footer/contact, auth email sender) and update the domain references (`medconf.vercel.app`).
3. **Draft status.** These are drafts. They need a solicitor's review before paid features (sponsored listings, ads, affiliates, organiser accounts) launch.
4. **Standing rule.** Any change that collects new personal data, adds a supplier or service, or adds a cookie / localStorage key / third-party script or embed **must update `privacy.md` and/or `cookies.md` in the same change, and bump `last_updated`**. Add this to the conventions list in CLAUDE.md.
5. **The future-features checklist in section 4 below.** Keep it in memory and review it each time one of those features is built.

---

## 1. Must do before the legal pages go live (blocking)

The documents describe some behaviour that **doesn't exist yet**. Either build it, or edit the document so it's true. Don't publish statements that are false.

### 1.1 Fill the placeholders
- The operator's full legal name, plus company name/number if it's a limited company. **Ask the owner.**
- A geographic postal address. **Ask the owner.** A virtual office address is fine if they don't want their home address published.
- The publication date (front-matter `last_updated` and the "Last updated" line).
- The ICO registration number, once the owner has paid the ICO data protection fee.
- `terms.md` §7: the response time for organiser requests (suggest 5 working days).
- `privacy.md` §6: the backup retention period. Check what the Supabase plan actually keeps.
- `privacy.md` §5: the supplier table, if anything has changed.

### 1.2 Routes and rendering
- Add `/terms`, `/privacy` and `/cookies` as **static** pages under `medconf-website/src/app/`. They must be public: not in `isGatedPath`, and not disallowed in `robots.ts`.
- Rendering: either convert the Markdown to TSX, or add a build-time Markdown renderer. Strip the front-matter and HTML comments. Use the site's existing type styles. Tables must scroll horizontally on mobile rather than overflow.
- Add the three pages to `sitemap.ts`.
- Add a **Contact** destination. A `mailto:hellomedicon@gmail.com` link is fine for now; a `/contact` page is better later.

### 1.3 Footer (`src/components/layout/Footer.tsx`)
- Replace the three `href="#"` links with `/privacy`, `/terms` and contact. Add a **Cookie policy** link.
- Change "© {year} MedConf." to use the brand constant.

### 1.4 Sign-up consent wording (`AuthTerms` in `src/components/auth/AuthCard.tsx`)
On the **sign-up** page, replace the current text with something like:

> By creating an account you confirm you're 18 or over and agree to our [Terms of Use](/terms). Read how we use your information in our [Privacy Policy](/privacy).

Keep the existing "we don't take bookings" line if wanted. On the **login** page, a lighter version with the same links is enough. Optionally, add the same links to the community **Submit** form's confirmation text (`SubmitEventForm.tsx` ~L364).

### 1.5 Self-serve account deletion (Settings)
`privacy.md` §6–7 and `terms.md` §3/§13 say users can delete their account themselves in **Settings**. Build:
- A "Delete account" section in `/settings` with a clear confirmation step (e.g. type DELETE). Then sign the user out and redirect to `/`.
- **Server-side deletion.** The service-role key must never reach the client (CLAUDE.md §7). Use either:
  - a `SECURITY DEFINER` Postgres function that deletes `auth.users` where `id = auth.uid()`, with EXECUTE granted to `authenticated` only; or
  - a server route/action using a service-role key held in a **server-only** Vercel env var (not `NEXT_PUBLIC_`).
- **Keep published community content when an account is deleted.** Today `community_contributions.user_id ... ON DELETE CASCADE` deletes all contributions, and `community_facts` / `community_tiers` cascade from them. That means deleting an account would silently remove published facts and fee tiers from listings. Required behaviour (matches `privacy.md` §6):
  - **Unpublished** contributions (pending / needs_info / rejected / expired / hidden): delete.
  - **Published / merged** contributions: keep, set `user_id = NULL`, and clear `note` and `evidence_url`.
  - This needs a schema migration (`user_id` nullable + `ON DELETE SET NULL`, plus a delete trigger or the deletion function doing the split). Update `supabase_schema.sql` and RLS (a NULL owner must not become readable to anyone new).
  - `community_contributions.moderator_id REFERENCES auth.users(id)` has no ON DELETE rule, so deleting a moderator's account will fail. Set it to `ON DELETE SET NULL`.
- Confirm that saved events, reminders, notifications, profile and notification preferences all disappear (they already cascade from `auth.users`).
- Add tests.

### 1.6 Specialty-alert toggle (Settings)
`privacy.md` §3 says users can turn specialty alerts off in Settings. Onboarding sets `notification_preferences.email_new_conferences = true`, and `fire_specialty_alerts.py` uses that column as the in-app opt-in, but there's no UI to change it. Add an **"In-app alerts for new events in my specialty"** toggle in Settings bound to that column. Consider renaming the column later; it isn't email.

### 1.7 Retention jobs
- **Notifications older than 12 months:** delete them, using a daily SQL job or an extra step in an existing cron.
- **Inactive accounts (3 years):** email the user, then delete after 30 days if they haven't signed in (`auth.users.last_sign_in_at`). This needs email sending. If it won't be built before launch, it's acceptable to launch first only because the earliest possible trigger is years away. Record it as a tracked TODO in memory, and build it well before then.

### 1.8 Data minimisation in `user_profiles`
- Remove the `country DEFAULT 'United Kingdom'` default. It records a country for every user although none is asked for.
- The old 3-step wizard collected `institution`, `region` and `country`. These are no longer collected or used, and the privacy policy doesn't list them. Write a migration to **null them out** for existing users (or drop the columns if nothing reads them; grep the scraper and website first).

### 1.9 Email provider (owner + you)
- Auth emails currently go through **consumer Gmail SMTP** (`hellomedicon@gmail.com`). Two issues:
  1. A consumer Gmail account comes with no data processing agreement.
  2. Every verification and reset email (address plus link) is kept in the account's **Sent** folder.
- Short term: ask the owner to set up auto-deletion of sent auth emails, e.g. a Gmail filter or periodic clean-up.
- Medium term: move to Resend (already planned), or Google Workspace. Then update `privacy.md` §5.

### 1.10 Supplier checks (owner)
For each supplier in `privacy.md` §5, confirm the data processing agreement / terms and the transfer mechanism. Adjust §5 wording if anything differs:
- Supabase: accept its DPA in the dashboard.
- Vercel: DPA, plus its Data Privacy Framework (DPF) / UK Extension status.
- GitHub: covered by the GitHub DPA.
- NVIDIA API: check whether prompts are retained or used for training. If they are, say so, or switch providers for submission checks.
- Google.

### 1.11 Re-audit cookies and storage just before publishing
Grep for `document.cookie`, `cookies().set`, `localStorage`, `sessionStorage`, `<script`, `<iframe` and any new SDKs. Make `cookies.md` match exactly.

---

## 2. Owner actions (not code; remind the owner)
- Pay the **ICO data protection fee** (the ICO site has a self-assessment) and add the registration number.
- Decide on publishing a **postal address** (virtual office is fine).
- **Online Safety Act:** published community contributions may make the site a "user-to-user service". Use Ofcom's online checker and, if it applies, keep a short written illegal-content risk assessment. The reporting route in `terms.md` §10 helps.
- **Scraped content / IP:** listings and descriptions are copied from organiser sites, some of whose terms restrict automated collection or reuse. The organiser correction/removal route (`terms.md` §7) should be honoured promptly. This risk grows once the site earns money from sponsored listings, ads or affiliates. Consider a legal review at that point.
- Get a **solicitor review** before paid features launch.

---

## 2a. Google Analytics (built 31 Oct 2026 — branch `feat/google-analytics-consent`, not pushed)

What exists: `src/lib/analytics/{config,consent,sanitize}.ts`, `src/components/analytics/{CookieConsent,GoogleAnalytics,CookieSettingsButton}.tsx`, footer "Cookie settings", `<CookieConsent />` in `app/layout.tsx`, tests in `src/lib/__tests__/analytics.test.ts`. Behaviour (browser-tested): no GA request or cookie before consent; Accept loads gtag.js with ads denied, Google signals off, `_ga` ~13 months, manual page_view with sanitised URLs (nothing under `/auth`, no `?q=`, no email-like values); Reject/withdraw deletes `_ga*` and reloads; choice in `mc_consent` (v1, 6 months).

**GA property (created 31 Oct 2026):** Google account `hellomedicon@gmail.com` → GA account "MediCon" (a414219256) → property "MediCon website" (p561731546), UK time zone, GBP → web stream "MediCon website", `https://medconf.vercel.app`, **Measurement ID `G-M2DLMQR888`**. Google Analytics Terms and Data Processing Terms accepted (UK). When the custom domain goes live, edit the stream URL (Admin → Data streams) — same ID, history kept.

**Analytics is OFF until `NEXT_PUBLIC_GA_MEASUREMENT_ID` is set.** Go-live order:
1. Merge the branch into `main` and push (pushing `main` auto-deploys to production — that's safe here: with no env var the banner, tag and footer "Cookie settings" link all render nothing). Only the analytics files, footer and layout are in the branch commit; the owner's other uncommitted files (reports, masterlist) are not part of it — leave them alone.
2. Publish `/cookies`, `/privacy`, `/terms` (the banner links to `/cookies`; consent isn't informed without it).
3. Set `NEXT_PUBLIC_GA_MEASUREMENT_ID=G-M2DLMQR888` in Vercel (project `medconf`) for the **Production** environment only — not Preview or Development — then trigger a new production deploy. `NEXT_PUBLIC_` values are baked in at build time, so it has no effect until the redeploy.
4. Verify on the live site: banner shows, no `googletagmanager.com` request before Accept, GA Realtime shows the visit after Accept.

GA property settings as configured (the code and policies rely on them — keep them this way): Enhanced measurement → **Page changes based on browser history events OFF**, **Site search OFF**, **Form interactions OFF**, Video OFF (page views, scrolls, outbound clicks, file downloads ON); **Redact data** → email ON + URL query keys `email, q, next, token_hash, code, token` (backup to `sanitizeUrl`); Google signals OFF; event + user data retention **14 months**, "reset on new user activity" **OFF**; all account data-sharing settings OFF; no Google Ads links. If anyone changes these, update `privacy.md`/`cookies.md`.

Rules: never send user id, email, name or `?q=` text to GA; any new custom event must pass URLs through `sanitizeUrl()`; bump `CONSENT_VERSION` if the banner starts asking consent for anything else (ads, affiliates).

## 3. Facts the documents rely on (from the code, 31 Oct 2026)
If any of these change, update the documents.
- **Sign-in:** email + password only (Supabase Auth, PKCE). No social login.
- **Onboarding** collects specialty (taxonomy slug) and grade (Medical Student, Foundation Doctor, Core Trainee, Registrar, Fellow, Consultant, GP, Nurse, Allied Health, Other). Name is optional, in Settings.
- **Features:** saved events, reminders (abstract / start / registration; in-app), personal calendar + `.ics` download (client-side file), in-app notifications, daily in-app specialty alerts. **No marketing or digest emails** (Settings shows "coming soon").
- **Community contributions:** payload, private `evidence_url` + `note`, moderator notes. Admins see the submitter's email/name. Public label is "Community" only. Max 10 pending. `enrich_submissions.py` sends the submission payload (event details, no name/email) and the fetched organiser page to the NVIDIA-hosted model.
- **Suppliers:** Supabase (eu-west-1), Vercel, Gmail SMTP, GitHub Actions (crons read user ids/specialty/reminders with the service key), NVIDIA API.
- **Cookies:** `sb-zcpszfbmvfylicpxgsfc-auth-token` (chunked, @supabase/ssr default maxAge 400 days), `...-code-verifier` (PKCE), `mc_next` (1 h), `mc_consent` (cookie choice, 6 months). After consent only: `_ga`, `_ga_M2DLMQR888` (~13 months).
- **localStorage:** `medconf-theme`, `medconf-accent`, `medconf:recent-searches`.
- **Google Analytics** only after consent (section 2a). **Not present:** ads or other third-party scripts. Fonts are self-hosted via `next/font`. Google Maps is a plain outbound link, not an embed.
- **Age:** 18+.
- **Audience:** international, UK first. Governing law: England & Wales.

---

## 4. Future features — legal checklist (keep in memory)
When building any of these, update the documents in the same change. Each has a `<!-- FUTURE: -->` slot in the drafts.

| Feature | Update needed |
|---|---|
| **Analytics** | **Google Analytics DONE** (section 2a, consent banner). Any additional analytics tool: update `privacy.md` §2/§3/§5/§6 and `cookies.md` |
| **Cloudflare Turnstile** (CAPTCHA) | Add Cloudflare to suppliers (§5) and `cookies.md` (strictly necessary/security) |
| **Resend** (or any email provider) | Replace Google in §5; sign its DPA |
| **Email digests / newsletter / specialty emails** | Opt-in with an **unticked** box (not default-on — onboarding currently defaults `email_new_conferences = true`, so don't reuse that value as email consent); unsubscribe link in every email; `privacy.md` §3 row (consent) |
| **Sponsored / featured events** | Label clearly ("Sponsored") wherever shown, including search results and emails; describe the effect on ranking in `terms.md` §12; consider Sponsor/Advertiser Terms; solicitor review |
| **Advertising** | Extend the existing consent banner (add a separate "advertising" choice, bump `CONSENT_VERSION`) if any ad tech sets cookies or uses personal data (reject as easy as accept, nothing set before consent, "Cookie settings" link in footer); name ad networks in §5; say whether ads are personalised. Contextual, non-personalised ads are simpler |
| **Affiliate links** | Label as affiliate links; if tracking cookies or redirects with identifiers are used, they need consent; update `cookies.md` and `privacy.md` |
| **Organiser self-service accounts** | New section or separate Organiser Terms (`terms.md` §7 slot); privacy policy for organiser contact data |
| **Google / social sign-in** | Add the provider to §2 and §5; describe what profile data is received |
| **Custom domain** | Replace `medconf.vercel.app` and the contact email throughout; update Supabase Auth Site URL / redirect allowlist (see CLAUDE.md) |
| **Rename from "MediCon"** | Change the brand constant; check every document for the old name |
| **Actively targeting EU/EEA users** | Consider whether an EU GDPR Article 27 representative is needed (`privacy.md` §1 slot) |
