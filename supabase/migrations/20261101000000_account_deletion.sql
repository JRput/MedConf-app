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
