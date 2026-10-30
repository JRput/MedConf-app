-- GENERATED from 20261031000000_provenance.sql + checks. Single transaction, ROLLED BACK: nothing persists.
-- Regenerate rather than hand-edit if the migration changes.
BEGIN;

-- legacy fixture row created BEFORE the migration: its written_at must stay NULL
INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run legacy', 'https://dry-run.invalid/legacy');
INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) SELECT id,'Legacy',10,'GBP' FROM conferences WHERE source_url='https://dry-run.invalid/legacy';

-- ============================================================
-- Evidence provenance (2026-10-31)  -- mission "provenance"
-- Additive: records WHICH page a price / venue / abstract fact came from, and how
-- that page was tied to the event. No backfill: existing rows stay NULL = unknown.
--   * pricing_tiers: evidence_url, evidence_identity, written_by, written_at
--   * conferences:   venue_evidence_url/_identity, abstract_evidence_url/_identity
--   * identity vocabulary (CHECK): own_page | strong | legacy (or NULL)
--     own_page = the event's own page; strong = a discovered page that passed the
--     STRONG page-identity gate; legacy = read-only history, never written anew.
--   * both remediator tier RPCs now RAISE 'provenance_rejected: <label>' (nothing
--     written) when ANY tier's evidence_identity is not own_page/strong (missing
--     counts as rejected), and store evidence_url / evidence_identity / written_by.
-- Grants unchanged (service_role only). Idempotent to re-apply. No BEGIN/COMMIT.
-- ============================================================

SET LOCAL lock_timeout = '10s';

ALTER TABLE public.pricing_tiers
  ADD COLUMN IF NOT EXISTS evidence_url TEXT,
  ADD COLUMN IF NOT EXISTS evidence_identity TEXT
    CONSTRAINT pricing_tiers_evidence_identity_check CHECK (evidence_identity IN ('own_page','strong','legacy')),
  ADD COLUMN IF NOT EXISTS written_by TEXT,
  ADD COLUMN IF NOT EXISTS written_at TIMESTAMPTZ;
-- Default set AFTER the column exists so existing rows stay NULL (a default on ADD COLUMN would stamp them all).
ALTER TABLE public.pricing_tiers ALTER COLUMN written_at SET DEFAULT now();

ALTER TABLE public.conferences
  ADD COLUMN IF NOT EXISTS venue_evidence_url TEXT,
  ADD COLUMN IF NOT EXISTS venue_evidence_identity TEXT
    CONSTRAINT conferences_venue_evidence_identity_check CHECK (venue_evidence_identity IN ('own_page','strong','legacy')),
  ADD COLUMN IF NOT EXISTS abstract_evidence_url TEXT,
  ADD COLUMN IF NOT EXISTS abstract_evidence_identity TEXT
    CONSTRAINT conferences_abstract_evidence_identity_check CHECK (abstract_evidence_identity IN ('own_page','strong','legacy'));

CREATE OR REPLACE FUNCTION public.remediator_insert_tiers_if_empty(p_conference_id INTEGER, p_tiers JSONB)
RETURNS INTEGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
  t JSONB;
  n INTEGER := 0;
