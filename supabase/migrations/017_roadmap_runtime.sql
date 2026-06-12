CREATE TABLE IF NOT EXISTS public.roadmap_plans (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  start_date DATE NOT NULL,
  weeks INTEGER NOT NULL DEFAULT 12,
  items JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_roadmap_plans_unique_client
  ON public.roadmap_plans (tenant_id, client_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_roadmap_plans_legacy
  ON public.roadmap_plans (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
