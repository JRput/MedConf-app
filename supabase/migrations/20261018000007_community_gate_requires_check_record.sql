-- ============================================================
-- Community Contributions — publish gate requires the check record (2026-10-18)
-- enrich_submissions.py pre-marks a row enrichment_status='failed' before it
-- fetches; if the job dies before the address check the row stays 'failed'.
-- approve/merge now also require enrichment->>'_submitted_url' (written only
-- after the check ran) unless approve_unchecked is set. Order: skipped,
-- waiting, missing check record, URL mismatch. Idempotent. Body otherwise
-- identical to 20261018000006.
-- ============================================================

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
  existing_archived BOOLEAN;
  existing_source INTEGER;
  new_conf_id INTEGER;
  target_id INTEGER;
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
  IF p_action IN ('approve', 'merge') THEN
    -- Fail closed: the organiser URL must have passed the enrichment job's
    -- address check ('fetched', 'blocked' and 'failed' all happen after that
    -- check; 'skipped' means it failed; 'waiting' means not yet checked).
    IF c.enrichment_status = 'skipped' THEN
      RAISE EXCEPTION 'This submission''s URL was rejected as unsafe and cannot be published' USING ERRCODE = '22023';
    END IF;
    IF c.enrichment_status = 'waiting' AND COALESCE((p_final ->> 'approve_unchecked')::boolean, FALSE) IS NOT TRUE THEN
      RAISE EXCEPTION 'This submission''s URL has not been safety-checked yet (next check within 6 hours). Approve anyway requires an explicit override.' USING ERRCODE = '22023';
    END IF;
    -- The address check must have actually run: the enrichment job pre-marks a
    -- row 'failed' before fetching, so status alone is not proof.
    IF COALESCE((p_final ->> 'approve_unchecked')::boolean, FALSE) IS NOT TRUE
       AND NOT (c.enrichment IS NOT NULL AND c.enrichment ? '_submitted_url' AND c.enrichment ->> '_submitted_url' IS NOT NULL) THEN
      RAISE EXCEPTION 'This submission has no completed safety check yet. Approve anyway requires an explicit override.' USING ERRCODE = '22023';
    END IF;
    -- Bind the approval to the URL that was actually checked: if the moderator
    -- (or a resubmit) changed the organiser URL, it must be re-checked or
    -- explicitly overridden.
    IF c.enrichment ? '_checked_url'
       AND COALESCE(p_final ->> 'organiser_url', c.payload ->> 'organiser_url') IS DISTINCT FROM c.enrichment ->> '_checked_url'
       AND COALESCE(p_final ->> 'organiser_url', c.payload ->> 'organiser_url') IS DISTINCT FROM c.enrichment ->> '_submitted_url'
       AND COALESCE((p_final ->> 'approve_unchecked')::boolean, FALSE) IS NOT TRUE THEN
      RAISE EXCEPTION 'The organiser URL differs from the one that was safety-checked. Approve anyway requires an explicit override.' USING ERRCODE = '22023';
    END IF;
  END IF;

  IF p_action = 'approve' THEN
    IF c.status NOT IN ('pending', 'needs_info') THEN
      RAISE EXCEPTION 'only pending items can be approved (status is %)', c.status;
    END IF;
    final := COALESCE(p_final, c.payload) - 'approve_unchecked';
    IF (final ->> 'organiser_url') IS NOT NULL AND c.enrichment -> '_rejected_urls' ? (final ->> 'organiser_url') THEN
      RAISE EXCEPTION 'The organiser URL was rejected by the safety check and cannot be published' USING ERRCODE = '22023';
    END IF;
    final := public.community_strip_rejected(final, c.enrichment -> '_rejected_urls');
    PERFORM public.community_validate_payload(final);

    IF c.kind = 'new_event' THEN
      src_url := COALESCE(NULLIF(final ->> 'organiser_url', ''), 'community:' || p_id::text);
      SELECT id, archived, source_id INTO existing_id, existing_archived, existing_source
        FROM conferences WHERE source_url = src_url;
      IF existing_id IS NOT NULL AND NOT (existing_archived IS TRUE AND existing_source = 1000) THEN
        RETURN jsonb_build_object('ok', FALSE, 'code', 'duplicate', 'conference_id', existing_id, 'status', c.status);
      END IF;

      IF existing_id IS NOT NULL THEN
        -- republish: a hidden (archived) community event for the same organiser URL
        UPDATE conferences SET
             conference_name = final ->> 'conference_name',
             specialty = NULLIF(final ->> 'specialty', ''),
             event_type = COALESCE(NULLIF(final ->> 'event_type', ''), 'conference'),
             event_format = NULLIF(final ->> 'event_format', ''),
             is_flagship = COALESCE((final ->> 'is_flagship')::boolean, FALSE),
             start_date = NULLIF(final ->> 'start_date', '')::date,
             end_date = NULLIF(final ->> 'end_date', '')::date,
             start_time = NULLIF(final ->> 'start_time', '')::time,
             venue_name = NULLIF(final ->> 'venue_name', ''),
             city = NULLIF(final ->> 'city', ''),
             region = NULLIF(final ->> 'region', ''),
             cpd_accredited = COALESCE((final ->> 'cpd_accredited')::boolean, FALSE),
             cpd_points = NULLIF(final ->> 'cpd_points', '')::integer,
             abstract_open = COALESCE((final ->> 'abstract_open')::boolean, FALSE),
             abstract_deadline = NULLIF(final ->> 'abstract_deadline', '')::date,
             abstract_deadline_note = NULLIF(final ->> 'abstract_deadline_note', ''),
             organiser_url = NULLIF(final ->> 'organiser_url', ''),
             booking_url = NULLIF(final ->> 'booking_url', ''),
             description = NULLIF(final ->> 'description', ''),
             source_id = 1000, archived = FALSE, last_seen_at = NOW(), updated_at = NOW()
         WHERE id = existing_id;
        DELETE FROM pricing_tiers WHERE conference_id = existing_id;
        new_conf_id := existing_id;
      ELSE
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
      END IF;

      PERFORM public.community_upsert_tiers(new_conf_id, final -> 'fees');

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
    final := COALESCE(p_final - 'merge_into_conference_id' - 'approve_unchecked', c.payload);
    IF final = '{}'::jsonb THEN
      final := c.payload;
    END IF;
    IF (final ->> 'organiser_url') IS NOT NULL AND c.enrichment -> '_rejected_urls' ? (final ->> 'organiser_url') THEN
      RAISE EXCEPTION 'The organiser URL was rejected by the safety check and cannot be published' USING ERRCODE = '22023';
    END IF;
    final := public.community_strip_rejected(final, c.enrichment -> '_rejected_urls');
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
    IF c.kind = 'new_event' AND c.status = 'published' AND c.conference_id IS NOT NULL THEN
      -- only the event this contribution created: community source, and the
      -- source_url this contribution's approval would have used
      UPDATE conferences SET archived = TRUE, updated_at = NOW()
       WHERE id = c.conference_id AND source_id = 1000
         AND source_url = COALESCE(NULLIF(c.final_payload ->> 'organiser_url', ''), 'community:' || c.id::text);
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
