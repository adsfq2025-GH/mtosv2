-- ================================================================
-- MIGRATION: 013_clickup_client_sync_runtime.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: clickup-client-sync-runtime · Neon Branch: [confirm_neon_branch] · Depends on: 001, 003, 007
-- Preserves: Existing ClickUp sync runtime remains available while Supabase-backed runtime state is introduced
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.clickup_client_sync_state (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  running BOOLEAN NOT NULL DEFAULT FALSE,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  last_error TEXT,
  last_run_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.clickup_client_sync_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  ok BOOLEAN NOT NULL DEFAULT FALSE,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  list_id TEXT,
  list_source TEXT,
  created_count INTEGER NOT NULL DEFAULT 0,
  updated_count INTEGER NOT NULL DEFAULT 0,
  paused_count INTEGER NOT NULL DEFAULT 0,
  assigned_found INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

COMMENT ON TABLE public.clickup_client_sync_state IS 'Latest runtime sync status per tenant/user for ClickUp client assignment sync.';
COMMENT ON TABLE public.clickup_client_sync_logs IS 'Historical ClickUp client assignment sync runs with summary metrics and debug details.';

-- STEP 4: Indexes
CREATE UNIQUE INDEX IF NOT EXISTS clickup_client_sync_state_tenant_user_unique_idx
  ON public.clickup_client_sync_state (tenant_id, user_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS clickup_client_sync_state_tenant_lookup_idx
  ON public.clickup_client_sync_state (tenant_id, updated_at DESC)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS clickup_client_sync_logs_legacy_source_unique_idx
  ON public.clickup_client_sync_logs (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS clickup_client_sync_logs_tenant_user_started_at_idx
  ON public.clickup_client_sync_logs (tenant_id, user_id, started_at DESC)
  WHERE is_deleted = FALSE;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.clickup_client_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.clickup_client_sync_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "clickup_client_sync_state_select" ON public.clickup_client_sync_state;
CREATE POLICY "clickup_client_sync_state_select" ON public.clickup_client_sync_state
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clickup_client_sync_state_insert" ON public.clickup_client_sync_state;
CREATE POLICY "clickup_client_sync_state_insert" ON public.clickup_client_sync_state
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clickup_client_sync_state_update" ON public.clickup_client_sync_state;
CREATE POLICY "clickup_client_sync_state_update" ON public.clickup_client_sync_state
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  )
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clickup_client_sync_logs_select" ON public.clickup_client_sync_logs;
CREATE POLICY "clickup_client_sync_logs_select" ON public.clickup_client_sync_logs
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clickup_client_sync_logs_insert" ON public.clickup_client_sync_logs;
CREATE POLICY "clickup_client_sync_logs_insert" ON public.clickup_client_sync_logs
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clickup_client_sync_logs_update" ON public.clickup_client_sync_logs;
CREATE POLICY "clickup_client_sync_logs_update" ON public.clickup_client_sync_logs
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  )
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

-- STEP 6: Triggers (updated_at + business logic)
DROP TRIGGER IF EXISTS clickup_client_sync_state_set_updated_at ON public.clickup_client_sync_state;
CREATE TRIGGER clickup_client_sync_state_set_updated_at
  BEFORE UPDATE ON public.clickup_client_sync_state
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS clickup_client_sync_logs_set_updated_at ON public.clickup_client_sync_logs;
CREATE TRIGGER clickup_client_sync_logs_set_updated_at
  BEFORE UPDATE ON public.clickup_client_sync_logs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
-- No functions or views in this migration.

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.clickup_client_sync_state REPLICA IDENTITY FULL;
ALTER TABLE public.clickup_client_sync_logs REPLICA IDENTITY FULL;

-- STEP 9: Seed data
-- No seed data.

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS clickup_client_sync_logs_set_updated_at ON public.clickup_client_sync_logs;
-- DROP TRIGGER IF EXISTS clickup_client_sync_state_set_updated_at ON public.clickup_client_sync_state;
-- DROP TABLE IF EXISTS public.clickup_client_sync_logs CASCADE;
-- DROP TABLE IF EXISTS public.clickup_client_sync_state CASCADE;
-- ================================================================
