-- ================================================================
-- MIGRATION: 012_action_items.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: action-items-core · Neon Branch: [confirm_neon_branch] · Depends on: 001, 003, 004, 005, 007
-- Preserves: Mongo action_items collection remains source-of-truth until phased backfill validation is approved
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.action_items (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  meeting_id UUID REFERENCES public.meetings(id) ON DELETE SET NULL,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  owner TEXT,
  owner_type TEXT NOT NULL DEFAULT 'agency',
  due_date DATE,
  status TEXT NOT NULL DEFAULT 'open',
  priority TEXT NOT NULL DEFAULT 'medium',
  pushed_to TEXT,
  external_id TEXT,
  external_url TEXT,
  last_reminded_at TIMESTAMPTZ,
  reminder_count INTEGER NOT NULL DEFAULT 0,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'mongo',
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
  CONSTRAINT action_items_owner_type_check
    CHECK (owner_type IN ('agency', 'client')),
  CONSTRAINT action_items_status_check
    CHECK (status IN ('open', 'in_progress', 'completed', 'blocked')),
  CONSTRAINT action_items_priority_check
    CHECK (priority IN ('low', 'medium', 'high')),
  CONSTRAINT action_items_reminder_count_check
    CHECK (reminder_count >= 0)
);

COMMENT ON TABLE public.action_items IS 'Parallel Postgres action items for phased Mongo to Supabase cutover.';

-- STEP 4: Indexes
CREATE INDEX IF NOT EXISTS action_items_tenant_created_at_idx
  ON public.action_items (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS action_items_tenant_client_status_idx
  ON public.action_items (tenant_id, client_id, status)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS action_items_tenant_meeting_idx
  ON public.action_items (tenant_id, meeting_id)
  WHERE is_deleted = FALSE
    AND meeting_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS action_items_tenant_due_date_idx
  ON public.action_items (tenant_id, due_date, status)
  WHERE is_deleted = FALSE
    AND due_date IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS action_items_legacy_source_unique_idx
  ON public.action_items (legacy_source_kind, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL
    AND is_deleted = FALSE;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.action_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "action_items_select" ON public.action_items;
CREATE POLICY "action_items_select" ON public.action_items
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "action_items_insert" ON public.action_items;
CREATE POLICY "action_items_insert" ON public.action_items
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "action_items_update" ON public.action_items;
CREATE POLICY "action_items_update" ON public.action_items
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
DROP TRIGGER IF EXISTS action_items_set_updated_at ON public.action_items;
CREATE TRIGGER action_items_set_updated_at
  BEFORE UPDATE ON public.action_items
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
-- No functions or views in this migration.

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.action_items REPLICA IDENTITY FULL;

-- STEP 9: Seed data
-- No seed data. Backfill must be performed in a later approved cutover step.

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS action_items_set_updated_at ON public.action_items;
-- DROP TABLE IF EXISTS public.action_items CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql, 003_tenancy_core.sql, 004_clients.sql, 005_meetings.sql, 006_integrations_metadata.sql, 007_bridge_foundation_and_source_maps.sql, 008_bridge_backfill_and_reconciliation.sql, 009_bridge_apply_execute_hardening.sql, 010_bridge_blocker_fixes.sql, 011_bridge_tenant_fallback_uuid_fix.sql, 012_action_items.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/012_action_items.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename='action_items';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [action_items]  →  Frontend realtime: [action_items]
