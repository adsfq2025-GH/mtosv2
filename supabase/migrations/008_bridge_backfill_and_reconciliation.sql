-- ================================================================
-- MIGRATION: 008_bridge_backfill_and_reconciliation.sql
-- Mode: BROWNFIELD-ADDITIVE
-- Module: bridge-apply · Neon Branch: [confirm_neon_branch] · Depends on: 001, 002, 003, 004, 005, 006, 007
-- Preserves: Mongo runtime untouched; bridge application is additive and idempotent against staged source payloads only
-- ================================================================
-- STEP 1: Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- STEP 2: Enums
-- No new enums in this migration.

-- STEP 3: CREATE TABLE or ALTER TABLE (additive only in Brownfield)
-- No new tables in this migration.

-- STEP 4: Indexes
-- No new indexes in this migration.

-- STEP 5: RLS (ENABLE + all policies)
ALTER TABLE public.bridge_import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_staging_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_source_id_maps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_import_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bridge_reconciliation_snapshots ENABLE ROW LEVEL SECURITY;

-- STEP 6: Triggers (updated_at + business logic)
-- No new triggers in this migration.

-- STEP 7: Functions / Views
CREATE OR REPLACE VIEW public.bridge_run_entity_summary_v
AS
SELECT
  s.import_run_id,
  s.entity_type,
  COUNT(*) AS source_count,
  COUNT(*) FILTER (WHERE s.status = 'staged') AS staged_count,
  COUNT(*) FILTER (WHERE s.status = 'applied') AS applied_count,
  COUNT(*) FILTER (WHERE s.status = 'blocked') AS blocked_count,
  COUNT(*) FILTER (WHERE s.status = 'error') AS error_count,
  COUNT(DISTINCT m.source_id) AS mapped_count,
  COUNT(i.id) AS issue_count,
  MAX(s.updated_at) AS last_updated_at
FROM public.bridge_staging_payloads s
LEFT JOIN public.bridge_source_id_maps m
  ON m.source_system = s.source_system
 AND m.entity_type = s.entity_type
 AND m.source_id = s.source_id
LEFT JOIN public.bridge_import_issues i
  ON i.import_run_id = s.import_run_id
 AND i.entity_type = s.entity_type
 AND COALESCE(i.source_id, '') = COALESCE(s.source_id, '')
GROUP BY s.import_run_id, s.entity_type;

CREATE OR REPLACE VIEW public.bridge_issue_summary_v
AS
SELECT
  import_run_id,
  entity_type,
  severity,
  code,
  COUNT(*) AS issue_count,
  MAX(created_at) AS last_created_at
FROM public.bridge_import_issues
GROUP BY import_run_id, entity_type, severity, code;

