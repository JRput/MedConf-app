-- ============================================================
-- Community Contributions v2 (2026-10-18)
-- Users add missing information to listed events and submit
-- events that are not listed; everything is moderated.
--
-- RULE: scraped columns are never written by the community path for
-- scraped rows. Community data lives in community_facts /
-- community_tiers and is shown only where the scraped value is
-- missing. New community events are ordinary conferences rows under
-- the inactive source 1000, so the daily remediator (--source 1000)
-- can fill their empty fields while nothing ever scrapes them.
--
-- Idempotent: safe to re-run.
-- ============================================================

-- ------------------------------------------------------------
-- 1. Admin flag + helpers
-- ------------------------------------------------------------
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- TRUE for the service role (cron scripts) and for direct SQL as the
-- database owner; FALSE for every browser/anon request.
CREATE OR REPLACE FUNCTION public.is_privileged_caller()
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT COALESCE(auth.role() = 'service_role', FALSE)
      OR current_user IN ('postgres', 'supabase_admin')
$$;

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE((SELECT is_admin FROM user_profiles WHERE id = auth.uid()), FALSE)
$$;

-- Clients can never grant themselves admin: INSERT with is_admin=TRUE or
-- any UPDATE that changes is_admin is rejected unless the caller is the
-- service role / database owner.
CREATE OR REPLACE FUNCTION public.user_profiles_guard_is_admin()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF public.is_privileged_caller() THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'INSERT' AND NEW.is_admin IS TRUE THEN
    RAISE EXCEPTION 'is_admin can only be set by the service role' USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.is_admin IS DISTINCT FROM OLD.is_admin THEN
    RAISE EXCEPTION 'is_admin can only be changed by the service role' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_user_profiles_guard_is_admin ON user_profiles;
CREATE TRIGGER trg_user_profiles_guard_is_admin
  BEFORE INSERT OR UPDATE ON user_profiles
  FOR EACH ROW EXECUTE FUNCTION public.user_profiles_guard_is_admin();

-- ------------------------------------------------------------
-- 2. Community source row (inactive: never scraped; remediator only)
-- ------------------------------------------------------------
INSERT INTO scraper_sources (id, source_name, base_url, extraction_instructions, active, society, default_event_type)
VALUES (
  1000,
  'Community submissions',
  'https://community.medconf.invalid',
  'User-submitted events, moderated in-app. Not scraped. python -m remediator --source 1000 fills empty fields from each row''s organiser site.',
  FALSE,
  'Community',
  'mixed'
)
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 3. Notification types for submitters and moderators
-- ------------------------------------------------------------
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN
  ('reminder', 'new_in_specialty', 'conference_change', 'system', 'contribution_update', 'moderation'));

-- ------------------------------------------------------------
-- 4. Tables
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS community_contributions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('new_event', 'add_info')),
  -- required for add_info; set on approval for new_event
  conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'needs_info', 'published', 'rejected', 'merged', 'expired', 'hidden')),
  payload JSONB NOT NULL,                 -- user-entered (see website lib/community/schema.ts)
  enrichment JSONB,                       -- {field: {value, method, agrees}} from enrich_submissions.py
  enrichment_status TEXT NOT NULL DEFAULT 'waiting'
    CHECK (enrichment_status IN ('waiting', 'fetched', 'blocked', 'failed', 'skipped')),
  enriched_at TIMESTAMPTZ,
  evidence_url TEXT,                      -- private message to the moderator
  note TEXT,                              -- private message to the moderator
  final_payload JSONB,                    -- what the moderator approved
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

CREATE TABLE IF NOT EXISTS community_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contribution_id UUID NOT NULL REFERENCES community_contributions(id) ON DELETE CASCADE,
  conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
  field TEXT NOT NULL CHECK (field IN (
    'start_date', 'end_date', 'start_time', 'venue_name', 'city', 'region', 'event_format',
    'abstract_deadline', 'abstract_open', 'abstract_deadline_note', 'cpd_accredited', 'cpd_points',
    'organiser_url', 'booking_url', 'description', 'note')),
  value JSONB NOT NULL,
  is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_community_facts_conf_published ON community_facts (conference_id) WHERE is_published;

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

