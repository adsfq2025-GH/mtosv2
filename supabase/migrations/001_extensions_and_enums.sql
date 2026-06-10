-- ================================================================
-- MIGRATION: 001_extensions_and_enums.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: foundation · Neon Branch: [confirm_neon_branch] · Depends on: none
-- Preserves: Mongo runtime untouched; additive Postgres foundation only
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- STEP 2: Enums
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'user_role_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.user_role_type AS ENUM
      ('platform_admin','tenant_owner','manager','staff','customer');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'booking_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.booking_status_type AS ENUM
      ('pending','confirmed','en_route','in_progress','completed','cancelled','no_show');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'subscription_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.subscription_status_type AS ENUM
      ('onboarding','trialing','active','past_due','canceled','suspended');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'membership_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.membership_status_type AS ENUM
      ('active','invited','disabled');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'tenant_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.tenant_status_type AS ENUM
      ('active','suspended','archived');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'client_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.client_status_type AS ENUM
      ('active','paused','churned');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'risk_level_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.risk_level_type AS ENUM
      ('low','medium','high');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'sentiment_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.sentiment_type AS ENUM
      ('positive','neutral','negative');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'meeting_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.meeting_status_type AS ENUM
      ('scheduled','prep','in_progress','completed','cancelled');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'integration_status_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.integration_status_type AS ENUM
      ('not_connected','connected','error','coming_soon');
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'integration_auth_kind_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.integration_auth_kind_type AS ENUM
      ('oauth','api_key','metadata_only','vault_ref','external_secret');
  END IF;
END
$$;

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
-- No tables in this migration.

-- STEP 4: Indexes
-- No indexes in this migration.

-- STEP 5: RLS (ENABLE + all policies)
-- No tables in this migration.

-- STEP 6: Triggers (updated_at + business logic)
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

-- STEP 7: Functions / Views
CREATE OR REPLACE FUNCTION public.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'tenant_id', '')::uuid
$$;

CREATE OR REPLACE FUNCTION public.current_member_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'member_id', '')::uuid
$$;

CREATE OR REPLACE FUNCTION public.current_user_role()
RETURNS public.user_role_type
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'user_role', '')::public.user_role_type
$$;

CREATE OR REPLACE FUNCTION public.current_tenant_slug()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'tenant_slug', '')
$$;

CREATE OR REPLACE FUNCTION public.current_subscription_status()
RETURNS public.subscription_status_type
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(auth.jwt() ->> 'subscription_status', '')::public.subscription_status_type
$$;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
-- No realtime tables in this migration.

-- STEP 9: Seed data
-- No seed data in this migration.

-- ================================================================
-- ROLLBACK:
-- DROP FUNCTION IF EXISTS public.current_subscription_status();
-- DROP FUNCTION IF EXISTS public.current_tenant_slug();
-- DROP FUNCTION IF EXISTS public.current_user_role();
-- DROP FUNCTION IF EXISTS public.current_member_id();
-- DROP FUNCTION IF EXISTS public.current_tenant_id();
-- DROP FUNCTION IF EXISTS public.set_updated_at();
-- DROP TYPE IF EXISTS public.integration_auth_kind_type;
-- DROP TYPE IF EXISTS public.integration_status_type;
-- DROP TYPE IF EXISTS public.meeting_status_type;
-- DROP TYPE IF EXISTS public.sentiment_type;
-- DROP TYPE IF EXISTS public.risk_level_type;
-- DROP TYPE IF EXISTS public.client_status_type;
-- DROP TYPE IF EXISTS public.tenant_status_type;
-- DROP TYPE IF EXISTS public.membership_status_type;
-- DROP TYPE IF EXISTS public.subscription_status_type;
-- DROP TYPE IF EXISTS public.booking_status_type;
-- DROP TYPE IF EXISTS public.user_role_type;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [001_extensions_and_enums.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/001_extensions_and_enums.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [foundation helper functions and enums]  →  Frontend realtime: [none]
