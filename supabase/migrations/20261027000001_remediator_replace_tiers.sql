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