-- ------------------------------------------------------------
-- 5. Triggers on community_contributions
-- ------------------------------------------------------------
-- Insert: the caller owns the row, it starts pending with no enrichment
-- or moderation state, is size-capped, and each user may hold at most
-- 10 items awaiting review.
CREATE OR REPLACE FUNCTION public.community_contributions_before_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  pending_count INTEGER;
BEGIN
  IF public.is_privileged_caller() THEN
    IF NEW.user_id IS NULL THEN
      RAISE EXCEPTION 'user_id is required';
    END IF;
  ELSE
    IF auth.uid() IS NULL THEN
      RAISE EXCEPTION 'Sign in to contribute' USING ERRCODE = '42501';
    END IF;
    NEW.user_id := auth.uid();
  END IF;

  NEW.status := 'pending';
  NEW.enrichment := NULL;
  NEW.enrichment_status := 'waiting';
  NEW.enriched_at := NULL;
  NEW.final_payload := NULL;
  NEW.moderator_id := NULL;
  NEW.moderator_note := NULL;
  NEW.reviewed_at := NULL;
  NEW.created_at := NOW();
  NEW.updated_at := NOW();

  IF pg_column_size(NEW.payload) > 32768 THEN
    RAISE EXCEPTION 'Contribution too large';
  END IF;

  SELECT count(*) INTO pending_count
  FROM community_contributions
  WHERE user_id = NEW.user_id AND status IN ('pending', 'needs_info');
  IF pending_count >= 10 THEN
    RAISE EXCEPTION 'Too many pending contributions';
  END IF;

  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_community_contributions_before_insert ON community_contributions;
CREATE TRIGGER trg_community_contributions_before_insert
  BEFORE INSERT ON community_contributions
  FOR EACH ROW EXECUTE FUNCTION public.community_contributions_before_insert();

-- Update by the owner (the only owner transition is needs_info -> pending,
-- i.e. a resubmit): keep identity/moderation columns fixed and queue the
-- item for enrichment again.
CREATE OR REPLACE FUNCTION public.community_contributions_before_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT public.is_privileged_caller() AND NOT public.is_admin() THEN
    NEW.user_id := OLD.user_id;
    NEW.kind := OLD.kind;
    NEW.conference_id := OLD.conference_id;
    NEW.final_payload := OLD.final_payload;
    NEW.moderator_id := OLD.moderator_id;
    NEW.moderator_note := OLD.moderator_note;
    NEW.reviewed_at := OLD.reviewed_at;
    NEW.created_at := OLD.created_at;
    NEW.enrichment := NULL;
    NEW.enrichment_status := 'waiting';
    NEW.enriched_at := NULL;
    IF pg_column_size(NEW.payload) > 32768 THEN
      RAISE EXCEPTION 'Contribution too large';
    END IF;
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_community_contributions_before_update ON community_contributions;
CREATE TRIGGER trg_community_contributions_before_update
  BEFORE UPDATE ON community_contributions
  FOR EACH ROW EXECUTE FUNCTION public.community_contributions_before_update();

-- ------------------------------------------------------------
-- 6. Row level security
-- ------------------------------------------------------------
ALTER TABLE community_contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_tiers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Owner or admin can view contributions" ON community_contributions;
CREATE POLICY "Owner or admin can view contributions"
  ON community_contributions FOR SELECT
  USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS "Signed-in users can submit contributions" ON community_contributions;
CREATE POLICY "Signed-in users can submit contributions"
  ON community_contributions FOR INSERT
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Owner can resubmit after needs_info" ON community_contributions;
CREATE POLICY "Owner can resubmit after needs_info"
  ON community_contributions FOR UPDATE
  USING (auth.uid() = user_id AND status = 'needs_info')
  WITH CHECK (auth.uid() = user_id AND status = 'pending');
-- No DELETE for clients. Admin writes go through moderate_contribution().

DROP POLICY IF EXISTS "Published facts are public" ON community_facts;
CREATE POLICY "Published facts are public"
  ON community_facts FOR SELECT
  USING (is_published OR public.is_admin());

DROP POLICY IF EXISTS "Published tiers are public" ON community_tiers;
CREATE POLICY "Published tiers are public"
  ON community_tiers FOR SELECT
  USING (is_published OR public.is_admin());
-- No client writes on facts/tiers (RPC only).

GRANT SELECT, INSERT, UPDATE ON community_contributions TO authenticated;
GRANT SELECT ON community_facts, community_tiers TO anon, authenticated;
GRANT ALL ON community_contributions, community_facts, community_tiers TO service_role;

-- ------------------------------------------------------------
-- 7. Helpers used by the moderation RPC
-- ------------------------------------------------------------
-- Turn any approved payload into {"fields": {...}, "fees": {...}}. add_info
-- payloads already have that shape; new_event payloads (used on 'merge')
-- are reduced to the keys community_facts accepts.
CREATE OR REPLACE FUNCTION public.community_to_fact_payload(p_final JSONB)
RETURNS JSONB LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  fields JSONB := '{}'::jsonb;
  k TEXT;
  v JSONB;
