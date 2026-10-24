-- MedConf Supabase Database Schema
-- Run this in your Supabase SQL editor to set up all tables

-- ============================================
-- SCRAPER TABLES
-- ============================================

-- Table: scraper_sources
-- Registry of websites to scrape for conference data
CREATE TABLE IF NOT EXISTS scraper_sources (
    id SERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    base_url TEXT NOT NULL UNIQUE,
    extraction_instructions TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    last_scraped_at TIMESTAMPTZ,
    last_status TEXT,
    pagination_type TEXT DEFAULT 'single_page' CHECK (pagination_type IN ('single_page','page_query','next_link','infinite_scroll')),
    pagination_template TEXT,
    max_pages_hint INTEGER,
    last_full_walk_at TIMESTAMPTZ,
    -- TRUE when a source's detail "page" is actually the homepage of a small
    -- subsite (info split across /tickets, /programme, /abstracts, etc).
    -- Triggers browser.fetch_multi_page_text() instead of single-page read.
    detail_is_multipage BOOLEAN DEFAULT FALSE,
    -- Hint to the scraper for which event_type the source primarily emits.
    -- Per-source extractors can override per row; this just sets the default.
    -- Short organisation label (e.g. "RCEM", "RCSEng") used to fold
    -- multiple sources from the same society into a single chip on the
    -- directory's source filter row.
    society TEXT,
    default_event_type TEXT NOT NULL DEFAULT 'conference'
        CHECK (default_event_type IN ('conference','workshop','course','mixed')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table: scraper_logs
-- Detailed logs of each scraper run
CREATE TABLE IF NOT EXISTS scraper_logs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES scraper_sources(id) ON DELETE CASCADE,
    run_started_at TIMESTAMPTZ NOT NULL,
    run_ended_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    conferences_found INTEGER DEFAULT 0,
    conferences_inserted INTEGER DEFAULT 0,
    conferences_updated INTEGER DEFAULT 0,
    errors_encountered INTEGER DEFAULT 0,
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CONFERENCE TABLES
-- ============================================

-- Table: conferences
-- Core conference information
CREATE TABLE IF NOT EXISTS conferences (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES scraper_sources(id) ON DELETE SET NULL,
    listing_hash TEXT,
    last_seen_at TIMESTAMPTZ,
    last_detail_at TIMESTAMPTZ,
    conference_name TEXT NOT NULL,
    specialty TEXT,
    start_date DATE,
    end_date DATE,
    start_time TIME,
    venue_name TEXT,
    city TEXT,
    region TEXT,
    event_format TEXT CHECK (event_format IS NULL OR event_format IN ('in_person', 'online', 'hybrid')),
    is_sold_out BOOLEAN DEFAULT FALSE,
    cpd_accredited BOOLEAN DEFAULT FALSE,
    cpd_points INTEGER,
    abstract_open BOOLEAN DEFAULT FALSE,
    -- Curator-set free text shown in place of the date when an organiser
    -- confirms abstract submissions are open but hasn't published a deadline
    -- (e.g. "see event page for details"). When NULL, the date governs.
    abstract_deadline_note TEXT,
    abstract_deadline DATE,
    -- Remediator round-robin stamp (when the last remediation attempt started)
    remediation_attempted_at TIMESTAMPTZ,
    organiser_url TEXT,
    booking_url TEXT,
    source_url TEXT UNIQUE NOT NULL,
    description TEXT,
    -- Three-way classification:
    --   'conference' — multi-day scheduled event with talks (default)
    --   'workshop'   — single-session practical learning event (CPD courses,
    --                  webinars, training sessions)
    --   'course'     — recurring offering with multiple bookable session dates
    --                  (see course_sessions for the per-date rows)
    event_type TEXT NOT NULL DEFAULT 'conference'
        CHECK (event_type IN ('conference','workshop','course')),
    -- On-demand catch-up content. When TRUE the event is a recording of a past
    -- live session that users can register to watch until the access deadline.
    -- start_date holds the access deadline (so the row ages out of the directory
    -- after it expires); on_demand_original_date is the date the live session
    -- actually ran (informational, surfaced in the UI as "Originally aired …").
    is_on_demand BOOLEAN NOT NULL DEFAULT FALSE,
    on_demand_original_date DATE,
    -- International / national flagship conference (Annual Conference,
    -- World Congress, etc). Distinct from regional/local events which
    -- keep event_type='conference' but is_flagship=FALSE. Drives the
    -- Major / Regional split on the directory's type filter.
    is_flagship BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table: course_sessions
-- One row per scheduled run of a course. A course parent row in conferences
-- (event_type = 'course') has many of these; each session has its own date
-- range, availability state, and optionally its own booking URL and pricing.
-- Conferences (event_type = 'conference') do not use this table.
CREATE TABLE IF NOT EXISTS course_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    end_date DATE,
    start_time TEXT,
    -- Free text when the source publishes duration as words rather than a
    -- precise date span (e.g. "3 days", "Half day", "6 evenings").
    duration_text TEXT,
    -- Source-truth booking status for THIS specific session
    availability_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (availability_status IN ('available','limited','sold_out','unknown')),
    -- Only set when the source publishes a number ("Only 3 spots left")
    spots_left INTEGER,
    -- Some sources expose a different booking URL per session
    booking_url TEXT,
    -- Per-session venue. Many course sources run the same course at multiple
    -- regional centres, so we keep these on the session rather than the parent.
    -- Parent (conferences) row's venue/city/region stays null when sessions vary.
    venue_name TEXT,
    city TEXT,
    region TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_course_sessions_course ON course_sessions(course_id);
CREATE INDEX IF NOT EXISTS idx_course_sessions_start_date ON course_sessions(start_date);
CREATE INDEX IF NOT EXISTS idx_course_sessions_status ON course_sessions(availability_status);
CREATE INDEX IF NOT EXISTS idx_course_sessions_city ON course_sessions(city);

-- Table: pricing_tiers
-- Conference / course pricing information (multiple tiers per parent).
-- For courses with FLAT pricing across all sessions, session_id IS NULL.
-- For courses with per-session pricing (e.g. early-bird per session),
-- session_id references a specific course_sessions row.
CREATE TABLE IF NOT EXISTS pricing_tiers (
    id SERIAL PRIMARY KEY,
    conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
    session_id UUID REFERENCES course_sessions(id) ON DELETE CASCADE,
    tier_label TEXT NOT NULL,
    -- `price_gbp` is a historical column name. The real currency for the
    -- amount is the `currency` column below; most rows are GBP (the
    -- default) but international events (RCOG World Congress, etc.) can be
    -- USD/EUR/etc.
    price_gbp DECIMAL(10,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    is_early_bird BOOLEAN DEFAULT FALSE,
    early_bird_deadline DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pricing_tiers_session ON pricing_tiers(session_id);
CREATE INDEX IF NOT EXISTS idx_conferences_event_type ON conferences(event_type);

-- ============================================
-- USER TABLES
-- ============================================

-- Table: user_profiles
-- Extended user information beyond Supabase auth
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT,
    role TEXT,
    specialty TEXT,
    region TEXT,
    institution TEXT,
    country TEXT DEFAULT 'United Kingdom',
    -- NULL = onboarding wizard not yet completed. Route guard uses this
    -- to bounce signed-in users to /onboarding until they finish the
    -- 3-step wizard. Set on the final wizard step's submit.
    profile_completed_at TIMESTAMPTZ,
    -- Watermark for the "new in your specialty" daily alerts cron.
    -- Each run finds conferences created AFTER this timestamp matching
    -- the user's specialty, fires one batched notification, and advances
    -- the watermark. Stamped to NOW() on onboarding completion so new
    -- users only get alerted about events added after they joined
    -- (rather than every match in the catalogue).
    last_specialty_alert_at TIMESTAMPTZ,
    -- Moderator flag for /admin/moderation. Only the service role / DB
    -- owner may set it (trg_user_profiles_guard_is_admin); clients that
    -- try are rejected. See COMMUNITY CONTRIBUTIONS below.
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_profiles_role ON user_profiles(role);
CREATE INDEX IF NOT EXISTS idx_user_profiles_profile_completed ON user_profiles(profile_completed_at);

-- Table: saved_conferences
-- User's saved/bookmarked conferences
CREATE TABLE IF NOT EXISTS saved_conferences (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, conference_id)
);

-- Table: notification_preferences
-- User notification settings
CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email_new_conferences BOOLEAN DEFAULT TRUE,
    email_abstract_deadlines BOOLEAN DEFAULT TRUE,
    email_price_changes BOOLEAN DEFAULT FALSE,
    email_frequency TEXT DEFAULT 'weekly',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- pgcrypto provides gen_random_uuid() used below.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Table: user_reminders
-- Reminders a user has set on a saved conference. The daily reminder
-- cron looks for rows where scheduled_for <= today AND status = 'scheduled',
-- creates a notification row, and marks the reminder as sent.
CREATE TABLE IF NOT EXISTS user_reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    reminder_type TEXT NOT NULL CHECK (reminder_type IN ('abstract_deadline','conference_start','registration_deadline')),
    lead_time_days INTEGER NOT NULL,
    target_date DATE NOT NULL,
    scheduled_for DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','sent','cancelled')),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, conference_id, reminder_type, lead_time_days)
);
CREATE INDEX IF NOT EXISTS idx_user_reminders_user ON user_reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_user_reminders_scheduled ON user_reminders(scheduled_for) WHERE status = 'scheduled';

-- Table: notifications
-- The in-app notification feed surfaced in the bell dropdown.
-- Only the cron (service role) writes here — there's no INSERT policy
-- for end users. Users can read/update/delete their own rows only.
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- 'contribution_update' = to a submitter about their community contribution;
    -- 'moderation' = daily pending-count digest to admins.
    type TEXT NOT NULL CHECK (type IN ('reminder','new_in_specialty','conference_change','system','contribution_update','moderation')),
    title TEXT NOT NULL,
    body TEXT,
    conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
    reminder_id UUID REFERENCES user_reminders(id) ON DELETE SET NULL,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON notifications(user_id, read_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user_id, created_at DESC);

-- ============================================
-- INDEXES
-- ============================================

-- Performance indexes for common queries
CREATE INDEX IF NOT EXISTS idx_conferences_specialty ON conferences(specialty);
CREATE INDEX IF NOT EXISTS idx_conferences_region ON conferences(region);
CREATE INDEX IF NOT EXISTS idx_conferences_start_date ON conferences(start_date);
CREATE INDEX IF NOT EXISTS idx_conferences_archived ON conferences(archived);
CREATE INDEX IF NOT EXISTS idx_conferences_is_sold_out ON conferences(is_sold_out);
CREATE INDEX IF NOT EXISTS idx_conferences_event_format ON conferences(event_format);
CREATE INDEX IF NOT EXISTS idx_conferences_source_id ON conferences(source_id);
CREATE INDEX IF NOT EXISTS idx_conferences_source_url ON conferences(source_url);
CREATE INDEX IF NOT EXISTS idx_conferences_abstract_deadline ON conferences(abstract_deadline) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_conferences_created_at ON conferences(created_at) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_pricing_tiers_conference ON pricing_tiers(conference_id);
CREATE INDEX IF NOT EXISTS idx_saved_conferences_user ON saved_conferences(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_conferences_conf ON saved_conferences(conference_id);
CREATE INDEX IF NOT EXISTS idx_scraper_logs_source ON scraper_logs(source_id);

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_conferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE conferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_tiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraper_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraper_logs ENABLE ROW LEVEL SECURITY;

-- ============================================
-- RLS POLICIES - USER PROFILES
-- ============================================

-- Users can view their own profile
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can insert their own profile
CREATE POLICY "Users can insert own profile"
    ON user_profiles FOR INSERT
    WITH CHECK (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- ============================================
-- RLS POLICIES - SAVED CONFERENCES
-- ============================================

-- Users can view their own saved conferences
CREATE POLICY "Users can view own saved conferences"
    ON saved_conferences FOR SELECT
    USING (auth.uid() = user_id);

-- Users can save conferences
CREATE POLICY "Users can save conferences"
    ON saved_conferences FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can delete their saved conferences
CREATE POLICY "Users can delete own saved conferences"
    ON saved_conferences FOR DELETE
    USING (auth.uid() = user_id);

-- ============================================
-- RLS POLICIES - NOTIFICATION PREFERENCES
-- ============================================

-- Users can view their own notification preferences
CREATE POLICY "Users can view own notification preferences"
    ON notification_preferences FOR SELECT
    USING (auth.uid() = id);

-- Users can insert their own notification preferences
CREATE POLICY "Users can insert own notification preferences"
    ON notification_preferences FOR INSERT
    WITH CHECK (auth.uid() = id);

-- Users can update their own notification preferences
CREATE POLICY "Users can update own notification preferences"
    ON notification_preferences FOR UPDATE
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- ============================================
-- RLS POLICIES - USER REMINDERS (Owner-only)
-- ============================================

CREATE POLICY "Owner can select own user_reminders"
    ON user_reminders FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Owner can insert own user_reminders"
    ON user_reminders FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Owner can update own user_reminders"
    ON user_reminders FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Owner can delete own user_reminders"
    ON user_reminders FOR DELETE
    USING (auth.uid() = user_id);

-- ============================================
-- RLS POLICIES - NOTIFICATIONS (Owner read-only; cron writes via service key)
-- ============================================

CREATE POLICY "Owner can select own notifications"
    ON notifications FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Owner can update own notifications"
    ON notifications FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Owner can delete own notifications"
    ON notifications FOR DELETE
    USING (auth.uid() = user_id);
-- No INSERT policy — only the service role (reminder cron) creates notifications.

-- ============================================
-- RLS POLICIES - CONFERENCES (Public Read)
-- ============================================

-- Signed-in users can view non-archived conferences (access gate Phase 2, 2026-10-24; anon reads go through home_preview/event_preview)
CREATE POLICY "Authenticated can view conferences"
    ON conferences FOR SELECT TO authenticated
    USING (archived = FALSE);

-- ============================================
-- RLS POLICIES - PRICING TIERS (Public Read)
-- ============================================

-- Anyone can view pricing tiers
CREATE POLICY "Authenticated can view pricing tiers"
    ON pricing_tiers FOR SELECT TO authenticated
    USING (TRUE);

-- Anyone can view course sessions
CREATE POLICY "Authenticated can view course sessions"
    ON course_sessions FOR SELECT TO authenticated
    USING (TRUE);

-- ============================================
-- RLS POLICIES - SCRAPER TABLES (Admin Only via Service Key)
-- ============================================

-- Scraper sources: writes are admin-only (service key bypasses RLS).
CREATE POLICY "Scraper sources are admin only"
    ON scraper_sources FOR ALL
    USING (FALSE);

-- ...but the public site needs to read source names/base URLs to label
-- conference cards and build the source filter. This SELECT-only policy is
-- OR'd with the admin-only one above, so reads are public while writes stay
-- blocked. The table holds no secrets (API keys live in env / GH secrets).
-- NOTE: this was lost in the 2026-05 project migration and had to be re-added,
-- which is why source labels briefly disappeared from the cards.
CREATE POLICY "Authenticated can view scraper sources"
    ON scraper_sources FOR SELECT TO authenticated
    USING (TRUE);

-- Scraper logs: no public access (use service key)
CREATE POLICY "Scraper logs are admin only"
    ON scraper_logs FOR ALL
    USING (FALSE);

-- ============================================
-- SEED DATA - EXAMPLE SCRAPER SOURCES
-- ============================================

-- Insert example scraper sources (adjust URLs as needed)
INSERT INTO scraper_sources (source_name, base_url, extraction_instructions) VALUES
(
    'RCGP Events',
    'https://www.rcgp.org.uk/events',
    'Navigate to the events page. Find all upcoming medical conferences and CPD events. For each event, extract: name, dates, location, CPD points if mentioned, pricing tiers, and registration links.'
),
(
    'BMJ Events',
    'https://events.bmj.com/',
    'Browse the events listing. Extract all medical conferences with dates, locations, specialties, CPD information, and pricing details. Follow links to individual event pages for complete information.'
),
(
    'Royal Society of Medicine',
    'https://www.rsm.ac.uk/events/',
    'Navigate through the RSM events calendar. Extract conference details including specialty, dates, venue, CPD points, abstract submission deadlines, and registration fees for different attendee categories.'
)
ON CONFLICT (base_url) DO NOTHING;

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to automatically update updated_at timestamp
-- ============================================
-- COMMUNITY CONTRIBUTIONS (2026-10-18)
-- Full definitions (triggers, RLS, RPC bodies) live in
-- supabase/migrations/20261018000000_community_contributions.sql.
-- Rule: scraped columns are never written by the community path for
-- scraped rows; community data is overlaid only where the scraped value
-- is missing. New community events are ordinary conferences rows under
-- the inactive source 1000 ('Community submissions', society 'Community'),
-- enriched by `python -m remediator --source 1000`, never scraped.
-- Re-publish rule (20261018000005): approving a new_event whose organiser URL
-- matches an ARCHIVED source-1000 row (a hidden community event) updates and
-- un-archives that row and rebuilds its pricing_tiers instead of returning
-- 'duplicate'. Any other existing row with that source_url is still a duplicate.
-- Dates (20261018000006): community_validate_payload() requires real YYYY-MM-DD dates
-- (community_safe_date) and end >= start; expiry uses the safe cast. Hiding archives
-- the conferences row only for a 'published' new_event whose source_url this
-- contribution created; 'merged' items never archive their target.
-- Publish gate (20261018000007): approve/merge need enrichment->>'_submitted_url' (proof the address check ran) unless overridden.
-- ============================================

-- One row per user submission. kind='add_info' targets an existing
-- conference; kind='new_event' gets conference_id on approval.
CREATE TABLE IF NOT EXISTS community_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('new_event','add_info')),
    conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','needs_info','published','rejected','merged','expired','hidden')),
    payload JSONB NOT NULL,            -- user-entered; shapes in medconf-website/src/lib/community/schema.ts
    enrichment JSONB,                  -- {field: {value, method, agrees}} from enrich_submissions.py
    enrichment_status TEXT NOT NULL DEFAULT 'waiting'
        CHECK (enrichment_status IN ('waiting','fetched','blocked','failed','skipped')),
    enriched_at TIMESTAMPTZ,
    evidence_url TEXT,                 -- private, for the moderator
    note TEXT,                         -- private, for the moderator
    final_payload JSONB,               -- what the moderator approved
    moderator_id UUID REFERENCES auth.users(id),
    moderator_note TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (kind <> 'add_info' OR conference_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_community_contributions_status ON community_contributions (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_contributions_user ON community_contributions (user_id);
CREATE INDEX IF NOT EXISTS idx_community_contributions_conf ON community_contributions (conference_id);

-- Published overlay values for a scraped conference (shown only where the
-- scraped column is empty). Written by moderate_contribution() only.
CREATE TABLE IF NOT EXISTS community_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contribution_id UUID NOT NULL REFERENCES community_contributions(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    field TEXT NOT NULL CHECK (field IN ('start_date','end_date','start_time','venue_name','city','region','event_format',
        'abstract_deadline','abstract_open','abstract_deadline_note','cpd_accredited','cpd_points',
        'organiser_url','booking_url','description','note')),
    value JSONB NOT NULL,
    is_published BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_community_facts_conf_published ON community_facts (conference_id) WHERE is_published;

-- Community-provided fee tiers for a scraped conference (used when it has
-- no pricing_tiers). Never attached to course sessions.
CREATE TABLE IF NOT EXISTS community_tiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contribution_id UUID NOT NULL REFERENCES community_contributions(id) ON DELETE CASCADE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    tier_label TEXT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    is_early_bird BOOLEAN DEFAULT FALSE,
    early_bird_deadline DATE,
    is_published BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_community_tiers_conf_published ON community_tiers (conference_id) WHERE is_published;

-- Functions (bodies in the migration):
--   is_privileged_caller()  service role or DB owner
--   is_admin()              SECURITY DEFINER read of user_profiles.is_admin for auth.uid()
--   moderate_contribution(p_id, p_action, p_note, p_final) -> jsonb   admin only;
--       actions approve | needs_info | reject | merge | hide; approve of a
--       new_event inserts conferences (source_id 1000) + pricing_tiers and
--       returns {ok:false, code:'duplicate', conference_id} on a source_url clash
--   expire_stale_contributions() -> int   admin or service role; closes pending
--       items whose event date has passed
-- Triggers: trg_user_profiles_guard_is_admin (clients cannot set is_admin),
--   trg_community_contributions_before_insert (owner = auth.uid(), status pending,
--   max 10 pending per user, 32 KB payload cap),
--   trg_community_contributions_before_update (owner may only resubmit).
-- RLS: contributions SELECT owner or admin, INSERT owner, UPDATE owner only
--   needs_info -> pending; facts/tiers SELECT where is_published or admin;
--   no client writes on facts/tiers.
-- Seed: scraper_sources id 1000 'Community submissions' (active FALSE, society 'Community').
-- Hardening (20261018000001): community_url_ok()/community_validate_payload()
--   enforce http(s) URLs, length caps and <= 12 tiers on insert, resubmit,
--   approve, merge and publish_facts; the insert trigger takes a per-user
--   advisory lock so the pending cap cannot be raced; policy "Admins can view
--   profiles" on user_profiles; moderate_contribution() also accepts the
--   service role (automation / end-to-end tests).

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
CREATE TRIGGER update_conferences_updated_at
    BEFORE UPDATE ON conferences
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_notification_preferences_updated_at
    BEFORE UPDATE ON notification_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================
-- Remediator conditional tier insert (2026-10-24)
-- Inserts tiers only when none exist; serialised only against writers that take
-- the same conferences row lock (moderate_contribution does, database.py does not).
-- ============================================
CREATE OR REPLACE FUNCTION public.remediator_insert_tiers_if_empty(p_conference_id INTEGER, p_tiers JSONB)
RETURNS INTEGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
  t JSONB;
  n INTEGER := 0;
BEGIN
  PERFORM 1 FROM conferences WHERE id = p_conference_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;
  IF EXISTS (SELECT 1 FROM pricing_tiers WHERE conference_id = p_conference_id) THEN
    RETURN 0;
  END IF;
  FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(p_tiers, '[]'::jsonb)) LOOP
    IF NULLIF(t ->> 'tier_label', '') IS NULL OR NULLIF(t ->> 'price_gbp', '') IS NULL THEN
      CONTINUE;
    END IF;
    INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, is_early_bird, early_bird_deadline)
    VALUES (p_conference_id, t ->> 'tier_label', (t ->> 'price_gbp')::numeric,
            COALESCE(NULLIF(t ->> 'currency', ''), 'GBP'),
            COALESCE((t ->> 'is_early_bird')::boolean, FALSE),
            NULLIF(t ->> 'early_bird_deadline', '')::date);
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION public.remediator_insert_tiers_if_empty(INTEGER, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.remediator_insert_tiers_if_empty(INTEGER, JSONB) TO service_role;

-- ============================================
-- ACCESS GATE PHASE 2 (2026-10-24) - migration 20261024000001_access_gate_phase2.sql
-- Anonymous reads of directory data are closed. The four read policies above
-- are TO authenticated; community_facts/community_tiers read policies are
-- likewise TO authenticated (migration 20261018000000 section updated by the
-- Phase 2 migration) and anon SELECT on them is revoked.
-- Also revoked from anon: SELECT on directory_events (view) and EXECUTE on
-- directory_facets(text,date,date,text[],text[],text[],text[],text,text,text[],boolean,boolean)
-- (both live in 20261002000000_directory_query_layer.sql, not in this file).
-- The anonymous teaser is served only by these SECURITY DEFINER functions:
-- ============================================
CREATE OR REPLACE FUNCTION public.home_preview()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH live AS (
    SELECT c.id, c.conference_name, c.specialty, c.event_format, c.start_date,
           c.end_date, c.abstract_open, c.abstract_deadline, s.society
    FROM public.conferences c
    LEFT JOIN public.scraper_sources s ON s.id = c.source_id
    WHERE c.archived = FALSE
      AND (c.start_date IS NULL OR c.start_date >= current_date OR c.end_date >= current_date)
  ),
  month_rows AS (
    SELECT * FROM live
    WHERE start_date IS NOT NULL
      AND start_date <= (date_trunc('month', current_date) + interval '1 month' - interval '1 day')::date
      AND (end_date >= current_date OR (end_date IS NULL AND start_date >= current_date))
  ),
  closing AS (
    SELECT * FROM live WHERE abstract_open IS TRUE AND abstract_deadline >= current_date
  ),
  closing_window AS (
    SELECT * FROM closing WHERE abstract_deadline <= current_date + 14
  ),
  closing_list AS (
    SELECT id, conference_name, society, abstract_deadline
    FROM (
      SELECT * FROM closing_window
      UNION ALL
      SELECT * FROM closing WHERE NOT EXISTS (SELECT 1 FROM closing_window)
    ) u
    ORDER BY abstract_deadline ASC, id ASC
    LIMIT 5
  ),
  spec AS (
    SELECT specialty, count(*) AS n FROM live
    WHERE specialty IS NOT NULL AND specialty <> ''
    GROUP BY specialty ORDER BY n DESC, specialty ASC LIMIT 40
  ),
  soc AS (
    SELECT society, count(*) AS n FROM live
    WHERE society IS NOT NULL AND society <> ''
    GROUP BY society ORDER BY n DESC, society ASC LIMIT 40
  )
  SELECT jsonb_build_object(
    'counts', jsonb_build_object(
      'events', (SELECT count(*) FROM live),
      'societies', (SELECT count(DISTINCT society) FROM live WHERE society IS NOT NULL AND society <> ''),
      'specialties', (SELECT count(DISTINCT specialty) FROM live WHERE specialty IS NOT NULL AND specialty <> ''),
      'closing_soon', (SELECT count(*) FROM closing_window),
      'this_month', (SELECT count(*) FROM month_rows),
      'online_this_month', (SELECT count(*) FROM month_rows WHERE event_format = 'online')
    ),
    'closing_soon', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
               'id', id, 'name', conference_name, 'society', society,
               'days_left', (abstract_deadline - current_date))
             ORDER BY abstract_deadline ASC, id ASC)
      FROM closing_list), '[]'::jsonb),
    'this_month', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
               'id', id, 'name', conference_name, 'society', society,
               'start_date', start_date, 'end_date', end_date)
             ORDER BY start_date ASC, id ASC)
      FROM (SELECT * FROM month_rows ORDER BY start_date ASC, id ASC LIMIT 12) m), '[]'::jsonb),
    'specialties', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('specialty', specialty, 'count', n) ORDER BY n DESC, specialty ASC)
      FROM spec), '[]'::jsonb),
    'societies', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('society', society, 'count', n) ORDER BY n DESC, society ASC)
      FROM soc), '[]'::jsonb)
  );
