-- ================================================================
-- MIGRATION: 006_integrations_metadata.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: integrations-metadata · Neon Branch: [confirm_neon_branch] · Depends on: 001, 003, 004
-- Preserves: Mongo integration documents remain source-of-truth until approved cutover; this migration stores metadata and secret references only
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.integration_catalog (
  platform TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT,
  auth_kind public.integration_auth_kind_type NOT NULL DEFAULT 'metadata_only',
  capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.tenant_integrations (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  platform TEXT NOT NULL REFERENCES public.integration_catalog(platform) ON DELETE RESTRICT,
  label TEXT NOT NULL,
  status public.integration_status_type NOT NULL DEFAULT 'not_connected',
  last_synced_at TIMESTAMPTZ,
  last_error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  vault_secret_ref TEXT,
  oauth_connection_ref TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.user_oauth_accounts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  platform TEXT NOT NULL REFERENCES public.integration_catalog(platform) ON DELETE RESTRICT,
  account_email CITEXT,
  external_account_id TEXT,
  scopes TEXT[] NOT NULL DEFAULT '{}'::text[],
  last_synced_at TIMESTAMPTZ,
  oauth_connection_ref TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.client_integration_bindings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL REFERENCES public.integration_catalog(platform) ON DELETE RESTRICT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  external_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE TABLE IF NOT EXISTS public.integration_location_bindings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  platform TEXT NOT NULL REFERENCES public.integration_catalog(platform) ON DELETE RESTRICT,
  location_id TEXT NOT NULL,
  label TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  vault_secret_ref TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

COMMENT ON COLUMN public.tenant_integrations.vault_secret_ref IS 'Reference key only. Never store raw credentials in this table.';
COMMENT ON COLUMN public.integration_location_bindings.vault_secret_ref IS 'Reference key only. Never store raw location tokens in this table.';
COMMENT ON COLUMN public.user_oauth_accounts.oauth_connection_ref IS 'Reference to external secret or token store. Raw refresh tokens do not belong in Postgres columns.';

-- STEP 4: Indexes
CREATE UNIQUE INDEX IF NOT EXISTS tenant_integrations_tenant_platform_unique_idx
  ON public.tenant_integrations (tenant_id, platform)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS tenant_integrations_status_idx
  ON public.tenant_integrations (tenant_id, status)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS user_oauth_accounts_unique_idx
  ON public.user_oauth_accounts (tenant_id, user_id, provider, platform)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS user_oauth_accounts_lookup_idx
  ON public.user_oauth_accounts (tenant_id, user_id, platform)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS client_integration_bindings_unique_idx
  ON public.client_integration_bindings (tenant_id, client_id, platform)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS client_integration_bindings_lookup_idx
  ON public.client_integration_bindings (tenant_id, platform, enabled)
  WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS integration_location_bindings_unique_idx
  ON public.integration_location_bindings (tenant_id, platform, location_id)
  WHERE is_deleted = FALSE;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.integration_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_oauth_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.client_integration_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.integration_location_bindings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "integration_catalog_select" ON public.integration_catalog;
CREATE POLICY "integration_catalog_select" ON public.integration_catalog
  FOR SELECT
  TO authenticated
  USING (is_active = TRUE);

DROP POLICY IF EXISTS "tenant_integrations_select" ON public.tenant_integrations;
CREATE POLICY "tenant_integrations_select" ON public.tenant_integrations
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "tenant_integrations_insert" ON public.tenant_integrations;
CREATE POLICY "tenant_integrations_insert" ON public.tenant_integrations
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "tenant_integrations_update" ON public.tenant_integrations;
CREATE POLICY "tenant_integrations_update" ON public.tenant_integrations
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

DROP POLICY IF EXISTS "user_oauth_accounts_select" ON public.user_oauth_accounts;
CREATE POLICY "user_oauth_accounts_select" ON public.user_oauth_accounts
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
    AND (
      user_id = auth.uid()
      OR (auth.jwt() ->> 'user_role') IN ('tenant_owner', 'manager')
    )
  );

DROP POLICY IF EXISTS "user_oauth_accounts_insert" ON public.user_oauth_accounts;
CREATE POLICY "user_oauth_accounts_insert" ON public.user_oauth_accounts
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
    AND user_id = auth.uid()
  );

DROP POLICY IF EXISTS "user_oauth_accounts_update" ON public.user_oauth_accounts;
CREATE POLICY "user_oauth_accounts_update" ON public.user_oauth_accounts
  FOR UPDATE
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
    AND (
      user_id = auth.uid()
      OR (auth.jwt() ->> 'user_role') IN ('tenant_owner', 'manager')
    )
  )
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
    AND (
      user_id = auth.uid()
      OR (auth.jwt() ->> 'user_role') IN ('tenant_owner', 'manager')
    )
  );

DROP POLICY IF EXISTS "client_integration_bindings_select" ON public.client_integration_bindings;
CREATE POLICY "client_integration_bindings_select" ON public.client_integration_bindings
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "client_integration_bindings_insert" ON public.client_integration_bindings;
CREATE POLICY "client_integration_bindings_insert" ON public.client_integration_bindings
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "client_integration_bindings_update" ON public.client_integration_bindings;
CREATE POLICY "client_integration_bindings_update" ON public.client_integration_bindings
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