BEGIN
  -- Provenance gate (2026-10-31): every tier must carry evidence_identity own_page|strong AND a non-empty evidence_url.
  FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(p_tiers, '[]'::jsonb)) LOOP
    IF COALESCE(t ->> 'evidence_identity', '') NOT IN ('own_page', 'strong')
       OR NULLIF(t ->> 'evidence_url', '') IS NULL THEN
      RAISE EXCEPTION 'provenance_rejected: %', COALESCE(t ->> 'tier_label', '');
    END IF;
  END LOOP;
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
    INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, is_early_bird, early_bird_deadline,
                               evidence_url, evidence_identity, written_by)
    VALUES (p_conference_id, t ->> 'tier_label', (t ->> 'price_gbp')::numeric,
            COALESCE(NULLIF(t ->> 'currency', ''), 'GBP'),
            COALESCE((t ->> 'is_early_bird')::boolean, FALSE),
            NULLIF(t ->> 'early_bird_deadline', '')::date,
            NULLIF(t ->> 'evidence_url', ''), t ->> 'evidence_identity', NULLIF(t ->> 'written_by', ''));
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION public.remediator_insert_tiers_if_empty(INTEGER, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.remediator_insert_tiers_if_empty(INTEGER, JSONB) TO service_role;

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
  -- Provenance gate (2026-10-31): every tier must carry evidence_identity own_page|strong AND a non-empty evidence_url.
  FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(p_tiers, '[]'::jsonb)) LOOP
    IF COALESCE(t ->> 'evidence_identity', '') NOT IN ('own_page', 'strong')
       OR NULLIF(t ->> 'evidence_url', '') IS NULL THEN
      RAISE EXCEPTION 'provenance_rejected: %', COALESCE(t ->> 'tier_label', '');
    END IF;
  END LOOP;

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
        BEGIN
          dl := (t ->> 'early_bird_deadline')::date;
        EXCEPTION WHEN others THEN
          dl := NULL;   -- an impossible date (2027-02-31) drops the deadline, never the tier
        END;
      END IF;
      IF price > 0 THEN any_pos := TRUE; END IF;
      v := v || jsonb_build_array(jsonb_build_object(
             'l', btrim(t ->> 'tier_label'), 'p', price, 'c', cur,
             'e', COALESCE((t ->> 'is_early_bird')::boolean, FALSE), 'd', dl,
             'u', NULLIF(t ->> 'evidence_url', ''), 'i', t ->> 'evidence_identity',
             'w', NULLIF(t ->> 'written_by', '')));
    EXCEPTION WHEN others THEN
      CONTINUE;   -- bad boolean: skip this tier only (a bad date only nulls the deadline)
    END;
  END LOOP;
  IF NOT any_pos THEN RETURN 0; END IF;

  DELETE FROM pricing_tiers WHERE conference_id = p_conference_id;
  FOR t IN SELECT * FROM jsonb_array_elements(v) LOOP
    INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, is_early_bird, early_bird_deadline,
                               evidence_url, evidence_identity, written_by)
    VALUES (p_conference_id, t ->> 'l', (t ->> 'p')::numeric, t ->> 'c', (t ->> 'e')::boolean,
            NULLIF(t ->> 'd', 'null')::date, t ->> 'u', t ->> 'i', t ->> 'w');
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION public.remediator_replace_tiers_if_zero_or_generic(bigint, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.remediator_replace_tiers_if_zero_or_generic(bigint, jsonb) TO service_role;

-- ===== checks (from 20261031000000_checks.txt) =====
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='pricing_tiers' AND column_name IN ('evidence_url','evidence_identity','written_by','written_at')) = 4 AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#1 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='conferences' AND column_name IN ('venue_evidence_url','venue_evidence_identity','abstract_evidence_url','abstract_evidence_identity')) = 4 AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#2 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM pg_constraint WHERE contype='c' AND conname IN ('pricing_tiers_evidence_identity_check','conferences_venue_evidence_identity_check','conferences_abstract_evidence_identity_check')) = 3 AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#3 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT bool_and(pg_get_constraintdef(oid) LIKE '%own_page%' AND pg_get_constraintdef(oid) LIKE '%strong%' AND pg_get_constraintdef(oid) LIKE '%legacy%') FROM pg_constraint WHERE conname IN ('pricing_tiers_evidence_identity_check','conferences_venue_evidence_identity_check','conferences_abstract_evidence_identity_check')) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#4 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT count(*) FROM public.pricing_tiers WHERE evidence_identity IS NOT NULL) = 0 AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#5 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT NOT has_function_privilege('anon','public.remediator_insert_tiers_if_empty(integer,jsonb)','EXECUTE') AND NOT has_function_privilege('authenticated','public.remediator_insert_tiers_if_empty(integer,jsonb)','EXECUTE') AND NOT has_function_privilege('public','public.remediator_insert_tiers_if_empty(integer,jsonb)','EXECUTE') AND has_function_privilege('service_role','public.remediator_insert_tiers_if_empty(integer,jsonb)','EXECUTE') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#6 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT NOT has_function_privilege('anon','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AND NOT has_function_privilege('authenticated','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AND NOT has_function_privilege('public','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AND has_function_privilege('service_role','public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)','EXECUTE') AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#7 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT prosecdef FROM pg_proc WHERE oid='public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)'::regprocedure) AND NOT (SELECT prosecdef FROM pg_proc WHERE oid='public.remediator_insert_tiers_if_empty(integer,jsonb)'::regprocedure) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#8 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT bool_and(prosrc LIKE '%provenance_rejected%' AND prosrc LIKE '%FOR UPDATE%' AND prosrc LIKE '%evidence_identity%') FROM pg_proc WHERE proname IN ('remediator_insert_tiers_if_empty','remediator_replace_tiers_if_zero_or_generic')) AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#9 FAILED'; END IF; END $chk$;
DO $chk$ BEGIN IF NOT COALESCE((SELECT ok FROM (SELECT (SELECT proconfig::text FROM pg_proc WHERE oid='public.remediator_replace_tiers_if_zero_or_generic(bigint,jsonb)'::regprocedure) LIKE '%search_path=public, pg_catalog%' AS ok) q LIMIT 1), false) THEN RAISE EXCEPTION 'dry-run check 0000#10 FAILED'; END IF; END $chk$;

