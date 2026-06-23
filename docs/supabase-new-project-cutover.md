# Supabase New Project Cutover

This is the clean reset path for moving MTOS to a brand-new Supabase project with no Mongo migration dependency.

## Goal

- New Supabase project
- Fresh public schema
- Fresh auth setup
- Fresh storage bucket
- First tenant bootstrapped correctly
- Backend pointed at Supabase only

## Run Order

1. Create the new Supabase project.
2. In SQL Editor, run `supabase/bootstrap/000_supabase_native_bootstrap.sql`.
3. In SQL Editor, run `supabase/bootstrap/001_supabase_native_storage_and_seed.sql`.
4. In Authentication settings, configure the Custom Access Token Hook to call `public.custom_access_token_hook`.
5. Enable the auth providers you need:
   - Email
   - Google
6. Create the first auth user in Supabase Auth.
7. Copy that user UUID and run:

```sql
select public.bootstrap_new_project(
  '<first-user-uuid>',
  'Map Ranking',
  'map-ranking'
);
```

8. Set backend env from `backend/.env.example`.
9. Set frontend env from `frontend/.env.example`.
10. Deploy backend and frontend with the new project credentials.

## Backend Rules

Use these settings for the clean reset:

- `SUPABASE_ENABLED=true`
- `SUPABASE_NATIVE_ONLY_MODE=true`
- `SUPABASE_RUNTIME_BRIDGE_ENABLED=true`
- `SUPABASE_OAUTH_TOKEN_MONGO_MIRROR_ENABLED=false`
- `SUPABASE_OAUTH_TOKEN_NO_MONGO_READS_ENABLED=true`

Why the bridge flag stays on for now:

- It keeps the remaining bridge-backed domains reading and writing the new Supabase project.
- It does not require Mongo if Mongo mirror/reads are disabled.
- It should be removed only after the remaining routes are fully rewritten.

## Required Backend Secrets

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `JWT_SECRET`
- `INTEGRATION_ENCRYPTION_KEY`

## First Validation

After deploy:

1. Open `GET /api/`
2. Confirm `db_ready=true`
3. Confirm `supabase_native_only_mode=true`
4. Sign in with the first user
5. Confirm tenant, users, clients, meetings, and prompt center load correctly

## Important Reality Check

This repo still contains legacy bridge-era code paths in some domains. This cutover package gives you:

- the fresh schema
- the storage/bootstrap SQL
- the env layout
- direct Supabase readiness validation

It does not magically remove every remaining bridge reference in one commit. The remaining runtime cleanup should continue after the new project is live, but this package gives you the correct new-project baseline to stop stacking more damage onto the old mixed environment.