DROP POLICY IF EXISTS "integration_location_bindings_select" ON public.integration_location_bindings;
CREATE POLICY "integration_location_bindings_select" ON public.integration_location_bindings
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "integration_location_bindings_insert" ON public.integration_location_bindings;
CREATE POLICY "integration_location_bindings_insert" ON public.integration_location_bindings
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "integration_location_bindings_update" ON public.integration_location_bindings;
CREATE POLICY "integration_location_bindings_update" ON public.integration_location_bindings
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
DROP TRIGGER IF EXISTS integration_catalog_set_updated_at ON public.integration_catalog;
CREATE TRIGGER integration_catalog_set_updated_at
  BEFORE UPDATE ON public.integration_catalog
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS tenant_integrations_set_updated_at ON public.tenant_integrations;
CREATE TRIGGER tenant_integrations_set_updated_at
  BEFORE UPDATE ON public.tenant_integrations
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS user_oauth_accounts_set_updated_at ON public.user_oauth_accounts;
CREATE TRIGGER user_oauth_accounts_set_updated_at
  BEFORE UPDATE ON public.user_oauth_accounts
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS client_integration_bindings_set_updated_at ON public.client_integration_bindings;
CREATE TRIGGER client_integration_bindings_set_updated_at
  BEFORE UPDATE ON public.client_integration_bindings
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS integration_location_bindings_set_updated_at ON public.integration_location_bindings;
CREATE TRIGGER integration_location_bindings_set_updated_at
  BEFORE UPDATE ON public.integration_location_bindings
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
-- No functions or views in this migration.

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.tenant_integrations REPLICA IDENTITY FULL;
ALTER TABLE public.user_oauth_accounts REPLICA IDENTITY FULL;
ALTER TABLE public.client_integration_bindings REPLICA IDENTITY FULL;
ALTER TABLE public.integration_location_bindings REPLICA IDENTITY FULL;

-- STEP 9: Seed data
INSERT INTO public.integration_catalog (platform, label, category, description, auth_kind, capabilities)
VALUES
  ('google_oauth', 'Google OAuth', 'Core', 'OAuth client used for Google-connected products.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('clickup', 'ClickUp', 'Project Management', 'Pull account activity and push action items.', 'vault_ref', '{"supports_push": true}'::jsonb),
  ('gohighlevel', 'GoHighLevel', 'CRM', 'CRM pipelines, leads, communications, workflows.', 'vault_ref', '{"supports_import": true}'::jsonb),
  ('google_ads', 'Google Ads', 'Paid Media', 'PPC metrics, conversions, budget pacing, optimization opportunities.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_business_profile', 'Google Business Profile', 'Local SEO', 'GBP calls, direction requests, reviews, local visibility.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_analytics', 'Google Analytics 4', 'Analytics', 'Traffic, conversions, attribution, engagement.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_search_console', 'Google Search Console', 'SEO', 'Organic keywords, CTR, impressions, indexing.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('ahrefs', 'Ahrefs', 'SEO', 'Backlinks, organic keywords, competitor analysis.', 'vault_ref', '{"supports_pull": true}'::jsonb),
  ('meta_ads', 'Meta Ads', 'Paid Media', 'Facebook and Instagram ads, retargeting, lead generation.', 'vault_ref', '{"supports_pull": true}'::jsonb),
  ('google_lsa', 'Google LSA (Local Services Ads)', 'Paid Media', 'LSA leads, calls, lead quality scoring.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_drive', 'Google Drive', 'Documents', 'Onboarding forms, deliverables, photos, meeting recordings.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('gmail', 'Gmail', 'Communication', 'Communication history and follow-up drafts.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_meet', 'Google Meet', 'Meetings', 'Meeting recordings and transcript discovery.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_calendar', 'Google Calendar', 'Meetings', 'Calendar synchronization.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('map_checkins', 'Map Check-ins', 'Local Rank Tracking', 'Geo-grid heat map rankings and field check-ins.', 'vault_ref', '{"supports_pull": true}'::jsonb)
ON CONFLICT (platform) DO UPDATE
SET label = EXCLUDED.label,
    category = EXCLUDED.category,
    description = EXCLUDED.description,
    auth_kind = EXCLUDED.auth_kind,
    capabilities = EXCLUDED.capabilities,
    is_active = TRUE,
    updated_at = NOW();

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS integration_location_bindings_set_updated_at ON public.integration_location_bindings;
-- DROP TRIGGER IF EXISTS client_integration_bindings_set_updated_at ON public.client_integration_bindings;
-- DROP TRIGGER IF EXISTS user_oauth_accounts_set_updated_at ON public.user_oauth_accounts;
-- DROP TRIGGER IF EXISTS tenant_integrations_set_updated_at ON public.tenant_integrations;
-- DROP TRIGGER IF EXISTS integration_catalog_set_updated_at ON public.integration_catalog;
-- DROP TABLE IF EXISTS public.integration_location_bindings CASCADE;
-- DROP TABLE IF EXISTS public.client_integration_bindings CASCADE;
-- DROP TABLE IF EXISTS public.user_oauth_accounts CASCADE;
-- DROP TABLE IF EXISTS public.tenant_integrations CASCADE;
-- DROP TABLE IF EXISTS public.integration_catalog CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql, 003_tenancy_core.sql, 004_clients.sql, 005_meetings.sql, 006_integrations_metadata.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/006_integrations_metadata.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [integration_catalog, tenant_integrations, user_oauth_accounts, client_integration_bindings, integration_location_bindings]  →  Frontend realtime: [tenant_integrations, client_integration_bindings]