-- ===== behaviour =====
DO $t$
DECLARE cid integer; r integer; caught boolean;
  good jsonb := '[{"tier_label":"Delegate","price_gbp":"120.00","currency":"EUR","evidence_url":"https://dry-run.invalid/fees","evidence_identity":"own_page","written_by":"remediator"},{"tier_label":"Trainee","price_gbp":"60","currency":"EUR","evidence_url":"https://dry-run.invalid/fees2","evidence_identity":"strong","written_by":"remediator"}]';
  bad jsonb  := '[{"tier_label":"Delegate","price_gbp":"120","currency":"EUR","evidence_url":"https://dry-run.invalid/fees","evidence_identity":"own_page"},{"tier_label":"Sneaky","price_gbp":"60","currency":"EUR","evidence_url":"https://other.invalid/x","evidence_identity":"legacy"}]';
  nourl jsonb := '[{"tier_label":"NoUrl","price_gbp":"60","currency":"EUR","evidence_identity":"own_page"}]';
  missing jsonb := '[{"tier_label":"NoEvidence","price_gbp":"60","currency":"EUR"}]';
BEGIN
  IF (SELECT written_at FROM pricing_tiers WHERE tier_label='Legacy' AND conference_id=(SELECT id FROM conferences WHERE source_url='https://dry-run.invalid/legacy')) IS NOT NULL THEN RAISE EXCEPTION 'W1: existing row written_at was stamped'; END IF;
  -- insert_if_empty: good provenance
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run ins', 'https://dry-run.invalid/i') RETURNING id INTO cid;
  r := public.remediator_insert_tiers_if_empty(cid, good);
  IF r <> 2 THEN RAISE EXCEPTION 'I1: expected 2 inserted, got %', r; END IF;
  IF (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid AND evidence_url IS NOT NULL AND evidence_identity IN ('own_page','strong') AND written_by='remediator' AND written_at IS NOT NULL) <> 2 THEN RAISE EXCEPTION 'I2: evidence not written (incl. written_at set)'; END IF;
  -- insert_if_empty: bad / missing provenance on an empty conference writes nothing
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run ins bad', 'https://dry-run.invalid/ib') RETURNING id INTO cid;
  caught := FALSE;
  BEGIN PERFORM public.remediator_insert_tiers_if_empty(cid, bad);
  EXCEPTION WHEN raise_exception THEN caught := (SQLERRM = 'provenance_rejected: Sneaky'); END;
  IF NOT caught THEN RAISE EXCEPTION 'I3: bad tier not rejected with expected message'; END IF;
  IF (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid) <> 0 THEN RAISE EXCEPTION 'I4: rejected batch wrote rows'; END IF;
  caught := FALSE;
  BEGIN PERFORM public.remediator_insert_tiers_if_empty(cid, missing);
  EXCEPTION WHEN raise_exception THEN caught := (SQLERRM = 'provenance_rejected: NoEvidence'); END;
  IF NOT caught THEN RAISE EXCEPTION 'I5: missing identity not rejected'; END IF;

  caught := FALSE;
  BEGIN PERFORM public.remediator_insert_tiers_if_empty(cid, nourl);
  EXCEPTION WHEN raise_exception THEN caught := (SQLERRM = 'provenance_rejected: NoUrl'); END;
  IF NOT caught THEN RAISE EXCEPTION 'I6: good identity but missing url not rejected (insert)'; END IF;
  caught := FALSE;
  BEGIN PERFORM public.remediator_replace_tiers_if_zero_or_generic(cid, nourl);
  EXCEPTION WHEN raise_exception THEN caught := (SQLERRM = 'provenance_rejected: NoUrl'); END;
  IF NOT caught THEN RAISE EXCEPTION 'I7: good identity but missing url not rejected (replace)'; END IF;

  -- replace_if_zero_or_generic: good provenance
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run rep', 'https://dry-run.invalid/r') RETURNING id INTO cid;
  INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) VALUES (cid,'Free',0,'GBP');
  r := public.remediator_replace_tiers_if_zero_or_generic(cid, good);
  IF r <> 2 THEN RAISE EXCEPTION 'R1: expected 2 replaced, got %', r; END IF;
  IF (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid AND evidence_url IS NOT NULL AND evidence_identity IN ('own_page','strong') AND written_by='remediator' AND written_at IS NOT NULL) <> 2 THEN RAISE EXCEPTION 'R2: evidence not written'; END IF;
  -- replace: bad provenance leaves the existing zero tier untouched
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run rep bad', 'https://dry-run.invalid/rb') RETURNING id INTO cid;
  INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency) VALUES (cid,'Free',0,'GBP');
  caught := FALSE;
  BEGIN PERFORM public.remediator_replace_tiers_if_zero_or_generic(cid, bad);
  EXCEPTION WHEN raise_exception THEN caught := (SQLERRM = 'provenance_rejected: Sneaky'); END;
  IF NOT caught THEN RAISE EXCEPTION 'R3: bad tier not rejected with expected message'; END IF;
  IF (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid AND tier_label='Free') <> 1 OR (SELECT count(*) FROM pricing_tiers WHERE conference_id=cid) <> 1 THEN RAISE EXCEPTION 'R4: rejected batch changed rows'; END IF;
  caught := FALSE;
  BEGIN PERFORM public.remediator_replace_tiers_if_zero_or_generic(cid, missing);
  EXCEPTION WHEN raise_exception THEN caught := TRUE; END;
  IF NOT caught THEN RAISE EXCEPTION 'R5: missing identity not rejected'; END IF;

  -- identity CHECKs
  caught := FALSE;
  BEGIN INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, evidence_identity) VALUES (cid,'x',1,'GBP','nonsense');
  EXCEPTION WHEN check_violation THEN caught := TRUE; END;
  IF NOT caught THEN RAISE EXCEPTION 'C1: bad tier identity accepted'; END IF;
  caught := FALSE;
  BEGIN UPDATE conferences SET venue_evidence_identity = 'nonsense' WHERE id = cid;
  EXCEPTION WHEN check_violation THEN caught := TRUE; END;
  IF NOT caught THEN RAISE EXCEPTION 'C2: bad venue identity accepted'; END IF;
  caught := FALSE;
  BEGIN UPDATE conferences SET abstract_evidence_identity = 'nonsense' WHERE id = cid;
  EXCEPTION WHEN check_violation THEN caught := TRUE; END;
  IF NOT caught THEN RAISE EXCEPTION 'C3: bad abstract identity accepted'; END IF;
  UPDATE conferences SET venue_evidence_url='https://dry-run.invalid/v', venue_evidence_identity='own_page', abstract_evidence_url='https://dry-run.invalid/a', abstract_evidence_identity='strong' WHERE id = cid;
END $t$;

ROLLBACK;
