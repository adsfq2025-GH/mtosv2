-- ================================================================
-- MIGRATION: 009_bridge_apply_execute_hardening.sql
-- Mode: BROWNFIELD-FIX
-- Module: bridge-security-hardening · Neon Branch: main · Depends on: 007, 008
-- Preserves: bridge_apply_* function bodies remain untouched; grants are narrowed additively to intended privileged roles only
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
REVOKE EXECUTE ON FUNCTION public.bridge_apply_users(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_tenants(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_memberships(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bridge_apply_all(UUID) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.bridge_apply_users(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_tenants(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_memberships(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_all(UUID) TO service_role, supabase_auth_admin;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
-- Realtime not applicable to function grant hardening.

-- STEP 9: Seed data
-- No seed data in this migration.
-- ================================================================
-- ROLLBACK:
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_users(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_tenants(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_memberships(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) TO PUBLIC, anon, authenticated;
-- GRANT EXECUTE ON FUNCTION public.bridge_apply_all(UUID) TO PUBLIC, anon, authenticated;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [009_bridge_apply_execute_hardening.sql]  ·  Target Neon branch: [main]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/009_bridge_apply_execute_hardening.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [bridge_apply_all]  →  Frontend realtime: [none]
