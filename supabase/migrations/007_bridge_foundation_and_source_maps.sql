-- ================================================================
-- MIGRATION: 007_bridge_foundation_and_source_maps.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: bridge-foundation · Neon Branch: [confirm_neon_branch] · Depends on: 001, 002, 003, 004, 005, 006
-- Preserves: tenants, user_profiles, tenant_members, clients, meetings, tenant_integrations, client_integration_bindings remain additive-only; Mongo runtime remains untouched
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.tenant_members
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.meetings
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.tenant_integrations
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

ALTER TABLE public.client_integration_bindings
  ADD COLUMN IF NOT EXISTS legacy_source_id TEXT,
  ADD COLUMN IF NOT EXISTS legacy_source_kind TEXT NOT NULL DEFAULT 'mongo';

CREATE TABLE IF NOT EXISTS public.bridge_import_runs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
  source_system TEXT NOT NULL DEFAULT 'mongo',
  entity_scope TEXT[] NOT NULL DEFAULT '{}'::text[],
  status TEXT NOT NULL DEFAULT 'staged',
  git_branch TEXT,
  neon_branch TEXT,
  notes TEXT,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  initiated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  started_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  CONSTRAINT bridge_import_runs_status_check
    CHECK (status IN ('staged','running','completed','completed_with_issues','failed','cancelled'))
);

