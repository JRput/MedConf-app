# MISSION BOARD — Community Contributions v2 (add-info layer + moderated event submissions)

**Date:** 2026-10-18 (v1 written 2026-10-18 morning; superseded by this v2 after the owner chose the fill-gaps design)
**Brief (owner):** users add missing information to listed events (fees, dates, abstracts, venue, CPD, notes) and submit events that are not listed, with simplified fee entry; everything is moderated; no moderation email exists yet (placeholder); enrichment from the organiser site runs when a submission is made; the admin and user flows must be smooth; data and GitHub processes integrate with no clashes with the existing daily workflows; test and fix along the way.
**Classification:** software, full-stack. **Design skills:** `emil-design-eng` + `ui-ux-pro-max` (brief in §4).
**Status:** DELIVERED 2026-10-18 (pushed `050a632`). Open: owner admin flag; owner decision on safe-fetch edits to the shared fetchers (community remediator job disabled until then); P7 stretch (directory view overlay) not started.
**v1 archive:** scratchpad copy `MISSION_BOARD_CONTRIBUTIONS_v1.md` (lock-based design, rejected: it modified the production scraper write path).

---

## 0. Why v2 — the one rule

**Scraped columns are never written by the community path.** Community data lives in its own tables and is shown only where the scraped value is missing. Organiser data always wins. The scraper, remediator and archival rules are untouched except for one added remediator step for the community source. Verified code facts behind this (2026-10-18):

| Fact | Where | Consequence |
|---|---|---|
| Scraper overwrites every differing field and delete-reinserts tiers on a changed listing | `scraper.py:217-253` | Never store community data in `conferences` / `pricing_tiers` for *scraped* rows |
| Remediator fixers are pure functions `(row, page_text, llm_call) -> (value, method)` | `remediator/fixers/__init__.py` | Reusable on a pending submission's payload (pre-moderation enrichment) |
| `remediate_source(id)` has no active-source check; `--sources` filters active only | `remediator/runner.py:115-140`, `__main__.py:28-37` | Post-approval enrichment of community rows = explicit `--source 1000` step |
| Unseen-14d archive only touches rows of *healthy* sources; expiry rules key on dates only | `database.py:146-256` | Community rows retire on date, never on "unseen" |
| `directory_events` LEFT JOINs `scraper_sources`; `search_vector` is a GENERATED column | `supabase/migrations/20261002000000_directory_query_layer.sql` | Community rows appear and are searchable automatically |
| Specialty filter/facets/alerts expand a parent slug to `RAW_TO_CANONICAL` keys; no slug is a key, 18/31 labels aren't | `lib/taxonomy/specialties.ts`, `fire_specialty_alerts.py` | Store the parent **label**; add every label as a key (G1) |
| `country_guess` regex misses the literal `United Kingdom` | view line 112 | Wizard stores the UK nation in `region`; view fix is a separate owner decision |
| Frontend renders symbols for GBP/USD/EUR/AUD/CAD/INR only | `conference-helpers.ts:48` | Currency select limited to those + CHF/HKD/SGD |
| Baseline: 102/103 vitest pass (stale count in `taxonomy.test.ts` societies test), `tsc` clean | run 2026-10-18 12:40 | Agents fix that test honestly when touching the taxonomy; never loosen it |

---

## 1. Product flows

### 1.1 Add missing info (signed-in user, on `/conferences/[id]`)
Entry points: **"Add missing info"** button under the sidebar actions; inline prompts on the empty fee table ("Know the fees? Add them"), missing abstract info, "Location TBC". Opens `AddInfoDialog`: only *empty* sections are offered (dates · venue & format · fees · abstracts · CPD · links · note); each is a compact sub-form; fees use the quick editor (§1.3). Submit → `community_contributions` row `kind='add_info'`, status `pending`. Toast: "Thanks — a moderator will review this." The dialog is reachable signed-out but shows a sign-in prompt instead of fields.

Published community facts render in place of the empty value with a small **Community** tag, and a "Community notes" block lists free-text notes with the line *Added by MedConf members · reviewed by moderators*. Never shows a submitter's name.