$$;
REVOKE ALL ON FUNCTION public.home_preview() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.home_preview() TO anon, authenticated;

CREATE OR REPLACE FUNCTION public.event_preview(p_id integer)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT jsonb_build_object(
    'id', c.id,
    'conference_name', c.conference_name,
    'specialty', c.specialty,
    'event_type', c.event_type,
    'event_format', c.event_format,
    'is_flagship', COALESCE(c.is_flagship, FALSE),
    'is_on_demand', COALESCE(c.is_on_demand, FALSE),
    'start_date', c.start_date,
    'end_date', c.end_date,
    'city', c.city,
    'region', c.region,
    'society', s.society,
    'description_excerpt', NULLIF(left(btrim(regexp_replace(COALESCE(c.description, ''), '\s+', ' ', 'g')), 300), '')
  )
  FROM public.conferences c
  LEFT JOIN public.scraper_sources s ON s.id = c.source_id
  WHERE c.id = p_id AND c.archived = FALSE;
$$;
REVOKE ALL ON FUNCTION public.event_preview(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.event_preview(integer) TO anon, authenticated;

CREATE OR REPLACE FUNCTION public.sitemap_events()
RETURNS TABLE(id integer, updated_at timestamptz) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT c.id, c.updated_at FROM public.conferences c
  WHERE c.archived = FALSE
  ORDER BY c.updated_at DESC NULLS LAST, c.id DESC
  LIMIT 5000;
$$;
REVOKE ALL ON FUNCTION public.sitemap_events() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sitemap_events() TO anon, authenticated;
