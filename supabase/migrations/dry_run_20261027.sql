-- GENERATED from the 0000/0001 migrations + checks (cat). Rolled-back dry run: nothing persists.
-- Regenerate rather than hand-edit if a migration changes.

-- ===== 20261027000000_event_type_degree.sql =====
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

-- Backfill: record first, then update (same predicate; idempotent via ON CONFLICT / event_type filter).
INSERT INTO public.event_type_degree_backfill (conference_id, prev_event_type)
SELECT id, event_type FROM public.conferences
 WHERE archived = FALSE AND event_type = 'conference' AND public.is_degree_title(conference_name)
ON CONFLICT (conference_id) DO NOTHING;

UPDATE public.conferences SET event_type = 'degree'
 WHERE archived = FALSE AND event_type = 'conference' AND public.is_degree_title(conference_name);

-- ===== checks [0000] =====
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM pg_constraint WHERE conrelid='public.conferences'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%') = 1 AND (SELECT bool_and(pg_get_constraintdef(oid) LIKE '%degree%' AND pg_get_constraintdef(oid) LIKE '%workshop%' AND pg_get_constraintdef(oid) LIKE '%course%' AND pg_get_constraintdef(oid) LIKE '%conference%') FROM pg_constraint WHERE conrelid='public.conferences'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#1 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM pg_constraint WHERE conrelid='public.scraper_sources'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%') = 1 AND (SELECT bool_and(pg_get_constraintdef(oid) LIKE '%degree%' AND pg_get_constraintdef(oid) LIKE '%mixed%') FROM pg_constraint WHERE conrelid='public.scraper_sources'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#2 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT bool_and(public.is_degree_title(t)) AS ok FROM unnest(ARRAY['Postgraduate Diploma in International Expedition and Wilderness Medicine','RCPSG Postgraduate Diploma in Travel Medicine','Diploma in Orthodontic Therapy (DipOT) course','Level 7 Diploma in Injectables','Royal College Advanced Certificate in Clinical Education','MSc in Clinical Oncology','M.Sc. Sports Medicine','MRes Cancer Sciences','PGCert Medical Education','Master''s in Public Health','Bachelor of Medical Science','Doctorate in Clinical Practice','Certificate in Aesthetics Level 7']) t) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#3 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT bool_and(NOT public.is_degree_title(t)) AS ok FROM unnest(ARRAY['MRCP(UK) Diploma Ceremony','MRCP(UK) Diploma Ceremony 2027','Preparation Course for the Diploma in Special Care Dentistry','OSCE Revision Course for MSc students','PgDip Graduation Day','Annual Awards Dinner MSc','Mock Exam Day for the Diploma','A Conversation with Selwyn O. Rogers Jr., MD, MPH, FACS','ASCO Annual Meeting','RCEM Annual Conference 2027','PhD Student Symposium','Advanced Life Support Provider Course','MSc Student Prize Lecture','Masters of Endoscopy Live 2027']) t) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#4 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT public.is_degree_title(NULL) = false AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#5 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT NOT has_function_privilege('anon','public.is_degree_title(text)','EXECUTE') AND NOT has_function_privilege('authenticated','public.is_degree_title(text)','EXECUTE') AND has_function_privilege('service_role','public.is_degree_title(text)','EXECUTE') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#6 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM public.conferences WHERE archived=false AND event_type='conference' AND public.is_degree_title(conference_name)) = 0 AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#7 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM public.conferences WHERE event_type='degree' AND archived=false) = (SELECT count(*) FROM public.event_type_degree_backfill) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#8 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT NOT has_table_privilege('anon','public.event_type_degree_backfill','SELECT') AND NOT has_table_privilege('authenticated','public.event_type_degree_backfill','SELECT') AND (SELECT relrowsecurity FROM pg_class WHERE oid='public.event_type_degree_backfill'::regclass) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#9 FAILED'; END IF; END $chk$;
-- ===== 20261027000001_remediator_replace_tiers.sql =====
-- ============================================================
-- Remediator: replace tiers when they are all-zero or one generic label (2026-10-27)
-- Companion to remediator_insert_tiers_if_empty (which skips any conference that
-- already has tiers, so corrections for false-Free / partial rows were dropped).
-- Under the conferences row lock (same lock as moderate_contribution and the
-- insert function) it replaces the existing tiers ONLY when:
--   (a) the conference has >= 1 tier and EVERY tier has price 0, or
--   (b) it has exactly one tier whose label is generic (case/space-insensitive):
--       Standard, Registration, Registration fee, Fee, Fees, Price, Course fee, Delegate.
-- Anything else (real or mixed tiers, community-entered tiers) is left alone.
-- A conference with NO tiers returns 0: use remediator_insert_tiers_if_empty.
-- Input tier validation (invalid tiers are skipped, never defaulted):
--   * tier_label non-empty; price_gbp a plain non-negative number (<= 2 decimals);
--   * currency REQUIRED, 3 letters -- a missing currency is NEVER defaulted to GBP;
--   * early_bird_deadline must parse as YYYY-MM-DD else NULL.
--   * the valid set must contain at least one price > 0, otherwise nothing is
--     deleted or inserted (never replace a false-Free with another all-free set).
-- Returns rows inserted (0 = nothing changed). SECURITY DEFINER, service_role only.
-- Idempotent to re-apply (CREATE OR REPLACE).
-- ============================================================

CREATE OR REPLACE FUNCTION public.remediator_replace_tiers_if_zero_or_generic(p_conference_id bigint, p_tiers jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_catalog AS $$
DECLARE
  t jsonb;
  v jsonb := '[]'::jsonb;
  n_exist integer;
  n_zero integer;
  one_label text;
  price numeric;
  cur text;
  dl date;
  any_pos boolean := FALSE;
  n integer := 0;
BEGIN
  PERFORM 1 FROM conferences WHERE id = p_conference_id FOR UPDATE;
  IF NOT FOUND THEN RETURN 0; END IF;

  SELECT count(*), count(*) FILTER (WHERE price_gbp = 0), min(tier_label)
    INTO n_exist, n_zero, one_label
    FROM pricing_tiers WHERE conference_id = p_conference_id;
  IF n_exist = 0 THEN RETURN 0; END IF;
  IF NOT (n_zero = n_exist
          OR (n_exist = 1 AND lower(regexp_replace(btrim(one_label), '\s+', ' ', 'g'))
              IN ('standard','registration','registration fee','fee','fees','price','course fee','delegate'))) THEN
    RETURN 0;
  END IF;

  FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(p_tiers, '[]'::jsonb)) LOOP
    BEGIN
      IF NULLIF(btrim(t ->> 'tier_label'), '') IS NULL THEN CONTINUE; END IF;
      IF COALESCE(t ->> 'price_gbp', '') !~ '^\d{1,8}(\.\d{1,2})?$' THEN CONTINUE; END IF;
      cur := upper(btrim(COALESCE(t ->> 'currency', '')));
      IF cur !~ '^[A-Z]{3}$' THEN CONTINUE; END IF;   -- no GBP default, ever
      price := (t ->> 'price_gbp')::numeric;
      dl := NULL;
      IF COALESCE(t ->> 'early_bird_deadline', '') ~ '^\d{4}-\d{2}-\d{2}$' THEN
        dl := (t ->> 'early_bird_deadline')::date;
      END IF;
      IF price > 0 THEN any_pos := TRUE; END IF;
      v := v || jsonb_build_array(jsonb_build_object(
             'l', btrim(t ->> 'tier_label'), 'p', price, 'c', cur,
             'e', COALESCE((t ->> 'is_early_bird')::boolean, FALSE), 'd', dl));
    EXCEPTION WHEN others THEN
      CONTINUE;   -- bad date / boolean: skip this tier only
    END;
  END LOOP;
  IF NOT any_pos THEN RETURN 0; END IF;

  DELETE FROM pricing_tiers WHERE conference_id = p_conference_id;
  FOR t IN SELECT * FROM jsonb_array_elements(v) LOOP
    INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, is_early_bird, early_bird_deadline)
    VALUES (p_conference_id, t ->> 'l', (t ->> 'p')::numeric, t ->> 'c', (t ->> 'e')::boolean,
            NULLIF(t ->> 'd', 'null')::date);
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION public.remediator_replace_tiers_if_zero_or_generic(bigint, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.remediator_replace_tiers_if_zero_or_generic(bigint, jsonb) TO service_role;

-- ===== checks [0001] + behaviour tests =====
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT prosecdef FROM pg_proc WHERE oid='public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)'::regprocedure) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#1 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)'::regprocedure) = (SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.is_degree_title(text)'::regprocedure) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#2 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT NOT has_function_privilege('anon','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AND NOT has_function_privilege('authenticated','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AND NOT has_function_privilege('public','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#3 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT has_function_privilege('service_role','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#4 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT proconfig::text FROM pg_proc WHERE oid='public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)'::regprocedure) LIKE '%search_path=public, pg_catalog%' AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#5 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT prosrc LIKE '%FOR UPDATE%' AND prosrc LIKE '%no GBP default%' AND prosrc NOT LIKE '%COALESCE(NULLIF(t ->> ''currency''%' AS ok FROM pg_proc WHERE proname='remediator_replace_tiers_if_zero_or_generic') q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0001#6 FAILED'; END IF; END $chk$;

