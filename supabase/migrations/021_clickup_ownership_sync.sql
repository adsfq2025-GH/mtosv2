-- ================================================================
-- MIGRATION: 021_clickup_ownership_sync.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: clickup-ownership-sync · Depends on: 003, 004
-- Preserves: Existing client/account-manager behavior while adding ownership sync history and exceptions
-- ================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS external_ref TEXT;

CREATE INDEX IF NOT EXISTS clients_tenant_external_ref_idx
  ON public.clients (tenant_id, external_ref)
  WHERE is_deleted = FALSE
    AND external_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.client_ownership (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  source TEXT NOT NULL DEFAULT 'clickup_sync',
  synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.ownership_sync_runs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  provider TEXT NOT NULL DEFAULT 'clickup',
  source TEXT NOT NULL DEFAULT 'clickup_sync',
  cadence_minutes INTEGER,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  matched_clients INTEGER NOT NULL DEFAULT 0,
  unmatched_clients INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.ownership_sync_exceptions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  run_id UUID REFERENCES public.ownership_sync_runs(id) ON DELETE SET NULL,
  client_name TEXT NOT NULL,
  external_account_manager TEXT,
  suggested_user_name TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS client_ownership_active_unique_idx
  ON public.client_ownership (tenant_id, client_id)
  WHERE active = TRUE
    AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS client_ownership_tenant_synced_idx
  ON public.client_ownership (tenant_id, synced_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ownership_sync_runs_tenant_started_idx
  ON public.ownership_sync_runs (tenant_id, started_at DESC)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS ownership_sync_exceptions_open_unique_idx
  ON public.ownership_sync_exceptions (tenant_id, client_name, COALESCE(external_account_manager, ''), reason)
  WHERE status = 'open'
    AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ownership_sync_exceptions_tenant_seen_idx
  ON public.ownership_sync_exceptions (tenant_id, last_seen_at DESC)
  WHERE is_deleted = FALSE;

ALTER TABLE public.client_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ownership_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ownership_sync_exceptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "client_ownership_select" ON public.client_ownership;
CREATE POLICY "client_ownership_select" ON public.client_ownership
  FOR SELECT TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "client_ownership_insert" ON public.client_ownership;
CREATE POLICY "client_ownership_insert" ON public.client_ownership
  FOR INSERT TO authenticated
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "client_ownership_update" ON public.client_ownership;
CREATE POLICY "client_ownership_update" ON public.client_ownership
  FOR UPDATE TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE)
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_runs_select" ON public.ownership_sync_runs;
CREATE POLICY "ownership_sync_runs_select" ON public.ownership_sync_runs
  FOR SELECT TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_runs_insert" ON public.ownership_sync_runs;
CREATE POLICY "ownership_sync_runs_insert" ON public.ownership_sync_runs
  FOR INSERT TO authenticated
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_runs_update" ON public.ownership_sync_runs;
CREATE POLICY "ownership_sync_runs_update" ON public.ownership_sync_runs
  FOR UPDATE TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE)
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_exceptions_select" ON public.ownership_sync_exceptions;
CREATE POLICY "ownership_sync_exceptions_select" ON public.ownership_sync_exceptions
  FOR SELECT TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_exceptions_insert" ON public.ownership_sync_exceptions;
CREATE POLICY "ownership_sync_exceptions_insert" ON public.ownership_sync_exceptions
  FOR INSERT TO authenticated
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP POLICY IF EXISTS "ownership_sync_exceptions_update" ON public.ownership_sync_exceptions;
CREATE POLICY "ownership_sync_exceptions_update" ON public.ownership_sync_exceptions
  FOR UPDATE TO authenticated
  USING (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE)
  WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id')::uuid AND is_deleted = FALSE);

DROP TRIGGER IF EXISTS client_ownership_set_updated_at ON public.client_ownership;
CREATE TRIGGER client_ownership_set_updated_at
  BEFORE UPDATE ON public.client_ownership
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS ownership_sync_runs_set_updated_at ON public.ownership_sync_runs;
CREATE TRIGGER ownership_sync_runs_set_updated_at
  BEFORE UPDATE ON public.ownership_sync_runs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS ownership_sync_exceptions_set_updated_at ON public.ownership_sync_exceptions;
CREATE TRIGGER ownership_sync_exceptions_set_updated_at
  BEFORE UPDATE ON public.ownership_sync_exceptions
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.client_ownership REPLICA IDENTITY FULL;
ALTER TABLE public.ownership_sync_runs REPLICA IDENTITY FULL;
ALTER TABLE public.ownership_sync_exceptions REPLICA IDENTITY FULL;
