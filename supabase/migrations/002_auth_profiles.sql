-- ================================================================
-- MIGRATION: 002_auth_profiles.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: auth-core · Neon Branch: [confirm_neon_branch] · Depends on: 001
-- Preserves: Mongo runtime untouched; additive Supabase profile bridge only
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email CITEXT,
  full_name TEXT,
  avatar_url TEXT,
  auth_provider TEXT NOT NULL DEFAULT 'email',
  system_role public.user_role_type NOT NULL DEFAULT 'customer',
  legacy_user_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE public.user_profiles IS 'Supabase-auth-linked profile records. This table is additive and does not replace the legacy Mongo users collection until cutover.';
COMMENT ON COLUMN public.user_profiles.system_role IS 'Global system role. Use platform_admin only for service-level support users.';

-- STEP 4: Indexes
CREATE UNIQUE INDEX IF NOT EXISTS user_profiles_email_unique_idx
  ON public.user_profiles (email)
  WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_profiles_system_role_idx
  ON public.user_profiles (system_role);

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "user_profiles_select" ON public.user_profiles;
CREATE POLICY "user_profiles_select" ON public.user_profiles
  FOR SELECT
  TO authenticated
  USING (id = auth.uid());

DROP POLICY IF EXISTS "user_profiles_update" ON public.user_profiles;
CREATE POLICY "user_profiles_update" ON public.user_profiles
  FOR UPDATE
  TO authenticated
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS "user_profiles_auth_admin_select" ON public.user_profiles;
CREATE POLICY "user_profiles_auth_admin_select" ON public.user_profiles
  FOR SELECT
  TO supabase_auth_admin
  USING (TRUE);

DROP POLICY IF EXISTS "user_profiles_auth_admin_insert" ON public.user_profiles;
CREATE POLICY "user_profiles_auth_admin_insert" ON public.user_profiles
  FOR INSERT
  TO supabase_auth_admin
  WITH CHECK (TRUE);

DROP POLICY IF EXISTS "user_profiles_auth_admin_update" ON public.user_profiles;
CREATE POLICY "user_profiles_auth_admin_update" ON public.user_profiles
  FOR UPDATE
  TO supabase_auth_admin
  USING (TRUE)
  WITH CHECK (TRUE);

-- STEP 6: Triggers (updated_at + business logic)
CREATE OR REPLACE FUNCTION public.handle_auth_user_profile_sync()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  derived_name TEXT;
  derived_provider TEXT;
  derived_system_role public.user_role_type;
BEGIN
  derived_name := COALESCE(
    NULLIF(TRIM(NEW.raw_user_meta_data ->> 'name'), ''),
    NULLIF(TRIM(NEW.raw_user_meta_data ->> 'full_name'), ''),
    NULLIF(TRIM(NEW.raw_user_meta_data ->> 'display_name'), ''),
    NULLIF(TRIM(SPLIT_PART(COALESCE(NEW.email, ''), '@', 1)), '')
  );

  derived_provider := COALESCE(
    NULLIF(TRIM(NEW.raw_app_meta_data ->> 'provider'), ''),
    'email'
  );

  derived_system_role := CASE LOWER(COALESCE(NEW.raw_app_meta_data ->> 'system_role', ''))
    WHEN 'platform_admin' THEN 'platform_admin'::public.user_role_type
    ELSE 'customer'::public.user_role_type
  END;

  INSERT INTO public.user_profiles (
    id,
    email,
    full_name,
    avatar_url,
    auth_provider,
    system_role,
    created_at,
    updated_at
  )
  VALUES (
    NEW.id,
    NULLIF(TRIM(LOWER(NEW.email)), '')::citext,
    derived_name,
    NULLIF(TRIM(COALESCE(NEW.raw_user_meta_data ->> 'avatar_url', NEW.raw_user_meta_data ->> 'picture')), ''),
    derived_provider,
    derived_system_role,
    NOW(),
    NOW()
  )
  ON CONFLICT (id) DO UPDATE
  SET email = EXCLUDED.email,
      full_name = COALESCE(EXCLUDED.full_name, public.user_profiles.full_name),
      avatar_url = COALESCE(EXCLUDED.avatar_url, public.user_profiles.avatar_url),
      auth_provider = EXCLUDED.auth_provider,
      system_role = CASE
        WHEN public.user_profiles.system_role = 'platform_admin'::public.user_role_type
          THEN public.user_profiles.system_role
        ELSE EXCLUDED.system_role
      END,
      updated_at = NOW();

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_profile_sync ON auth.users;
CREATE TRIGGER on_auth_user_profile_sync
  AFTER INSERT OR UPDATE OF email, raw_user_meta_data, raw_app_meta_data
  ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_auth_user_profile_sync();

DROP TRIGGER IF EXISTS user_profiles_set_updated_at ON public.user_profiles;
CREATE TRIGGER user_profiles_set_updated_at
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.handle_auth_user_profile_sync() TO supabase_auth_admin;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.user_profiles REPLICA IDENTITY FULL;

-- STEP 9: Seed data
INSERT INTO public.user_profiles (
  id,
  email,
  full_name,
  avatar_url,
  auth_provider,
  system_role,
  created_at,
  updated_at
)
SELECT
  au.id,
  NULLIF(TRIM(LOWER(au.email)), '')::citext,
  COALESCE(
    NULLIF(TRIM(au.raw_user_meta_data ->> 'name'), ''),
    NULLIF(TRIM(au.raw_user_meta_data ->> 'full_name'), ''),
    NULLIF(TRIM(SPLIT_PART(COALESCE(au.email, ''), '@', 1)), '')
  ),
  NULLIF(TRIM(COALESCE(au.raw_user_meta_data ->> 'avatar_url', au.raw_user_meta_data ->> 'picture')), ''),
  COALESCE(
    NULLIF(TRIM(au.raw_app_meta_data ->> 'provider'), ''),
    'email'
  ),
  CASE LOWER(COALESCE(au.raw_app_meta_data ->> 'system_role', ''))
    WHEN 'platform_admin' THEN 'platform_admin'::public.user_role_type
    ELSE 'customer'::public.user_role_type
  END,
  COALESCE(au.created_at, NOW()),
  NOW()
FROM auth.users au
ON CONFLICT (id) DO NOTHING;

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS user_profiles_set_updated_at ON public.user_profiles;
-- DROP TRIGGER IF EXISTS on_auth_user_profile_sync ON auth.users;
-- DROP FUNCTION IF EXISTS public.handle_auth_user_profile_sync();
-- DROP TABLE IF EXISTS public.user_profiles CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/002_auth_profiles.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [user_profiles]  →  Frontend realtime: [user_profiles]
