-- Rollback of 20261101000000_account_deletion.sql.
-- Data caveats: dropped user_profiles columns come back EMPTY (their values are gone by design);
-- anonymised contributions have no owner, so restoring NOT NULL on user_id FAILS while any row has
-- user_id IS NULL (delete or reassign those rows first). Deleted accounts are not recoverable.
DROP TRIGGER IF EXISTS trg_notifications_skip_orphan ON public.notifications;
DROP FUNCTION IF EXISTS public.notifications_skip_orphan();
DROP TRIGGER IF EXISTS trg_auth_users_erase_contributions ON auth.users;
DROP FUNCTION IF EXISTS public.auth_users_before_delete();
DROP FUNCTION IF EXISTS public._erase_user_contributions(UUID);
DROP FUNCTION IF EXISTS public.delete_my_account();

-- original guard body (20261018000001_community_hardening.sql), invoker rights
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

ALTER TABLE public.community_contributions DROP CONSTRAINT IF EXISTS community_contributions_moderator_id_fkey;
ALTER TABLE public.community_contributions
  ADD CONSTRAINT community_contributions_moderator_id_fkey FOREIGN KEY (moderator_id) REFERENCES auth.users(id);

ALTER TABLE public.community_contributions DROP CONSTRAINT IF EXISTS community_contributions_user_id_fkey;
ALTER TABLE public.community_contributions
  ADD CONSTRAINT community_contributions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.community_contributions ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS region TEXT,
  ADD COLUMN IF NOT EXISTS institution TEXT,
  ADD COLUMN IF NOT EXISTS country TEXT;
-- default set AFTER the column exists so existing rows stay NULL
ALTER TABLE public.user_profiles ALTER COLUMN country SET DEFAULT 'United Kingdom';