BEGIN
  IF p_final ? 'fields' THEN
    RETURN p_final;
  END IF;
  FOR k, v IN SELECT * FROM jsonb_each(COALESCE(p_final, '{}'::jsonb)) LOOP
    IF k IN ('start_date', 'end_date', 'start_time', 'venue_name', 'city', 'region', 'event_format',
             'abstract_deadline', 'abstract_open', 'abstract_deadline_note', 'cpd_accredited', 'cpd_points',
             'organiser_url', 'booking_url', 'description', 'note')
       AND v IS NOT NULL AND v <> 'null'::jsonb AND v <> '""'::jsonb THEN
      fields := fields || jsonb_build_object(k, v);
    END IF;
  END LOOP;
  RETURN jsonb_build_object('fields', fields, 'fees', p_final -> 'fees');
END $$;

-- Materialise an approved add_info payload onto a conference as published
-- facts and tiers.
CREATE OR REPLACE FUNCTION public.community_publish_facts(p_contribution UUID, p_conference INTEGER, p_final JSONB)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
  shaped JSONB := public.community_to_fact_payload(p_final);
  k TEXT;
  v JSONB;
  t JSONB;
  n INTEGER := 0;
  cur TEXT := COALESCE(shaped -> 'fees' ->> 'currency', 'GBP');
BEGIN
  FOR k, v IN SELECT * FROM jsonb_each(COALESCE(shaped -> 'fields', '{}'::jsonb)) LOOP
    IF v IS NULL OR v = 'null'::jsonb OR v = '""'::jsonb THEN
      CONTINUE;
    END IF;
    INSERT INTO community_facts (contribution_id, conference_id, field, value, is_published)
    VALUES (p_contribution, p_conference, k, v, TRUE);
    n := n + 1;
  END LOOP;

  FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(shaped -> 'fees' -> 'tiers', '[]'::jsonb)) LOOP
    IF NULLIF(t ->> 'price', '') IS NULL THEN
      CONTINUE;
    END IF;
    INSERT INTO community_tiers (contribution_id, conference_id, tier_label, price, currency, is_early_bird, early_bird_deadline, is_published)
    VALUES (p_contribution, p_conference, COALESCE(NULLIF(t ->> 'label', ''), 'Standard'), (t ->> 'price')::numeric, cur,
            COALESCE((t ->> 'is_early_bird')::boolean, FALSE), NULLIF(t ->> 'early_bird_deadline', '')::date, TRUE);
    n := n + 1;
  END LOOP;

  IF jsonb_array_length(COALESCE(shaped -> 'fees' -> 'tiers', '[]'::jsonb)) = 0
     AND NULLIF(shaped -> 'fees' ->> 'from_price', '') IS NOT NULL THEN
    INSERT INTO community_tiers (contribution_id, conference_id, tier_label, price, currency, is_published)
    VALUES (p_contribution, p_conference, 'Standard', (shaped -> 'fees' ->> 'from_price')::numeric, cur, TRUE);
    n := n + 1;
  END IF;
  RETURN n;
END $$;

