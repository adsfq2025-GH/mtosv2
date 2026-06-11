-- ================================================================
-- MIGRATION: 010_bridge_blocker_fixes.sql
-- Mode: BROWNFIELD-FIX
-- Module: bridge-blocker-fixes · Neon Branch: main · Depends on: 007, 008, 009
-- Preserves: bridge staging tables, bridge source maps, tenants, clients, meetings, tenant_integrations, client_integration_bindings remain additive-only; existing rows are not dropped
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
CREATE OR REPLACE FUNCTION public.bridge_normalize_platform_alias(p_platform TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE LOWER(COALESCE(NULLIF(BTRIM(p_platform), ''), ''))
    WHEN 'clickup_client_health_tracker' THEN 'clickup'
    ELSE NULLIF(LOWER(BTRIM(p_platform)), '')
  END
$$;

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

  SELECT CASE
    WHEN COUNT(*) = 1 THEN MIN(t.id)
    ELSE NULL
  END
  INTO v_target_tenant_id
  FROM public.tenants t
  WHERE t.is_deleted = FALSE;

  RETURN v_target_tenant_id;
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
      v_target_tenant_id := public.bridge_resolve_tenant_id_fallback(
        rec.source_system,
        rec.tenant_source_id,
        rec.payload,
        NULL
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
      v_target_tenant_id := public.bridge_resolve_tenant_id_fallback(
        rec.source_system,
        rec.tenant_source_id,
        rec.payload,
        rec.payload ->> 'client_id'
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
      v_target_tenant_id := public.bridge_resolve_tenant_id_fallback(
        rec.source_system,
        rec.tenant_source_id,
        rec.payload,
        NULL
      );
      v_platform := public.bridge_normalize_platform_alias(rec.payload ->> 'platform');

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
      v_target_tenant_id := public.bridge_resolve_tenant_id_fallback(
        rec.source_system,
        rec.tenant_source_id,
        rec.payload,
        rec.payload ->> 'client_id'
      );
      v_client_id := public.bridge_resolve_target_id('clients', NULLIF(rec.payload ->> 'client_id', ''), rec.source_system);
      v_platform := public.bridge_normalize_platform_alias(rec.payload ->> 'platform');

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

GRANT EXECUTE ON FUNCTION public.bridge_normalize_platform_alias(TEXT) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) TO service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) TO service_role, supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.bridge_normalize_platform_alias(TEXT) FROM authenticated, anon, public;
REVOKE EXECUTE ON FUNCTION public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT) FROM authenticated, anon, public;

-- STEP 8: Realtime (REPLICA IDENTITY FULL if needed)
-- Realtime not applicable to bridge helper function fixes.

-- STEP 9: Seed data
-- No seed data in this migration.
-- ================================================================
-- ROLLBACK:
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_client_bindings(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_integrations(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_meetings(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_apply_clients(UUID) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT) FROM service_role, supabase_auth_admin;
-- REVOKE EXECUTE ON FUNCTION public.bridge_normalize_platform_alias(TEXT) FROM service_role, supabase_auth_admin;
-- DROP FUNCTION IF EXISTS public.bridge_resolve_tenant_id_fallback(TEXT, TEXT, JSONB, TEXT);
-- DROP FUNCTION IF EXISTS public.bridge_normalize_platform_alias(TEXT);
-- Reapply: supabase/migrations/008_bridge_backfill_and_reconciliation.sql
-- ================================================================

-- Neon Hand-Off Block
-- Migrations this session: [010_bridge_blocker_fixes.sql]  ·  Target Neon branch: [main]
-- Apply:  psql $DATABASE_URL -f supabase/migrations/010_bridge_blocker_fixes.sql
-- Verify: SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
-- Promote: neon branches merge feat-[slug] --project-id $NEON_PROJECT_ID
-- → API Agent ready: [bridge_apply_clients, bridge_apply_meetings, bridge_apply_integrations, bridge_apply_client_bindings]  →  Frontend realtime: [none]