CREATE OR REPLACE FUNCTION public.bridge_capture_reconciliation_snapshot(
  p_import_run_id UUID,
  p_entity_type TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_source_count INTEGER := 0;
  v_staged_count INTEGER := 0;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_mapped_count INTEGER := 0;
  v_target_count INTEGER := 0;
  v_mismatch_count INTEGER := 0;
BEGIN
  SELECT
    COUNT(*),
    COUNT(*) FILTER (WHERE status = 'staged'),
    COUNT(*) FILTER (WHERE status = 'applied'),
    COUNT(*) FILTER (WHERE status IN ('blocked', 'error'))
  INTO
    v_source_count,
    v_staged_count,
    v_applied_count,
    v_blocked_count
  FROM public.bridge_staging_payloads
  WHERE import_run_id = p_import_run_id
    AND entity_type = p_entity_type;

  SELECT COUNT(*)
  INTO v_mapped_count
  FROM public.bridge_source_id_maps m
  WHERE m.entity_type = p_entity_type
    AND EXISTS (
      SELECT 1
      FROM public.bridge_staging_payloads s
      WHERE s.import_run_id = p_import_run_id
        AND s.entity_type = p_entity_type
        AND s.source_system = m.source_system
        AND s.source_id = m.source_id
    );

  SELECT COUNT(*)
  INTO v_mismatch_count
  FROM public.bridge_import_issues i
  WHERE i.import_run_id = p_import_run_id
    AND i.entity_type = p_entity_type
    AND i.severity = 'error';

  v_target_count := CASE p_entity_type
    WHEN 'users' THEN (
      SELECT COUNT(*)
      FROM public.user_profiles up
      WHERE EXISTS (
        SELECT 1
        FROM public.bridge_source_id_maps m
        WHERE m.entity_type = 'users'
          AND m.target_id = up.id
          AND EXISTS (
            SELECT 1
            FROM public.bridge_staging_payloads s
            WHERE s.import_run_id = p_import_run_id
              AND s.entity_type = 'users'
              AND s.source_system = m.source_system
              AND s.source_id = m.source_id
          )
      )
    )
    WHEN 'tenants' THEN (
      SELECT COUNT(*)
      FROM public.tenants t
      WHERE t.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'tenants'
            AND m.target_id = t.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'tenants'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    WHEN 'memberships' THEN (
      SELECT COUNT(*)
      FROM public.tenant_members tm
      WHERE tm.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'memberships'
            AND m.target_id = tm.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'memberships'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    WHEN 'clients' THEN (
      SELECT COUNT(*)
      FROM public.clients c
      WHERE c.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'clients'
            AND m.target_id = c.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'clients'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    WHEN 'meetings' THEN (
      SELECT COUNT(*)
      FROM public.meetings mt
      WHERE mt.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'meetings'
            AND m.target_id = mt.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'meetings'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    WHEN 'integrations' THEN (
      SELECT COUNT(*)
      FROM public.tenant_integrations ti
      WHERE ti.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'integrations'
            AND m.target_id = ti.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'integrations'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    WHEN 'client_bindings' THEN (
      SELECT COUNT(*)
      FROM public.client_integration_bindings cb
      WHERE cb.is_deleted = FALSE
        AND EXISTS (
          SELECT 1
          FROM public.bridge_source_id_maps m
          WHERE m.entity_type = 'client_bindings'
            AND m.target_id = cb.id
            AND EXISTS (
              SELECT 1
              FROM public.bridge_staging_payloads s
              WHERE s.import_run_id = p_import_run_id
                AND s.entity_type = 'client_bindings'
                AND s.source_system = m.source_system
                AND s.source_id = m.source_id
            )
        )
    )
    ELSE 0
  END;

  DELETE FROM public.bridge_reconciliation_snapshots
  WHERE import_run_id = p_import_run_id
    AND entity_type = p_entity_type;

  INSERT INTO public.bridge_reconciliation_snapshots (
    import_run_id,
    entity_type,
    source_count,
    staged_count,
    applied_count,
    blocked_count,
    mapped_count,
    target_count,
    mismatch_count,
    details,
    created_at,
    updated_at
  )
  VALUES (
    p_import_run_id,
    p_entity_type,
    v_source_count,
    v_staged_count,
    v_applied_count,
    v_blocked_count,
    v_mapped_count,
    v_target_count,
    v_mismatch_count,
    jsonb_build_object(
      'captured_at', NOW(),
      'entity_type', p_entity_type
    ),
    NOW(),
    NOW()
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_refresh_run_snapshots(p_import_run_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_entity_type TEXT;
BEGIN
  FOR v_entity_type IN
    SELECT UNNEST(ARRAY['users','tenants','memberships','clients','meetings','integrations','client_bindings']::text[])
  LOOP
    PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, v_entity_type);
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_users(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_user_id UUID;
  v_legacy_uuid UUID;
  v_email CITEXT;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'users'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_email := NULLIF(LOWER(BTRIM(rec.payload ->> 'email')), '')::citext;
      v_legacy_uuid := public.bridge_safe_uuid(rec.source_id);

      SELECT COALESCE(
        public.bridge_resolve_target_id('users', rec.source_id, rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = v_legacy_uuid
          LIMIT 1
        ),
        (
          SELECT au.id
          FROM auth.users au
          WHERE v_email IS NOT NULL
            AND LOWER(au.email) = LOWER(v_email::text)
          ORDER BY au.created_at ASC
          LIMIT 1
        )
      )
      INTO v_target_user_id;

      IF v_target_user_id IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'users',
          rec.source_id,
          'missing_auth_user',
          jsonb_build_object('email', rec.payload ->> 'email'),
          'error',
          NULL
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            error_text = 'No matching auth.users row found for staged user payload.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      INSERT INTO public.user_profiles (
        id,
        email,
        full_name,
        avatar_url,
        auth_provider,
        system_role,
        legacy_user_id,
        legacy_source_id,
        legacy_source_kind,
        created_at,
        updated_at
      )
      VALUES (
        v_target_user_id,
        v_email,
        NULLIF(BTRIM(COALESCE(rec.payload ->> 'name', rec.payload ->> 'full_name')), ''),
        NULLIF(BTRIM(rec.payload ->> 'avatar_url'), ''),
        COALESCE(NULLIF(BTRIM(rec.payload ->> 'auth_provider'), ''), 'email'),
        public.bridge_normalize_user_system_role(rec.payload ->> 'role'),
        v_legacy_uuid,
        rec.source_id,
        rec.source_system,
        COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
        NOW()
      )
      ON CONFLICT (id) DO UPDATE
      SET email = COALESCE(EXCLUDED.email, public.user_profiles.email),
          full_name = COALESCE(EXCLUDED.full_name, public.user_profiles.full_name),
          avatar_url = COALESCE(EXCLUDED.avatar_url, public.user_profiles.avatar_url),
          auth_provider = EXCLUDED.auth_provider,
          system_role = EXCLUDED.system_role,
          legacy_user_id = COALESCE(EXCLUDED.legacy_user_id, public.user_profiles.legacy_user_id),
          legacy_source_id = EXCLUDED.legacy_source_id,
          legacy_source_kind = EXCLUDED.legacy_source_kind,
          updated_at = NOW();

      PERFORM public.bridge_upsert_source_map(
        NULL,
        rec.source_system,
        'users',
        rec.source_id,
        'public.user_profiles',
        v_target_user_id,
        p_import_run_id,
        jsonb_build_object('email', rec.payload ->> 'email')
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          target_id = v_target_user_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'users',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          NULL
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'users');

  RETURN jsonb_build_object(
    'entity', 'users',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_tenants(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_owner_user_id UUID;
  v_slug CITEXT;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'tenants'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_slug := NULLIF(LOWER(BTRIM(rec.payload ->> 'slug')), '')::citext;

      IF v_slug IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'tenants',
          rec.source_id,
          'missing_slug',
          jsonb_build_object('payload', rec.payload),
          'error',
          NULL
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            error_text = 'Tenant slug is required for additive tenant backfill.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      v_owner_user_id := COALESCE(
        public.bridge_resolve_target_id('users', COALESCE(NULLIF(rec.payload ->> 'owner_user_id', ''), NULLIF(rec.payload ->> 'owner_id', '')), rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = public.bridge_safe_uuid(COALESCE(NULLIF(rec.payload ->> 'owner_user_id', ''), NULLIF(rec.payload ->> 'owner_id', '')))
          LIMIT 1
        )
      );

      SELECT COALESCE(
        public.bridge_resolve_target_id('tenants', rec.source_id, rec.source_system),
        (
          SELECT t.id
          FROM public.tenants t
          WHERE t.legacy_source_kind = rec.source_system
            AND t.legacy_source_id = rec.source_id
            AND t.is_deleted = FALSE
          LIMIT 1
        ),
        (
          SELECT t.id
          FROM public.tenants t
          WHERE t.slug = v_slug
            AND t.is_deleted = FALSE
          LIMIT 1
        )
      )
      INTO v_target_tenant_id;

      IF v_target_tenant_id IS NULL THEN
        INSERT INTO public.tenants (
          slug,
          name,
          status,
          subscription_status,
          subscription_expires_at,
          trial_ends_at,
          owner_user_id,
          metadata,
          created_at,
          updated_at,
          legacy_source_id,
          legacy_source_kind
        )
        VALUES (
          v_slug,
          COALESCE(NULLIF(BTRIM(rec.payload ->> 'name'), ''), v_slug::text),
          public.bridge_normalize_tenant_status(rec.payload ->> 'status'),
          public.bridge_normalize_subscription_status(COALESCE(rec.payload ->> 'subscription_status', rec.payload #>> '{subscription,status}')),
          public.bridge_parse_timestamptz(COALESCE(rec.payload ->> 'subscription_expires_at', rec.payload #>> '{subscription,expires_at}')),
          public.bridge_parse_timestamptz(COALESCE(rec.payload ->> 'trial_ends_at', rec.payload #>> '{subscription,trial_ends_at}')),
          v_owner_user_id,
          COALESCE(
            CASE WHEN jsonb_typeof(rec.payload -> 'metadata') = 'object' THEN rec.payload -> 'metadata' ELSE '{}'::jsonb END,
            '{}'::jsonb
          ) || jsonb_build_object(
            'bridge_source_id', rec.source_id,
            'bridge_source_system', rec.source_system
          ),
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW(),
          rec.source_id,
          rec.source_system
        )
        RETURNING id INTO v_target_tenant_id;
      ELSE
        UPDATE public.tenants
        SET slug = v_slug,
            name = COALESCE(NULLIF(BTRIM(rec.payload ->> 'name'), ''), public.tenants.name),
            status = public.bridge_normalize_tenant_status(rec.payload ->> 'status'),
            subscription_status = public.bridge_normalize_subscription_status(COALESCE(rec.payload ->> 'subscription_status', rec.payload #>> '{subscription,status}')),
            subscription_expires_at = COALESCE(
              public.bridge_parse_timestamptz(COALESCE(rec.payload ->> 'subscription_expires_at', rec.payload #>> '{subscription,expires_at}')),
              public.tenants.subscription_expires_at
            ),
            trial_ends_at = COALESCE(
              public.bridge_parse_timestamptz(COALESCE(rec.payload ->> 'trial_ends_at', rec.payload #>> '{subscription,trial_ends_at}')),
              public.tenants.trial_ends_at
            ),
            owner_user_id = COALESCE(v_owner_user_id, public.tenants.owner_user_id),
            metadata = COALESCE(public.tenants.metadata, '{}'::jsonb)
              || COALESCE(
                CASE WHEN jsonb_typeof(rec.payload -> 'metadata') = 'object' THEN rec.payload -> 'metadata' ELSE '{}'::jsonb END,
                '{}'::jsonb
              )
              || jsonb_build_object('bridge_source_id', rec.source_id, 'bridge_source_system', rec.source_system),
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_target_tenant_id;
      END IF;

      IF COALESCE(NULLIF(rec.payload ->> 'owner_user_id', ''), NULLIF(rec.payload ->> 'owner_id', '')) IS NOT NULL
         AND v_owner_user_id IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'tenants',
          rec.source_id,
          'owner_not_mapped',
          jsonb_build_object('owner_source_id', COALESCE(rec.payload ->> 'owner_user_id', rec.payload ->> 'owner_id')),
          'warning',
          v_target_tenant_id
        );
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'tenants',
        rec.source_id,
        'public.tenants',
        v_target_tenant_id,
        p_import_run_id,
        jsonb_build_object('slug', v_slug)
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_target_tenant_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'tenants',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          NULL
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'tenants');

  RETURN jsonb_build_object(
    'entity', 'tenants',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_memberships(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_target_user_id UUID;
  v_invited_by UUID;
  v_membership_id UUID;
  v_legacy_uuid UUID;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'memberships'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_target_tenant_id := public.bridge_resolve_target_id(
        'tenants',
        COALESCE(NULLIF(rec.tenant_source_id, ''), NULLIF(rec.payload ->> 'tenant_id', '')),
        rec.source_system
      );

      v_target_user_id := COALESCE(
        public.bridge_resolve_target_id('users', NULLIF(rec.payload ->> 'user_id', ''), rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = public.bridge_safe_uuid(NULLIF(rec.payload ->> 'user_id', ''))
          LIMIT 1
        )
      );

      v_invited_by := COALESCE(
        public.bridge_resolve_target_id('users', NULLIF(rec.payload ->> 'invited_by', ''), rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = public.bridge_safe_uuid(NULLIF(rec.payload ->> 'invited_by', ''))
          LIMIT 1
        )
      );

      IF v_target_tenant_id IS NULL OR v_target_user_id IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'memberships',
          rec.source_id,
          'missing_parent_mapping',
          jsonb_build_object(
            'tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id'),
            'user_source_id', rec.payload ->> 'user_id'
          ),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Membership requires both mapped tenant and mapped auth user.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      v_legacy_uuid := public.bridge_safe_uuid(rec.source_id);

      SELECT tm.id
      INTO v_membership_id
      FROM public.tenant_members tm
      WHERE tm.tenant_id = v_target_tenant_id
        AND tm.user_id = v_target_user_id
        AND tm.is_deleted = FALSE
      LIMIT 1;

      IF v_membership_id IS NULL THEN
        INSERT INTO public.tenant_members (
          tenant_id,
          user_id,
          role,
          status,
          is_default,
          invited_by,
          joined_at,
          legacy_membership_id,
          legacy_source_id,
          legacy_source_kind,
          created_at,
          updated_at
        )
        VALUES (
          v_target_tenant_id,
          v_target_user_id,
          public.bridge_normalize_membership_role(rec.payload ->> 'role'),
          public.bridge_normalize_membership_status(rec.payload ->> 'status'),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'is_default'), ''), 'false'))
            WHEN 'true' THEN TRUE
            WHEN '1' THEN TRUE
            ELSE FALSE
          END,
          v_invited_by,
          public.bridge_parse_timestamptz(rec.payload ->> 'joined_at'),
          v_legacy_uuid,
          rec.source_id,
          rec.source_system,
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW()
        )
        RETURNING id INTO v_membership_id;
      ELSE
        UPDATE public.tenant_members
        SET role = public.bridge_normalize_membership_role(rec.payload ->> 'role'),
            status = public.bridge_normalize_membership_status(rec.payload ->> 'status'),
            is_default = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'is_default'), ''), CASE WHEN public.tenant_members.is_default THEN 'true' ELSE 'false' END))
              WHEN 'true' THEN TRUE
              WHEN '1' THEN TRUE
              ELSE FALSE
            END,
            invited_by = COALESCE(v_invited_by, public.tenant_members.invited_by),
            joined_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'joined_at'), public.tenant_members.joined_at),
            legacy_membership_id = COALESCE(v_legacy_uuid, public.tenant_members.legacy_membership_id),
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_membership_id;
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'memberships',
        rec.source_id,
        'public.tenant_members',
        v_membership_id,
        p_import_run_id,
        jsonb_build_object('user_id', rec.payload ->> 'user_id')
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_membership_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'memberships',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'memberships');

  RETURN jsonb_build_object(
    'entity', 'memberships',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_clients(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_account_manager_user_id UUID;
  v_client_id UUID;
  v_legacy_uuid UUID;
  v_mrr NUMERIC(12,2);
  v_health_score INTEGER;
  v_churn_risk_score INTEGER;
  v_nps_rolling_avg NUMERIC(5,2);
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'clients'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_target_tenant_id := public.bridge_resolve_target_id(
        'tenants',
        COALESCE(NULLIF(rec.tenant_source_id, ''), NULLIF(rec.payload ->> 'tenant_id', '')),
        rec.source_system
      );

      IF v_target_tenant_id IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'clients',
          rec.source_id,
          'missing_tenant_mapping',
          jsonb_build_object('tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id')),
          'error',
          NULL
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            error_text = 'Client requires mapped tenant before additive insert/update.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      IF NULLIF(BTRIM(rec.payload ->> 'name'), '') IS NULL OR NULLIF(BTRIM(rec.payload ->> 'company'), '') IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'clients',
          rec.source_id,
          'missing_required_fields',
          jsonb_build_object('name', rec.payload ->> 'name', 'company', rec.payload ->> 'company'),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Client requires non-empty name and company.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      v_account_manager_user_id := COALESCE(
        public.bridge_resolve_target_id('users', COALESCE(NULLIF(rec.payload ->> 'account_manager_id', ''), NULLIF(rec.payload ->> 'account_manager_user_id', '')), rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = public.bridge_safe_uuid(COALESCE(NULLIF(rec.payload ->> 'account_manager_id', ''), NULLIF(rec.payload ->> 'account_manager_user_id', '')))
          LIMIT 1
        )
      );

      v_legacy_uuid := public.bridge_safe_uuid(rec.source_id);
      v_mrr := 0;
      v_health_score := 75;
      v_churn_risk_score := 0;
      v_nps_rolling_avg := NULL;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'mrr'), '') IS NOT NULL THEN
          v_mrr := (rec.payload ->> 'mrr')::numeric(12,2);
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_mrr := 0;
      END;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'health_score'), '') IS NOT NULL THEN
          v_health_score := GREATEST(0, LEAST(100, (rec.payload ->> 'health_score')::integer));
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_health_score := 75;
      END;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'churn_risk_score'), '') IS NOT NULL THEN
          v_churn_risk_score := GREATEST(0, LEAST(100, (rec.payload ->> 'churn_risk_score')::integer));
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_churn_risk_score := 0;
      END;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'nps_rolling_avg'), '') IS NOT NULL THEN
          v_nps_rolling_avg := (rec.payload ->> 'nps_rolling_avg')::numeric(5,2);
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_nps_rolling_avg := NULL;
      END;

      SELECT COALESCE(
        public.bridge_resolve_target_id('clients', rec.source_id, rec.source_system),
        (
          SELECT c.id
          FROM public.clients c
          WHERE c.tenant_id = v_target_tenant_id
            AND c.legacy_source_kind = rec.source_system
            AND c.legacy_source_id = rec.source_id
            AND c.is_deleted = FALSE
          LIMIT 1
        )
      )
      INTO v_client_id;

      IF v_client_id IS NULL THEN
        INSERT INTO public.clients (
          tenant_id,
          name,
          company,
          industry,
          primary_contact,
          email,
          phone,
          website,
          location,
          account_manager_user_id,
          account_manager_name,
          services,
          assigned_products,
          crm_data,
          gbp_data,
          onboarding_date,
          mrr,
          health_score,
          churn_risk,
          sentiment,
          notes,
          avatar_url,
          status,
          suggestions,
          suggestions_generated_at,
          suggestions_model,
          feedback_alert,
          feedback_alert_level,
          feedback_alert_reason,
          feedback_last_submitted_at,
          feedback_rolling_avg,
          health_alert,
          health_alert_level,
          health_alert_reason,
          churn_risk_score,
          churn_risk_indicators,
          nps_rolling_avg,
          sentiment_rolling,
          health_last_submitted_at,
          legacy_client_id,
          legacy_source_id,
          legacy_source_kind,
          created_at,
          updated_at
        )
        VALUES (
          v_target_tenant_id,
          NULLIF(BTRIM(rec.payload ->> 'name'), ''),
          NULLIF(BTRIM(rec.payload ->> 'company'), ''),
          NULLIF(BTRIM(rec.payload ->> 'industry'), ''),
          NULLIF(BTRIM(rec.payload ->> 'primary_contact'), ''),
          NULLIF(LOWER(BTRIM(rec.payload ->> 'email')), '')::citext,
          NULLIF(BTRIM(rec.payload ->> 'phone'), ''),
          NULLIF(BTRIM(rec.payload ->> 'website'), ''),
          NULLIF(BTRIM(rec.payload ->> 'location'), ''),
          v_account_manager_user_id,
          NULLIF(BTRIM(rec.payload ->> 'account_manager_name'), ''),
          public.bridge_jsonb_text_array(rec.payload -> 'services'),
          public.bridge_jsonb_text_array(rec.payload -> 'assigned_products'),
          CASE WHEN jsonb_typeof(rec.payload -> 'crm_data') = 'object' THEN rec.payload -> 'crm_data' ELSE '{}'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'gbp_data') = 'object' THEN rec.payload -> 'gbp_data' ELSE '{}'::jsonb END,
          public.bridge_parse_date(rec.payload ->> 'onboarding_date'),
          v_mrr,
          v_health_score,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'churn_risk'), ''), ''))
            WHEN 'medium' THEN 'medium'::public.risk_level_type
            WHEN 'high' THEN 'high'::public.risk_level_type
            ELSE 'low'::public.risk_level_type
          END,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment'), ''), ''))
            WHEN 'positive' THEN 'positive'::public.sentiment_type
            WHEN 'negative' THEN 'negative'::public.sentiment_type
            ELSE 'neutral'::public.sentiment_type
          END,
          NULLIF(BTRIM(rec.payload ->> 'notes'), ''),
          NULLIF(BTRIM(rec.payload ->> 'avatar_url'), ''),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
            WHEN 'paused' THEN 'paused'::public.client_status_type
            WHEN 'churned' THEN 'churned'::public.client_status_type
            ELSE 'active'::public.client_status_type
          END,
          CASE WHEN jsonb_typeof(rec.payload -> 'suggestions') = 'array' THEN rec.payload -> 'suggestions' ELSE '[]'::jsonb END,
          public.bridge_parse_timestamptz(rec.payload ->> 'suggestions_generated_at'),
          NULLIF(BTRIM(rec.payload ->> 'suggestions_model'), ''),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'feedback_alert'), ''), 'false'))
            WHEN 'true' THEN TRUE
            WHEN '1' THEN TRUE
            ELSE FALSE
          END,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'feedback_alert_level'), ''), ''))
            WHEN 'medium' THEN 'medium'::public.risk_level_type
            WHEN 'high' THEN 'high'::public.risk_level_type
            ELSE 'low'::public.risk_level_type
          END,
          NULLIF(BTRIM(rec.payload ->> 'feedback_alert_reason'), ''),
          public.bridge_parse_timestamptz(rec.payload ->> 'feedback_last_submitted_at'),
          CASE WHEN jsonb_typeof(rec.payload -> 'feedback_rolling_avg') = 'object' THEN rec.payload -> 'feedback_rolling_avg' ELSE '{}'::jsonb END,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_alert'), ''), 'false'))
            WHEN 'true' THEN TRUE
            WHEN '1' THEN TRUE
            ELSE FALSE
          END,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_alert_level'), ''), ''))
            WHEN 'medium' THEN 'medium'::public.risk_level_type
            WHEN 'high' THEN 'high'::public.risk_level_type
            ELSE 'low'::public.risk_level_type
          END,
          NULLIF(BTRIM(rec.payload ->> 'health_alert_reason'), ''),
          v_churn_risk_score,
          public.bridge_jsonb_text_array(rec.payload -> 'churn_risk_indicators'),
          v_nps_rolling_avg,
          CASE WHEN jsonb_typeof(rec.payload -> 'sentiment_rolling') = 'object' THEN rec.payload -> 'sentiment_rolling' ELSE '{}'::jsonb END,
          public.bridge_parse_timestamptz(rec.payload ->> 'health_last_submitted_at'),
          v_legacy_uuid,
          rec.source_id,
          rec.source_system,
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW()
        )
        RETURNING id INTO v_client_id;
      ELSE
        UPDATE public.clients
        SET name = NULLIF(BTRIM(rec.payload ->> 'name'), ''),
            company = NULLIF(BTRIM(rec.payload ->> 'company'), ''),
            industry = COALESCE(NULLIF(BTRIM(rec.payload ->> 'industry'), ''), public.clients.industry),
            primary_contact = COALESCE(NULLIF(BTRIM(rec.payload ->> 'primary_contact'), ''), public.clients.primary_contact),
            email = COALESCE(NULLIF(LOWER(BTRIM(rec.payload ->> 'email')), '')::citext, public.clients.email),
            phone = COALESCE(NULLIF(BTRIM(rec.payload ->> 'phone'), ''), public.clients.phone),
            website = COALESCE(NULLIF(BTRIM(rec.payload ->> 'website'), ''), public.clients.website),
            location = COALESCE(NULLIF(BTRIM(rec.payload ->> 'location'), ''), public.clients.location),
            account_manager_user_id = COALESCE(v_account_manager_user_id, public.clients.account_manager_user_id),
            account_manager_name = COALESCE(NULLIF(BTRIM(rec.payload ->> 'account_manager_name'), ''), public.clients.account_manager_name),
            services = public.bridge_jsonb_text_array(rec.payload -> 'services'),
            assigned_products = public.bridge_jsonb_text_array(rec.payload -> 'assigned_products'),
            crm_data = CASE WHEN jsonb_typeof(rec.payload -> 'crm_data') = 'object' THEN rec.payload -> 'crm_data' ELSE public.clients.crm_data END,
            gbp_data = CASE WHEN jsonb_typeof(rec.payload -> 'gbp_data') = 'object' THEN rec.payload -> 'gbp_data' ELSE public.clients.gbp_data END,
            onboarding_date = COALESCE(public.bridge_parse_date(rec.payload ->> 'onboarding_date'), public.clients.onboarding_date),
            mrr = v_mrr,
            health_score = v_health_score,
            churn_risk = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'churn_risk'), ''), ''))
              WHEN 'medium' THEN 'medium'::public.risk_level_type
              WHEN 'high' THEN 'high'::public.risk_level_type
              ELSE 'low'::public.risk_level_type
            END,
            sentiment = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment'), ''), ''))
              WHEN 'positive' THEN 'positive'::public.sentiment_type
              WHEN 'negative' THEN 'negative'::public.sentiment_type
              ELSE 'neutral'::public.sentiment_type
            END,
            notes = COALESCE(NULLIF(BTRIM(rec.payload ->> 'notes'), ''), public.clients.notes),
            avatar_url = COALESCE(NULLIF(BTRIM(rec.payload ->> 'avatar_url'), ''), public.clients.avatar_url),
            status = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
              WHEN 'paused' THEN 'paused'::public.client_status_type
              WHEN 'churned' THEN 'churned'::public.client_status_type
              ELSE 'active'::public.client_status_type
            END,
            suggestions = CASE WHEN jsonb_typeof(rec.payload -> 'suggestions') = 'array' THEN rec.payload -> 'suggestions' ELSE public.clients.suggestions END,
            suggestions_generated_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'suggestions_generated_at'), public.clients.suggestions_generated_at),
            suggestions_model = COALESCE(NULLIF(BTRIM(rec.payload ->> 'suggestions_model'), ''), public.clients.suggestions_model),
            feedback_alert = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'feedback_alert'), ''), CASE WHEN public.clients.feedback_alert THEN 'true' ELSE 'false' END))
              WHEN 'true' THEN TRUE
              WHEN '1' THEN TRUE
              ELSE FALSE
            END,
            feedback_alert_level = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'feedback_alert_level'), ''), ''))
              WHEN 'medium' THEN 'medium'::public.risk_level_type
              WHEN 'high' THEN 'high'::public.risk_level_type
              ELSE 'low'::public.risk_level_type
            END,
            feedback_alert_reason = COALESCE(NULLIF(BTRIM(rec.payload ->> 'feedback_alert_reason'), ''), public.clients.feedback_alert_reason),
            feedback_last_submitted_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'feedback_last_submitted_at'), public.clients.feedback_last_submitted_at),
            feedback_rolling_avg = CASE WHEN jsonb_typeof(rec.payload -> 'feedback_rolling_avg') = 'object' THEN rec.payload -> 'feedback_rolling_avg' ELSE public.clients.feedback_rolling_avg END,
            health_alert = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_alert'), ''), CASE WHEN public.clients.health_alert THEN 'true' ELSE 'false' END))
              WHEN 'true' THEN TRUE
              WHEN '1' THEN TRUE
              ELSE FALSE
            END,
            health_alert_level = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_alert_level'), ''), ''))
              WHEN 'medium' THEN 'medium'::public.risk_level_type
              WHEN 'high' THEN 'high'::public.risk_level_type
              ELSE 'low'::public.risk_level_type
            END,
            health_alert_reason = COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_alert_reason'), ''), public.clients.health_alert_reason),
            churn_risk_score = v_churn_risk_score,
            churn_risk_indicators = public.bridge_jsonb_text_array(rec.payload -> 'churn_risk_indicators'),
            nps_rolling_avg = COALESCE(v_nps_rolling_avg, public.clients.nps_rolling_avg),
            sentiment_rolling = CASE WHEN jsonb_typeof(rec.payload -> 'sentiment_rolling') = 'object' THEN rec.payload -> 'sentiment_rolling' ELSE public.clients.sentiment_rolling END,
            health_last_submitted_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'health_last_submitted_at'), public.clients.health_last_submitted_at),
            legacy_client_id = COALESCE(v_legacy_uuid, public.clients.legacy_client_id),
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_client_id;
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'clients',
        rec.source_id,
        'public.clients',
        v_client_id,
        p_import_run_id,
        jsonb_build_object('tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id'))
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_client_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'clients',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'clients');

  RETURN jsonb_build_object(
    'entity', 'clients',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_meetings(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_client_id UUID;
  v_account_manager_user_id UUID;
  v_meeting_id UUID;
  v_legacy_uuid UUID;
  v_duration_minutes INTEGER := 60;
  v_nps_score INTEGER;
  v_meeting_score INTEGER;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'meetings'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_target_tenant_id := public.bridge_resolve_target_id(
        'tenants',
        COALESCE(NULLIF(rec.tenant_source_id, ''), NULLIF(rec.payload ->> 'tenant_id', '')),
        rec.source_system
      );

      v_client_id := public.bridge_resolve_target_id(
        'clients',
        NULLIF(rec.payload ->> 'client_id', ''),
        rec.source_system
      );

      IF v_target_tenant_id IS NULL OR v_client_id IS NULL OR NULLIF(BTRIM(rec.payload ->> 'title'), '') IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'meetings',
          rec.source_id,
          'missing_parent_or_title',
          jsonb_build_object(
            'tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id'),
            'client_source_id', rec.payload ->> 'client_id',
            'title', rec.payload ->> 'title'
          ),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Meeting requires mapped tenant, mapped client, and non-empty title.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      v_account_manager_user_id := COALESCE(
        public.bridge_resolve_target_id('users', COALESCE(NULLIF(rec.payload ->> 'account_manager_id', ''), NULLIF(rec.payload ->> 'account_manager_user_id', '')), rec.source_system),
        (
          SELECT au.id
          FROM auth.users au
          WHERE au.id = public.bridge_safe_uuid(COALESCE(NULLIF(rec.payload ->> 'account_manager_id', ''), NULLIF(rec.payload ->> 'account_manager_user_id', '')))
          LIMIT 1
        )
      );

      v_duration_minutes := 60;
      v_nps_score := NULL;
      v_meeting_score := NULL;
      v_legacy_uuid := public.bridge_safe_uuid(rec.source_id);

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'duration_minutes'), '') IS NOT NULL THEN
          v_duration_minutes := GREATEST(1, (rec.payload ->> 'duration_minutes')::integer);
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_duration_minutes := 60;
      END;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'nps_score'), '') IS NOT NULL THEN
          v_nps_score := GREATEST(0, LEAST(10, (rec.payload ->> 'nps_score')::integer));
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_nps_score := NULL;
      END;

      BEGIN
        IF NULLIF(BTRIM(rec.payload ->> 'meeting_score'), '') IS NOT NULL THEN
          v_meeting_score := GREATEST(0, LEAST(100, (rec.payload ->> 'meeting_score')::integer));
        END IF;
      EXCEPTION
        WHEN OTHERS THEN
          v_meeting_score := NULL;
      END;

      SELECT COALESCE(
        public.bridge_resolve_target_id('meetings', rec.source_id, rec.source_system),
        (
          SELECT m.id
          FROM public.meetings m
          WHERE m.tenant_id = v_target_tenant_id
            AND m.legacy_source_kind = rec.source_system
            AND m.legacy_source_id = rec.source_id
            AND m.is_deleted = FALSE
          LIMIT 1
        )
      )
      INTO v_meeting_id;

      IF v_meeting_id IS NULL THEN
        INSERT INTO public.meetings (
          tenant_id,
          client_id,
          client_name,
          account_manager_user_id,
          account_manager_name,
          title,
          scheduled_at,
          status,
          google_meet_url,
          duration_minutes,
          brief_generated_at,
          brief_model,
          wins,
          wins_library,
          issues,
          issues_library,
          talking_points,
          talking_points_library,
          suggested_questions,
          prep_checklist,
          ace_up_the_sleeve,
          testimonial_opportunity,
          strategic_recommendations,
          campaign_recommendations,
          health_signal,
          automation_draft,
          automation_draft_generated_at,
          automation_approved_at,
          kpi_snapshot,
          notes,
          transcript,
          transcript_source,
          transcript_analyzed_at,
          sentiment,
          sentiment_summary,
          transcript_analysis,
          transcript_analysis_by_model,
          nps_score,
          sentiment_classification,
          health_notes,
          recap_html,
          recap_email,
          recap_subject,
          recap_sent_at,
          meeting_score,
          checklist,
          deliverable_reviews,
          discovery_questions,
          feedback,
          legacy_meeting_id,
          legacy_source_id,
          legacy_source_kind,
          created_at,
          updated_at
        )
        VALUES (
          v_target_tenant_id,
          v_client_id,
          NULLIF(BTRIM(rec.payload ->> 'client_name'), ''),
          v_account_manager_user_id,
          NULLIF(BTRIM(rec.payload ->> 'account_manager_name'), ''),
          NULLIF(BTRIM(rec.payload ->> 'title'), ''),
          public.bridge_parse_timestamptz(rec.payload ->> 'scheduled_at'),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
            WHEN 'prep' THEN 'prep'::public.meeting_status_type
            WHEN 'in_progress' THEN 'in_progress'::public.meeting_status_type
            WHEN 'completed' THEN 'completed'::public.meeting_status_type
            WHEN 'cancelled' THEN 'cancelled'::public.meeting_status_type
            ELSE 'scheduled'::public.meeting_status_type
          END,
          NULLIF(BTRIM(rec.payload ->> 'google_meet_url'), ''),
          v_duration_minutes,
          public.bridge_parse_timestamptz(rec.payload ->> 'brief_generated_at'),
          NULLIF(BTRIM(rec.payload ->> 'brief_model'), ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'wins') = 'array' THEN rec.payload -> 'wins' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'wins_library') = 'array' THEN rec.payload -> 'wins_library' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'issues') = 'array' THEN rec.payload -> 'issues' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'issues_library') = 'array' THEN rec.payload -> 'issues_library' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'talking_points') = 'array' THEN rec.payload -> 'talking_points' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'talking_points_library') = 'array' THEN rec.payload -> 'talking_points_library' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'suggested_questions') = 'array' THEN rec.payload -> 'suggested_questions' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'prep_checklist') = 'array' THEN rec.payload -> 'prep_checklist' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'ace_up_the_sleeve') = 'array' THEN rec.payload -> 'ace_up_the_sleeve' ELSE '[]'::jsonb END,
          NULLIF(BTRIM(rec.payload ->> 'testimonial_opportunity'), ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'strategic_recommendations') = 'array' THEN rec.payload -> 'strategic_recommendations' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'campaign_recommendations') = 'array' THEN rec.payload -> 'campaign_recommendations' ELSE '[]'::jsonb END,
          NULLIF(BTRIM(rec.payload ->> 'health_signal'), ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'automation_draft') = 'object' THEN rec.payload -> 'automation_draft' ELSE '{}'::jsonb END,
          public.bridge_parse_timestamptz(rec.payload ->> 'automation_draft_generated_at'),
          public.bridge_parse_timestamptz(rec.payload ->> 'automation_approved_at'),
          CASE WHEN jsonb_typeof(rec.payload -> 'kpi_snapshot') = 'object' THEN rec.payload -> 'kpi_snapshot' ELSE '{}'::jsonb END,
          NULLIF(BTRIM(rec.payload ->> 'notes'), ''),
          NULLIF(rec.payload ->> 'transcript', ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'transcript_source') = 'object' THEN rec.payload -> 'transcript_source' ELSE '{}'::jsonb END,
          public.bridge_parse_timestamptz(rec.payload ->> 'transcript_analyzed_at'),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment'), ''), ''))
            WHEN 'positive' THEN 'positive'::public.sentiment_type
            WHEN 'negative' THEN 'negative'::public.sentiment_type
            WHEN 'neutral' THEN 'neutral'::public.sentiment_type
            ELSE NULL
          END,
          NULLIF(BTRIM(rec.payload ->> 'sentiment_summary'), ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'transcript_analysis') = 'object' THEN rec.payload -> 'transcript_analysis' ELSE '{}'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'transcript_analysis_by_model') = 'object' THEN rec.payload -> 'transcript_analysis_by_model' ELSE '{}'::jsonb END,
          v_nps_score,
          NULLIF(BTRIM(rec.payload ->> 'sentiment_classification'), ''),
          NULLIF(BTRIM(rec.payload ->> 'health_notes'), ''),
          NULLIF(rec.payload ->> 'recap_html', ''),
          NULLIF(rec.payload ->> 'recap_email', ''),
          NULLIF(BTRIM(rec.payload ->> 'recap_subject'), ''),
          public.bridge_parse_timestamptz(rec.payload ->> 'recap_sent_at'),
          v_meeting_score,
          CASE WHEN jsonb_typeof(rec.payload -> 'checklist') = 'object' THEN rec.payload -> 'checklist' ELSE '{}'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'deliverable_reviews') = 'object' THEN rec.payload -> 'deliverable_reviews' ELSE '{}'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'discovery_questions') = 'array' THEN rec.payload -> 'discovery_questions' ELSE '[]'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'feedback') IN ('object', 'array') THEN rec.payload -> 'feedback' ELSE NULL END,
          v_legacy_uuid,
          rec.source_id,
          rec.source_system,
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW()
        )
        RETURNING id INTO v_meeting_id;
      ELSE
        UPDATE public.meetings
        SET tenant_id = v_target_tenant_id,
            client_id = v_client_id,
            client_name = COALESCE(NULLIF(BTRIM(rec.payload ->> 'client_name'), ''), public.meetings.client_name),
            account_manager_user_id = COALESCE(v_account_manager_user_id, public.meetings.account_manager_user_id),
            account_manager_name = COALESCE(NULLIF(BTRIM(rec.payload ->> 'account_manager_name'), ''), public.meetings.account_manager_name),
            title = NULLIF(BTRIM(rec.payload ->> 'title'), ''),
            scheduled_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'scheduled_at'), public.meetings.scheduled_at),
            status = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
              WHEN 'prep' THEN 'prep'::public.meeting_status_type
              WHEN 'in_progress' THEN 'in_progress'::public.meeting_status_type
              WHEN 'completed' THEN 'completed'::public.meeting_status_type
              WHEN 'cancelled' THEN 'cancelled'::public.meeting_status_type
              ELSE 'scheduled'::public.meeting_status_type
            END,
            google_meet_url = COALESCE(NULLIF(BTRIM(rec.payload ->> 'google_meet_url'), ''), public.meetings.google_meet_url),
            duration_minutes = v_duration_minutes,
            brief_generated_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'brief_generated_at'), public.meetings.brief_generated_at),
            brief_model = COALESCE(NULLIF(BTRIM(rec.payload ->> 'brief_model'), ''), public.meetings.brief_model),
            wins = CASE WHEN jsonb_typeof(rec.payload -> 'wins') = 'array' THEN rec.payload -> 'wins' ELSE public.meetings.wins END,
            wins_library = CASE WHEN jsonb_typeof(rec.payload -> 'wins_library') = 'array' THEN rec.payload -> 'wins_library' ELSE public.meetings.wins_library END,
            issues = CASE WHEN jsonb_typeof(rec.payload -> 'issues') = 'array' THEN rec.payload -> 'issues' ELSE public.meetings.issues END,
            issues_library = CASE WHEN jsonb_typeof(rec.payload -> 'issues_library') = 'array' THEN rec.payload -> 'issues_library' ELSE public.meetings.issues_library END,
            talking_points = CASE WHEN jsonb_typeof(rec.payload -> 'talking_points') = 'array' THEN rec.payload -> 'talking_points' ELSE public.meetings.talking_points END,
            talking_points_library = CASE WHEN jsonb_typeof(rec.payload -> 'talking_points_library') = 'array' THEN rec.payload -> 'talking_points_library' ELSE public.meetings.talking_points_library END,
            suggested_questions = CASE WHEN jsonb_typeof(rec.payload -> 'suggested_questions') = 'array' THEN rec.payload -> 'suggested_questions' ELSE public.meetings.suggested_questions END,
            prep_checklist = CASE WHEN jsonb_typeof(rec.payload -> 'prep_checklist') = 'array' THEN rec.payload -> 'prep_checklist' ELSE public.meetings.prep_checklist END,
            ace_up_the_sleeve = CASE WHEN jsonb_typeof(rec.payload -> 'ace_up_the_sleeve') = 'array' THEN rec.payload -> 'ace_up_the_sleeve' ELSE public.meetings.ace_up_the_sleeve END,
            testimonial_opportunity = COALESCE(NULLIF(BTRIM(rec.payload ->> 'testimonial_opportunity'), ''), public.meetings.testimonial_opportunity),
            strategic_recommendations = CASE WHEN jsonb_typeof(rec.payload -> 'strategic_recommendations') = 'array' THEN rec.payload -> 'strategic_recommendations' ELSE public.meetings.strategic_recommendations END,
            campaign_recommendations = CASE WHEN jsonb_typeof(rec.payload -> 'campaign_recommendations') = 'array' THEN rec.payload -> 'campaign_recommendations' ELSE public.meetings.campaign_recommendations END,
            health_signal = COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_signal'), ''), public.meetings.health_signal),
            automation_draft = CASE WHEN jsonb_typeof(rec.payload -> 'automation_draft') = 'object' THEN rec.payload -> 'automation_draft' ELSE public.meetings.automation_draft END,
            automation_draft_generated_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'automation_draft_generated_at'), public.meetings.automation_draft_generated_at),
            automation_approved_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'automation_approved_at'), public.meetings.automation_approved_at),
            kpi_snapshot = CASE WHEN jsonb_typeof(rec.payload -> 'kpi_snapshot') = 'object' THEN rec.payload -> 'kpi_snapshot' ELSE public.meetings.kpi_snapshot END,
            notes = COALESCE(NULLIF(BTRIM(rec.payload ->> 'notes'), ''), public.meetings.notes),
            transcript = COALESCE(NULLIF(rec.payload ->> 'transcript', ''), public.meetings.transcript),
            transcript_source = CASE WHEN jsonb_typeof(rec.payload -> 'transcript_source') = 'object' THEN rec.payload -> 'transcript_source' ELSE public.meetings.transcript_source END,
            transcript_analyzed_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'transcript_analyzed_at'), public.meetings.transcript_analyzed_at),
            sentiment = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment'), ''), ''))
              WHEN 'positive' THEN 'positive'::public.sentiment_type
              WHEN 'negative' THEN 'negative'::public.sentiment_type
              WHEN 'neutral' THEN 'neutral'::public.sentiment_type
              ELSE public.meetings.sentiment
            END,
            sentiment_summary = COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment_summary'), ''), public.meetings.sentiment_summary),
            transcript_analysis = CASE WHEN jsonb_typeof(rec.payload -> 'transcript_analysis') = 'object' THEN rec.payload -> 'transcript_analysis' ELSE public.meetings.transcript_analysis END,
            transcript_analysis_by_model = CASE WHEN jsonb_typeof(rec.payload -> 'transcript_analysis_by_model') = 'object' THEN rec.payload -> 'transcript_analysis_by_model' ELSE public.meetings.transcript_analysis_by_model END,
            nps_score = COALESCE(v_nps_score, public.meetings.nps_score),
            sentiment_classification = COALESCE(NULLIF(BTRIM(rec.payload ->> 'sentiment_classification'), ''), public.meetings.sentiment_classification),
            health_notes = COALESCE(NULLIF(BTRIM(rec.payload ->> 'health_notes'), ''), public.meetings.health_notes),
            recap_html = COALESCE(NULLIF(rec.payload ->> 'recap_html', ''), public.meetings.recap_html),
            recap_email = COALESCE(NULLIF(rec.payload ->> 'recap_email', ''), public.meetings.recap_email),
            recap_subject = COALESCE(NULLIF(BTRIM(rec.payload ->> 'recap_subject'), ''), public.meetings.recap_subject),
            recap_sent_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'recap_sent_at'), public.meetings.recap_sent_at),
            meeting_score = COALESCE(v_meeting_score, public.meetings.meeting_score),
            checklist = CASE WHEN jsonb_typeof(rec.payload -> 'checklist') = 'object' THEN rec.payload -> 'checklist' ELSE public.meetings.checklist END,
            deliverable_reviews = CASE WHEN jsonb_typeof(rec.payload -> 'deliverable_reviews') = 'object' THEN rec.payload -> 'deliverable_reviews' ELSE public.meetings.deliverable_reviews END,
            discovery_questions = CASE WHEN jsonb_typeof(rec.payload -> 'discovery_questions') = 'array' THEN rec.payload -> 'discovery_questions' ELSE public.meetings.discovery_questions END,
            feedback = CASE WHEN jsonb_typeof(rec.payload -> 'feedback') IN ('object', 'array') THEN rec.payload -> 'feedback' ELSE public.meetings.feedback END,
            legacy_meeting_id = COALESCE(v_legacy_uuid, public.meetings.legacy_meeting_id),
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_meeting_id;
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'meetings',
        rec.source_id,
        'public.meetings',
        v_meeting_id,
        p_import_run_id,
        jsonb_build_object('client_source_id', rec.payload ->> 'client_id')
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_meeting_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'meetings',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'meetings');

  RETURN jsonb_build_object(
    'entity', 'meetings',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_integrations(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_integration_id UUID;
  v_platform TEXT;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'integrations'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_target_tenant_id := public.bridge_resolve_target_id(
        'tenants',
        COALESCE(NULLIF(rec.tenant_source_id, ''), NULLIF(rec.payload ->> 'tenant_id', '')),
        rec.source_system
      );
      v_platform := NULLIF(BTRIM(rec.payload ->> 'platform'), '');

      IF v_target_tenant_id IS NULL OR v_platform IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'integrations',
          rec.source_id,
          'missing_tenant_or_platform',
          jsonb_build_object(
            'tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id'),
            'platform', rec.payload ->> 'platform'
          ),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Integration metadata requires mapped tenant and known platform.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      IF NOT EXISTS (
        SELECT 1
        FROM public.integration_catalog ic
        WHERE ic.platform = v_platform
      ) THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'integrations',
          rec.source_id,
          'unknown_platform',
          jsonb_build_object('platform', v_platform),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Platform is not present in integration_catalog.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      SELECT COALESCE(
        public.bridge_resolve_target_id('integrations', rec.source_id, rec.source_system),
        (
          SELECT ti.id
          FROM public.tenant_integrations ti
          WHERE ti.tenant_id = v_target_tenant_id
            AND ti.platform = v_platform
            AND ti.is_deleted = FALSE
          LIMIT 1
        )
      )
      INTO v_integration_id;

      IF v_integration_id IS NULL THEN
        INSERT INTO public.tenant_integrations (
          tenant_id,
          platform,
          label,
          status,
          last_synced_at,
          last_error,
          metadata,
          vault_secret_ref,
          oauth_connection_ref,
          legacy_source_id,
          legacy_source_kind,
          created_at,
          updated_at
        )
        VALUES (
          v_target_tenant_id,
          v_platform,
          COALESCE(NULLIF(BTRIM(rec.payload ->> 'label'), ''), v_platform),
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
            WHEN 'connected' THEN 'connected'::public.integration_status_type
            WHEN 'error' THEN 'error'::public.integration_status_type
            WHEN 'coming_soon' THEN 'coming_soon'::public.integration_status_type
            ELSE 'not_connected'::public.integration_status_type
          END,
          public.bridge_parse_timestamptz(rec.payload ->> 'last_synced_at'),
          NULLIF(BTRIM(rec.payload ->> 'last_error'), ''),
          CASE WHEN jsonb_typeof(rec.payload -> 'metadata') = 'object' THEN rec.payload -> 'metadata' ELSE '{}'::jsonb END,
          NULL,
          NULL,
          rec.source_id,
          rec.source_system,
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW()
        )
        RETURNING id INTO v_integration_id;
      ELSE
        UPDATE public.tenant_integrations
        SET label = COALESCE(NULLIF(BTRIM(rec.payload ->> 'label'), ''), public.tenant_integrations.label),
            status = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'status'), ''), ''))
              WHEN 'connected' THEN 'connected'::public.integration_status_type
              WHEN 'error' THEN 'error'::public.integration_status_type
              WHEN 'coming_soon' THEN 'coming_soon'::public.integration_status_type
              ELSE 'not_connected'::public.integration_status_type
            END,
            last_synced_at = COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'last_synced_at'), public.tenant_integrations.last_synced_at),
            last_error = COALESCE(NULLIF(BTRIM(rec.payload ->> 'last_error'), ''), public.tenant_integrations.last_error),
            metadata = CASE WHEN jsonb_typeof(rec.payload -> 'metadata') = 'object' THEN rec.payload -> 'metadata' ELSE public.tenant_integrations.metadata END,
            vault_secret_ref = NULL,
            oauth_connection_ref = NULL,
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_integration_id;
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'integrations',
        rec.source_id,
        'public.tenant_integrations',
        v_integration_id,
        p_import_run_id,
        jsonb_build_object('platform', v_platform)
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_integration_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'integrations',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'integrations');

  RETURN jsonb_build_object(
    'entity', 'integrations',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_client_bindings(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  rec RECORD;
  v_target_tenant_id UUID;
  v_client_id UUID;
  v_binding_id UUID;
  v_platform TEXT;
  v_applied_count INTEGER := 0;
  v_blocked_count INTEGER := 0;
  v_error_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT *
    FROM public.bridge_staging_payloads
    WHERE import_run_id = p_import_run_id
      AND entity_type = 'client_bindings'
    ORDER BY created_at ASC, source_id ASC
  LOOP
    BEGIN
      v_target_tenant_id := public.bridge_resolve_target_id(
        'tenants',
        COALESCE(NULLIF(rec.tenant_source_id, ''), NULLIF(rec.payload ->> 'tenant_id', '')),
        rec.source_system
      );
      v_client_id := public.bridge_resolve_target_id('clients', NULLIF(rec.payload ->> 'client_id', ''), rec.source_system);
      v_platform := NULLIF(BTRIM(rec.payload ->> 'platform'), '');

      IF v_target_tenant_id IS NULL OR v_client_id IS NULL OR v_platform IS NULL THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'client_bindings',
          rec.source_id,
          'missing_parent_or_platform',
          jsonb_build_object(
            'tenant_source_id', COALESCE(rec.tenant_source_id, rec.payload ->> 'tenant_id'),
            'client_source_id', rec.payload ->> 'client_id',
            'platform', rec.payload ->> 'platform'
          ),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Client binding requires mapped tenant, mapped client, and known platform.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      IF NOT EXISTS (
        SELECT 1
        FROM public.integration_catalog ic
        WHERE ic.platform = v_platform
      ) THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'client_bindings',
          rec.source_id,
          'unknown_platform',
          jsonb_build_object('platform', v_platform),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'blocked',
            tenant_id = v_target_tenant_id,
            error_text = 'Platform is not present in integration_catalog.',
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_blocked_count := v_blocked_count + 1;
        CONTINUE;
      END IF;

      SELECT COALESCE(
        public.bridge_resolve_target_id('client_bindings', rec.source_id, rec.source_system),
        (
          SELECT cb.id
          FROM public.client_integration_bindings cb
          WHERE cb.tenant_id = v_target_tenant_id
            AND cb.client_id = v_client_id
            AND cb.platform = v_platform
            AND cb.is_deleted = FALSE
          LIMIT 1
        )
      )
      INTO v_binding_id;

      IF v_binding_id IS NULL THEN
        INSERT INTO public.client_integration_bindings (
          tenant_id,
          client_id,
          platform,
          enabled,
          external_ids,
          config,
          legacy_source_id,
          legacy_source_kind,
          created_at,
          updated_at
        )
        VALUES (
          v_target_tenant_id,
          v_client_id,
          v_platform,
          CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'enabled'), ''), 'true'))
            WHEN 'false' THEN FALSE
            WHEN '0' THEN FALSE
            ELSE TRUE
          END,
          CASE WHEN jsonb_typeof(rec.payload -> 'external_ids') = 'object' THEN rec.payload -> 'external_ids' ELSE '{}'::jsonb END,
          CASE WHEN jsonb_typeof(rec.payload -> 'config') = 'object' THEN rec.payload -> 'config' ELSE '{}'::jsonb END,
          rec.source_id,
          rec.source_system,
          COALESCE(public.bridge_parse_timestamptz(rec.payload ->> 'created_at'), NOW()),
          NOW()
        )
        RETURNING id INTO v_binding_id;
      ELSE
        UPDATE public.client_integration_bindings
        SET enabled = CASE LOWER(COALESCE(NULLIF(BTRIM(rec.payload ->> 'enabled'), ''), CASE WHEN public.client_integration_bindings.enabled THEN 'true' ELSE 'false' END))
              WHEN 'false' THEN FALSE
              WHEN '0' THEN FALSE
              ELSE TRUE
            END,
            external_ids = CASE WHEN jsonb_typeof(rec.payload -> 'external_ids') = 'object' THEN rec.payload -> 'external_ids' ELSE public.client_integration_bindings.external_ids END,
            config = CASE WHEN jsonb_typeof(rec.payload -> 'config') = 'object' THEN rec.payload -> 'config' ELSE public.client_integration_bindings.config END,
            legacy_source_id = rec.source_id,
            legacy_source_kind = rec.source_system,
            updated_at = NOW()
        WHERE id = v_binding_id;
      END IF;

      PERFORM public.bridge_upsert_source_map(
        v_target_tenant_id,
        rec.source_system,
        'client_bindings',
        rec.source_id,
        'public.client_integration_bindings',
        v_binding_id,
        p_import_run_id,
        jsonb_build_object('platform', v_platform, 'client_source_id', rec.payload ->> 'client_id')
      );

      UPDATE public.bridge_staging_payloads
      SET status = 'applied',
          tenant_id = v_target_tenant_id,
          target_id = v_binding_id,
          error_text = NULL,
          processed_at = NOW(),
          updated_at = NOW()
      WHERE id = rec.id;

      v_applied_count := v_applied_count + 1;
    EXCEPTION
      WHEN OTHERS THEN
        PERFORM public.bridge_record_issue(
          p_import_run_id,
          'client_bindings',
          rec.source_id,
          'apply_exception',
          jsonb_build_object('message', SQLERRM),
          'error',
          v_target_tenant_id
        );

        UPDATE public.bridge_staging_payloads
        SET status = 'error',
            error_text = SQLERRM,
            processed_at = NOW(),
            updated_at = NOW()
        WHERE id = rec.id;

        v_error_count := v_error_count + 1;
    END;
  END LOOP;

  PERFORM public.bridge_capture_reconciliation_snapshot(p_import_run_id, 'client_bindings');

  RETURN jsonb_build_object(
    'entity', 'client_bindings',
    'applied', v_applied_count,
    'blocked', v_blocked_count,
    'errors', v_error_count
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.bridge_apply_all(p_import_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  v_users JSONB;
  v_tenants JSONB;
  v_memberships JSONB;
  v_clients JSONB;
  v_meetings JSONB;
  v_integrations JSONB;
  v_client_bindings JSONB;
  v_issue_count INTEGER := 0;
  v_error_count INTEGER := 0;
  v_metrics JSONB;
BEGIN
  UPDATE public.bridge_import_runs
  SET status = 'running',
      updated_at = NOW()
  WHERE id = p_import_run_id;

  v_users := public.bridge_apply_users(p_import_run_id);
  v_tenants := public.bridge_apply_tenants(p_import_run_id);
  v_memberships := public.bridge_apply_memberships(p_import_run_id);
  v_clients := public.bridge_apply_clients(p_import_run_id);
  v_meetings := public.bridge_apply_meetings(p_import_run_id);
  v_integrations := public.bridge_apply_integrations(p_import_run_id);
  v_client_bindings := public.bridge_apply_client_bindings(p_import_run_id);

  PERFORM public.bridge_refresh_run_snapshots(p_import_run_id);

  SELECT COUNT(*),
         COUNT(*) FILTER (WHERE severity = 'error')
  INTO v_issue_count, v_error_count
  FROM public.bridge_import_issues
  WHERE import_run_id = p_import_run_id;

  v_metrics := jsonb_build_object(
    'users', v_users,
    'tenants', v_tenants,
    'memberships', v_memberships,
    'clients', v_clients,
    'meetings', v_meetings,
    'integrations', v_integrations,
    'client_bindings', v_client_bindings,
    'issue_count', v_issue_count,
    'error_issue_count', v_error_count
  );

  UPDATE public.bridge_import_runs
  SET status = CASE WHEN v_issue_count > 0 THEN 'completed_with_issues' ELSE 'completed' END,
      metrics = COALESCE(metrics, '{}'::jsonb) || v_metrics,
      finished_at = NOW(),
      updated_at = NOW()
  WHERE id = p_import_run_id;

  RETURN v_metrics;
EXCEPTION
  WHEN OTHERS THEN
    UPDATE public.bridge_import_runs
    SET status = 'failed',
        metrics = COALESCE(metrics, '{}'::jsonb) || jsonb_build_object('fatal_error', SQLERRM),
        finished_at = NOW(),
        updated_at = NOW()
    WHERE id = p_import_run_id;

    RAISE;
END;
$$;

GRANT SELECT ON public.bridge_run_entity_summary_v TO service_role, supabase_auth_admin;
GRANT SELECT ON public.bridge_issue_summary_v TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_capture_reconciliation_snapshot(UUID, TEXT) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_refresh_run_snapshots(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_users(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_tenants(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_memberships(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_all(UUID) TO service_role, supabase_auth_admin;
REVOKE ALL ON public.bridge_run_entity_summary_v FROM authenticated, anon, public;
REVOKE ALL ON public.bridge_issue_summary_v FROM authenticated, anon, public;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
-- Realtime not required for bridge helper functions and views.

-- STEP 9: Seed data
-- No seed data in this migration.

-- ================================================================
-- ROLLBACK:
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_all(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_memberships(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_tenants(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_users(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_refresh_run_snapshots(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_capture_reconciliation_snapshot(UUID, TEXT) FROM service_role, supabase_auth_admin;
-- DROP FUNCTION IF EXISTS public.bridge_apply_all(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_client_bindings(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_integrations(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_meetings(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_clients(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_memberships(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_tenants(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_apply_users(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_refresh_run_snapshots(UUID);
-- DROP FUNCTION IF EXISTS public.bridge_capture_reconciliation_snapshot(UUID, TEXT);
-- DROP VIEW IF EXISTS public.bridge_issue_summary_v;
-- DROP VIEW IF EXISTS public.bridge_run_entity_summary_v;
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [007_bridge_foundation_and_source_maps.sql, 008_bridge_backfill_and_reconciliation.sql]  ·  Target Neon branch: [confirm_neon_branch]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/008_bridge_backfill_and_reconciliation.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [bridge_apply_all, bridge_run_entity_summary_v, bridge_issue_summary_v]  →  Frontend realtime: [none]