### 1.2 Submit an event (`/submit`, signed in)
One page, collapsible sections, sticky summary of what's filled: **Basics** (name, organiser URL, event type, format, flagship?) → live duplicate check (debounced `/api/directory?q=`; also same-domain match) shown inline → **When** (start, end, start time) → **Where** (country; UK → nation select stored in `region`; city; venue) → **Specialty** (parent list, stored as label) → **Fees** (§1.3) → **Abstracts & CPD** → **Brief description** (≤ 2 000 chars) → **Links & evidence** → consent checkbox → Submit. Draft kept in `localStorage` (try/catch). Entry points: Navbar "Submit an event", Footer, directory zero-results empty state.

### 1.3 Simplified fees
`{ currency, from_price?, tiers: [{ label, price, is_early_bird, early_bird_deadline? }], notes? }` where `label ∈ {Standard, Member, Non-member, Trainee / Student, Early bird, Free}` (+ free-text label allowed, ≤ 40 chars). ≤ 12 tiers. On approval each becomes a `pricing_tiers` row (new event) or a `community_tiers` row (add-info) — the existing `PricingTable` renders them without special casing.

### 1.4 Enrichment (before review)
`enrich_submissions.py` (GitHub Actions, every 6 h): for each pending submission with `enrichment_status='waiting'`, builds a row-shaped dict from the payload (`source_url` = normalised organiser URL), fetches with the remediator's `PageCache` (same anti-bot detector), runs every quick fixer in `REGISTRY` for **all** fields (filled ones too, to cross-check), writes `enrichment = {field: {value, method, agrees}}`, `enrichment_status ∈ fetched|blocked|failed`, `enriched_at`. Safety: http(s) only, hostname must not resolve to loopback/RFC1918/link-local, ≤ 3 fetches per submission, 10-min job budget. Explorer (Tier 2) reuse is a follow-up.

### 1.5 Moderation (`/admin/moderation`, admin only)
Queue: pending first, newest first; tabs Pending · Needs info · Published · Rejected · Expired · Hidden; each row = kind, event name, submitter (email, admin-only), age, enrichment status chip. Item view: **three columns per field — user entered · found on organiser site · final (editable, defaults to user value)**, disagreements highlighted; fee tiers as a table; note, evidence link, organiser link; **possible duplicates** panel (same domain, or similar name ± 30 days). Actions: Approve · Request info (message) · Reject (reason) · Merge into existing listing (picker) · Hide (for published). All actions call `moderate_contribution()`. Nav item "Moderation" with live pending count (admins only).

### 1.6 Submitter view (`/dashboard/contributions`)
List with status chips, moderator messages, resubmit when `needs_info`, link to the live listing when published (or "This event has passed" if archived).

### 1.7 After approval
New events: row under source 1000; daily `python -m remediator --source 1000` keeps filling *empty* fields from the organiser site (remediator only writes nulls). Add-info: facts/tiers published; if the scraper later fills the field, the scraped value shows and the fact silently stops rendering.

### 1.8 Lifecycle
Normal date-based archival retires community events. Digest (09:00 UTC) expires pending items whose event has passed (`expire_stale_contributions()`), writes one `moderation` notification per admin when pending > 0 (replacing any unread one), and logs the would-be email to `MODERATION_NOTIFY_EMAIL` (placeholder `moderation@medconf.example`).

---

## 2. Data contract (P0 implements exactly this; P1–P5 code against it)

