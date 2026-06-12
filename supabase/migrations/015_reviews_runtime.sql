CREATE TABLE IF NOT EXISTS public.client_review_goals (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  monthly_goal INTEGER NOT NULL DEFAULT 10,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_client_review_goals_unique_client
  ON public.client_review_goals (tenant_id, client_id)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_client_review_goals_legacy
  ON public.client_review_goals (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;

CREATE TABLE IF NOT EXISTS public.review_events (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  meeting_id UUID REFERENCES public.meetings(id) ON DELETE SET NULL,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  kind TEXT NOT NULL DEFAULT 'requested',
  count INTEGER NOT NULL DEFAULT 1,
  occurred_on DATE NOT NULL,
  channel TEXT DEFAULT 'other',
  source TEXT DEFAULT 'manual',
  notes TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_events_client_occurred
  ON public.review_events (tenant_id, client_id, occurred_on DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_review_events_legacy
  ON public.review_events (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;

CREATE TABLE IF NOT EXISTS public.review_monthly_snapshots (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  month TEXT NOT NULL,
  received INTEGER NOT NULL DEFAULT 0,
  avg_rating NUMERIC,
  source TEXT DEFAULT 'gbp',
  kpi_period_kind TEXT,
  kpi_period_current_end DATE,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_monthly_snapshots_unique_month
  ON public.review_monthly_snapshots (tenant_id, client_id, month)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_review_monthly_snapshots_month
  ON public.review_monthly_snapshots (tenant_id, month DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_review_monthly_snapshots_legacy
  ON public.review_monthly_snapshots (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
