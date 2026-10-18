-- ============================================================
-- Community Contributions — hardening (2026-10-18, follows 20261018000000)
-- Addresses the automated security review of the first migration:
--   * server-side validation of URLs / lengths / tier count on every
--     write path (insert, owner resubmit, approve, merge, publish_facts)
--   * per-user advisory lock so the 10-pending cap cannot be raced
--   * admins may read user_profiles (moderation shows the submitter)
--   * moderate_contribution() also accepts the service role (automation,
--     end-to-end tests); it already bypasses RLS everywhere else
-- Idempotent.
-- ============================================================

-- NULL / empty is fine (optional fields); anything present must be http(s).
CREATE OR REPLACE FUNCTION public.community_url_ok(v TEXT)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
  SELECT v IS NULL OR v = '' OR (v ~* '^https?://[^\s]+$' AND length(v) <= 2048)
$$;

CREATE OR REPLACE FUNCTION public.community_validate_payload(p JSONB)
RETURNS VOID LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p IS NULL OR jsonb_typeof(p) <> 'object' THEN
    RAISE EXCEPTION 'payload must be a JSON object';
  END IF;
  IF NOT public.community_url_ok(p ->> 'organiser_url')
     OR NOT public.community_url_ok(p ->> 'booking_url')
     OR NOT public.community_url_ok(p ->> 'evidence_url')
     OR NOT public.community_url_ok(p -> 'fields' ->> 'organiser_url')
     OR NOT public.community_url_ok(p -> 'fields' ->> 'booking_url') THEN
    RAISE EXCEPTION 'URLs must start with http:// or https://';
  END IF;
  IF length(COALESCE(p ->> 'conference_name', '')) > 200
     OR length(COALESCE(p ->> 'description', '')) > 2000
     OR length(COALESCE(p -> 'fields' ->> 'description', '')) > 2000
     OR length(COALESCE(p -> 'fields' ->> 'note', '')) > 1000
     OR length(COALESCE(p ->> 'note', '')) > 1000 THEN
    RAISE EXCEPTION 'Text too long';
  END IF;
  IF jsonb_typeof(p -> 'fees' -> 'tiers') = 'array' AND jsonb_array_length(p -> 'fees' -> 'tiers') > 12 THEN
    RAISE EXCEPTION 'Too many fee tiers';
  END IF;
END $$;

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

  -- Serialise per user so two concurrent inserts cannot both pass the cap.
  PERFORM pg_advisory_xact_lock(hashtext(NEW.user_id::text));
  PERFORM public.community_validate_payload(NEW.payload);
  IF NOT public.community_url_ok(NEW.evidence_url) THEN
    RAISE EXCEPTION 'URLs must start with http:// or https://';
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
    PERFORM public.community_validate_payload(NEW.payload);
    IF NOT public.community_url_ok(NEW.evidence_url) THEN
      RAISE EXCEPTION 'URLs must start with http:// or https://';
    END IF;
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END $$;

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
    IF k IN ('organiser_url', 'booking_url') AND NOT public.community_url_ok(v #>> '{}') THEN
      RAISE EXCEPTION 'URLs must start with http:// or https://';
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
  IF NOT (public.is_admin() OR public.is_privileged_caller()) THEN
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
    PERFORM public.community_validate_payload(final);

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
    PERFORM public.community_validate_payload(final);
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

-- Moderators need to see who submitted an item. is_admin() is SECURITY
-- DEFINER, so this policy does not recurse through RLS.
DROP POLICY IF EXISTS "Admins can view profiles" ON user_profiles;
CREATE POLICY "Admins can view profiles"
  ON user_profiles FOR SELECT
  USING (public.is_admin());

REVOKE EXECUTE ON FUNCTION public.community_validate_payload(JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.community_url_ok(TEXT) TO anon, authenticated, service_role;
