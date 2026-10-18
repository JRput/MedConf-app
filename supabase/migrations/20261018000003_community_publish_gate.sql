-- ============================================================
-- Community Contributions — server-side publish gate (2026-10-18)
-- The UI's canApprove() is a convenience; the database must hold the line:
--   * approve/merge refused when the enrichment job rejected the URL
--   * URL fields must point at a public hostname: no IP literals, no
--     localhost, no credentials, no whitespace (DNS cannot be resolved
--     here; the enrichment job does the address-level check)
-- Idempotent.
-- ============================================================

CREATE OR REPLACE FUNCTION public.community_url_ok(v TEXT)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
  SELECT v IS NULL OR v = '' OR (
       v ~* '^https?://[^\s/?#@]+(/[^\s]*)?(\?[^\s]*)?$'       -- scheme://host[/path][?query], no userinfo, no whitespace
   AND length(v) <= 2048
   AND v !~* '^https?://(localhost|127\.|10\.|0\.|169\.254\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|\[|[0-9]+(\.[0-9]+){3}([:/?#]|$))'
  )
$$;

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

  -- The enrichment job marks a submission 'skipped' when its URL failed the
  -- private-address / scheme check. Such an item can never be approved or
  -- merged, whatever the UI sends.
  IF p_action IN ('approve', 'merge') AND c.enrichment_status = 'skipped' THEN
    RAISE EXCEPTION 'This submission''s URL was rejected as unsafe and cannot be published' USING ERRCODE = '22023';
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
