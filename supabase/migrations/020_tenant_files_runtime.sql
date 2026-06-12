CREATE TABLE IF NOT EXISTS public.tenant_files (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  legacy_source_id TEXT,
  legacy_source_kind TEXT NOT NULL DEFAULT 'runtime',
  purpose TEXT NOT NULL DEFAULT 'documentation',
  filename TEXT,
  mime_type TEXT,
  size_bytes BIGINT NOT NULL DEFAULT 0,
  storage JSONB NOT NULL DEFAULT '{}'::jsonb,
  extracted_text TEXT,
  extracted_chars INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  is_deleted BOOLEAN DEFAULT FALSE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tenant_files_tenant_created
  ON public.tenant_files (tenant_id, created_at DESC)
  WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_tenant_files_legacy
  ON public.tenant_files (tenant_id, legacy_source_id)
  WHERE legacy_source_id IS NOT NULL AND is_deleted = FALSE;
