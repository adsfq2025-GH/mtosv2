-- ================================================================
-- MIGRATION: 003_tenancy_core.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: tenancy-core · Neon Branch: [confirm_neon_branch] · Depends on: 001, 002
-- Preserves: Mongo tenants, memberships, domains, and tenant settings remain source-of-truth until cutover
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.tenants (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  slug CITEXT NOT NULL,
  name TEXT NOT NULL,
  status public.tenant_status_type NOT NULL DEFAULT 'active',
  subscription_status public.subscription_status_type NOT NULL DEFAULT 'onboarding',
  subscription_expires_at TIMESTAMPTZ,
  trial_ends_at TIMESTAMPTZ,
  owner_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.tenant_members (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role public.user_role_type NOT NULL,
  status public.membership_status_type NOT NULL DEFAULT 'active',
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  invited_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  joined_at TIMESTAMPTZ,
  legacy_membership_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
  CONSTRAINT tenant_members_role_check
    CHECK (role IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type, 'staff'::public.user_role_type, 'customer'::public.user_role_type))
);

CREATE TABLE IF NOT EXISTS public.tenant_settings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  branding JSONB NOT NULL DEFAULT '{}'::jsonb,
  terminology JSONB NOT NULL DEFAULT '{}'::jsonb,
  workflows JSONB NOT NULL DEFAULT '{}'::jsonb,
  analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.tenant_domains (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  domain CITEXT NOT NULL,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

-- STEP 4: Indexes
CREATE UNIQUE INDEX IF NOT EXISTS tenants_slug_unique_idx
  ON public.tenants (slug)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS tenants_subscription_status_idx
  ON public.tenants (subscription_status, status)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_members_tenant_user_unique_idx
  ON public.tenant_members (tenant_id, user_id)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_members_default_active_unique_idx
  ON public.tenant_members (user_id)
  WHERE is_default = TRUE
    AND status = 'active'::public.membership_status_type
    AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS tenant_members_lookup_idx
  ON public.tenant_members (tenant_id, status, role);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_settings_tenant_unique_idx
  ON public.tenant_settings (tenant_id)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_domains_domain_unique_idx
  ON public.tenant_domains (domain)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS tenant_domains_tenant_lookup_idx
  ON public.tenant_domains (tenant_id, is_primary)
  WHERE is_deleted = FALSE;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_domains ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenants_select" ON public.tenants;
CREATE POLICY "tenants_select" ON public.tenants
  FOR SELECT
  TO authenticated
  USING (id = public.current_tenant_id() AND is_deleted = FALSE);

DROP POLICY IF EXISTS "tenants_update" ON public.tenants;
CREATE POLICY "tenants_update" ON public.tenants
  FOR UPDATE
  TO authenticated
  USING (
    id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  )
  WITH CHECK (
    id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_members_select" ON public.tenant_members;
CREATE POLICY "tenant_members_select" ON public.tenant_members
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND (
      user_id = auth.uid()
      OR public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
    )
  );

DROP POLICY IF EXISTS "tenant_members_insert" ON public.tenant_members;
CREATE POLICY "tenant_members_insert" ON public.tenant_members
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_members_update" ON public.tenant_members;
CREATE POLICY "tenant_members_update" ON public.tenant_members
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  )
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_settings_select" ON public.tenant_settings;
CREATE POLICY "tenant_settings_select" ON public.tenant_settings
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "tenant_settings_insert" ON public.tenant_settings;
CREATE POLICY "tenant_settings_insert" ON public.tenant_settings
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_settings_update" ON public.tenant_settings;
CREATE POLICY "tenant_settings_update" ON public.tenant_settings
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  )
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_domains_select" ON public.tenant_domains;
CREATE POLICY "tenant_domains_select" ON public.tenant_domains
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "tenant_domains_insert" ON public.tenant_domains;
CREATE POLICY "tenant_domains_insert" ON public.tenant_domains
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenant_domains_update" ON public.tenant_domains;
CREATE POLICY "tenant_domains_update" ON public.tenant_domains
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  )
  WITH CHECK (
    tenant_id = public.current_tenant_id()
    AND is_deleted = FALSE
    AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
  );