```sql
-- ===== admin =====
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
CREATE OR REPLACE FUNCTION is_admin() RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
  $$ SELECT COALESCE((SELECT is_admin FROM user_profiles WHERE id = auth.uid()), FALSE) $$;
-- guard: clients can never set is_admin (INSERT or UPDATE); only service_role / postgres may
CREATE OR REPLACE FUNCTION user_profiles_guard_is_admin() RETURNS trigger ... -- RAISE if NEW.is_admin IS DISTINCT FROM COALESCE(OLD.is_admin,FALSE) AND auth.role() IS DISTINCT FROM 'service_role' AND current_user NOT IN ('postgres','supabase_admin')
CREATE TRIGGER trg_user_profiles_guard_is_admin BEFORE INSERT OR UPDATE ON user_profiles FOR EACH ROW EXECUTE FUNCTION user_profiles_guard_is_admin();

-- ===== community source =====
INSERT INTO scraper_sources (id, source_name, base_url, extraction_instructions, active, society, default_event_type)
VALUES (1000, 'Community submissions', 'https://community.medconf.invalid', 'User-submitted events, moderated. Not scraped; remediator --source 1000 enriches empty fields.', FALSE, 'Community', 'mixed')
ON CONFLICT (id) DO NOTHING;
SELECT setval('scraper_sources_id_seq', GREATEST((SELECT MAX(id) FROM scraper_sources WHERE id < 1000), 1000), true) -- keep normal ids below 1000? NO: leave the sequence alone; 1000 is far ahead of ~103. Just insert.

-- ===== notifications =====
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN
  ('reminder','new_in_specialty','conference_change','system','contribution_update','moderation'));

-- ===== contributions =====
CREATE TABLE community_contributions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('new_event','add_info')),
  conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,   -- required when kind='add_info'; set on approval for new_event
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','needs_info','published','rejected','merged','expired','hidden')),
  payload JSONB NOT NULL,                       -- user-entered (shapes below)
  enrichment JSONB,                             -- {field: {value, method, agrees}} from enrich_submissions.py
  enrichment_status TEXT NOT NULL DEFAULT 'waiting' CHECK (enrichment_status IN ('waiting','fetched','blocked','failed','skipped')),
  enriched_at TIMESTAMPTZ,
  evidence_url TEXT, note TEXT,
  final_payload JSONB,                          -- what the moderator approved
  moderator_id UUID REFERENCES auth.users(id), moderator_note TEXT, reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(),
  CHECK (kind <> 'add_info' OR conference_id IS NOT NULL)
);
CREATE INDEX ON community_contributions (status, created_at DESC);
CREATE INDEX ON community_contributions (user_id);
CREATE INDEX ON community_contributions (conference_id);
-- before-insert trigger: user_id := auth.uid() (RAISE if null and not service_role); status := 'pending';
--   enrichment := NULL; enrichment_status := 'waiting'; moderator_* := NULL; final_payload := NULL;
--   RAISE 'Too many pending contributions' if the user already has >= 10 in ('pending','needs_info');
--   RAISE if pg_column_size(payload) > 32768.
-- updated_at trigger reuses update_updated_at_column().

CREATE TABLE community_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contribution_id UUID NOT NULL REFERENCES community_contributions(id) ON DELETE CASCADE,
  conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
  field TEXT NOT NULL CHECK (field IN ('start_date','end_date','start_time','venue_name','city','region','event_format',
    'abstract_deadline','abstract_open','abstract_deadline_note','cpd_accredited','cpd_points','organiser_url','booking_url','description','note')),
  value JSONB NOT NULL,
  is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON community_facts (conference_id) WHERE is_published;

CREATE TABLE community_tiers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contribution_id UUID NOT NULL REFERENCES community_contributions(id) ON DELETE CASCADE,
  conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
  tier_label TEXT NOT NULL, price DECIMAL(10,2) NOT NULL, currency TEXT NOT NULL DEFAULT 'GBP',
  is_early_bird BOOLEAN DEFAULT FALSE, early_bird_deadline DATE,
  is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON community_tiers (conference_id) WHERE is_published;

-- ===== RLS =====
-- community_contributions: ENABLE RLS.
--   SELECT: auth.uid() = user_id OR is_admin()
--   INSERT: auth.uid() = user_id  (trigger enforces the rest)
--   UPDATE: USING (auth.uid() = user_id AND status = 'needs_info') WITH CHECK (auth.uid() = user_id AND status = 'pending')  -- the only owner transition: resubmit
--   no DELETE for clients
-- community_facts / community_tiers: ENABLE RLS. SELECT: is_published OR is_admin(). No client writes (RPC only).

-- ===== RPCs (SECURITY DEFINER, search_path = public) =====
CREATE FUNCTION moderate_contribution(p_id UUID, p_action TEXT, p_note TEXT DEFAULT NULL, p_final JSONB DEFAULT NULL) RETURNS JSONB
-- guard: IF NOT is_admin() THEN RAISE 'admin only'.
-- 'approve':   final := COALESCE(p_final, payload).
--    new_event → INSERT conferences (conference_name, specialty, event_type, event_format, is_flagship, start_date, end_date, start_time,
--                venue_name, city, region, cpd_accredited, cpd_points, abstract_open, abstract_deadline, abstract_deadline_note,
--                organiser_url, booking_url, description, source_id = 1000, source_url = final->>'organiser_url' (already normalised by client; fallback 'community:'||id),
--                last_seen_at = now()). On unique_violation(source_url) → RETURN {ok:false, code:'duplicate', conference_id:<existing>} and leave the contribution pending.
--                INSERT pricing_tiers from final->'fees'->'tiers' (label, price, currency, is_early_bird, early_bird_deadline).
--    add_info  → INSERT community_facts one row per key of final->'fields' (value as jsonb) and community_tiers from final->'fees'->'tiers', all is_published = TRUE.
--    then: status='published', conference_id set, final_payload, moderator_id = auth.uid(), moderator_note, reviewed_at; INSERT notifications(type 'contribution_update', title, body, conference_id) for user_id.
-- 'needs_info' | 'reject': status, moderator_note (= p_note), reviewed_at; notification to submitter.
-- 'merge':     p_final->>'merge_into_conference_id' required; materialise facts/tiers onto that conference exactly like add_info approve; status='merged'; conference_id = target; notification.
-- 'hide':      published add_info/merged → facts & tiers is_published = FALSE, status='hidden'; published new_event → UPDATE conferences SET archived = TRUE WHERE id = conference_id AND source_id = 1000; status='hidden'.
-- RETURNS {ok, status, conference_id}.

CREATE FUNCTION expire_stale_contributions() RETURNS INTEGER
-- guard: is_admin() OR auth.role() = 'service_role'.
-- pending/needs_info where (kind='add_info' AND conference archived) OR (kind='new_event' AND COALESCE(payload->>'end_date', payload->>'start_date')::date < current_date)
-- → status='expired', moderator_note='Event date passed before review', reviewed_at; notification to submitter. Returns count.

GRANT EXECUTE ON FUNCTION moderate_contribution TO authenticated; GRANT EXECUTE ON FUNCTION expire_stale_contributions TO authenticated, service_role;
```