-- ------------------------------------------------------------
-- 8. Moderation RPC (admins only). SECURITY DEFINER so the service key
--    never has to leave the scraper: all writes to conferences /
--    pricing_tiers / notifications happen here, under the function owner.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.moderate_contribution(
  p_id UUID,
  p_action TEXT,
  p_note TEXT DEFAULT NULL,
  p_final JSONB DEFAULT NULL
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  c community_contributions%ROWTYPE;
  final JSONB;
  src_url TEXT;
  existing_id INTEGER;
  new_conf_id INTEGER;
  target_id INTEGER;
  t JSONB;
  cur TEXT;
  n_title TEXT;
  n_body TEXT;
  new_status TEXT;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;

  SELECT * INTO c FROM community_contributions WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'contribution % not found', p_id;
  END IF;

  IF p_action = 'approve' THEN
    IF c.status NOT IN ('pending', 'needs_info') THEN
      RAISE EXCEPTION 'only pending items can be approved (status is %)', c.status;
    END IF;
    final := COALESCE(p_final, c.payload);

    IF c.kind = 'new_event' THEN
      src_url := COALESCE(NULLIF(final ->> 'organiser_url', ''), 'community:' || p_id::text);
      SELECT id INTO existing_id FROM conferences WHERE source_url = src_url;
      IF existing_id IS NOT NULL THEN
        RETURN jsonb_build_object('ok', FALSE, 'code', 'duplicate', 'conference_id', existing_id, 'status', c.status);
      END IF;

      INSERT INTO conferences (
        conference_name, specialty, event_type, event_format, is_flagship,
        start_date, end_date, start_time, venue_name, city, region,
        cpd_accredited, cpd_points, abstract_open, abstract_deadline, abstract_deadline_note,
        organiser_url, booking_url, description, source_id, source_url, last_seen_at, archived
      ) VALUES (
        final ->> 'conference_name',
        NULLIF(final ->> 'specialty', ''),
        COALESCE(NULLIF(final ->> 'event_type', ''), 'conference'),
        NULLIF(final ->> 'event_format', ''),
        COALESCE((final ->> 'is_flagship')::boolean, FALSE),
        NULLIF(final ->> 'start_date', '')::date,
        NULLIF(final ->> 'end_date', '')::date,
        NULLIF(final ->> 'start_time', '')::time,
        NULLIF(final ->> 'venue_name', ''),
        NULLIF(final ->> 'city', ''),
        NULLIF(final ->> 'region', ''),
        COALESCE((final ->> 'cpd_accredited')::boolean, FALSE),
        NULLIF(final ->> 'cpd_points', '')::integer,
        COALESCE((final ->> 'abstract_open')::boolean, FALSE),
        NULLIF(final ->> 'abstract_deadline', '')::date,
        NULLIF(final ->> 'abstract_deadline_note', ''),
        NULLIF(final ->> 'organiser_url', ''),
        NULLIF(final ->> 'booking_url', ''),
        NULLIF(final ->> 'description', ''),
        1000, src_url, NOW(), FALSE
      ) RETURNING id INTO new_conf_id;

      cur := COALESCE(final -> 'fees' ->> 'currency', 'GBP');
      FOR t IN SELECT * FROM jsonb_array_elements(COALESCE(final -> 'fees' -> 'tiers', '[]'::jsonb)) LOOP
        IF NULLIF(t ->> 'price', '') IS NULL THEN
          CONTINUE;
        END IF;
        INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency, is_early_bird, early_bird_deadline)
        VALUES (new_conf_id, COALESCE(NULLIF(t ->> 'label', ''), 'Standard'), (t ->> 'price')::numeric, cur,
                COALESCE((t ->> 'is_early_bird')::boolean, FALSE), NULLIF(t ->> 'early_bird_deadline', '')::date);
      END LOOP;
      IF jsonb_array_length(COALESCE(final -> 'fees' -> 'tiers', '[]'::jsonb)) = 0
         AND NULLIF(final -> 'fees' ->> 'from_price', '') IS NOT NULL THEN
        INSERT INTO pricing_tiers (conference_id, tier_label, price_gbp, currency)
        VALUES (new_conf_id, 'Standard', (final -> 'fees' ->> 'from_price')::numeric, cur);
      END IF;

      target_id := new_conf_id;
      new_status := 'published';
      UPDATE community_contributions
         SET status = new_status, conference_id = new_conf_id, final_payload = final,
             moderator_id = auth.uid(), moderator_note = p_note, reviewed_at = NOW(), updated_at = NOW()
       WHERE id = p_id;
      n_title := 'Your event submission is live';
      n_body := COALESCE(final ->> 'conference_name', 'Your event') || ' is now listed on MedConf.';
    ELSE
      target_id := c.conference_id;
      PERFORM public.community_publish_facts(p_id, target_id, final);
      new_status := 'published';
      UPDATE community_contributions
         SET status = new_status, final_payload = final,
             moderator_id = auth.uid(), moderator_note = p_note, reviewed_at = NOW(), updated_at = NOW()
       WHERE id = p_id;
      n_title := 'Your added information is live';
      n_body := 'Thanks — a moderator approved the details you added.';
    END IF;

  ELSIF p_action IN ('needs_info', 'reject') THEN
    IF c.status NOT IN ('pending', 'needs_info') THEN
      RAISE EXCEPTION 'only pending items can be %ed (status is %)', p_action, c.status;
    END IF;
    target_id := c.conference_id;
    new_status := p_action;
    UPDATE community_contributions
       SET status = new_status, moderator_id = auth.uid(), moderator_note = p_note, reviewed_at = NOW(), updated_at = NOW()
     WHERE id = p_id;
    IF p_action = 'needs_info' THEN
      n_title := 'A moderator needs more information';
      n_body := COALESCE(p_note, 'Please check your contribution and resubmit.');
    ELSE
      n_title := 'Your contribution was not published';
      n_body := COALESCE(p_note, 'A moderator reviewed it and decided not to publish it.');
    END IF;

  ELSIF p_action = 'merge' THEN
    IF c.status NOT IN ('pending', 'needs_info') THEN
      RAISE EXCEPTION 'only pending items can be merged (status is %)', c.status;
    END IF;
    target_id := NULLIF(p_final ->> 'merge_into_conference_id', '')::integer;
    IF target_id IS NULL THEN
      RAISE EXCEPTION 'merge_into_conference_id is required';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM conferences WHERE id = target_id) THEN
      RAISE EXCEPTION 'conference % not found', target_id;
    END IF;
    final := COALESCE(p_final - 'merge_into_conference_id', c.payload);
    IF final = '{}'::jsonb THEN
      final := c.payload;
    END IF;
    PERFORM public.community_publish_facts(p_id, target_id, final);
    new_status := 'merged';
    UPDATE community_contributions
       SET status = new_status, conference_id = target_id, final_payload = final,
           moderator_id = auth.uid(), moderator_note = p_note, reviewed_at = NOW(), updated_at = NOW()
     WHERE id = p_id;
    n_title := 'Your contribution was merged into an existing listing';
    n_body := 'The event was already listed; the details you added now appear on it.';

  ELSIF p_action = 'hide' THEN
    IF c.status NOT IN ('published', 'merged') THEN
      RAISE EXCEPTION 'only published items can be hidden (status is %)', c.status;
    END IF;
    UPDATE community_facts SET is_published = FALSE WHERE contribution_id = p_id;
    UPDATE community_tiers SET is_published = FALSE WHERE contribution_id = p_id;
    IF c.kind = 'new_event' AND c.conference_id IS NOT NULL THEN
      UPDATE conferences SET archived = TRUE, updated_at = NOW()
       WHERE id = c.conference_id AND source_id = 1000;
    END IF;
    target_id := c.conference_id;
    new_status := 'hidden';
    UPDATE community_contributions
       SET status = new_status, moderator_id = auth.uid(), moderator_note = COALESCE(p_note, moderator_note),
           reviewed_at = NOW(), updated_at = NOW()
     WHERE id = p_id;
    n_title := 'Your contribution was unpublished';
    n_body := COALESCE(p_note, 'A moderator removed it from the listing.');

  ELSE
    RAISE EXCEPTION 'unknown action %', p_action;
  END IF;

  INSERT INTO notifications (user_id, type, title, body, conference_id)
  VALUES (c.user_id, 'contribution_update', n_title, n_body, target_id);

  RETURN jsonb_build_object('ok', TRUE, 'status', new_status, 'conference_id', target_id);
