-- Dry run for 20261101000000_account_deletion.sql. Single transaction, ROLLED BACK: nothing persists.
-- Includes the migration body so it can be run standalone.
BEGIN;

-- ============================================================
-- Self-serve account deletion + data minimisation (2026-11-01)
-- Legal brief 1.5 and 1.8. Applied with medconf-scraper/apply_migration.py.
--
--  (a) community_contributions.user_id becomes nullable, FK ON DELETE SET NULL;
--      moderator_id FK ON DELETE SET NULL (was: no rule, so deleting a moderator failed).
--  (b) public._erase_user_contributions(uid): internal, granted to nobody. Takes the per-user advisory lock
--      (same key as the insert trigger, so a concurrent insert cannot slip in), then
--        - deletes unpublished contributions (pending / needs_info / rejected / expired / hidden; facts / tiers cascade);
--        - keeps published / merged ones with user_id, note, evidence_url set to NULL.
--      It runs from BOTH deletion paths: public.delete_my_account() (SECURITY DEFINER, authenticated only,
--      just deletes the auth.users row) and a BEFORE DELETE trigger on auth.users, so a dashboard / GoTrue
--      admin deletion ends in the identical state. The auth.users delete cascades to user_profiles,
--      notification_preferences, saved_conferences, user_reminders and notifications.
--  (c) Trigger fixes that the above REQUIRES (the existing guards would silently undo it):
--        - community_contributions_before_update() resets user_id / moderator_id / enrichment for any
--          non-privileged caller (privileged = session_user postgres|supabase_admin or service role,
--          NOT the definer role). It now returns early (1) inside delete_my_account() (transaction-local
--          setting medconf.account_deletion = 'on', which PostgREST clients cannot set; it is left on until the
--          transaction ends) and (2) when the referenced auth user is already gone. In both cases ONLY user_id,
--          moderator_id, note, evidence_url may change, and only to NULL; anything else falls through to the
--          normal checks. The function is SECURITY DEFINER so it can read auth.users.
--        - notifications.user_id is NOT NULL and moderate_contribution() inserts a 'contribution_update'
--          notification for c.user_id; moderating an anonymised row (e.g. unpublishing) would raise. A BEFORE
--          INSERT trigger now drops (and RAISE LOGs) only 'contribution_update' rows with user_id IS NULL;
--          every other type still fails loudly on NOT NULL.
--  (d) RLS: no change needed. Every owner policy on community_contributions uses auth.uid() = user_id,
--      which is never true for a NULL owner; admins can still read anonymised rows; facts / tiers policies
--      depend only on is_published. A NULL-owner row is therefore not readable or editable by any new party.
--  (e) user_profiles minimisation: DROP DEFAULT on country, then DROP COLUMN institution, region, country.
--      Decision = DROP. Evidence: no website file reads or writes them (onboarding upsert writes id, email,
--      role, specialty, profile_completed_at, last_specialty_alert_at only; settings / dashboard / middleware /
--      useIsAdmin / useModeration select other columns), the scraper reads only id, email, specialty,
--      last_specialty_alert_at, is_admin, no view or function references them. The unused UserProfile
--      interface in medconf-website/src/lib/types.ts still lists them (type only; owner of that file to trim).
-- Grants: unchanged elsewhere. Idempotent to re-apply. No BEGIN/COMMIT.
-- ============================================================

SET LOCAL lock_timeout = '10s';

-- (a) ownership columns --------------------------------------------------
ALTER TABLE public.community_contributions ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE public.community_contributions DROP CONSTRAINT IF EXISTS community_contributions_user_id_fkey;
ALTER TABLE public.community_contributions
  ADD CONSTRAINT community_contributions_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.community_contributions DROP CONSTRAINT IF EXISTS community_contributions_moderator_id_fkey;
ALTER TABLE public.community_contributions
  ADD CONSTRAINT community_contributions_moderator_id_fkey
  FOREIGN KEY (moderator_id) REFERENCES auth.users(id) ON DELETE SET NULL;