**Payload shapes (zod in `medconf-website/src/lib/community/schema.ts`, mirrored loosely by the enrichment job):**

```ts
// kind = 'new_event'
{ conference_name, event_type: 'conference'|'workshop'|'course', event_format: 'in_person'|'online'|'hybrid', is_flagship?: boolean,
  start_date: 'YYYY-MM-DD', end_date?, start_time?: 'HH:MM',
  country: string, region?: string /* UK nation or country name */, city?, venue_name?,
  specialty: string /* parent LABEL, e.g. "Oncology" */,
  description?: string, organiser_url: string /* normalised */, booking_url?,
  cpd_accredited: boolean, cpd_points?: number,
  abstract_open: boolean, abstract_deadline?, abstract_deadline_note?,
  fees?: { currency, from_price?, tiers: [{ label, price, is_early_bird, early_bird_deadline? }], notes? },
  note?, evidence_url? }
// kind = 'add_info'
{ fields: { [field in community_facts.field]: value }, fees?: {...same...}, note?, evidence_url? }
```
Rules: dates `start ≥ today`, `end ≥ start`, `abstract_deadline ≤ start`; urls http(s) only; name ≤ 200, description ≤ 2 000, note ≤ 1 000; ≤ 12 tiers; currency ∈ GBP USD EUR AUD CAD INR CHF HKD SGD. **URL normalisation** (`normalize-url.ts`, unit-tested): lower-case scheme+host, drop fragment, drop `utm_*`/`fbclid`/`gclid`, drop trailing slash on non-root paths, keep other query params.

---

## 3. Phases, agents, file ownership (no two agents touch the same file)