DROP POLICY IF EXISTS "tenants_auth_admin_select" ON public.tenants;
CREATE POLICY "tenants_auth_admin_select" ON public.tenants
  FOR SELECT
  TO supabase_auth_admin
  USING (TRUE);

DROP POLICY IF EXISTS "tenant_members_auth_admin_select" ON public.tenant_members;
CREATE POLICY "tenant_members_auth_admin_select" ON public.tenant_members
  FOR SELECT
  TO supabase_auth_admin
  USING (TRUE);

DROP POLICY IF EXISTS "tenant_settings_auth_admin_select" ON public.tenant_settings;
CREATE POLICY "tenant_settings_auth_admin_select" ON public.tenant_settings
  FOR SELECT
  TO supabase_auth_admin
  USING (TRUE);

DROP POLICY IF EXISTS "tenant_domains_auth_admin_select" ON public.tenant_domains;
CREATE POLICY "tenant_domains_auth_admin_select" ON public.tenant_domains
  FOR SELECT
  TO supabase_auth_admin
  USING (TRUE);

-- STEP 6: Triggers (updated_at + business logic)
DROP TRIGGER IF EXISTS tenants_set_updated_at ON public.tenants;
CREATE TRIGGER tenants_set_updated_at
  BEFORE UPDATE ON public.tenants
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS tenant_members_set_updated_at ON public.tenant_members;
CREATE TRIGGER tenant_members_set_updated_at
  BEFORE UPDATE ON public.tenant_members
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS tenant_settings_set_updated_at ON public.tenant_settings;
CREATE TRIGGER tenant_settings_set_updated_at
  BEFORE UPDATE ON public.tenant_settings
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS tenant_domains_set_updated_at ON public.tenant_domains;
CREATE TRIGGER tenant_domains_set_updated_at
  BEFORE UPDATE ON public.tenant_domains
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.tenant_members_default_enforcer()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF pg_trigger_depth() > 1 THEN
    RETURN NEW;
  END IF;

  IF NEW.is_deleted = TRUE OR NEW.status <> 'active'::public.membership_status_type THEN
    NEW.is_default := FALSE;
    RETURN NEW;
  END IF;

  IF NEW.is_default IS TRUE THEN
    UPDATE public.tenant_members
    SET is_default = FALSE,
        updated_at = NOW()
    WHERE user_id = NEW.user_id
      AND id <> COALESCE(NEW.id, gen_random_uuid())
      AND is_default = TRUE;
  ELSIF NOT EXISTS (
    SELECT 1
    FROM public.tenant_members tm
    WHERE tm.user_id = NEW.user_id
      AND tm.status = 'active'::public.membership_status_type
      AND tm.is_deleted = FALSE
      AND tm.id <> COALESCE(NEW.id, '00000000-0000-0000-0000-000000000000'::uuid)
  ) THEN
    NEW.is_default := TRUE;
  END IF;

  IF NEW.joined_at IS NULL AND NEW.status = 'active'::public.membership_status_type THEN
    NEW.joined_at := NOW();
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tenant_members_default_enforcer_trigger ON public.tenant_members;
CREATE TRIGGER tenant_members_default_enforcer_trigger
  BEFORE INSERT OR UPDATE OF is_default, status, is_deleted
  ON public.tenant_members
  FOR EACH ROW
  EXECUTE FUNCTION public.tenant_members_default_enforcer();

-- STEP 7: Functions / Views
DROP POLICY IF EXISTS "user_profiles_select" ON public.user_profiles;
CREATE POLICY "user_profiles_select" ON public.user_profiles
  FOR SELECT
  TO authenticated
  USING (
    id = auth.uid()
    OR EXISTS (
      SELECT 1
      FROM public.tenant_members tm
      WHERE tm.user_id = public.user_profiles.id
        AND tm.tenant_id = public.current_tenant_id()
        AND tm.status = 'active'::public.membership_status_type
        AND tm.is_deleted = FALSE
        AND public.current_user_role() IN ('tenant_owner'::public.user_role_type, 'manager'::public.user_role_type)
    )
  );

CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  claims jsonb;
  system_role public.user_role_type;
  effective_role public.user_role_type;
  selected_member_id UUID;
  selected_tenant_id UUID;
  selected_member_role public.user_role_type;
  selected_tenant_slug TEXT;
  selected_subscription_status public.subscription_status_type;