-- (c1) update guard: let account deletion through ------------------------
CREATE OR REPLACE FUNCTION public.community_contributions_before_update()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth AS $$
BEGIN
  -- Account deletion (setting set by _erase_user_contributions, or an FK SET NULL after the auth user is gone).
  -- Only user_id / moderator_id / note / evidence_url may change, and only to NULL; else normal checks.
  IF (COALESCE(current_setting('medconf.account_deletion', true), '') = 'on'
      OR (OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = OLD.user_id))
      OR (OLD.moderator_id IS NOT NULL AND NEW.moderator_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = OLD.moderator_id)))
     AND (to_jsonb(NEW) - ARRAY['user_id','moderator_id','note','evidence_url','updated_at'])
         = (to_jsonb(OLD) - ARRAY['user_id','moderator_id','note','evidence_url','updated_at'])
     AND (NEW.user_id IS NULL OR NEW.user_id IS NOT DISTINCT FROM OLD.user_id)
     AND (NEW.moderator_id IS NULL OR NEW.moderator_id IS NOT DISTINCT FROM OLD.moderator_id)
     AND (NEW.note IS NULL OR NEW.note IS NOT DISTINCT FROM OLD.note)
     AND (NEW.evidence_url IS NULL OR NEW.evidence_url IS NOT DISTINCT FROM OLD.evidence_url) THEN
    NEW.updated_at := NOW();
    RETURN NEW;
  END IF;

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

-- (c2) notifications for an anonymised contribution are skipped ----------
CREATE OR REPLACE FUNCTION public.notifications_skip_orphan()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.user_id IS NULL AND NEW.type = 'contribution_update' THEN
    RAISE LOG 'notifications_skip_orphan: dropped contribution_update notification (conference_id=%) for a deleted account', NEW.conference_id;
    RETURN NULL;   -- row dropped: the recipient deleted their account
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_notifications_skip_orphan ON public.notifications;
CREATE TRIGGER trg_notifications_skip_orphan
  BEFORE INSERT ON public.notifications
  FOR EACH ROW EXECUTE FUNCTION public.notifications_skip_orphan();

-- (b) shared erase logic + both deletion paths ----------------------------
CREATE OR REPLACE FUNCTION public._erase_user_contributions(uid UUID)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth AS $$
BEGIN
  -- Same key as the insert trigger: a concurrent insert by this user waits, then fails its FK.
  PERFORM pg_advisory_xact_lock(hashtext(uid::text));
  -- Transaction-local marker read by community_contributions_before_update().
  PERFORM set_config('medconf.account_deletion', 'on', true);

  -- Unpublished contributions go (their facts / tiers cascade).
  DELETE FROM public.community_contributions
   WHERE user_id = uid AND status NOT IN ('published', 'merged');

  -- Published / merged contributions stay, anonymised.
  UPDATE public.community_contributions
     SET user_id = NULL, note = NULL, evidence_url = NULL
   WHERE user_id = uid;
END $$;

REVOKE ALL ON FUNCTION public._erase_user_contributions(UUID) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.auth_users_before_delete()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth AS $$
BEGIN
  PERFORM public._erase_user_contributions(OLD.id);
  RETURN OLD;
END $$;

REVOKE ALL ON FUNCTION public.auth_users_before_delete() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_auth_users_erase_contributions ON auth.users;
CREATE TRIGGER trg_auth_users_erase_contributions
  BEFORE DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.auth_users_before_delete();

CREATE OR REPLACE FUNCTION public.delete_my_account()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth AS $$
DECLARE
  uid UUID := auth.uid();
BEGIN
  IF uid IS NULL THEN
    RAISE EXCEPTION 'Sign in required' USING ERRCODE = '42501';
  END IF;

  -- The BEFORE DELETE trigger erases the contributions; the delete cascades to user_profiles,
  -- notification_preferences, saved_conferences, user_reminders, notifications, and SET NULLs
  -- community_contributions.moderator_id where this user moderated.
  DELETE FROM auth.users WHERE id = uid;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Account not found' USING ERRCODE = 'P0002';
  END IF;
END $$;

REVOKE ALL ON FUNCTION public.delete_my_account() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.delete_my_account() TO authenticated;

-- (e) user_profiles minimisation -----------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'user_profiles' AND column_name = 'country') THEN
    ALTER TABLE public.user_profiles ALTER COLUMN country DROP DEFAULT;
  END IF;
END $$;

ALTER TABLE public.user_profiles
  DROP COLUMN IF EXISTS institution,
  DROP COLUMN IF EXISTS region,
  DROP COLUMN IF EXISTS country;

