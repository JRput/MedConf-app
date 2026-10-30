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