CREATE TABLE IF NOT EXISTS public.bridge_staging_payloads (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  import_run_id UUID NOT NULL REFERENCES public.bridge_import_runs(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL,
  source_system TEXT NOT NULL DEFAULT 'mongo',
  source_collection TEXT NOT NULL,
  source_id TEXT NOT NULL,
  tenant_source_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_checksum TEXT,
  status TEXT NOT NULL DEFAULT 'staged',
  error_text TEXT,
  processed_at TIMESTAMPTZ,
  target_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  CONSTRAINT bridge_staging_payloads_entity_type_check
    CHECK (entity_type IN ('users','tenants','memberships','clients','meetings','integrations','client_bindings')),
  CONSTRAINT bridge_staging_payloads_status_check
    CHECK (status IN ('staged','applied','blocked','error'))
);

CREATE TABLE IF NOT EXISTS public.bridge_source_id_maps (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
  source_system TEXT NOT NULL DEFAULT 'mongo',
  entity_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_id UUID NOT NULL,
  import_run_id UUID REFERENCES public.bridge_import_runs(id) ON DELETE SET NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  CONSTRAINT bridge_source_id_maps_entity_type_check
    CHECK (entity_type IN ('users','tenants','memberships','clients','meetings','integrations','client_bindings'))
);

CREATE TABLE IF NOT EXISTS public.bridge_import_issues (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  import_run_id UUID NOT NULL REFERENCES public.bridge_import_runs(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL,
  source_id TEXT,
  severity TEXT NOT NULL DEFAULT 'error',
  code TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  CONSTRAINT bridge_import_issues_entity_type_check
    CHECK (entity_type IN ('users','tenants','memberships','clients','meetings','integrations','client_bindings')),
  CONSTRAINT bridge_import_issues_severity_check
    CHECK (severity IN ('info','warning','error'))
);

CREATE TABLE IF NOT EXISTS public.bridge_reconciliation_snapshots (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  import_run_id UUID NOT NULL REFERENCES public.bridge_import_runs(id) ON DELETE CASCADE,
  tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  staged_count INTEGER NOT NULL DEFAULT 0,
  applied_count INTEGER NOT NULL DEFAULT 0,
  blocked_count INTEGER NOT NULL DEFAULT 0,
  mapped_count INTEGER NOT NULL DEFAULT 0,
  target_count INTEGER NOT NULL DEFAULT 0,
  mismatch_count INTEGER NOT NULL DEFAULT 0,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  CONSTRAINT bridge_reconciliation_snapshots_entity_type_check
    CHECK (entity_type IN ('users','tenants','memberships','clients','meetings','integrations','client_bindings'))
);

COMMENT ON TABLE public.bridge_import_runs IS 'Phase 2 import batches for additive Mongo to Supabase bridge work.';
COMMENT ON TABLE public.bridge_staging_payloads IS 'Raw sanitized source payloads staged before SQL-native application into tenant-safe tables.';
COMMENT ON TABLE public.bridge_source_id_maps IS 'Text-based source ID registry for all legacy Mongo identifiers, including tenants.';
COMMENT ON TABLE public.bridge_import_issues IS 'Import blockers, mismatches, and non-fatal warnings captured during bridge application.';
COMMENT ON TABLE public.bridge_reconciliation_snapshots IS 'Run-level and tenant-level reconciliation summaries for additive cutover validation.';

-- STEP 4: Indexes
CREATE UNIQUE INDEX IF NOT EXISTS tenants_legacy_source_unique_idx
  ON public.tenants (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS user_profiles_legacy_source_unique_idx
  ON public.user_profiles (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_members_legacy_source_unique_idx
  ON public.tenant_members (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS clients_legacy_source_unique_idx
  ON public.clients (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS meetings_legacy_source_unique_idx
  ON public.meetings (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_integrations_legacy_source_unique_idx
  ON public.tenant_integrations (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS client_integration_bindings_legacy_source_unique_idx
  ON public.client_integration_bindings (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS bridge_import_runs_status_idx
  ON public.bridge_import_runs (status, started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS bridge_staging_payloads_run_entity_source_unique_idx
  ON public.bridge_staging_payloads (import_run_id, entity_type, source_id);

CREATE INDEX IF NOT EXISTS bridge_staging_payloads_entity_status_idx
  ON public.bridge_staging_payloads (import_run_id, entity_type, status, created_at DESC);

CREATE INDEX IF NOT EXISTS bridge_staging_payloads_tenant_lookup_idx
  ON public.bridge_staging_payloads (tenant_source_id, entity_type);

CREATE UNIQUE INDEX IF NOT EXISTS bridge_source_id_maps_source_unique_idx
  ON public.bridge_source_id_maps (source_system, entity_type, source_id);

CREATE INDEX IF NOT EXISTS bridge_source_id_maps_target_idx
  ON public.bridge_source_id_maps (entity_type, target_id);

CREATE INDEX IF NOT EXISTS bridge_source_id_maps_tenant_idx
  ON public.bridge_source_id_maps (tenant_id, entity_type);

CREATE INDEX IF NOT EXISTS bridge_import_issues_run_entity_idx
  ON public.bridge_import_issues (import_run_id, entity_type, severity, created_at DESC);

CREATE INDEX IF NOT EXISTS bridge_reconciliation_snapshots_run_entity_idx
  ON public.bridge_reconciliation_snapshots (import_run_id, entity_type, created_at DESC);

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.bridge_import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_staging_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_source_id_maps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_import_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_reconciliation_snapshots ENABLE ROW LEVEL SECURITY;

-- Internal bridge tables are service-role-only by default. No authenticated policies are created here.

-- STEP 6: Triggers (updated_at + business logic)
DROP TRIGGER IF EXISTS bridge_import_runs_set_updated_at ON public.bridge_import_runs;
CREATE TRIGGER bridge_import_runs_set_updated_at
  BEFORE UPDATE ON public.bridge_import_runs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS bridge_staging_payloads_set_updated_at ON public.bridge_staging_payloads;
CREATE TRIGGER bridge_staging_payloads_set_updated_at
  BEFORE UPDATE ON public.bridge_staging_payloads
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS bridge_source_id_maps_set_updated_at ON public.bridge_source_id_maps;
CREATE TRIGGER bridge_source_id_maps_set_updated_at
  BEFORE UPDATE ON public.bridge_source_id_maps
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS bridge_import_issues_set_updated_at ON public.bridge_import_issues;
CREATE TRIGGER bridge_import_issues_set_updated_at
  BEFORE UPDATE ON public.bridge_import_issues
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS bridge_reconciliation_snapshots_set_updated_at ON public.bridge_reconciliation_snapshots;
CREATE TRIGGER bridge_reconciliation_snapshots_set_updated_at
  BEFORE UPDATE ON public.bridge_reconciliation_snapshots
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
CREATE OR REPLACE FUNCTION public.bridge_safe_uuid(p_value TEXT)
RETURNS UUID
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  IF p_value IS NULL OR BTRIM(p_value) = '' THEN
    RETURN NULL;
  END IF;

  IF p_value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
    RETURN p_value::uuid;
  END IF;

  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_parse_timestamptz(p_value TEXT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF p_value IS NULL OR BTRIM(p_value) = '' THEN
    RETURN NULL;
  END IF;

  RETURN p_value::timestamptz;
EXCEPTION
  WHEN OTHERS THEN
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_parse_date(p_value TEXT)
RETURNS DATE
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF p_value IS NULL OR BTRIM(p_value) = '' THEN
    RETURN NULL;
  END IF;

  RETURN SPLIT_PART(p_value, 'T', 1)::date;
EXCEPTION
  WHEN OTHERS THEN
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_jsonb_text_array(p_value JSONB)
RETURNS TEXT[]
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(array_agg(value), ARRAY[]::text[])
  FROM jsonb_array_elements_text(
    CASE
      WHEN jsonb_typeof(COALESCE(p_value, '[]'::jsonb)) = 'array' THEN COALESCE(p_value, '[]'::jsonb)
      ELSE '[]'::jsonb
    END
  ) AS t(value)
$$;

CREATE OR REPLACE FUNCTION public.bridge_normalize_user_system_role(p_value TEXT)
RETURNS public.user_role_type
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_value), ''), ''))
    WHEN 'admin' THEN 'platform_admin'::public.user_role_type
    WHEN 'manager' THEN 'manager'::public.user_role_type
    ELSE 'customer'::public.user_role_type
  END
$$;

CREATE OR REPLACE FUNCTION public.bridge_normalize_membership_role(p_value TEXT)
RETURNS public.user_role_type
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_value), ''), ''))
    WHEN 'owner' THEN 'tenant_owner'::public.user_role_type
    WHEN 'admin' THEN 'manager'::public.user_role_type
    WHEN 'member' THEN 'staff'::public.user_role_type
    WHEN 'viewer' THEN 'customer'::public.user_role_type
    ELSE 'customer'::public.user_role_type
  END
$$;

CREATE OR REPLACE FUNCTION public.bridge_normalize_membership_status(p_value TEXT)
RETURNS public.membership_status_type
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_value), ''), ''))
    WHEN 'invited' THEN 'invited'::public.membership_status_type
    WHEN 'disabled' THEN 'disabled'::public.membership_status_type
    ELSE 'active'::public.membership_status_type
  END
