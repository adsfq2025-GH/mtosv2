CREATE TABLE IF NOT EXISTS public.content_captures (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  meeting_id UUID REFERENCES public.meetings(id) ON DELETE SET NULL,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  type TEXT NOT NULL DEFAULT 'quote',
  content TEXT NOT NULL,
  sentiment_score NUMERIC,
  timestamp_in_meeting TEXT,
  requested BOOLEAN NOT NULL DEFAULT FALSE,
  received BOOLEAN NOT NULL DEFAULT FALSE,
  routed_to_marketing BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_content_captures_tenant_created
  ON public.content_captures (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_content_captures_client
  ON public.content_captures (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_content_captures_meeting
  ON public.content_captures (tenant_id, meeting_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_content_captures_legacy
  ON public.content_captures (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
