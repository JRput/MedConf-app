-- ============================================================
-- event_type 'degree' (2026-10-27)  -- Ticket M, mission "cross-source coverage"
-- Awarded qualifications (MSc, PgDip, "Diploma in ...", ...) get their own
-- event type instead of being badged conference/course.
--   1. public.is_degree_title(text): the ONE SQL home of the title rule. The
--      scraper's Python rule must stay identical (same include / exclude regex).
--   2. Widen conferences.event_type and scraper_sources.default_event_type CHECKs.
--   3. Backfill non-archived rows whose title matches; previous type is kept in
--      public.event_type_degree_backfill so the rollback restores it exactly.
-- Ordering (HQ LESSONS #86): apply this BEFORE pushing scraper code that emits
-- 'degree'. Additive for readers: directory_events / directory_facets /
-- home_preview / event_preview / sitemap_events pass event_type through, no
-- hard-coded type list. Idempotent to re-apply. No BEGIN/COMMIT (the applier wraps).
-- Rule edits: change the two regexes below, re-run (CREATE OR REPLACE), and
-- re-run the backfill UPDATE; keep medconf-scraper's Python copy in lockstep.
-- ============================================================

SET LOCAL lock_timeout = '10s';

CREATE OR REPLACE FUNCTION public.is_degree_title(p_title text)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $f$
  SELECT COALESCE(p_title, '') ~* '(\y(m\.?sc|b\.?sc|mres|mphil|phd|dphil|mba|mph|pgcert|pgdip)\y|\ypostgraduate\s+(certificate|diploma)\y|\ydiploma\s+in\y|\yadvanced\s+certificate\s+in\y|\ycertificate\s+in\y.*\ylevel\s*7\y|\ymaster''?s?\s+(of|in)\y|\ybachelors?\s+of\y|\ydoctorate\s+(in|of)\y)'
     AND COALESCE(p_title, '') !~* '(\y(ceremon\w*|graduation|awards?|prepar\w*|revision|exam\w*|mock|osce|symposium|congress|conference|webinar|lecture|open\s+day|viva|workshop|info(rmation)?\s+session|alumni|interview|live\s+20\d\d|networking|taster|masterclass)\y|\yfor\s+the\s+diploma\y|,\s*(md|do|mph|mba|phd|msc|mres|mphil|dphil|pgcert|pgdip|facs|frcp|frcs|frca|mrcp|mrcs|rn|bds)\y)'
$f$;
REVOKE EXECUTE ON FUNCTION public.is_degree_title(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.is_degree_title(text) TO service_role;

-- Widen the CHECKs. The inline CHECKs are unnamed in the baseline, so find them
-- by definition rather than by an assumed name. Skips when already widened.
DO $$
DECLARE
  r record;
  n integer;
BEGIN
  -- conferences.event_type
  SELECT count(*) INTO n FROM pg_constraint
   WHERE conrelid = 'public.conferences'::regclass AND contype = 'c'
     AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%';
  IF n > 1 THEN RAISE EXCEPTION 'conferences: % event_type CHECKs found, expected at most 1', n; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.conferences'::regclass AND contype = 'c'
                    AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%'
                    AND pg_get_constraintdef(oid) LIKE '%degree%') THEN
    FOR r IN SELECT conname FROM pg_constraint
              WHERE conrelid = 'public.conferences'::regclass AND contype = 'c'
                AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%' LOOP
      EXECUTE format('ALTER TABLE public.conferences DROP CONSTRAINT %I', r.conname);
    END LOOP;
    ALTER TABLE public.conferences ADD CONSTRAINT conferences_event_type_check
      CHECK (event_type IN ('conference','workshop','course','degree'));
  END IF;

  -- scraper_sources.default_event_type
  SELECT count(*) INTO n FROM pg_constraint
   WHERE conrelid = 'public.scraper_sources'::regclass AND contype = 'c'
     AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%';
  IF n > 1 THEN RAISE EXCEPTION 'scraper_sources: % default_event_type CHECKs found, expected at most 1', n; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.scraper_sources'::regclass AND contype = 'c'
                    AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%'
                    AND pg_get_constraintdef(oid) LIKE '%degree%') THEN
    FOR r IN SELECT conname FROM pg_constraint
              WHERE conrelid = 'public.scraper_sources'::regclass AND contype = 'c'
                AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%' LOOP
      EXECUTE format('ALTER TABLE public.scraper_sources DROP CONSTRAINT %I', r.conname);
    END LOOP;
    ALTER TABLE public.scraper_sources ADD CONSTRAINT scraper_sources_default_event_type_check
      CHECK (default_event_type IN ('conference','workshop','course','degree','mixed'));
  END IF;
END $$;

-- Record of what the backfill changed (service-key only: RLS on, no policies, no grants).
CREATE TABLE IF NOT EXISTS public.event_type_degree_backfill (
  conference_id INTEGER PRIMARY KEY,
  prev_event_type TEXT NOT NULL,
  backfilled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.event_type_degree_backfill ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_type_degree_backfill FROM PUBLIC, anon, authenticated;

-- Backfill: only rows stored as 'conference' (an extractor's course/workshop is kept; else rows would flip on every re-detail). Record first, then update (same predicate; idempotent via ON CONFLICT / event_type filter).
INSERT INTO public.event_type_degree_backfill (conference_id, prev_event_type)
SELECT id, event_type FROM public.conferences
 WHERE archived = FALSE AND event_type = 'conference' AND public.is_degree_title(conference_name)
ON CONFLICT (conference_id) DO NOTHING;

UPDATE public.conferences SET event_type = 'degree'
 WHERE archived = FALSE AND event_type = 'conference' AND public.is_degree_title(conference_name);
