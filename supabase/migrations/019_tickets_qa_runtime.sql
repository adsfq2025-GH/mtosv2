CREATE TABLE IF NOT EXISTS public.tickets (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  meeting_id UUID NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  department TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'open',
  external_id TEXT,
  external_url TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_meeting
  ON public.tickets (tenant_id, meeting_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_tickets_client
  ON public.tickets (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_tickets_legacy
  ON public.tickets (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;

CREATE TABLE IF NOT EXISTS public.qa_scorecards (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  meeting_id UUID NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  account_manager_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  account_manager_name TEXT,
  total_score INTEGER NOT NULL DEFAULT 0,
  dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
  feedback TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_scorecards_meeting
  ON public.qa_scorecards (tenant_id, meeting_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_qa_scorecards_client
  ON public.qa_scorecards (tenant_id, client_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_qa_scorecards_legacy
  ON public.qa_scorecards (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
