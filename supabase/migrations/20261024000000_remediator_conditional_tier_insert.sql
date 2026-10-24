-- ============================================================
-- Remediator: conditional tier insert (2026-10-24)
-- The remediator used to replace pricing with delete-all + insert, which raced
-- with moderate_contribution / community_upsert_tiers (check-then-act): a tier
-- set written between the remediator's read and its delete was destroyed.
-- This function inserts tiers only when the conference currently has none,
-- serialised on the conferences row lock. Returns the number inserted (0 = row
-- missing, tiers already present, or nothing valid). SECURITY INVOKER: the
-- caller is the service role. Idempotent to re-apply (CREATE OR REPLACE).
-- ============================================================

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
