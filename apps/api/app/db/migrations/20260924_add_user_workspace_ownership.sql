-- Add explicit ownership boundaries for user workspaces.

ALTER TABLE public.user_profiles
  ADD CONSTRAINT user_profiles_auth_user_id_fkey
  FOREIGN KEY (id) REFERENCES public.auth_users(id);

-- Existing records belong to the original profile (id 1).
-- New application users use a profile id matching auth_users.id.

ALTER TABLE public.content_items
  ADD COLUMN IF NOT EXISTS profile_id INTEGER;

UPDATE public.content_items
SET profile_id = 1
WHERE profile_id IS NULL;

ALTER TABLE public.content_items
  ALTER COLUMN profile_id SET NOT NULL;

ALTER TABLE public.content_items
  ADD CONSTRAINT content_items_profile_id_fkey
  FOREIGN KEY (profile_id) REFERENCES public.user_profiles(id);

CREATE INDEX IF NOT EXISTS idx_content_items_profile_id
  ON public.content_items(profile_id);

ALTER TABLE public.agent_runs
  ADD COLUMN IF NOT EXISTS user_id INTEGER;

UPDATE public.agent_runs
SET user_id = 1
WHERE user_id IS NULL;

ALTER TABLE public.agent_runs
  ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE public.agent_runs
  ADD CONSTRAINT agent_runs_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES public.auth_users(id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id
  ON public.agent_runs(user_id);

UPDATE public.user_profiles
SET display_name = 'Kanishka Utsav'
WHERE id = 1;

INSERT INTO public.user_profiles (id, display_name, role, created_at, updated_at)
SELECT id, COALESCE(display_name, split_part(email, '@', 1)), COALESCE(role, 'user'), now(), now()
FROM public.auth_users
WHERE NOT EXISTS (
  SELECT 1 FROM public.user_profiles p WHERE p.id = public.auth_users.id
);