$$;

CREATE OR REPLACE FUNCTION public.bridge_normalize_tenant_status(p_value TEXT)
RETURNS public.tenant_status_type
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_value), ''), ''))
    WHEN 'suspended' THEN 'suspended'::public.tenant_status_type
    WHEN 'archived' THEN 'archived'::public.tenant_status_type
    ELSE 'active'::public.tenant_status_type
  END
$$;

CREATE OR REPLACE FUNCTION public.bridge_normalize_subscription_status(p_value TEXT)
RETURNS public.subscription_status_type
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_value), ''), ''))
    WHEN 'trialing' THEN 'trialing'::public.subscription_status_type
    WHEN 'active' THEN 'active'::public.subscription_status_type
    WHEN 'past_due' THEN 'past_due'::public.subscription_status_type
    WHEN 'canceled' THEN 'canceled'::public.subscription_status_type
    WHEN 'suspended' THEN 'suspended'::public.subscription_status_type
    ELSE 'onboarding'::public.subscription_status_type
  END
$$;

CREATE OR REPLACE FUNCTION public.bridge_record_issue(
  p_import_run_id UUID,
  p_entity_type TEXT,
  p_source_id TEXT,
  p_code TEXT,
  p_detail JSONB DEFAULT '{}'::jsonb,
  p_severity TEXT DEFAULT 'error',
  p_tenant_id UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
  v_issue_id UUID;
BEGIN
  INSERT INTO public.bridge_import_issues (
    import_run_id,
    tenant_id,
    entity_type,
    source_id,
    severity,
    code,
    detail,
    created_at,
    updated_at
  )
  VALUES (
    p_import_run_id,
    p_tenant_id,
    p_entity_type,
    p_source_id,
    COALESCE(NULLIF(BTRIM(p_severity), ''), 'error'),
    p_code,
    COALESCE(p_detail, '{}'::jsonb),
    NOW(),
    NOW()
  )
  RETURNING id INTO v_issue_id;

  RETURN v_issue_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_upsert_source_map(
  p_tenant_id UUID,
  p_source_system TEXT,
  p_entity_type TEXT,
  p_source_id TEXT,
  p_target_table TEXT,
  p_target_id UUID,
  p_import_run_id UUID DEFAULT NULL,
  p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
  v_map_id UUID;
BEGIN
  INSERT INTO public.bridge_source_id_maps (
    tenant_id,
    source_system,
    entity_type,
    source_id,
    target_table,
    target_id,
    import_run_id,
    metadata,
    created_at,
    updated_at
  )
  VALUES (
    p_tenant_id,
    COALESCE(NULLIF(BTRIM(p_source_system), ''), 'mongo'),
    p_entity_type,
    p_source_id,
    p_target_table,
    p_target_id,
    p_import_run_id,
    COALESCE(p_metadata, '{}'::jsonb),
    NOW(),
    NOW()
  )
  ON CONFLICT (source_system, entity_type, source_id) DO UPDATE
  SET tenant_id = EXCLUDED.tenant_id,
      target_table = EXCLUDED.target_table,
      target_id = EXCLUDED.target_id,
      import_run_id = COALESCE(EXCLUDED.import_run_id, public.bridge_source_id_maps.import_run_id),
      metadata = public.bridge_source_id_maps.metadata || EXCLUDED.metadata,
      updated_at = NOW()
  RETURNING id INTO v_map_id;

  RETURN v_map_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_resolve_target_id(
  p_entity_type TEXT,
  p_source_id TEXT,
  p_source_system TEXT DEFAULT 'mongo'
)
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT m.target_id
  FROM public.bridge_source_id_maps m
  WHERE m.entity_type = p_entity_type
    AND m.source_system = COALESCE(NULLIF(BTRIM(p_source_system), ''), 'mongo')
    AND m.source_id = p_source_id
  LIMIT 1
$$;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.bridge_import_runs REPLICA IDENTITY FULL;
ALTER TABLE public.bridge_staging_payloads REPLICA IDENTITY FULL;
ALTER TABLE public.bridge_source_id_maps REPLICA IDENTITY FULL;
ALTER TABLE public.bridge_import_issues REPLICA IDENTITY FULL;
ALTER TABLE public.bridge_reconciliation_snapshots REPLICA IDENTITY FULL;

-- STEP 9: Seed data
-- No seed data in this migration.

-- ================================================================
-- ROLLBACK:
-- DROP FUNCTION IF EXISTS public.bridge_resolve_target_id(TEXT, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_upsert_source_map(UUID, TEXT, TEXT, TEXT, TEXT, UUID, UUID, JSONB);
-- DROP FUNCTION IF EXISTS public.bridge_record_issue(UUID, TEXT, TEXT, TEXT, JSONB, TEXT, UUID);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_subscription_status(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_tenant_status(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_membership_status(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_membership_role(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_user_system_role(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_jsonb_text_array(JSONB);
-- DROP FUNCTION IF EXISTS public.bridge_parse_date(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_parse_timestamptz(TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_safe_uuid(TEXT);
-- DROP TRIGGER IF EXISTS bridge_reconciliation_snapshots_set_updated_at ON public.bridge_reconciliation_snapshots;
-- DROP TRIGGER IF EXISTS bridge_import_issues_set_updated_at ON public.bridge_import_issues;
-- DROP TRIGGER IF EXISTS bridge_source_id_maps_set_updated_at ON public.bridge_source_id_maps;
-- DROP TRIGGER IF EXISTS bridge_staging_payloads_set_updated_at ON public.bridge_staging_payloads;
-- DROP TRIGGER IF EXISTS bridge_import_runs_set_updated_at ON public.bridge_import_runs;
-- DROP TABLE IF EXISTS public.bridge_reconciliation_snapshots CASCADE;
-- DROP TABLE IF EXISTS public.bridge_import_issues CASCADE;
-- DROP TABLE IF EXISTS public.bridge_source_id_maps CASCADE;
-- DROP TABLE IF EXISTS public.bridge_staging_payloads CASCADE;
-- DROP TABLE IF EXISTS public.bridge_import_runs CASCADE;
-- DROP INDEX IF EXISTS public.client_integration_bindings_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.tenant_integrations_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.meetings_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.clients_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.tenant_members_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.user_profiles_legacy_source_unique_idx;
-- DROP INDEX IF EXISTS public.tenants_legacy_source_unique_idx;
-- ALTER TABLE public.client_integration_bindings DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.tenant_integrations DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.meetings DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.clients DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.tenant_members DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.user_profiles DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ALTER TABLE public.tenants DROP COLUMN IF EXISTS legacy_source_kind, DROP COLUMN IF EXISTS legacy_source_id;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [007_bridge_foundation_and_source_maps.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/007_bridge_foundation_and_source_maps.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [bridge_import_runs, bridge_staging_payloads, bridge_source_id_maps, bridge_import_issues, bridge_reconciliation_snapshots]  →  Frontend realtime: [none]