END $$;

-- ------------------------------------------------------------
-- 9. Expiry (daily digest, service role) — pending items whose event has
--    already happened are closed so nothing lingers in the queue.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.expire_stale_contributions()
RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  r RECORD;
  n INTEGER := 0;
BEGIN
  IF NOT (public.is_admin() OR public.is_privileged_caller()) THEN
    RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
  END IF;

  FOR r IN
    SELECT cc.id, cc.user_id, cc.conference_id
    FROM community_contributions cc
    LEFT JOIN conferences conf ON conf.id = cc.conference_id
    WHERE cc.status IN ('pending', 'needs_info')
      AND (
        (cc.kind = 'add_info' AND conf.archived IS TRUE)
        OR (
          cc.kind = 'new_event'
          AND COALESCE(cc.payload ->> 'end_date', cc.payload ->> 'start_date') ~ '^\d{4}-\d{2}-\d{2}$'
          AND COALESCE(cc.payload ->> 'end_date', cc.payload ->> 'start_date')::date < CURRENT_DATE
        )
      )
  LOOP
    UPDATE community_contributions
       SET status = 'expired', moderator_note = 'Event date passed before review', reviewed_at = NOW(), updated_at = NOW()
     WHERE id = r.id;
    INSERT INTO notifications (user_id, type, title, body, conference_id)
    VALUES (r.user_id, 'contribution_update', 'Your contribution expired',
            'The event date passed before a moderator could review it.', r.conference_id);
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

GRANT EXECUTE ON FUNCTION public.is_admin() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.moderate_contribution(UUID, TEXT, TEXT, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.expire_stale_contributions() TO authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.community_publish_facts(UUID, INTEGER, JSONB) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.community_to_fact_payload(JSONB) FROM PUBLIC;
