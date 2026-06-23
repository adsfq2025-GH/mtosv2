# Supabase-Native Rebuild Plan

## Goal

Replace the current hybrid Mongo + Supabase bridge architecture with a single-source-of-truth Supabase system:

- Supabase Auth for login/session identity
- Postgres for all application data
- RLS for tenant isolation
- UUID primary keys only
- No `legacy_source_id`
- No Mongo document mirroring
- No runtime bridge dependency

The bootstrap schema for the fresh project is in:

- [000_supabase_native_bootstrap.sql](file:///d:/mtosv2/supabase/bootstrap/000_supabase_native_bootstrap.sql)

## Why The Current System Breaks

The current backend still carries brownfield assumptions:

- Mongo-shaped documents in `backend/models.py`
- bridge translation in `backend/runtime_bridge.py`
- custom app JWT layered on top of Supabase Auth in `backend/auth.py`
- mixed fallback logic in `backend/server.py`
- additive migrations that preserve old runtime behavior instead of defining a clean target

That leads to:

- stale reads between sources
- mismatched IDs
- partial feature cutovers
- complex auth/tenant resolution
- harder debugging for OAuth and ClickUp sync

## New Target Architecture

### Identity

- Supabase Auth is the only login source
- `public.user_profiles` mirrors `auth.users`
- `public.custom_access_token_hook(jsonb)` injects:
  - `tenant_id`
  - `member_id`
  - `tenant_slug`
  - `subscription_status`
  - `user_role`

### Authorization

- RLS enforces tenant boundaries
- backend stops minting custom JWTs
- backend verifies Supabase bearer tokens only

### Core Data Domains

- `tenants`
- `tenant_members`
- `tenant_settings`
- `tenant_domains`
- `clients`
- `meetings`
- `action_items`

### Integrations

- `integration_catalog`
- `tenant_integrations`
- `user_oauth_accounts`
- `client_integration_bindings`
- `integration_location_bindings`

### Ownership + ClickUp

- `client_ownership`
- `ownership_sync_runs`
- `ownership_sync_exceptions`
- `clickup_client_sync_state`
- `clickup_client_sync_logs`

### Runtime Feature Domains

- `client_review_goals`
- `review_events`
- `review_monthly_snapshots`
- `discovery_question_templates`
- `roadmap_plans`
- `content_captures`
- `tickets`
- `qa_scorecards`
- `tenant_files`
- `ai_visibility_configs`
- `ai_visibility_runs`
- `ai_visibility_scans`
- `ai_territory_events`

## What To Delete From The Old Design

These are the major backend concepts to phase out completely:

- `backend/db.py` Mongo client usage
- `backend/BaseDocument` / `to_mongo()` / `_id` semantics
- `backend/runtime_bridge.py`
- bridge-domain feature flags in `backend/supabase_config.py`
- any `legacy_source_id` / mirror / backfill logic
- custom token minting in `backend/auth.py`

## Backend Rewrite Plan

### Phase 1: Foundation

- Add a Supabase-native admin client/repository layer
- Stop adding new Mongo/bridge code
- Keep existing API contracts stable where possible

### Phase 2: Auth

- Replace custom JWT issuance with Supabase token verification
- Replace `get_current_user` / `get_current_context` to read claims directly from Supabase bearer tokens
- Resolve tenant membership from claims + `tenant_members`

### Phase 3: Repositories

Replace bridge-backed persistence with direct repositories:

- `ClientRepository`
- `MeetingRepository`
- `ActionItemRepository`
- `IntegrationRepository`
- `OwnershipRepository`
- `ReviewRepository`
- `DiscoveryRepository`
- `RoadmapRepository`
- `ContentCaptureRepository`
- `TicketRepository`
- `QaRepository`
- `AiVisibilityRepository`

### Phase 4: Endpoints

Refactor routes in this order:

1. auth
2. clients
3. meetings
4. action items
5. integrations / oauth
6. clickup sync / ownership
7. reviews
8. discovery
9. roadmap
10. content captures
11. files
12. ai visibility
13. dashboard aggregation

### Phase 5: Frontend

- Keep API shapes stable where possible
- Remove assumptions about Mongo IDs
- Rely on Supabase-backed UUIDs only
- Continue using backend APIs unless frontend is later moved to Supabase client queries directly

## SQL Bootstrapping Notes

The bootstrap SQL:

- is greenfield
- includes RLS
- includes the auth profile sync trigger
- includes the access token hook
- seeds `integration_catalog`
- keeps the current app feature set, but without bridge columns

It does not yet include:

- frontend/browser auth rollout details for every screen
- an in-database CMS/docs table, because the current docs hub is mostly code/static content

This repo now also includes a follow-up SQL file for storage and first-project bootstrap:

- `supabase/bootstrap/001_supabase_native_storage_and_seed.sql`

## Recommended Environment Variables

### Backend

- `SUPABASE_ENABLED=true`
- `SUPABASE_NATIVE_ONLY_MODE=true`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `JWT_SECRET`
- `INTEGRATION_ENCRYPTION_KEY`
- `SUPABASE_JWT_SECRET` or equivalent verification config, depending on the chosen auth library
- integration secrets as needed:
  - `MTOS_CLICKUP_API_TOKEN`
  - `MTOS_CLICKUP_TEAM_ID`
  - `MTOS_CLICKUP_LIST_ID`
  - `MTOS_CLICKUP_AM_CUSTOM_FIELD_ID`

### Frontend

- `REACT_APP_BACKEND_URL`
- `REACT_APP_GOOGLE_CLIENT_ID`

## Cutover Strategy

Because this is a destructive reset, the safest order is:

1. create a new Supabase project or wipe old public tables
2. run `supabase/bootstrap/000_supabase_native_bootstrap.sql`
3. run `supabase/bootstrap/001_supabase_native_storage_and_seed.sql`
4. configure the access token hook in Supabase Auth to call `public.custom_access_token_hook`
5. create your first auth user in Supabase Auth
6. run `select public.bootstrap_new_project('<first-user-uuid>', 'Map Ranking', 'map-ranking');`
7. configure auth providers and redirect URLs
8. set backend env vars with `SUPABASE_NATIVE_ONLY_MODE=true`
9. smoke test auth, tenants, clients, meetings, and integrations
10. then restore/import any seed data you actually want

Important today: keep `SUPABASE_RUNTIME_BRIDGE_ENABLED=true` during the first cutover to the new project. That keeps the remaining not-yet-cut-over domains working against Supabase while Mongo stays out of the picture.

## New Project Runbook

For a brand-new Supabase project, use this exact order:

1. In Supabase, create the new project and wait until the database is fully ready.
2. Open SQL Editor and run `000_supabase_native_bootstrap.sql`.
3. Open SQL Editor and run `001_supabase_native_storage_and_seed.sql`.
4. In Authentication settings, configure the Custom Access Token Hook to call `public.custom_access_token_hook`.
5. In Authentication providers, enable Email and Google if you plan to use Google sign-in immediately.
6. In Authentication users, create the first user manually or sign up once through the app after backend env is set.
7. Copy that first user's UUID and run:

```sql
select public.bootstrap_new_project(
  '<first-user-uuid>',
  'Map Ranking',
  'map-ranking'
);
```

8. Set backend env from `backend/.env.example`.
9. Set frontend env from `frontend/.env.example`.
10. Start backend, hit `/api/`, then sign in and verify tenant, clients, meetings, integrations, and prompt center.

## Current Start Of Refactor

This repo now includes:

- a fresh Supabase bootstrap schema
- this migration plan document

The next code step is to replace the bridge foundation with a direct Supabase repository layer and then migrate auth/context resolution to Supabase-only.