BEGIN
  claims := event -> 'claims';

  SELECT up.system_role
  INTO system_role
  FROM public.user_profiles up
  WHERE up.id = (event ->> 'user_id')::uuid;

  SELECT
    tm.id AS member_id,
    tm.tenant_id,
    tm.role,
    t.slug,
    t.subscription_status
  INTO selected_member_id,
       selected_tenant_id,
       selected_member_role,
       selected_tenant_slug,
       selected_subscription_status
  FROM public.tenant_members tm
  JOIN public.tenants t
    ON t.id = tm.tenant_id
   AND t.is_deleted = FALSE
  WHERE tm.user_id = (event ->> 'user_id')::uuid
    AND tm.status = 'active'::public.membership_status_type
    AND tm.is_deleted = FALSE
  ORDER BY
    tm.is_default DESC,
    CASE tm.role
      WHEN 'tenant_owner'::public.user_role_type THEN 0
      WHEN 'manager'::public.user_role_type THEN 1
      WHEN 'staff'::public.user_role_type THEN 2
      ELSE 3
    END,
    tm.created_at ASC
  LIMIT 1;

  effective_role := COALESCE(
    CASE
      WHEN system_role = 'platform_admin'::public.user_role_type THEN system_role
      ELSE selected_member_role
    END,
    system_role,
    'customer'::public.user_role_type
  );

  claims := jsonb_set(claims, '{user_role}', to_jsonb(effective_role::text), TRUE);
  claims := jsonb_set(claims, '{tenant_id}', COALESCE(to_jsonb(selected_tenant_id), 'null'::jsonb), TRUE);
  claims := jsonb_set(claims, '{member_id}', COALESCE(to_jsonb(selected_member_id), 'null'::jsonb), TRUE);
  claims := jsonb_set(claims, '{tenant_slug}', COALESCE(to_jsonb(selected_tenant_slug), 'null'::jsonb), TRUE);
  claims := jsonb_set(claims, '{subscription_status}', COALESCE(to_jsonb(selected_subscription_status::text), 'null'::jsonb), TRUE);

  RETURN jsonb_set(event, '{claims}', claims, TRUE);
END;
$$;

GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) FROM authenticated, anon, public;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.tenants REPLICA IDENTITY FULL;
ALTER TABLE public.tenant_members REPLICA IDENTITY FULL;
ALTER TABLE public.tenant_settings REPLICA IDENTITY FULL;
ALTER TABLE public.tenant_domains REPLICA IDENTITY FULL;

-- STEP 9: Seed data
INSERT INTO public.tenant_settings (
  id,
  tenant_id,
  branding,
  terminology,
  workflows,
  analysis,
  created_at,
  updated_at
)
SELECT
  gen_random_uuid(),
  t.id,
  '{}'::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  NOW(),
  NOW()
FROM public.tenants t
WHERE NOT EXISTS (
  SELECT 1
  FROM public.tenant_settings ts
  WHERE ts.tenant_id = t.id
    AND ts.is_deleted = FALSE
);

-- ================================================================
-- ROLLBACK:
-- DROP FUNCTION IF EXISTS public.custom_access_token_hook(jsonb);
-- DROP FUNCTION IF EXISTS public.tenant_members_default_enforcer();
-- DROP TRIGGER IF EXISTS tenant_domains_set_updated_at ON public.tenant_domains;
-- DROP TRIGGER IF EXISTS tenant_settings_set_updated_at ON public.tenant_settings;
-- DROP TRIGGER IF EXISTS tenant_members_default_enforcer_trigger ON public.tenant_members;
-- DROP TRIGGER IF EXISTS tenant_members_set_updated_at ON public.tenant_members;
-- DROP TRIGGER IF EXISTS tenants_set_updated_at ON public.tenants;
-- DROP TABLE IF EXISTS public.tenant_domains CASCADE;
-- DROP TABLE IF EXISTS public.tenant_settings CASCADE;
-- DROP TABLE IF EXISTS public.tenant_members CASCADE;
-- DROP TABLE IF EXISTS public.tenants CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql, 003_tenancy_core.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/003_tenancy_core.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [tenants, tenant_members, tenant_settings, tenant_domains]  →  Frontend realtime: [tenants, tenant_members, tenant_settings]
