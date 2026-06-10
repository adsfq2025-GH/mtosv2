-- ================================================================
-- MIGRATION: 005_meetings.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: meetings-core · Neon Branch: [confirm_neon_branch] · Depends on: 001, 003, 004
-- Preserves: Mongo meetings collection remains source-of-truth until phased backfill validation is approved
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
CREATE TABLE IF NOT EXISTS public.meetings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  client_name TEXT,
  account_manager_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  account_manager_name TEXT,
  title TEXT NOT NULL,
  scheduled_at TIMESTAMPTZ,
  status public.meeting_status_type NOT NULL DEFAULT 'scheduled',
  google_meet_url TEXT,
  duration_minutes INTEGER NOT NULL DEFAULT 60,
  brief_generated_at TIMESTAMPTZ,
  brief_model TEXT,
  wins JSONB NOT NULL DEFAULT '[]'::jsonb,
  wins_library JSONB NOT NULL DEFAULT '[]'::jsonb,
  issues JSONB NOT NULL DEFAULT '[]'::jsonb,
  issues_library JSONB NOT NULL DEFAULT '[]'::jsonb,
  talking_points JSONB NOT NULL DEFAULT '[]'::jsonb,
  talking_points_library JSONB NOT NULL DEFAULT '[]'::jsonb,
  suggested_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
  prep_checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
  ace_up_the_sleeve JSONB NOT NULL DEFAULT '[]'::jsonb,
  testimonial_opportunity TEXT,
  strategic_recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
  campaign_recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
  health_signal TEXT,
  automation_draft JSONB NOT NULL DEFAULT '{}'::jsonb,
  automation_draft_generated_at TIMESTAMPTZ,
  automation_approved_at TIMESTAMPTZ,
  kpi_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  notes TEXT,
  transcript TEXT,
  transcript_source JSONB NOT NULL DEFAULT '{}'::jsonb,
  transcript_analyzed_at TIMESTAMPTZ,
  sentiment public.sentiment_type,
  sentiment_summary TEXT,
  transcript_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
  transcript_analysis_by_model JSONB NOT NULL DEFAULT '{}'::jsonb,
  nps_score INTEGER,
  sentiment_classification TEXT,
  health_notes TEXT,
  recap_html TEXT,
  recap_email TEXT,
  recap_subject TEXT,
  recap_sent_at TIMESTAMPTZ,
  meeting_score INTEGER,
  checklist JSONB NOT NULL DEFAULT '{}'::jsonb,
  deliverable_reviews JSONB NOT NULL DEFAULT '{}'::jsonb,
  discovery_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
  feedback JSONB,
  legacy_meeting_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
  CONSTRAINT meetings_duration_minutes_check CHECK (duration_minutes > 0),
  CONSTRAINT meetings_nps_score_check CHECK (nps_score IS NULL OR (nps_score BETWEEN 0 AND 10)),
  CONSTRAINT meetings_meeting_score_check CHECK (meeting_score IS NULL OR (meeting_score BETWEEN 0 AND 100))
);

COMMENT ON TABLE public.meetings IS 'Parallel Postgres meeting records for phased Mongo to Supabase cutover.';

-- STEP 4: Indexes
CREATE INDEX IF NOT EXISTS meetings_tenant_client_created_at_idx
  ON public.meetings (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS meetings_tenant_scheduled_at_idx
  ON public.meetings (tenant_id, scheduled_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS meetings_tenant_status_idx
  ON public.meetings (tenant_id, status)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS meetings_tenant_account_manager_idx
  ON public.meetings (tenant_id, account_manager_user_id)
  WHERE is_deleted = FALSE;

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "meetings_select" ON public.meetings;
CREATE POLICY "meetings_select" ON public.meetings
  FOR SELECT
  TO authenticated
  USING (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "meetings_insert" ON public.meetings;
CREATE POLICY "meetings_insert" ON public.meetings
  FOR INSERT
  TO authenticated
  WITH CHECK (
    tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
    AND is_deleted = FALSE
  );

DROP POLICY IF EXISTS "meetings_update" ON public.meetings;
CREATE POLICY "meetings_update" ON public.meetings
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
DROP TRIGGER IF EXISTS meetings_set_updated_at ON public.meetings;
CREATE TRIGGER meetings_set_updated_at
  BEFORE UPDATE ON public.meetings
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- STEP 7: Functions / Views
-- No functions or views in this migration.

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
ALTER TABLE public.meetings REPLICA IDENTITY FULL;

-- STEP 9: Seed data
-- No seed data. Backfill must be performed in a later approved cutover step.

-- ================================================================
-- ROLLBACK:
-- DROP TRIGGER IF EXISTS meetings_set_updated_at ON public.meetings;
-- DROP TABLE IF EXISTS public.meetings CASCADE;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql, 002_auth_profiles.sql, 003_tenancy_core.sql, 004_clients.sql, 005_meetings.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/005_meetings.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [meetings]  →  Frontend realtime: [meetings]