-- ---------------- fixtures (privileged: session_user postgres) ----------------
DO $t$
DECLARE
  a UUID := gen_random_uuid();   -- account that deletes itself
  m UUID := gen_random_uuid();   -- moderator of a's published contribution (deletes itself later)
  b UUID := gen_random_uuid();   -- bystander
  n UUID := gen_random_uuid();   -- moderator of b's published contribution (deleted "from the dashboard")
  q UUID := gen_random_uuid();   -- owner deleted by plain DELETE FROM auth.users (dashboard path)
  c_q_pend UUID; c_q_pub UUID;
  cid INTEGER;
  c_pend UUID; c_pub UUID; c_b_pub UUID; c_b_nin UUID;
  caught BOOLEAN;
BEGIN
  INSERT INTO auth.users (id, email, aud, role) VALUES
    (a, 'dry-a@dry-run.invalid', 'authenticated', 'authenticated'),
    (m, 'dry-m@dry-run.invalid', 'authenticated', 'authenticated'),
    (b, 'dry-b@dry-run.invalid', 'authenticated', 'authenticated'),
    (n, 'dry-n@dry-run.invalid', 'authenticated', 'authenticated'),
    (q, 'dry-q@dry-run.invalid', 'authenticated', 'authenticated');
  INSERT INTO public.user_profiles (id, email, role, specialty) VALUES
    (a, 'dry-a@dry-run.invalid', 'consultant', 'cardiology'),
    (m, 'dry-m@dry-run.invalid', 'consultant', 'cardiology'),
    (b, 'dry-b@dry-run.invalid', 'consultant', 'cardiology');
  INSERT INTO public.notification_preferences (id) VALUES (a), (b);
  INSERT INTO conferences (conference_name, source_url) VALUES ('dry-run account deletion', 'https://dry-run.invalid/acct') RETURNING id INTO cid;
  INSERT INTO public.saved_conferences (user_id, conference_id) VALUES (a, cid), (b, cid);
  INSERT INTO public.notifications (user_id, type, title) VALUES (a, 'system', 'dry'), (b, 'system', 'dry');

  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload, note, evidence_url)
    VALUES (a, 'add_info', cid, '{}'::jsonb, 'private note', 'https://dry-run.invalid/e') RETURNING id INTO c_pend;
  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload, note, evidence_url)
    VALUES (a, 'add_info', cid, '{}'::jsonb, 'private note', 'https://dry-run.invalid/e') RETURNING id INTO c_pub;
  UPDATE public.community_contributions SET status = 'published', moderator_id = m, enrichment_status = 'fetched' WHERE id = c_pub;
  INSERT INTO public.community_facts (contribution_id, conference_id, field, value, is_published) VALUES (c_pub, cid, 'note', '"x"'::jsonb, TRUE);
  INSERT INTO public.community_tiers (contribution_id, conference_id, tier_label, price, is_published) VALUES (c_pub, cid, 'Standard', 10, TRUE);

  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload, note)
    VALUES (b, 'add_info', cid, '{}'::jsonb, 'b note') RETURNING id INTO c_b_pub;
  UPDATE public.community_contributions SET status = 'published', moderator_id = n WHERE id = c_b_pub;
  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload)
    VALUES (b, 'add_info', cid, '{}'::jsonb) RETURNING id INTO c_b_nin;
  UPDATE public.community_contributions SET status = 'needs_info' WHERE id = c_b_nin;

  INSERT INTO public.user_profiles (id, email, role, specialty) VALUES (q, 'dry-q@dry-run.invalid', 'consultant', 'cardiology');
  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload, note, evidence_url)
    VALUES (q, 'add_info', cid, '{}'::jsonb, 'q note', 'https://dry-run.invalid/q') RETURNING id INTO c_q_pend;
  INSERT INTO public.community_contributions (user_id, kind, conference_id, payload, note, evidence_url)
    VALUES (q, 'add_info', cid, '{}'::jsonb, 'q note', 'https://dry-run.invalid/q') RETURNING id INTO c_q_pub;
  UPDATE public.community_contributions SET status = 'published', moderator_id = n, enrichment_status = 'fetched' WHERE id = c_q_pub;

  -- Simulate PostgREST: from here the caller is NOT privileged (rolled back with the transaction).
  CREATE OR REPLACE FUNCTION public.is_privileged_caller() RETURNS BOOLEAN LANGUAGE sql STABLE AS 'SELECT FALSE';

  -- T0: grants
  IF NOT has_function_privilege('authenticated', 'public.delete_my_account()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.delete_my_account()', 'EXECUTE')
     OR has_function_privilege('public', 'public.delete_my_account()', 'EXECUTE') THEN
    RAISE EXCEPTION 'T0: grants wrong';
  END IF;

  -- T1: anon cannot execute
  caught := FALSE;
  SET LOCAL ROLE anon;
  BEGIN PERFORM public.delete_my_account(); EXCEPTION WHEN insufficient_privilege THEN caught := TRUE; END;
  RESET ROLE;
  IF NOT caught THEN RAISE EXCEPTION 'T1: anon could execute delete_my_account'; END IF;

  -- T2: authenticated with no subject is rejected
  caught := FALSE;
  PERFORM set_config('request.jwt.claims', '', true);
  PERFORM set_config('request.jwt.claim.sub', '', true);
  SET LOCAL ROLE authenticated;
  BEGIN PERFORM public.delete_my_account(); EXCEPTION WHEN insufficient_privilege THEN caught := TRUE; END;
  RESET ROLE;
  IF NOT caught THEN RAISE EXCEPTION 'T2: call without a user was accepted'; END IF;

  -- T3: a client cannot detach its own contribution via UPDATE (guard still active for non-privileged callers)
  PERFORM set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  PERFORM set_config('request.jwt.claim.sub', b::text, true);
  SET LOCAL ROLE authenticated;
  UPDATE public.community_contributions SET user_id = NULL, status = 'pending' WHERE id = c_b_nin;
  RESET ROLE;
  IF (SELECT user_id FROM public.community_contributions WHERE id = c_b_nin) IS DISTINCT FROM b THEN
    RAISE EXCEPTION 'T3: client detached its own contribution';
  END IF;

  -- T4: a deleted account's notifications cannot be created (orphan insert is dropped, not an error)
  INSERT INTO public.notifications (user_id, type, title) VALUES (NULL, 'contribution_update', 'orphan');
  IF EXISTS (SELECT 1 FROM public.notifications WHERE title = 'orphan') THEN RAISE EXCEPTION 'T4: orphan notification stored'; END IF;
  caught := FALSE;
  BEGIN INSERT INTO public.notifications (user_id, type, title) VALUES (NULL, 'system', 'orphan2');
  EXCEPTION WHEN not_null_violation THEN caught := TRUE; END;
  IF NOT caught THEN RAISE EXCEPTION 'T4b: non-contribution orphan notification did not fail loudly'; END IF;

  -- T3b: forged marker + a change outside the four columns falls through to the normal checks
  PERFORM set_config('medconf.account_deletion', 'on', true);
  PERFORM set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  PERFORM set_config('request.jwt.claim.sub', b::text, true);
  SET LOCAL ROLE authenticated;
  UPDATE public.community_contributions SET user_id = NULL, status = 'pending' WHERE id = c_b_nin;
  RESET ROLE;
  PERFORM set_config('medconf.account_deletion', '', true);
  IF (SELECT user_id FROM public.community_contributions WHERE id = c_b_nin) IS DISTINCT FROM b THEN
    RAISE EXCEPTION 'T3b: forged marker detached a contribution';
  END IF;

  -- T5: a deletes own account
  PERFORM set_config('request.jwt.claims', json_build_object('sub', a, 'role', 'authenticated')::text, true);
  PERFORM set_config('request.jwt.claim.sub', a::text, true);
  SET LOCAL ROLE authenticated;
  PERFORM public.delete_my_account();
  RESET ROLE;

  IF EXISTS (SELECT 1 FROM auth.users WHERE id = a) THEN RAISE EXCEPTION 'T5a: auth user remains'; END IF;
  IF EXISTS (SELECT 1 FROM public.user_profiles WHERE id = a) THEN RAISE EXCEPTION 'T5b: profile remains'; END IF;
  IF EXISTS (SELECT 1 FROM public.notification_preferences WHERE id = a) THEN RAISE EXCEPTION 'T5c: preferences remain'; END IF;
  IF EXISTS (SELECT 1 FROM public.saved_conferences WHERE user_id = a) THEN RAISE EXCEPTION 'T5d: saved rows remain'; END IF;
  IF EXISTS (SELECT 1 FROM public.notifications WHERE user_id = a) THEN RAISE EXCEPTION 'T5e: notifications remain'; END IF;
  IF EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_pend) THEN RAISE EXCEPTION 'T5f: pending contribution remains'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.community_contributions
                  WHERE id = c_pub AND user_id IS NULL AND note IS NULL AND evidence_url IS NULL AND status = 'published' AND moderator_id = m) THEN
    RAISE EXCEPTION 'T5g: published contribution not anonymised as expected';
  END IF;
  IF (SELECT enrichment_status FROM public.community_contributions WHERE id = c_pub) <> 'fetched' THEN RAISE EXCEPTION 'T5h: enrichment state reset on kept row'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.community_facts WHERE contribution_id = c_pub AND is_published)
     OR NOT EXISTS (SELECT 1 FROM public.community_tiers WHERE contribution_id = c_pub AND is_published) THEN
    RAISE EXCEPTION 'T5i: fact / tier lost';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = m) OR NOT EXISTS (SELECT 1 FROM public.user_profiles WHERE id = m) THEN
    RAISE EXCEPTION 'T5j: moderator affected';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = b) OR NOT EXISTS (SELECT 1 FROM public.saved_conferences WHERE user_id = b)
     OR NOT EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_b_pub AND user_id = b) THEN
    RAISE EXCEPTION 'T5k: bystander affected';
  END IF;
  -- anonymised row is invisible to a non-admin signed-in user
  PERFORM set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  PERFORM set_config('request.jwt.claim.sub', b::text, true);
  SET LOCAL ROLE authenticated;
  IF EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_pub) THEN RAISE EXCEPTION 'T5l: NULL-owner row readable by another user'; END IF;
  RESET ROLE;

  -- T6: moderator m (still referenced by c_pub) deletes their own account: moderator_id is nulled, row kept
  PERFORM set_config('request.jwt.claims', json_build_object('sub', m, 'role', 'authenticated')::text, true);
  PERFORM set_config('request.jwt.claim.sub', m::text, true);
  SET LOCAL ROLE authenticated;
  PERFORM public.delete_my_account();
  RESET ROLE;
  IF NOT EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_pub AND moderator_id IS NULL AND user_id IS NULL) THEN
    RAISE EXCEPTION 'T6: moderator deletion did not null moderator_id / keep the row';
  END IF;

  PERFORM set_config('medconf.account_deletion', '', true);
  -- T7: deletion by another path (dashboard / GoTrue admin) with the guard active: FK SET NULL must pass
  PERFORM set_config('request.jwt.claims', '', true);
  PERFORM set_config('request.jwt.claim.sub', '', true);
  DELETE FROM auth.users WHERE id = n;
  IF NOT EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_b_pub AND moderator_id IS NULL AND user_id = b) THEN
    RAISE EXCEPTION 'T7: direct auth user delete did not null moderator_id';
  END IF;

  -- T9: plain DELETE FROM auth.users (dashboard / GoTrue path) ends in the same state as the RPC path
  PERFORM set_config('medconf.account_deletion', '', true);
  DELETE FROM auth.users WHERE id = q;
  IF EXISTS (SELECT 1 FROM public.community_contributions WHERE id = c_q_pend) THEN RAISE EXCEPTION 'T9a: pending contribution remains'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.community_contributions
                  WHERE id = c_q_pub AND user_id IS NULL AND note IS NULL AND evidence_url IS NULL AND status = 'published' AND moderator_id IS NULL AND enrichment_status = 'fetched') THEN
    RAISE EXCEPTION 'T9b: published contribution not anonymised as via the RPC';
  END IF;
  IF EXISTS (SELECT 1 FROM public.user_profiles WHERE id = q) THEN RAISE EXCEPTION 'T9c: profile remains'; END IF;

  -- T8: dropped columns are gone
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='user_profiles' AND column_name IN ('institution','region','country')) THEN
    RAISE EXCEPTION 'T8: minimised columns still present';
  END IF;
END $t$;

ROLLBACK;
