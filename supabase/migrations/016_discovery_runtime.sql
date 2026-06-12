CREATE TABLE IF NOT EXISTS public.discovery_question_templates (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  kind TEXT NOT NULL DEFAULT 'operational',
  category TEXT NOT NULL,
  question TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  deliverables JSONB NOT NULL DEFAULT '[]'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discovery_templates_tenant_created
  ON public.discovery_question_templates (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_discovery_templates_legacy
  ON public.discovery_question_templates (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
