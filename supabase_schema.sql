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
    default_event_type TEXT NOT NULL DEFAULT 'conference'
        CHECK (default_event_type IN ('conference','course','mixed')),
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
    abstract_deadline DATE,
    organiser_url TEXT,
    booking_url TEXT,
    source_url TEXT UNIQUE NOT NULL,
    description TEXT,
    -- 'conference' (the default; single event, optional abstract submissions)
    -- 'course' (a recurring offering — see course_sessions for the dates).
    event_type TEXT NOT NULL DEFAULT 'conference'
        CHECK (event_type IN ('conference','course')),
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
    price_gbp DECIMAL(10,2) NOT NULL,
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
    type TEXT NOT NULL CHECK (type IN ('reminder','new_in_specialty','conference_change','system')),
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

-- Anyone can view non-archived conferences
CREATE POLICY "Anyone can view conferences"
    ON conferences FOR SELECT
    USING (archived = FALSE);

-- ============================================
-- RLS POLICIES - PRICING TIERS (Public Read)
-- ============================================

-- Anyone can view pricing tiers
CREATE POLICY "Anyone can view pricing tiers"
    ON pricing_tiers FOR SELECT
    USING (TRUE);

-- Anyone can view course sessions
CREATE POLICY "Anyone can view course sessions"
    ON course_sessions FOR SELECT
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
CREATE POLICY "Anyone can view scraper sources"
    ON scraper_sources FOR SELECT
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