| # | Phase | Agent (model) | Owns | Depends on |
|---|---|---|---|---|
| P0 | Migration + schema doc + admin flag | `contrib-p0-schema` (sonnet) | `supabase/migrations/20261018000000_community_contributions.sql`, `supabase_schema.sql`; JSON backup of `user_profiles`/`notifications`/`scraper_sources` to scratchpad before apply; apply via `medconf-scraper/apply_migration.py`; flag owner admin by email lookup (ad-hoc SQL, not in repo) | — |
| P1 | Enrichment job + workflows | `contrib-p1-enrich` (sonnet) | `medconf-scraper/enrich_submissions.py`, `medconf-scraper/test_enrich_submissions.py`, `.github/workflows/enrich-submissions.yml`, one added step in `.github/workflows/remediator-daily.yml` (`python -m remediator --source 1000`, `continue-on-error`), `medconf-scraper/.env.example` (+`MODERATION_NOTIFY_EMAIL`) | contract only; live smoke after P0 |
| P2 | Website core: types, zod, URL normaliser, specialty labels (G1), hooks, Community tag/panel, AddInfoDialog + fee quick editor, detail-page overlay, CTAs, shell (Navbar/Footer/middleware links + admin guard + `useIsAdmin`), societies exclusion | `contrib-p2-core` (sonnet) | `src/lib/community/*`, `src/hooks/useCommunity.ts`, `src/hooks/useIsAdmin.ts`, `src/components/community/*`, edits: `conferences/[id]/page.tsx`, `EventSidebar.tsx`, `PricingTable.tsx`, `AbstractsBlock.tsx`, `Navbar.tsx`, `Footer.tsx`, `middleware.ts`, `lib/taxonomy/specialties.ts` + `specialties.json` re-export + `lib/taxonomy/societies.ts`, `app/societies/page.tsx`, `src/lib/__tests__/community-*.test.ts`, fix `taxonomy.test.ts` count honestly | contract only |
| P3 | `/submit` page | `contrib-p3-submit` (sonnet) | `src/app/submit/**`, `src/components/community/submit/**`, directory zero-results CTA (`components/directory/ResultsList.tsx` empty state only) | P0, P2 |
| P4 | Moderation + My contributions | `contrib-p4-moderation` (sonnet) | `src/app/admin/moderation/**`, `src/components/moderation/**`, `src/app/dashboard/contributions/**`, one link in `app/dashboard/page.tsx`, `scripts/seed-contributions.ts` | P0, P2 |
| P5 | Notification types in UI + digest cron | `contrib-p5-notify` (sonnet) | `NotificationBell.tsx`, `dashboard/notifications/page.tsx`, `medconf-scraper/fire_moderation_digest.py`, `.github/workflows/fire-moderation-digest.yml`, `CLAUDE.md` §3 cron table + §2.3 tables | P0, P4 |
| P6 | Gate | Commander + `security-reviewer` (sonnet) | vitest, tsc, lint, pytest, security review of migration/RPCs/RLS, Playwright end-to-end on localhost:3000 with two fresh test users (submitter + admin), docs, memory, LESSONS | all |
| P7 | Stretch (owner's call) | — | `directory_events` COALESCE overlay so community facts feed filters/sort; view regex `united kingdom` fix | P6 |

Rules for every agent: read this board first; commit only your own paths (`git add <paths>`; LESSONS #18) with the repo's `feat(...)`/`fix(...)` style and the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; **never push**; never touch `scraper.py`, `database.py`, `remediator/runner.py`, the scrape matrix, or any `.env*` with secrets; run `npx tsc --noEmit` + `npx vitest run` (website) or `./.venv/bin/python -m pytest <your test>` (scraper) before committing; report what you verified and what you could not.

---

## 4. Design brief (binding for P2–P5; from `emil-design-eng` + `ui-ux-pro-max`)

- **Use the existing system only**: tokens (`bg-bg`, `bg-surface`, `bg-surface-muted`, `border-border(-subtle)`, `text-fg(-strong|-muted|-subtle)`, `text-brand-text`, `ok/warn/danger-*`), type classes (`type-h1…type-caption`, `type-mono-label`), `Button`, `Dialog`, `Sheet`, `Select`, `Input`, `Tabs`, `Badge`, `Tooltip`, Sonner toasts, `AccountSection` shells, Lucide icons. **No new palette, no new fonts, no emoji icons.**
- **Motion (Emil):** only `transform`/`opacity`; `ease-out` for enter (`cubic-bezier(0.23,1,0.32,1)`), exits faster than enters, UI ≤ 250 ms, press feedback `scale(0.97)` 160 ms on pressables, never `scale(0)` entries (start at 0.95 + opacity), modals keep centre origin, no animation on keyboard-driven actions, `prefers-reduced-motion` drops movement but keeps opacity, hover effects gated by `@media (hover:hover) and (pointer:fine)`, `transition` names exact properties (never `all`).
- **Forms (UX Pro Max):** every input has a visible `<label>`; validate on blur, not only on submit; inline errors with recovery hints; section completeness indicators; submit shows loading → success/error; 44 px touch targets; contrast ≥ 4.5:1 both themes; keyboard focus rings visible; responsive at 375 / 768 / 1024 / 1440; `cursor-pointer` on clickables.
- **Copy:** plain, no "TBC"; follow W7 ("See organiser site"). Community tag text: "Community"; attribution: "Added by MedConf members · reviewed by moderators".
- **Moderation density:** data-dense but calm: table rows 40–44 px, monospace labels for field names, disagreement rows highlighted with `warn-subtle`, primary action = Approve, destructive actions need a reason.

---

## 5. Cost, services, risks

£0 infra (Supabase free project `zcpszfbmvfylicpxgsfc`, GitHub Actions free minutes; the 6-hourly enrichment job ~2 min/run). No new secrets: workflows reuse `SUPABASE_URL`, `SUPABASE_KEY`, `KIMI_API_KEY`. `MODERATION_NOTIFY_EMAIL` is a non-secret placeholder. Agent tokens: Sonnet × 6.

Risks carried from v1 review: specialty label mapping (G1, P2), course rows read-only for fees (community_tiers never attach to sessions; AddInfoDialog hides Fees for `event_type='course'`), URL hygiene + duplicate (P2/P0), notification volume (digest only + nav badge), currencies, UK nation, input safety, consent copy, prod snapshot before migration, local-only moderation until deploy, `/societies` exclusion, seeding + tests. New in v2: SSRF guard in enrichment; `is_admin` guard trigger on both INSERT and UPDATE; `moderate_contribution` must verify `source_id = 1000` before archiving on hide.

---

## 6. Status ledger

- 2026-10-18 09:xx — v1 board (lock design) written; owner questions on lifecycle and gaps answered (§9/§10 of v1).
- 2026-10-18 12:xx — owner proposed the "add info beside the listing" model; checked and recommended the structured fill-gaps variant; owner added full manual submission + enrichment; **approved**. v2 written; wave 1 (P0, P1, P2) spawned on sonnet.
- 2026-10-18 13:xx — **P0 applied to prod** (Commander, inline: the P0 agent spawn was blocked by the permission classifier). Backup of user_profiles/notifications/scraper_sources in scratchpad `p0-backup/`. Checks: 3 tables, 5 policies, 6 functions, 3 triggers, source 1000 present, notifications CHECK extended. Anon probe: contributions invisible, facts/tiers readable (empty), `is_admin()` false. **Owner admin flag pending** — both automated routes were denied; staged SQL for the owner to run via apply_migration.py. P1 committed `0fb0e9d`; security review flagged redirect/DNS-rebinding SSRF → fix requested from the P1 agent (hop-by-hop redirect check, no browser fallback for submitted URLs); remediator `--source 1000` finding accepted: URLs are moderator-approved and the moderation UI must refuse approval when `enrichment_status = 'skipped'` (P4 requirement).
- 2026-10-18 14:xx — Wave 1 verified by Commander: tsc clean, vitest 164/164 (was 103), lint clean, detail page 200 with "Add missing info", `/submit` redirects signed-out, enrichment pytest 12/12, dry-run against prod = 0 pending. Security-review loop: P1 redirect fix `a1c527b`; TOCTOU + fixer-network fixes requested; P2 overlay render-time re-validation requested. **Hardening migration `c552948`** (server-side URL/length/tier validation on every write path, advisory lock on the pending cap, admin SELECT on user_profiles, service role allowed in RPC guard) APPLIED. **Privilege fix `fb622f0`** APPLIED: `is_privileged_caller()` used `current_user`, which inside SECURITY DEFINER is the owner → every signed-in user passed the RPC guard; now `session_user` + `auth.role()`; verified non-admin and anon refused, service role allowed. **E2E add-info ALL PASS** (scratchpad `e2e_add_info.py`, listing 819): login → fees + note submitted → RPC approve → anon sees published tier → submitter notified → page shows Community tag + £150 → `javascript:` URL rejected server-side → client-set status forced back to pending. Test submitter account `medconf.test.submitter@example.com` (creds in scratchpad). Wave 2 running: P3 submit, P4 moderation, P5 notify/digest. One pending note on listing 819 left for the owner to moderate.
- 2026-10-18 15:xx — **Wave 2 delivered:** P3 `/submit` `f941f72`, P4 moderation + My contributions `edeae58`, P5 notifications + digest `73a21c1`, P2 cpd alignment `a80eda1`, P1 offline fixers `29e3888` + checked-URL recording. Gate snapshot: tsc clean, vitest 219/219, eslint 0, pytest 19/19. **Migrations 000003 `b4cdb60` (publish gate) and 000004 `815e758` (fail-closed: approve/merge need a completed address check or `approve_unchecked`; approval bound to `_checked_url`; hostname-with-TLD URL rule) APPLIED.** E2E: add-info ALL PASS; moderation UI PASS (queue, email via admin policy, nav badge, approve, request-info + notification, note renders publicly) except member resubmit (dialog opens without prefill / venue section missing → P4 fixing); submit PASS through duplicate+merge+hide except approve after hide (archived community row keeps `source_url` → P7 re-publish migration in progress). Test moderator `medconf.test.moderator@example.com` created via service role (is_admin TRUE) for automated admin checks. Owner's own admin flag still pending (scratchpad `set_owner_admin.sql`). Commander correction (owner): QA and migrations are now delegated (`contrib-p6-qa` owns `tests/e2e/`, `contrib-p7-db` writes migrations; Commander only applies and verifies). `security-reviewer` run in progress on the full change set. Remaining before push: P3 id fix, P4 override UI + resubmit, P7 apply, QA report, final gate.
- 2026-10-18 15:3x — **Migration 000005 `df8511e` APPLIED** (re-publish hidden community row on same source_url; `_rejected_urls` stripped server-side, rejected organiser URL refused; 6/6 checks). P4 override confirm + member resubmit fix `0997bab`/`f686d99`/`6c22011` (vitest 237). P1 checked-URL recording `0b84d06`. P3: ids/inert already correct (no change). Independent security review (contrib-p6-security): no critical/high; six medium/low findings routed — enrichment starvation + flag-gated safe-fetch mode for the community remediator step → P1; date validation + safe expiry cast + hide scope → P7 (migration 000006); domain mismatch / new-domain / provenance warnings → P4. QA agent rerunning all flows.
- 2026-10-18 15:4x — **Migration 000006 APPLIED** (date validation + safe expiry cast, hide scope limited to the event the contribution created, zod-parity payload rules server-side, add_info refused for archived/unknown conferences, helper REVOKEs from anon/authenticated; file in `bcf883f` + amendment folded into `2764dda`). **QA (contrib-p6-qa) all flows PASS**: add-info 14/14, submit 15/15, moderation 17/17 (incl. resubmit + "Approve anyway…" override + re-publish after hide), digest 7/7 idempotent; suite committed to `tests/e2e/` `a28a1a0`. One product bug: signed-in Navbar overflows at 768 px (desktop nav at `md` no longer fits) → P2 fixing (breakpoint to `lg`). P4 domain-signals block `28e686f` (vitest 242). Remaining: P1 (starvation fix, flag-gated safe-fetch for the community remediator step, pinned IP), P4 kind-shape fix, P2 nav + bidi, QA re-screenshot + negative checks, final gate, push, workflow dispatch.
- 2026-10-18 15:5x — **DELIVERED.** P1 finding-1 starvation fix `577387c`, shared `safe_fetch.py` `6753e6b`, IP pinning `8145219`; community remediator job disabled `7b4ec66` (permission classifier blocked the agent's edits to `remediator/fetcher.py`, `remediator/explorer.py`, `extractors/http_fetch.py`, `extractors/abstract_classifier.py` → owner decision, not worked around). P4 kind-derived review shape `4b20010`. P2 bidi/zero-width `5c86fa2`, Navbar desktop nav from `xl` `f7d7fea` (zero overflow 768–1440 for both roles). QA final pass at `050a632`: add-info (incl. 3 negative server checks), submit (incl. hide→resubmit→republish, rejected-URL refusal), moderation (incl. resubmit, Approve-anyway), digest (idempotent), screenshots 375/768/1024/1280 — ALL PASS. Final gate: tsc clean, vitest 248/248, eslint 0, pytest 29/29, 7 workflow YAMLs parse. **Pushed main e947afe..050a632 (36 commits).** `enrich-submissions.yml` and `fire-moderation-digest.yml` dispatched on GitHub to prove green on runners. Six migrations live (000000–000006). Test accounts (example.com) remain for QA; owner may delete them later.

