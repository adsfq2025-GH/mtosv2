-- ================================================================
-- MIGRATION: 004_clients.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: clients-core · Neon Branch: [confirm_neon_branch] · Depends on: 001, 003
-- Preserves: Mongo clients collection remains source-of-truth until phased backfill validation is approved
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.clients (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  company TEXT NOT NULL,
  industry TEXT,
  primary_contact TEXT,
  email CITEXT,
  phone TEXT,
  website TEXT,
  location TEXT,
  account_manager_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  account_manager_name TEXT,
  services TEXT[] NOT NULL DEFAULT '{}'::text[],
  assigned_products TEXT[] NOT NULL DEFAULT '{}'::text[],
  crm_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  gbp_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  onboarding_date DATE,
  mrr NUMERIC(12,2) NOT NULL DEFAULT 0,
  health_score INTEGER NOT NULL DEFAULT 75,
  churn_risk public.risk_level_type NOT NULL DEFAULT 'low',
  sentiment public.sentiment_type NOT NULL DEFAULT 'neutral',
  notes TEXT,
  avatar_url TEXT,
  status public.client_status_type NOT NULL DEFAULT 'active',
  suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
  suggestions_generated_at TIMESTAMPTZ,
  suggestions_model TEXT,
  feedback_alert BOOLEAN NOT NULL DEFAULT FALSE,
  feedback_alert_level public.risk_level_type NOT NULL DEFAULT 'low',
  feedback_alert_reason TEXT,
  feedback_last_submitted_at TIMESTAMPTZ,
  feedback_rolling_avg JSONB NOT NULL DEFAULT '{}'::jsonb,
  health_alert BOOLEAN NOT NULL DEFAULT FALSE,
  health_alert_level public.risk_level_type NOT NULL DEFAULT 'low',
  health_alert_reason TEXT,
  churn_risk_score INTEGER NOT NULL DEFAULT 0,
  churn_risk_indicators TEXT[] NOT NULL DEFAULT '{}'::text[],
  nps_rolling_avg NUMERIC(5,2),
  sentiment_rolling JSONB NOT NULL DEFAULT '{}'::jsonb,
  health_last_submitted_at TIMESTAMPTZ,
  legacy_client_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
  CONSTRAINT clients_health_score_range CHECK (health_score BETWEEN 0 AND 100),
  CONSTRAINT clients_churn_risk_score_range CHECK (churn_risk_score BETWEEN 0 AND 100)
);

COMMENT ON TABLE public.clients IS 'Parallel Postgres client records for phased Mongo to Supabase cutover.';

-- STEP 4: Indexes
CREATE INDEX IF NOT EXISTS clients_tenant_created_at_idx
  ON public.clients (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS clients_tenant_status_idx
  ON public.clients (tenant_id, status)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS clients_tenant_account_manager_idx
  ON public.clients (tenant_id, account_manager_user_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS clients_tenant_email_idx
  ON public.clients (tenant_id, email)
  WHERE is_deleted = FALSE
    AND email IS NOT NULL;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "clients_select" ON public.clients;
CREATE POLICY "clients_select" ON public.clients
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clients_insert" ON public.clients;
CREATE POLICY "clients_insert" ON public.clients
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "clients_update" ON public.clients;
CREATE POLICY "clients_update" ON public.clients
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
DROP TRIGGER IF EXISTS clients_set_updated_at ON public.clients;
CREATE TRIGGER clients_set_updated_at
  BEFORE UPDATE ON public.clients
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
-- No functions or views in this migration.

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.clients REPLICA IDENTITY FULL;

-- STEP 9: Seed data
-- No seed data. Backfill must be performed in a later approved cutover step.

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS clients_set_updated_at ON public.clients;
-- DROP TABLE IF EXISTS public.clients CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql, 003_tenancy_core.sql, 004_clients.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/004_clients.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [clients]  →  Frontend realtime: [clients]
