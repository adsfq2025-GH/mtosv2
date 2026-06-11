-- ================================================================
-- MIGRATION: 011_bridge_tenant_fallback_uuid_fix.sql
-- Mode: BROWNFIELD-FIX
-- Module: bridge-tenant-fallback-fix · Neon Branch: main · Depends on: 010
-- Preserves: bridge helper functions and staged payloads remain additive-only; no tables or rows are dropped
-- ================================================================
-- STEP 1: Extensions
-- No extension changes in this migration.

-- STEP 2: Enums
-- No enum changes in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
-- No table changes in this migration.

-- STEP 4: Indexes
-- No index changes in this migration.

-- STEP 5: RLS (ENABLE + all policies)
-- No RLS changes in this migration.

-- STEP 6: Triggers (updated_at + business logic)
-- No trigger changes in this migration.

-- STEP 7: Functions / Views
CREATE OR REPLACE FUNCTION public.bridge_resolve_tenant_id_fallback(
  p_source_system TEXT,
  p_tenant_source_id TEXT DEFAULT NULL,
  p_payload JSONB DEFAULT '{}'::jsonb,
  p_client_source_id TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_target_tenant_id UUID;
  v_source_tenant_id TEXT;
  v_client_source_id TEXT;
BEGIN
  v_source_tenant_id := COALESCE(
    NULLIF(BTRIM(p_tenant_source_id), ''),
    NULLIF(BTRIM(p_payload ->> 'tenant_id'), '')
  );

  IF v_source_tenant_id IS NOT NULL THEN
    v_target_tenant_id := public.bridge_resolve_target_id(
      'tenants',
      v_source_tenant_id,
      COALESCE(NULLIF(BTRIM(p_source_system), ''), 'mongo')
    );

    IF v_target_tenant_id IS NOT NULL THEN
      RETURN v_target_tenant_id;
    END IF;
  END IF;

  v_client_source_id := COALESCE(
    NULLIF(BTRIM(p_client_source_id), ''),
    NULLIF(BTRIM(p_payload ->> 'client_id'), '')
  );

  IF v_client_source_id IS NOT NULL THEN
    SELECT c.tenant_id
    INTO v_target_tenant_id
    FROM public.clients c
    WHERE c.id = public.bridge_resolve_target_id(
      'clients',
      v_client_source_id,
      COALESCE(NULLIF(BTRIM(p_source_system), ''), 'mongo')
    )
      AND c.is_deleted = FALSE
    LIMIT 1;

    IF v_target_tenant_id IS NOT NULL THEN
      RETURN v_target_tenant_id;
    END IF;
  END IF;

  SELECT singleton_tenant_id
  INTO v_target_tenant_id
  FROM (
    SELECT CASE
      WHEN COUNT(*) = 1 THEN (ARRAY_AGG(t.id ORDER BY t.created_at ASC))[1]
      ELSE NULL::uuid
    END AS singleton_tenant_id
    FROM public.tenants t
    WHERE t.is_deleted = FALSE
  ) singleton_scope;

  RETURN v_target_tenant_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT) TO service_role, supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT) FROM authenticated, anon, public;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
-- Realtime not applicable to helper function patch.

-- STEP 9: Seed data
-- No seed data in this migration.
-- ================================================================
-- ROLLBACK:
-- Reapply: supabase/migrations/010_bridge_blocker_fixes.sql
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [011_bridge_tenant_fallback_uuid_fix.sql]  ·  Target Neon branch: [main]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/011_bridge_tenant_fallback_uuid_fix.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [bridge_resolve_tenant_id_fallback]  →  Frontend realtime: [none]