DO $t$
DECLARE cid integer; r integer; n integer; lbl text; cur text;
  good jsonb := '[{"tier_label":"Delegate","price_gbp":"120.00","currency":"EUR"},{"tier_label":"Trainee","price_gbp":"60","currency":"eur","is_early_bird":true,"early_bird_deadline":"2027-01-31"},{"tier_label":"No currency","price_gbp":"10"},{"tier_label":"","price_gbp":"10","currency":"GBP"},{"tier_label":"Bad price","price_gbp":"abc","currency":"GBP"},{"tier_label":"Bad date","price_gbp":"5","currency":"GBP","early_bird_deadline":"2027-02-31"}]';
BEGIN
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run zero', 'https://dry-run.invalid/a') RETURNING id INTO cid;
  INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) VALUES (cid,'Free',0,'GBP'),(cid,'Trainee',0,'GBP');
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, '[{"tier_label":"Z","price_gbp":"0","currency":"GBP"}]'::jsonb);
  IF r <> 0 THEN RAISE EXCEPTION 'F1: all-free replacement must be refused'; END IF;
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, '[{"tier_label":"A","price_gbp":"10"}]'::jsonb);
  IF r <> 0 OR (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid) <> 2 THEN RAISE EXCEPTION 'F2: no-currency set must change nothing'; END IF;
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, good);
  SELECT count(*) INTO n FROM pricing_tiers WHERE conference_id=cid;
  IF r <> 3 OR n <> 3 THEN RAISE EXCEPTION 'F3: expected 3 valid tiers (got %, %)', r, n; END IF;
  IF (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid AND currency='EUR') <> 2 THEN RAISE EXCEPTION 'F3b: currency not kept/uppercased'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pricing_tiers WHERE conference_id=cid AND early_bird_deadline='2027-01-31' AND is_early_bird) THEN RAISE EXCEPTION 'F3c: early bird lost'; END IF;
  -- now real tiers: must not be replaced
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, '[{"tier_label":"X","price_gbp":"1","currency":"GBP"}]'::jsonb);
  IF r <> 0 OR (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid) <> 3 THEN RAISE EXCEPTION 'F4: real tiers must be left alone'; END IF;
  -- single generic nonzero tier IS replaced
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run generic', 'https://dry-run.invalid/b') RETURNING id INTO cid;
  INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) VALUES (cid,'  Registration FEE ',50,'GBP');
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, '[{"tier_label":"Member","price_gbp":"40","currency":"GBP"},{"tier_label":"Non-member","price_gbp":"70","currency":"GBP"}]'::jsonb);
  IF r <> 2 OR (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid) <> 2 THEN RAISE EXCEPTION 'F5: generic single tier not replaced'; END IF;
  -- two generic-labelled nonzero tiers: not replaced; mixed zero/nonzero: not replaced
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run mixed', 'https://dry-run.invalid/c') RETURNING id INTO cid;
  INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) VALUES (cid,'Standard',0,'GBP'),(cid,'Student',20,'GBP');
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, '[{"tier_label":"Q","price_gbp":"9","currency":"GBP"}]'::jsonb);
  IF r <> 0 THEN RAISE EXCEPTION 'F6: mixed tiers must be left alone'; END IF;
  -- no tiers: returns 0 (insert function's job); missing conference: 0
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run empty', 'https://dry-run.invalid/d') RETURNING id INTO cid;
  IF public.remediator_replace_tiers_if_zero_or_generic(cid, good) <> 0 OR public.remediator_replace_tiers_if_zero_or_generic(-1, good) <> 0 THEN RAISE EXCEPTION 'F7'; END IF;
  -- constraint accepts degree
  INSERT INTO conferences (conference_name, source_url, event_type) VALUES ('dry-run degree', 'https://dry-run.invalid/e', 'degree');
  BEGIN
    INSERT INTO conferences (conference_name, source_url, event_type) VALUES ('dry-run bad', 'https://dry-run.invalid/f', 'nonsense');
    RAISE EXCEPTION 'F8: bad event_type accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
END $t$;

ROLLBACK;
