-- ================================================================
-- MIGRATION: 014_ai_visibility_runtime.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: ai-visibility-runtime · Depends on: 003, 004
-- Preserves: Existing runtime/API behavior while AI visibility and territory scans
--            are moved onto Supabase-backed storage behind feature flags.
-- ================================================================

CREATE TABLE IF NOT EXISTS public.ai_visibility_configs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'mongo',
  market TEXT NOT NULL DEFAULT '',
  market_override TEXT,
  keywords TEXT[] NOT NULL DEFAULT '{}'::text[],
  brand_override TEXT,
  domain_override TEXT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ai_visibility_configs_tenant_client_unique_idx
  ON public.ai_visibility_configs (tenant_id, client_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_visibility_configs_tenant_created_idx
  ON public.ai_visibility_configs (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_visibility_configs_legacy_source_idx
  ON public.ai_visibility_configs (legacy_source_id)
  WHERE is_deleted = FALSE
    AND legacy_source_id IS NOT NULL;

ALTER TABLE public.ai_visibility_configs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ai_visibility_configs_select" ON public.ai_visibility_configs;
CREATE POLICY "ai_visibility_configs_select" ON public.ai_visibility_configs
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_configs_insert" ON public.ai_visibility_configs;
CREATE POLICY "ai_visibility_configs_insert" ON public.ai_visibility_configs
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_configs_update" ON public.ai_visibility_configs;
CREATE POLICY "ai_visibility_configs_update" ON public.ai_visibility_configs
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

DROP TRIGGER IF EXISTS ai_visibility_configs_set_updated_at ON public.ai_visibility_configs;
CREATE TRIGGER ai_visibility_configs_set_updated_at
  BEFORE UPDATE ON public.ai_visibility_configs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.ai_visibility_configs REPLICA IDENTITY FULL;


CREATE TABLE IF NOT EXISTS public.ai_visibility_runs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  config_id UUID NOT NULL REFERENCES public.ai_visibility_configs(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'mongo',
  scan_id TEXT,
  market TEXT NOT NULL DEFAULT '',
  keyword TEXT NOT NULL,
  theme TEXT,
  prompt_kind TEXT,
  provider TEXT NOT NULL,
  prompt TEXT NOT NULL DEFAULT '',
  response_text TEXT NOT NULL DEFAULT '',
  parsed JSONB NOT NULL DEFAULT '{}'::jsonb,
  hit BOOLEAN NOT NULL DEFAULT FALSE,
  hit_brand BOOLEAN NOT NULL DEFAULT FALSE,
  hit_domain BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS ai_visibility_runs_config_created_idx
  ON public.ai_visibility_runs (config_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_visibility_runs_scan_idx
  ON public.ai_visibility_runs (tenant_id, scan_id, created_at DESC)
  WHERE is_deleted = FALSE
    AND scan_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ai_visibility_runs_legacy_source_idx
  ON public.ai_visibility_runs (legacy_source_id)
  WHERE is_deleted = FALSE
    AND legacy_source_id IS NOT NULL;

ALTER TABLE public.ai_visibility_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ai_visibility_runs_select" ON public.ai_visibility_runs;
CREATE POLICY "ai_visibility_runs_select" ON public.ai_visibility_runs
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_runs_insert" ON public.ai_visibility_runs;
CREATE POLICY "ai_visibility_runs_insert" ON public.ai_visibility_runs
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_runs_update" ON public.ai_visibility_runs;
CREATE POLICY "ai_visibility_runs_update" ON public.ai_visibility_runs
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

DROP TRIGGER IF EXISTS ai_visibility_runs_set_updated_at ON public.ai_visibility_runs;
CREATE TRIGGER ai_visibility_runs_set_updated_at
  BEFORE UPDATE ON public.ai_visibility_runs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.ai_visibility_runs REPLICA IDENTITY FULL;


CREATE TABLE IF NOT EXISTS public.ai_visibility_scans (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  config_id UUID NOT NULL REFERENCES public.ai_visibility_configs(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'mongo',
  scan_id TEXT,
  market TEXT NOT NULL DEFAULT '',
  brand TEXT NOT NULL DEFAULT '',
  domain TEXT NOT NULL DEFAULT '',
  providers JSONB NOT NULL DEFAULT '{}'::jsonb,
  total INTEGER NOT NULL DEFAULT 0,
  hits INTEGER NOT NULL DEFAULT 0,
  overall_visibility_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  share_of_voice JSONB NOT NULL DEFAULT '{}'::jsonb,
  platform_rankings JSONB NOT NULL DEFAULT '{}'::jsonb,
  themes JSONB NOT NULL DEFAULT '[]'::jsonb,
  prompts_total INTEGER NOT NULL DEFAULT 0,
  competitors JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_intelligence JSONB NOT NULL DEFAULT '{}'::jsonb,
  growth_engine JSONB NOT NULL DEFAULT '{}'::jsonb,
  territory_intelligence JSONB NOT NULL DEFAULT '{}'::jsonb,
  data_confidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS ai_visibility_scans_config_created_idx
  ON public.ai_visibility_scans (config_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_visibility_scans_client_created_idx
  ON public.ai_visibility_scans (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_visibility_scans_scan_id_idx
  ON public.ai_visibility_scans (tenant_id, scan_id)
  WHERE is_deleted = FALSE
    AND scan_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ai_visibility_scans_legacy_source_idx
  ON public.ai_visibility_scans (legacy_source_id)
  WHERE is_deleted = FALSE
    AND legacy_source_id IS NOT NULL;

ALTER TABLE public.ai_visibility_scans ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ai_visibility_scans_select" ON public.ai_visibility_scans;
CREATE POLICY "ai_visibility_scans_select" ON public.ai_visibility_scans
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_scans_insert" ON public.ai_visibility_scans;
CREATE POLICY "ai_visibility_scans_insert" ON public.ai_visibility_scans
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_visibility_scans_update" ON public.ai_visibility_scans;
CREATE POLICY "ai_visibility_scans_update" ON public.ai_visibility_scans
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

DROP TRIGGER IF EXISTS ai_visibility_scans_set_updated_at ON public.ai_visibility_scans;
CREATE TRIGGER ai_visibility_scans_set_updated_at
  BEFORE UPDATE ON public.ai_visibility_scans
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.ai_visibility_scans REPLICA IDENTITY FULL;


CREATE TABLE IF NOT EXISTS public.ai_territory_events (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  account_manager_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'mongo',
  kind TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'low',
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  scan_id TEXT,
  explain JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS ai_territory_events_client_created_idx
  ON public.ai_territory_events (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS ai_territory_events_scan_idx
  ON public.ai_territory_events (tenant_id, scan_id, created_at DESC)
  WHERE is_deleted = FALSE
    AND scan_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ai_territory_events_legacy_source_idx
  ON public.ai_territory_events (legacy_source_id)
  WHERE is_deleted = FALSE
    AND legacy_source_id IS NOT NULL;

ALTER TABLE public.ai_territory_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ai_territory_events_select" ON public.ai_territory_events;
CREATE POLICY "ai_territory_events_select" ON public.ai_territory_events
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_territory_events_insert" ON public.ai_territory_events;
CREATE POLICY "ai_territory_events_insert" ON public.ai_territory_events
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "ai_territory_events_update" ON public.ai_territory_events;
CREATE POLICY "ai_territory_events_update" ON public.ai_territory_events
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

DROP TRIGGER IF EXISTS ai_territory_events_set_updated_at ON public.ai_territory_events;
CREATE TRIGGER ai_territory_events_set_updated_at
  BEFORE UPDATE ON public.ai_territory_events
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.ai_territory_events REPLICA IDENTITY FULL;

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS ai_territory_events_set_updated_at ON public.ai_territory_events;
-- DROP TRIGGER IF EXISTS ai_visibility_scans_set_updated_at ON public.ai_visibility_scans;
-- DROP TRIGGER IF EXISTS ai_visibility_runs_set_updated_at ON public.ai_visibility_runs;
-- DROP TRIGGER IF EXISTS ai_visibility_configs_set_updated_at ON public.ai_visibility_configs;
-- DROP TABLE IF EXISTS public.ai_territory_events CASCADE;
-- DROP TABLE IF EXISTS public.ai_visibility_scans CASCADE;
-- DROP TABLE IF EXISTS public.ai_visibility_runs CASCADE;
-- DROP TABLE IF EXISTS public.ai_visibility_configs CASCADE;
-- ================================================================
