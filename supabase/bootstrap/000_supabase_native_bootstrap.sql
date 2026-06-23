-- ================================================================
-- FILE: 000_supabase_native_bootstrap.sql
-- PURPOSE: Fresh Supabase-only bootstrap for MTOS
-- MODE: GREENFIELD / DESTRUCTIVE RESET
-- NOTES:
--   - Run this on a new/empty Supabase project or after dropping old tables.
--   - This intentionally removes Mongo bridge concepts such as legacy ids.
--   - Auth source-of-truth is Supabase Auth only.
--   - App data source-of-truth is Postgres only.
-- ================================================================

create extension if not exists pgcrypto;
create extension if not exists citext;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role_type') then
    create type public.user_role_type as enum ('platform_admin', 'tenant_owner', 'manager', 'staff', 'customer');
  end if;
  if not exists (select 1 from pg_type where typname = 'membership_status_type') then
    create type public.membership_status_type as enum ('active', 'invited', 'disabled');
  end if;
  if not exists (select 1 from pg_type where typname = 'tenant_status_type') then
    create type public.tenant_status_type as enum ('active', 'suspended', 'archived');
  end if;
  if not exists (select 1 from pg_type where typname = 'subscription_status_type') then
    create type public.subscription_status_type as enum ('onboarding', 'trialing', 'active', 'past_due', 'canceled', 'suspended');
  end if;
  if not exists (select 1 from pg_type where typname = 'client_status_type') then
    create type public.client_status_type as enum ('active', 'paused', 'churned');
  end if;
  if not exists (select 1 from pg_type where typname = 'risk_level_type') then
    create type public.risk_level_type as enum ('low', 'medium', 'high');
  end if;
  if not exists (select 1 from pg_type where typname = 'sentiment_type') then
    create type public.sentiment_type as enum ('positive', 'neutral', 'negative');
  end if;
  if not exists (select 1 from pg_type where typname = 'meeting_status_type') then
    create type public.meeting_status_type as enum ('scheduled', 'prep', 'in_progress', 'completed', 'cancelled');
  end if;
  if not exists (select 1 from pg_type where typname = 'integration_status_type') then
    create type public.integration_status_type as enum ('not_connected', 'connected', 'error', 'coming_soon');
  end if;
  if not exists (select 1 from pg_type where typname = 'integration_auth_kind_type') then
    create type public.integration_auth_kind_type as enum ('oauth', 'api_key', 'metadata_only', 'vault_ref', 'external_secret');
  end if;
end
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create or replace function public.current_tenant_id()
returns uuid
language sql
stable
as $$
  select nullif(auth.jwt() ->> 'tenant_id', '')::uuid
$$;

create or replace function public.current_member_id()
returns uuid
language sql
stable
as $$
  select nullif(auth.jwt() ->> 'member_id', '')::uuid
$$;

create or replace function public.current_user_role()
returns public.user_role_type
language sql
stable
as $$
  select nullif(auth.jwt() ->> 'user_role', '')::public.user_role_type
$$;

create or replace function public.current_tenant_slug()
returns text
language sql
stable
as $$
  select nullif(auth.jwt() ->> 'tenant_slug', '')
$$;

create or replace function public.current_subscription_status()
returns public.subscription_status_type
language sql
stable
as $$
  select nullif(auth.jwt() ->> 'subscription_status', '')::public.subscription_status_type
$$;

create or replace function public.is_tenant_admin()
returns boolean
language sql
stable
as $$
  select coalesce(public.current_user_role() in ('platform_admin', 'tenant_owner', 'manager'), false)
$$;

create table if not exists public.user_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email citext,
  full_name text,
  avatar_url text,
  auth_provider text not null default 'email',
  system_role public.user_role_type not null default 'customer',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists user_profiles_email_unique_idx on public.user_profiles (email) where email is not null;
create index if not exists user_profiles_system_role_idx on public.user_profiles (system_role);

alter table public.user_profiles enable row level security;

drop policy if exists "user_profiles_self_select" on public.user_profiles;
create policy "user_profiles_self_select" on public.user_profiles
  for select to authenticated
  using (id = auth.uid());

drop policy if exists "user_profiles_self_update" on public.user_profiles;
create policy "user_profiles_self_update" on public.user_profiles
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

drop policy if exists "user_profiles_auth_admin_select" on public.user_profiles;
create policy "user_profiles_auth_admin_select" on public.user_profiles
  for select to supabase_auth_admin
  using (true);

drop policy if exists "user_profiles_auth_admin_insert" on public.user_profiles;
create policy "user_profiles_auth_admin_insert" on public.user_profiles
  for insert to supabase_auth_admin
  with check (true);

drop policy if exists "user_profiles_auth_admin_update" on public.user_profiles;
create policy "user_profiles_auth_admin_update" on public.user_profiles
  for update to supabase_auth_admin
  using (true)
  with check (true);

create or replace function public.handle_auth_user_profile_sync()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  derived_name text;
  derived_provider text;
  derived_system_role public.user_role_type;
begin
  derived_name := coalesce(
    nullif(trim(new.raw_user_meta_data ->> 'name'), ''),
    nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''),
    nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
    nullif(trim(split_part(coalesce(new.email, ''), '@', 1)), '')
  );

  derived_provider := coalesce(nullif(trim(new.raw_app_meta_data ->> 'provider'), ''), 'email');

  derived_system_role := case lower(coalesce(new.raw_app_meta_data ->> 'system_role', ''))
    when 'platform_admin' then 'platform_admin'::public.user_role_type
    else 'customer'::public.user_role_type
  end;

  insert into public.user_profiles (
    id,
    email,
    full_name,
    avatar_url,
    auth_provider,
    system_role,
    created_at,
    updated_at
  )
  values (
    new.id,
    nullif(trim(lower(new.email)), '')::citext,
    derived_name,
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'avatar_url', new.raw_user_meta_data ->> 'picture')), ''),
    derived_provider,
    derived_system_role,
    now(),
    now()
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(excluded.full_name, public.user_profiles.full_name),
        avatar_url = coalesce(excluded.avatar_url, public.user_profiles.avatar_url),
        auth_provider = excluded.auth_provider,
        system_role = case
          when public.user_profiles.system_role = 'platform_admin' then public.user_profiles.system_role
          else excluded.system_role
        end,
        updated_at = now();

  return new;
end;
$$;

drop trigger if exists on_auth_user_profile_sync on auth.users;
create trigger on_auth_user_profile_sync
  after insert or update of email, raw_user_meta_data, raw_app_meta_data
  on auth.users
  for each row
  execute function public.handle_auth_user_profile_sync();

drop trigger if exists user_profiles_set_updated_at on public.user_profiles;
create trigger user_profiles_set_updated_at
  before update on public.user_profiles
  for each row
  execute function public.set_updated_at();

grant usage on schema public to supabase_auth_admin;
grant execute on function public.handle_auth_user_profile_sync() to supabase_auth_admin;

create table if not exists public.tenants (
  id uuid primary key default gen_random_uuid(),
  slug citext not null,
  name text not null,
  status public.tenant_status_type not null default 'active',
  subscription_status public.subscription_status_type not null default 'onboarding',
  subscription_expires_at timestamptz,
  trial_ends_at timestamptz,
  owner_user_id uuid references auth.users(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.tenant_members (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role public.user_role_type not null,
  status public.membership_status_type not null default 'active',
  is_default boolean not null default false,
  invited_by uuid references auth.users(id) on delete set null,
  joined_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false,
  constraint tenant_members_role_check check (role in ('tenant_owner', 'manager', 'staff', 'customer'))
);

create table if not exists public.tenant_settings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  branding jsonb not null default '{}'::jsonb,
  terminology jsonb not null default '{}'::jsonb,
  workflows jsonb not null default '{}'::jsonb,
  analysis jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.tenant_domains (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  domain citext not null,
  is_primary boolean not null default false,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists tenants_slug_unique_idx on public.tenants (slug) where is_deleted = false;
create unique index if not exists tenant_members_tenant_user_unique_idx on public.tenant_members (tenant_id, user_id) where is_deleted = false;
create unique index if not exists tenant_members_default_active_unique_idx on public.tenant_members (user_id) where is_default = true and status = 'active' and is_deleted = false;
create unique index if not exists tenant_settings_tenant_unique_idx on public.tenant_settings (tenant_id) where is_deleted = false;
create unique index if not exists tenant_domains_domain_unique_idx on public.tenant_domains (domain) where is_deleted = false;
create index if not exists tenant_members_lookup_idx on public.tenant_members (tenant_id, status, role);
create index if not exists tenant_domains_tenant_lookup_idx on public.tenant_domains (tenant_id, is_primary) where is_deleted = false;

alter table public.tenants enable row level security;
alter table public.tenant_members enable row level security;
alter table public.tenant_settings enable row level security;
alter table public.tenant_domains enable row level security;

drop policy if exists "tenants_select" on public.tenants;
create policy "tenants_select" on public.tenants
  for select to authenticated
  using (id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "tenants_update" on public.tenants;
create policy "tenants_update" on public.tenants
  for update to authenticated
  using (id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin())
  with check (id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "tenant_members_select" on public.tenant_members;
create policy "tenant_members_select" on public.tenant_members
  for select to authenticated
  using (
    tenant_id = public.current_tenant_id()
    and is_deleted = false
    and (user_id = auth.uid() or public.is_tenant_admin())
  );

drop policy if exists "tenant_members_insert" on public.tenant_members;
create policy "tenant_members_insert" on public.tenant_members
  for insert to authenticated
  with check (
    tenant_id = public.current_tenant_id()
    and is_deleted = false
    and public.is_tenant_admin()
  );

drop policy if exists "tenant_members_update" on public.tenant_members;
create policy "tenant_members_update" on public.tenant_members
  for update to authenticated
  using (
    tenant_id = public.current_tenant_id()
    and is_deleted = false
    and public.is_tenant_admin()
  )
  with check (
    tenant_id = public.current_tenant_id()
    and is_deleted = false
    and public.is_tenant_admin()
  );

drop policy if exists "tenant_settings_select" on public.tenant_settings;
create policy "tenant_settings_select" on public.tenant_settings
  for select to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "tenant_settings_insert" on public.tenant_settings;
create policy "tenant_settings_insert" on public.tenant_settings
  for insert to authenticated
  with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "tenant_settings_update" on public.tenant_settings;
create policy "tenant_settings_update" on public.tenant_settings
  for update to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin())
  with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "tenant_domains_select" on public.tenant_domains;
create policy "tenant_domains_select" on public.tenant_domains
  for select to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "tenant_domains_insert" on public.tenant_domains;
create policy "tenant_domains_insert" on public.tenant_domains
  for insert to authenticated
  with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "tenant_domains_update" on public.tenant_domains;
create policy "tenant_domains_update" on public.tenant_domains
  for update to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin())
  with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "tenants_auth_admin_select" on public.tenants;
create policy "tenants_auth_admin_select" on public.tenants for select to supabase_auth_admin using (true);
drop policy if exists "tenant_members_auth_admin_select" on public.tenant_members;
create policy "tenant_members_auth_admin_select" on public.tenant_members for select to supabase_auth_admin using (true);
drop policy if exists "tenant_settings_auth_admin_select" on public.tenant_settings;
create policy "tenant_settings_auth_admin_select" on public.tenant_settings for select to supabase_auth_admin using (true);
drop policy if exists "tenant_domains_auth_admin_select" on public.tenant_domains;
create policy "tenant_domains_auth_admin_select" on public.tenant_domains for select to supabase_auth_admin using (true);

drop policy if exists "user_profiles_self_select" on public.user_profiles;
create policy "user_profiles_self_select" on public.user_profiles
  for select to authenticated
  using (
    id = auth.uid()
    or exists (
      select 1
      from public.tenant_members tm
      where tm.user_id = public.user_profiles.id
        and tm.tenant_id = public.current_tenant_id()
        and tm.status = 'active'
        and tm.is_deleted = false
        and public.is_tenant_admin()
    )
  );

drop trigger if exists tenants_set_updated_at on public.tenants;
create trigger tenants_set_updated_at before update on public.tenants for each row execute function public.set_updated_at();
drop trigger if exists tenant_members_set_updated_at on public.tenant_members;
create trigger tenant_members_set_updated_at before update on public.tenant_members for each row execute function public.set_updated_at();
drop trigger if exists tenant_settings_set_updated_at on public.tenant_settings;
create trigger tenant_settings_set_updated_at before update on public.tenant_settings for each row execute function public.set_updated_at();
drop trigger if exists tenant_domains_set_updated_at on public.tenant_domains;
create trigger tenant_domains_set_updated_at before update on public.tenant_domains for each row execute function public.set_updated_at();

create or replace function public.tenant_members_default_enforcer()
returns trigger
language plpgsql
as $$
begin
  if pg_trigger_depth() > 1 then
    return new;
  end if;

  if new.is_deleted = true or new.status <> 'active' then
    new.is_default := false;
    return new;
  end if;

  if new.is_default is true then
    update public.tenant_members
    set is_default = false,
        updated_at = now()
    where user_id = new.user_id
      and id <> coalesce(new.id, gen_random_uuid())
      and is_default = true;
  elsif not exists (
    select 1
    from public.tenant_members tm
    where tm.user_id = new.user_id
      and tm.status = 'active'
      and tm.is_deleted = false
      and tm.id <> coalesce(new.id, '00000000-0000-0000-0000-000000000000'::uuid)
  ) then
    new.is_default := true;
  end if;

  if new.joined_at is null and new.status = 'active' then
    new.joined_at := now();
  end if;

  return new;
end;
$$;

drop trigger if exists tenant_members_default_enforcer_trigger on public.tenant_members;
create trigger tenant_members_default_enforcer_trigger
  before insert or update of is_default, status, is_deleted
  on public.tenant_members
  for each row
  execute function public.tenant_members_default_enforcer();

create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  claims jsonb;
  system_role public.user_role_type;
  effective_role public.user_role_type;
  selected_member_id uuid;
  selected_tenant_id uuid;
  selected_member_role public.user_role_type;
  selected_tenant_slug text;
  selected_subscription_status public.subscription_status_type;
begin
  claims := event -> 'claims';

  select up.system_role
    into system_role
  from public.user_profiles up
  where up.id = (event ->> 'user_id')::uuid;

  select tm.id, tm.tenant_id, tm.role, t.slug, t.subscription_status
    into selected_member_id, selected_tenant_id, selected_member_role, selected_tenant_slug, selected_subscription_status
  from public.tenant_members tm
  join public.tenants t on t.id = tm.tenant_id and t.is_deleted = false
  where tm.user_id = (event ->> 'user_id')::uuid
    and tm.status = 'active'
    and tm.is_deleted = false
  order by tm.is_default desc,
           case tm.role
             when 'tenant_owner' then 0
             when 'manager' then 1
             when 'staff' then 2
             else 3
           end,
           tm.created_at asc
  limit 1;

  effective_role := coalesce(
    case when system_role = 'platform_admin' then system_role else selected_member_role end,
    system_role,
    'customer'::public.user_role_type
  );

  claims := jsonb_set(claims, '{user_role}', to_jsonb(effective_role::text), true);
  claims := jsonb_set(claims, '{tenant_id}', coalesce(to_jsonb(selected_tenant_id), 'null'::jsonb), true);
  claims := jsonb_set(claims, '{member_id}', coalesce(to_jsonb(selected_member_id), 'null'::jsonb), true);
  claims := jsonb_set(claims, '{tenant_slug}', coalesce(to_jsonb(selected_tenant_slug), 'null'::jsonb), true);
  claims := jsonb_set(claims, '{subscription_status}', coalesce(to_jsonb(selected_subscription_status::text), 'null'::jsonb), true);

  return jsonb_set(event, '{claims}', claims, true);
end;
$$;

grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;

insert into public.user_profiles (id, email, full_name, avatar_url, auth_provider, system_role, created_at, updated_at)
select
  au.id,
  nullif(trim(lower(au.email)), '')::citext,
  coalesce(
    nullif(trim(au.raw_user_meta_data ->> 'name'), ''),
    nullif(trim(au.raw_user_meta_data ->> 'full_name'), ''),
    nullif(trim(split_part(coalesce(au.email, ''), '@', 1)), '')
  ),
  nullif(trim(coalesce(au.raw_user_meta_data ->> 'avatar_url', au.raw_user_meta_data ->> 'picture')), ''),
  coalesce(nullif(trim(au.raw_app_meta_data ->> 'provider'), ''), 'email'),
  case lower(coalesce(au.raw_app_meta_data ->> 'system_role', ''))
    when 'platform_admin' then 'platform_admin'::public.user_role_type
    else 'customer'::public.user_role_type
  end,
  coalesce(au.created_at, now()),
  now()
from auth.users au
on conflict (id) do nothing;

create table if not exists public.clients (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  name text not null,
  company text not null,
  external_ref text,
  industry text,
  primary_contact text,
  email citext,
  phone text,
  website text,
  location text,
  account_manager_user_id uuid references auth.users(id) on delete set null,
  account_manager_name text,
  services text[] not null default '{}'::text[],
  assigned_products text[] not null default '{}'::text[],
  crm_data jsonb not null default '{}'::jsonb,
  gbp_data jsonb not null default '{}'::jsonb,
  onboarding_date date,
  mrr numeric(12,2) not null default 0,
  health_score integer not null default 75,
  churn_risk public.risk_level_type not null default 'low',
  sentiment public.sentiment_type not null default 'neutral',
  notes text,
  avatar_url text,
  status public.client_status_type not null default 'active',
  suggestions jsonb not null default '[]'::jsonb,
  suggestions_generated_at timestamptz,
  suggestions_model text,
  feedback_alert boolean not null default false,
  feedback_alert_level public.risk_level_type not null default 'low',
  feedback_alert_reason text,
  feedback_last_submitted_at timestamptz,
  feedback_rolling_avg jsonb not null default '{}'::jsonb,
  health_alert boolean not null default false,
  health_alert_level public.risk_level_type not null default 'low',
  health_alert_reason text,
  churn_risk_score integer not null default 0,
  churn_risk_indicators text[] not null default '{}'::text[],
  nps_rolling_avg numeric(5,2),
  sentiment_rolling jsonb not null default '{}'::jsonb,
  health_last_submitted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false,
  constraint clients_health_score_range check (health_score between 0 and 100),
  constraint clients_churn_risk_score_range check (churn_risk_score between 0 and 100)
);

create index if not exists clients_tenant_created_at_idx on public.clients (tenant_id, created_at desc) where is_deleted = false;
create index if not exists clients_tenant_status_idx on public.clients (tenant_id, status) where is_deleted = false;
create index if not exists clients_tenant_account_manager_idx on public.clients (tenant_id, account_manager_user_id) where is_deleted = false;
create index if not exists clients_tenant_email_idx on public.clients (tenant_id, email) where is_deleted = false and email is not null;
create index if not exists clients_tenant_external_ref_idx on public.clients (tenant_id, external_ref) where is_deleted = false and external_ref is not null;

alter table public.clients enable row level security;

drop policy if exists "clients_select" on public.clients;
create policy "clients_select" on public.clients
  for select to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "clients_insert" on public.clients;
create policy "clients_insert" on public.clients
  for insert to authenticated
  with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "clients_update" on public.clients;
create policy "clients_update" on public.clients
  for update to authenticated
  using (tenant_id = public.current_tenant_id() and is_deleted = false)
  with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop trigger if exists clients_set_updated_at on public.clients;
create trigger clients_set_updated_at before update on public.clients for each row execute function public.set_updated_at();

create table if not exists public.meetings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  client_name text,
  account_manager_user_id uuid references auth.users(id) on delete set null,
  account_manager_name text,
  title text not null,
  scheduled_at timestamptz,
  status public.meeting_status_type not null default 'scheduled',
  google_meet_url text,
  duration_minutes integer not null default 60,
  brief_generated_at timestamptz,
  brief_model text,
  wins jsonb not null default '[]'::jsonb,
  wins_library jsonb not null default '[]'::jsonb,
  issues jsonb not null default '[]'::jsonb,
  issues_library jsonb not null default '[]'::jsonb,
  talking_points jsonb not null default '[]'::jsonb,
  talking_points_library jsonb not null default '[]'::jsonb,
  suggested_questions jsonb not null default '[]'::jsonb,
  prep_checklist jsonb not null default '[]'::jsonb,
  ace_up_the_sleeve jsonb not null default '[]'::jsonb,
  testimonial_opportunity text,
  strategic_recommendations jsonb not null default '[]'::jsonb,
  campaign_recommendations jsonb not null default '[]'::jsonb,
  health_signal text,
  automation_draft jsonb not null default '{}'::jsonb,
  automation_draft_generated_at timestamptz,
  automation_approved_at timestamptz,
  kpi_snapshot jsonb not null default '{}'::jsonb,
  notes text,
  transcript text,
  transcript_source jsonb not null default '{}'::jsonb,
  transcript_analyzed_at timestamptz,
  sentiment public.sentiment_type,
  sentiment_summary text,
  transcript_analysis jsonb not null default '{}'::jsonb,
  transcript_analysis_by_model jsonb not null default '{}'::jsonb,
  nps_score integer,
  sentiment_classification text,
  health_notes text,
  recap_html text,
  recap_email text,
  recap_subject text,
  recap_sent_at timestamptz,
  meeting_score integer,
  checklist jsonb not null default '{}'::jsonb,
  deliverable_reviews jsonb not null default '{}'::jsonb,
  discovery_questions jsonb not null default '[]'::jsonb,
  feedback jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false,
  constraint meetings_duration_minutes_check check (duration_minutes > 0),
  constraint meetings_nps_score_check check (nps_score is null or nps_score between 0 and 10),
  constraint meetings_meeting_score_check check (meeting_score is null or meeting_score between 0 and 100)
);

create index if not exists meetings_tenant_client_created_idx on public.meetings (tenant_id, client_id, created_at desc) where is_deleted = false;
create index if not exists meetings_tenant_scheduled_idx on public.meetings (tenant_id, scheduled_at desc) where is_deleted = false;
create index if not exists meetings_tenant_status_idx on public.meetings (tenant_id, status) where is_deleted = false;
create index if not exists meetings_tenant_account_manager_idx on public.meetings (tenant_id, account_manager_user_id) where is_deleted = false;

alter table public.meetings enable row level security;

drop policy if exists "meetings_select" on public.meetings;
create policy "meetings_select" on public.meetings for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "meetings_insert" on public.meetings;
create policy "meetings_insert" on public.meetings for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "meetings_update" on public.meetings;
create policy "meetings_update" on public.meetings for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop trigger if exists meetings_set_updated_at on public.meetings;
create trigger meetings_set_updated_at before update on public.meetings for each row execute function public.set_updated_at();

create table if not exists public.action_items (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  meeting_id uuid references public.meetings(id) on delete set null,
  client_id uuid not null references public.clients(id) on delete cascade,
  title text not null,
  description text,
  owner text,
  owner_type text not null default 'agency',
  due_date date,
  status text not null default 'open',
  priority text not null default 'medium',
  pushed_to text,
  external_id text,
  external_url text,
  last_reminded_at timestamptz,
  reminder_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false,
  constraint action_items_owner_type_check check (owner_type in ('agency', 'client')),
  constraint action_items_status_check check (status in ('open', 'in_progress', 'completed', 'blocked')),
  constraint action_items_priority_check check (priority in ('low', 'medium', 'high')),
  constraint action_items_reminder_count_check check (reminder_count >= 0)
);

create index if not exists action_items_tenant_created_idx on public.action_items (tenant_id, created_at desc) where is_deleted = false;
create index if not exists action_items_tenant_client_status_idx on public.action_items (tenant_id, client_id, status) where is_deleted = false;
create index if not exists action_items_tenant_meeting_idx on public.action_items (tenant_id, meeting_id) where is_deleted = false and meeting_id is not null;
create index if not exists action_items_tenant_due_idx on public.action_items (tenant_id, due_date, status) where is_deleted = false and due_date is not null;

alter table public.action_items enable row level security;

drop policy if exists "action_items_select" on public.action_items;
create policy "action_items_select" on public.action_items for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "action_items_insert" on public.action_items;
create policy "action_items_insert" on public.action_items for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "action_items_update" on public.action_items;
create policy "action_items_update" on public.action_items for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop trigger if exists action_items_set_updated_at on public.action_items;
create trigger action_items_set_updated_at before update on public.action_items for each row execute function public.set_updated_at();

create table if not exists public.integration_catalog (
  platform text primary key,
  label text not null,
  category text not null,
  description text,
  auth_kind public.integration_auth_kind_type not null default 'metadata_only',
  capabilities jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.tenant_integrations (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  platform text not null references public.integration_catalog(platform) on delete restrict,
  label text not null,
  status public.integration_status_type not null default 'not_connected',
  last_synced_at timestamptz,
  last_error text,
  metadata jsonb not null default '{}'::jsonb,
  vault_secret_ref text,
  oauth_connection_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.user_oauth_accounts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  platform text not null references public.integration_catalog(platform) on delete restrict,
  account_email citext,
  external_account_id text,
  scopes text[] not null default '{}'::text[],
  last_synced_at timestamptz,
  oauth_connection_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.client_integration_bindings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  platform text not null references public.integration_catalog(platform) on delete restrict,
  enabled boolean not null default true,
  external_ids jsonb not null default '{}'::jsonb,
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.integration_location_bindings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  platform text not null references public.integration_catalog(platform) on delete restrict,
  location_id text not null,
  label text,
  metadata jsonb not null default '{}'::jsonb,
  vault_secret_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists tenant_integrations_tenant_platform_unique_idx on public.tenant_integrations (tenant_id, platform) where is_deleted = false;
create unique index if not exists user_oauth_accounts_unique_idx on public.user_oauth_accounts (tenant_id, user_id, provider, platform) where is_deleted = false;
create unique index if not exists client_integration_bindings_unique_idx on public.client_integration_bindings (tenant_id, client_id, platform) where is_deleted = false;
create unique index if not exists integration_location_bindings_unique_idx on public.integration_location_bindings (tenant_id, platform, location_id) where is_deleted = false;

alter table public.integration_catalog enable row level security;
alter table public.tenant_integrations enable row level security;
alter table public.user_oauth_accounts enable row level security;
alter table public.client_integration_bindings enable row level security;
alter table public.integration_location_bindings enable row level security;

drop policy if exists "integration_catalog_select" on public.integration_catalog;
create policy "integration_catalog_select" on public.integration_catalog for select to authenticated using (is_active = true);
drop policy if exists "tenant_integrations_select" on public.tenant_integrations;
create policy "tenant_integrations_select" on public.tenant_integrations for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "tenant_integrations_insert" on public.tenant_integrations;
create policy "tenant_integrations_insert" on public.tenant_integrations for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "tenant_integrations_update" on public.tenant_integrations;
create policy "tenant_integrations_update" on public.tenant_integrations for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "user_oauth_accounts_select" on public.user_oauth_accounts;
create policy "user_oauth_accounts_select" on public.user_oauth_accounts for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and (user_id = auth.uid() or public.is_tenant_admin()));
drop policy if exists "user_oauth_accounts_insert" on public.user_oauth_accounts;
create policy "user_oauth_accounts_insert" on public.user_oauth_accounts for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and user_id = auth.uid());
drop policy if exists "user_oauth_accounts_update" on public.user_oauth_accounts;
create policy "user_oauth_accounts_update" on public.user_oauth_accounts for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and (user_id = auth.uid() or public.is_tenant_admin())) with check (tenant_id = public.current_tenant_id() and is_deleted = false and (user_id = auth.uid() or public.is_tenant_admin()));
drop policy if exists "client_integration_bindings_select" on public.client_integration_bindings;
create policy "client_integration_bindings_select" on public.client_integration_bindings for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "client_integration_bindings_insert" on public.client_integration_bindings;
create policy "client_integration_bindings_insert" on public.client_integration_bindings for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "client_integration_bindings_update" on public.client_integration_bindings;
create policy "client_integration_bindings_update" on public.client_integration_bindings for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "integration_location_bindings_select" on public.integration_location_bindings;
create policy "integration_location_bindings_select" on public.integration_location_bindings for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "integration_location_bindings_insert" on public.integration_location_bindings;
create policy "integration_location_bindings_insert" on public.integration_location_bindings for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "integration_location_bindings_update" on public.integration_location_bindings;
create policy "integration_location_bindings_update" on public.integration_location_bindings for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop trigger if exists integration_catalog_set_updated_at on public.integration_catalog;
create trigger integration_catalog_set_updated_at before update on public.integration_catalog for each row execute function public.set_updated_at();
drop trigger if exists tenant_integrations_set_updated_at on public.tenant_integrations;
create trigger tenant_integrations_set_updated_at before update on public.tenant_integrations for each row execute function public.set_updated_at();
drop trigger if exists user_oauth_accounts_set_updated_at on public.user_oauth_accounts;
create trigger user_oauth_accounts_set_updated_at before update on public.user_oauth_accounts for each row execute function public.set_updated_at();
drop trigger if exists client_integration_bindings_set_updated_at on public.client_integration_bindings;
create trigger client_integration_bindings_set_updated_at before update on public.client_integration_bindings for each row execute function public.set_updated_at();
drop trigger if exists integration_location_bindings_set_updated_at on public.integration_location_bindings;
create trigger integration_location_bindings_set_updated_at before update on public.integration_location_bindings for each row execute function public.set_updated_at();

insert into public.integration_catalog (platform, label, category, description, auth_kind, capabilities)
values
  ('google_oauth', 'Google OAuth', 'Core', 'OAuth client used for Google-connected products.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('clickup', 'ClickUp', 'Project Management', 'Pull account activity and push action items.', 'vault_ref', '{"supports_push": true}'::jsonb),
  ('gohighlevel', 'GoHighLevel', 'CRM', 'CRM pipelines, leads, communications, workflows.', 'vault_ref', '{"supports_import": true}'::jsonb),
  ('google_ads', 'Google Ads', 'Paid Media', 'PPC metrics, conversions, budget pacing, optimization opportunities.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_business_profile', 'Google Business Profile', 'Local SEO', 'GBP calls, direction requests, reviews, local visibility.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_analytics', 'Google Analytics 4', 'Analytics', 'Traffic, conversions, attribution, engagement.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_search_console', 'Google Search Console', 'SEO', 'Organic keywords, CTR, impressions, indexing.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('ahrefs', 'Ahrefs', 'SEO', 'Backlinks, organic keywords, competitor analysis.', 'vault_ref', '{"supports_pull": true}'::jsonb),
  ('meta_ads', 'Meta Ads', 'Paid Media', 'Facebook and Instagram ads, retargeting, lead generation.', 'vault_ref', '{"supports_pull": true}'::jsonb),
  ('google_lsa', 'Google LSA (Local Services Ads)', 'Paid Media', 'LSA leads, calls, lead quality scoring.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_drive', 'Google Drive', 'Documents', 'Onboarding forms, deliverables, photos, meeting recordings.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('gmail', 'Gmail', 'Communication', 'Communication history and follow-up drafts.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_meet', 'Google Meet', 'Meetings', 'Meeting recordings and transcript discovery.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('google_calendar', 'Google Calendar', 'Meetings', 'Calendar synchronization.', 'oauth', '{"supports_oauth": true}'::jsonb),
  ('map_checkins', 'Map Check-ins', 'Local Rank Tracking', 'Geo-grid heat map rankings and field check-ins.', 'vault_ref', '{"supports_pull": true}'::jsonb)
on conflict (platform) do update
set label = excluded.label,
    category = excluded.category,
    description = excluded.description,
    auth_kind = excluded.auth_kind,
    capabilities = excluded.capabilities,
    is_active = true,
    updated_at = now();

create table if not exists public.clickup_client_sync_state (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  running boolean not null default false,
  started_at timestamptz,
  finished_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  last_run_id text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.clickup_client_sync_logs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  ok boolean not null default false,
  started_at timestamptz,
  finished_at timestamptz,
  list_id text,
  list_source text,
  created_count integer not null default 0,
  updated_count integer not null default 0,
  paused_count integer not null default 0,
  assigned_found integer not null default 0,
  error text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists clickup_client_sync_state_tenant_user_unique_idx on public.clickup_client_sync_state (tenant_id, user_id) where is_deleted = false;
create index if not exists clickup_client_sync_logs_tenant_user_started_idx on public.clickup_client_sync_logs (tenant_id, user_id, started_at desc) where is_deleted = false;

alter table public.clickup_client_sync_state enable row level security;
alter table public.clickup_client_sync_logs enable row level security;

drop policy if exists "clickup_client_sync_state_select" on public.clickup_client_sync_state;
create policy "clickup_client_sync_state_select" on public.clickup_client_sync_state for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "clickup_client_sync_state_insert" on public.clickup_client_sync_state;
create policy "clickup_client_sync_state_insert" on public.clickup_client_sync_state for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "clickup_client_sync_state_update" on public.clickup_client_sync_state;
create policy "clickup_client_sync_state_update" on public.clickup_client_sync_state for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "clickup_client_sync_logs_select" on public.clickup_client_sync_logs;
create policy "clickup_client_sync_logs_select" on public.clickup_client_sync_logs for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "clickup_client_sync_logs_insert" on public.clickup_client_sync_logs;
create policy "clickup_client_sync_logs_insert" on public.clickup_client_sync_logs for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "clickup_client_sync_logs_update" on public.clickup_client_sync_logs;
create policy "clickup_client_sync_logs_update" on public.clickup_client_sync_logs for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop trigger if exists clickup_client_sync_state_set_updated_at on public.clickup_client_sync_state;
create trigger clickup_client_sync_state_set_updated_at before update on public.clickup_client_sync_state for each row execute function public.set_updated_at();
drop trigger if exists clickup_client_sync_logs_set_updated_at on public.clickup_client_sync_logs;
create trigger clickup_client_sync_logs_set_updated_at before update on public.clickup_client_sync_logs for each row execute function public.set_updated_at();

create table if not exists public.client_ownership (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  user_id uuid references auth.users(id) on delete set null,
  source text not null default 'clickup_sync',
  synced_at timestamptz not null default now(),
  active boolean not null default true,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ownership_sync_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  provider text not null default 'clickup',
  source text not null default 'clickup_sync',
  cadence_minutes integer,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  matched_clients integer not null default 0,
  unmatched_clients integer not null default 0,
  status text not null default 'running',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ownership_sync_exceptions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  run_id uuid references public.ownership_sync_runs(id) on delete set null,
  client_name text not null,
  external_account_manager text,
  suggested_user_name text,
  reason text not null,
  status text not null default 'open',
  last_seen_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid references auth.users(id) on delete set null,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists client_ownership_active_unique_idx on public.client_ownership (tenant_id, client_id) where active = true and is_deleted = false;
create index if not exists client_ownership_tenant_synced_idx on public.client_ownership (tenant_id, synced_at desc) where is_deleted = false;
create index if not exists ownership_sync_runs_tenant_started_idx on public.ownership_sync_runs (tenant_id, started_at desc) where is_deleted = false;
create unique index if not exists ownership_sync_exceptions_open_unique_idx on public.ownership_sync_exceptions (tenant_id, client_name, coalesce(external_account_manager, ''), reason) where status = 'open' and is_deleted = false;

alter table public.client_ownership enable row level security;
alter table public.ownership_sync_runs enable row level security;
alter table public.ownership_sync_exceptions enable row level security;

drop policy if exists "client_ownership_select" on public.client_ownership;
create policy "client_ownership_select" on public.client_ownership for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "client_ownership_insert" on public.client_ownership;
create policy "client_ownership_insert" on public.client_ownership for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "client_ownership_update" on public.client_ownership;
create policy "client_ownership_update" on public.client_ownership for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ownership_sync_runs_select" on public.ownership_sync_runs;
create policy "ownership_sync_runs_select" on public.ownership_sync_runs for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ownership_sync_runs_insert" on public.ownership_sync_runs;
create policy "ownership_sync_runs_insert" on public.ownership_sync_runs for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "ownership_sync_runs_update" on public.ownership_sync_runs;
create policy "ownership_sync_runs_update" on public.ownership_sync_runs for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "ownership_sync_exceptions_select" on public.ownership_sync_exceptions;
create policy "ownership_sync_exceptions_select" on public.ownership_sync_exceptions for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ownership_sync_exceptions_insert" on public.ownership_sync_exceptions;
create policy "ownership_sync_exceptions_insert" on public.ownership_sync_exceptions for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "ownership_sync_exceptions_update" on public.ownership_sync_exceptions;
create policy "ownership_sync_exceptions_update" on public.ownership_sync_exceptions for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop trigger if exists client_ownership_set_updated_at on public.client_ownership;
create trigger client_ownership_set_updated_at before update on public.client_ownership for each row execute function public.set_updated_at();
drop trigger if exists ownership_sync_runs_set_updated_at on public.ownership_sync_runs;
create trigger ownership_sync_runs_set_updated_at before update on public.ownership_sync_runs for each row execute function public.set_updated_at();
drop trigger if exists ownership_sync_exceptions_set_updated_at on public.ownership_sync_exceptions;
create trigger ownership_sync_exceptions_set_updated_at before update on public.ownership_sync_exceptions for each row execute function public.set_updated_at();

create table if not exists public.client_review_goals (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  monthly_goal integer not null default 10,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.review_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  meeting_id uuid references public.meetings(id) on delete set null,
  kind text not null default 'requested',
  count integer not null default 1,
  occurred_on date not null,
  channel text default 'other',
  source text default 'manual',
  notes text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.review_monthly_snapshots (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  month text not null,
  received integer not null default 0,
  avg_rating numeric,
  source text default 'gbp',
  kpi_period_kind text,
  kpi_period_current_end date,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists client_review_goals_unique_client_idx on public.client_review_goals (tenant_id, client_id) where is_deleted = false;
create unique index if not exists review_monthly_snapshots_unique_month_idx on public.review_monthly_snapshots (tenant_id, client_id, month) where is_deleted = false;
create index if not exists review_events_client_occurred_idx on public.review_events (tenant_id, client_id, occurred_on desc) where is_deleted = false;

create table if not exists public.discovery_question_templates (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  kind text not null default 'operational',
  category text not null,
  question text not null,
  tags jsonb not null default '[]'::jsonb,
  deliverables jsonb not null default '[]'::jsonb,
  active boolean not null default true,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.roadmap_plans (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  start_date date not null,
  weeks integer not null default 12,
  items jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create unique index if not exists roadmap_plans_unique_client_idx on public.roadmap_plans (tenant_id, client_id) where is_deleted = false;

create table if not exists public.content_captures (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  meeting_id uuid references public.meetings(id) on delete set null,
  type text not null default 'quote',
  content text not null,
  sentiment_score numeric,
  timestamp_in_meeting text,
  requested boolean not null default false,
  received boolean not null default false,
  routed_to_marketing boolean not null default false,
  notes text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create index if not exists content_captures_client_idx on public.content_captures (tenant_id, client_id, created_at desc) where is_deleted = false;
create index if not exists content_captures_meeting_idx on public.content_captures (tenant_id, meeting_id) where is_deleted = false and meeting_id is not null;

create table if not exists public.tickets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  meeting_id uuid not null references public.meetings(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  department text not null,
  title text not null,
  description text,
  priority text not null default 'medium',
  status text not null default 'open',
  external_id text,
  external_url text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.qa_scorecards (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  meeting_id uuid not null references public.meetings(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  account_manager_user_id uuid references auth.users(id) on delete set null,
  account_manager_name text,
  total_score integer not null default 0,
  dimensions jsonb not null default '{}'::jsonb,
  feedback text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.tenant_files (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  purpose text not null default 'documentation',
  filename text,
  mime_type text,
  size_bytes bigint not null default 0,
  storage jsonb not null default '{}'::jsonb,
  extracted_text text,
  extracted_chars integer not null default 0,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ai_visibility_configs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  market text not null default '',
  market_override text,
  keywords text[] not null default '{}'::text[],
  brand_override text,
  domain_override text,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ai_visibility_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  config_id uuid not null references public.ai_visibility_configs(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  scan_id text,
  market text not null default '',
  keyword text not null,
  theme text,
  prompt_kind text,
  provider text not null,
  prompt text not null default '',
  response_text text not null default '',
  parsed jsonb not null default '{}'::jsonb,
  hit boolean not null default false,
  hit_brand boolean not null default false,
  hit_domain boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ai_visibility_scans (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  config_id uuid not null references public.ai_visibility_configs(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  scan_id text,
  market text not null default '',
  brand text not null default '',
  domain text not null default '',
  providers jsonb not null default '{}'::jsonb,
  total integer not null default 0,
  hits integer not null default 0,
  overall_visibility_score double precision not null default 0,
  share_of_voice jsonb not null default '{}'::jsonb,
  platform_rankings jsonb not null default '{}'::jsonb,
  themes jsonb not null default '[]'::jsonb,
  prompts_total integer not null default 0,
  competitors jsonb not null default '[]'::jsonb,
  content_intelligence jsonb not null default '{}'::jsonb,
  growth_engine jsonb not null default '{}'::jsonb,
  territory_intelligence jsonb not null default '{}'::jsonb,
  data_confidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

create table if not exists public.ai_territory_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  account_manager_user_id uuid references auth.users(id) on delete set null,
  kind text not null,
  severity text not null default 'low',
  title text not null,
  description text not null default '',
  scan_id text,
  explain jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  is_deleted boolean not null default false
);

-- Shared RLS for remaining tenant-scoped tables
alter table public.client_review_goals enable row level security;
alter table public.review_events enable row level security;
alter table public.review_monthly_snapshots enable row level security;
alter table public.discovery_question_templates enable row level security;
alter table public.roadmap_plans enable row level security;
alter table public.content_captures enable row level security;
alter table public.tickets enable row level security;
alter table public.qa_scorecards enable row level security;
alter table public.tenant_files enable row level security;
alter table public.ai_visibility_configs enable row level security;
alter table public.ai_visibility_runs enable row level security;
alter table public.ai_visibility_scans enable row level security;
alter table public.ai_territory_events enable row level security;

drop policy if exists "client_review_goals_select" on public.client_review_goals;
create policy "client_review_goals_select" on public.client_review_goals for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "client_review_goals_insert" on public.client_review_goals;
create policy "client_review_goals_insert" on public.client_review_goals for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "client_review_goals_update" on public.client_review_goals;
create policy "client_review_goals_update" on public.client_review_goals for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "review_events_select" on public.review_events;
create policy "review_events_select" on public.review_events for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "review_events_insert" on public.review_events;
create policy "review_events_insert" on public.review_events for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "review_events_update" on public.review_events;
create policy "review_events_update" on public.review_events for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "review_monthly_snapshots_select" on public.review_monthly_snapshots;
create policy "review_monthly_snapshots_select" on public.review_monthly_snapshots for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "review_monthly_snapshots_insert" on public.review_monthly_snapshots;
create policy "review_monthly_snapshots_insert" on public.review_monthly_snapshots for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "review_monthly_snapshots_update" on public.review_monthly_snapshots;
create policy "review_monthly_snapshots_update" on public.review_monthly_snapshots for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "discovery_question_templates_select" on public.discovery_question_templates;
create policy "discovery_question_templates_select" on public.discovery_question_templates for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "discovery_question_templates_insert" on public.discovery_question_templates;
create policy "discovery_question_templates_insert" on public.discovery_question_templates for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());
drop policy if exists "discovery_question_templates_update" on public.discovery_question_templates;
create policy "discovery_question_templates_update" on public.discovery_question_templates for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin()) with check (tenant_id = public.current_tenant_id() and is_deleted = false and public.is_tenant_admin());

drop policy if exists "roadmap_plans_select" on public.roadmap_plans;
create policy "roadmap_plans_select" on public.roadmap_plans for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "roadmap_plans_insert" on public.roadmap_plans;
create policy "roadmap_plans_insert" on public.roadmap_plans for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "roadmap_plans_update" on public.roadmap_plans;
create policy "roadmap_plans_update" on public.roadmap_plans for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "content_captures_select" on public.content_captures;
create policy "content_captures_select" on public.content_captures for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "content_captures_insert" on public.content_captures;
create policy "content_captures_insert" on public.content_captures for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "content_captures_update" on public.content_captures;
create policy "content_captures_update" on public.content_captures for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "tickets_select" on public.tickets;
create policy "tickets_select" on public.tickets for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "tickets_insert" on public.tickets;
create policy "tickets_insert" on public.tickets for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "tickets_update" on public.tickets;
create policy "tickets_update" on public.tickets for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "qa_scorecards_select" on public.qa_scorecards;
create policy "qa_scorecards_select" on public.qa_scorecards for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "qa_scorecards_insert" on public.qa_scorecards;
create policy "qa_scorecards_insert" on public.qa_scorecards for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "qa_scorecards_update" on public.qa_scorecards;
create policy "qa_scorecards_update" on public.qa_scorecards for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "tenant_files_select" on public.tenant_files;
create policy "tenant_files_select" on public.tenant_files for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "tenant_files_insert" on public.tenant_files;
create policy "tenant_files_insert" on public.tenant_files for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "tenant_files_update" on public.tenant_files;
create policy "tenant_files_update" on public.tenant_files for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "ai_visibility_configs_select" on public.ai_visibility_configs;
create policy "ai_visibility_configs_select" on public.ai_visibility_configs for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_configs_insert" on public.ai_visibility_configs;
create policy "ai_visibility_configs_insert" on public.ai_visibility_configs for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_configs_update" on public.ai_visibility_configs;
create policy "ai_visibility_configs_update" on public.ai_visibility_configs for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "ai_visibility_runs_select" on public.ai_visibility_runs;
create policy "ai_visibility_runs_select" on public.ai_visibility_runs for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_runs_insert" on public.ai_visibility_runs;
create policy "ai_visibility_runs_insert" on public.ai_visibility_runs for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_runs_update" on public.ai_visibility_runs;
create policy "ai_visibility_runs_update" on public.ai_visibility_runs for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "ai_visibility_scans_select" on public.ai_visibility_scans;
create policy "ai_visibility_scans_select" on public.ai_visibility_scans for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_scans_insert" on public.ai_visibility_scans;
create policy "ai_visibility_scans_insert" on public.ai_visibility_scans for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_visibility_scans_update" on public.ai_visibility_scans;
create policy "ai_visibility_scans_update" on public.ai_visibility_scans for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop policy if exists "ai_territory_events_select" on public.ai_territory_events;
create policy "ai_territory_events_select" on public.ai_territory_events for select to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_territory_events_insert" on public.ai_territory_events;
create policy "ai_territory_events_insert" on public.ai_territory_events for insert to authenticated with check (tenant_id = public.current_tenant_id() and is_deleted = false);
drop policy if exists "ai_territory_events_update" on public.ai_territory_events;
create policy "ai_territory_events_update" on public.ai_territory_events for update to authenticated using (tenant_id = public.current_tenant_id() and is_deleted = false) with check (tenant_id = public.current_tenant_id() and is_deleted = false);

drop trigger if exists client_review_goals_set_updated_at on public.client_review_goals;
create trigger client_review_goals_set_updated_at before update on public.client_review_goals for each row execute function public.set_updated_at();
drop trigger if exists review_events_set_updated_at on public.review_events;
create trigger review_events_set_updated_at before update on public.review_events for each row execute function public.set_updated_at();
drop trigger if exists review_monthly_snapshots_set_updated_at on public.review_monthly_snapshots;
create trigger review_monthly_snapshots_set_updated_at before update on public.review_monthly_snapshots for each row execute function public.set_updated_at();
drop trigger if exists discovery_question_templates_set_updated_at on public.discovery_question_templates;
create trigger discovery_question_templates_set_updated_at before update on public.discovery_question_templates for each row execute function public.set_updated_at();
drop trigger if exists roadmap_plans_set_updated_at on public.roadmap_plans;
create trigger roadmap_plans_set_updated_at before update on public.roadmap_plans for each row execute function public.set_updated_at();
drop trigger if exists content_captures_set_updated_at on public.content_captures;
create trigger content_captures_set_updated_at before update on public.content_captures for each row execute function public.set_updated_at();
drop trigger if exists tickets_set_updated_at on public.tickets;
create trigger tickets_set_updated_at before update on public.tickets for each row execute function public.set_updated_at();
drop trigger if exists qa_scorecards_set_updated_at on public.qa_scorecards;
create trigger qa_scorecards_set_updated_at before update on public.qa_scorecards for each row execute function public.set_updated_at();
drop trigger if exists tenant_files_set_updated_at on public.tenant_files;
create trigger tenant_files_set_updated_at before update on public.tenant_files for each row execute function public.set_updated_at();
drop trigger if exists ai_visibility_configs_set_updated_at on public.ai_visibility_configs;
create trigger ai_visibility_configs_set_updated_at before update on public.ai_visibility_configs for each row execute function public.set_updated_at();
drop trigger if exists ai_visibility_runs_set_updated_at on public.ai_visibility_runs;
create trigger ai_visibility_runs_set_updated_at before update on public.ai_visibility_runs for each row execute function public.set_updated_at();
drop trigger if exists ai_visibility_scans_set_updated_at on public.ai_visibility_scans;
create trigger ai_visibility_scans_set_updated_at before update on public.ai_visibility_scans for each row execute function public.set_updated_at();
drop trigger if exists ai_territory_events_set_updated_at on public.ai_territory_events;
create trigger ai_territory_events_set_updated_at before update on public.ai_territory_events for each row execute function public.set_updated_at();

alter table public.user_profiles replica identity full;
alter table public.tenants replica identity full;
alter table public.tenant_members replica identity full;
alter table public.tenant_settings replica identity full;
alter table public.tenant_domains replica identity full;
alter table public.clients replica identity full;
alter table public.meetings replica identity full;
alter table public.action_items replica identity full;
alter table public.tenant_integrations replica identity full;
alter table public.user_oauth_accounts replica identity full;
alter table public.client_integration_bindings replica identity full;
alter table public.integration_location_bindings replica identity full;
alter table public.clickup_client_sync_state replica identity full;
alter table public.clickup_client_sync_logs replica identity full;
alter table public.client_ownership replica identity full;
alter table public.ownership_sync_runs replica identity full;
alter table public.ownership_sync_exceptions replica identity full;
alter table public.client_review_goals replica identity full;
alter table public.review_events replica identity full;
alter table public.review_monthly_snapshots replica identity full;
alter table public.discovery_question_templates replica identity full;
alter table public.roadmap_plans replica identity full;
alter table public.content_captures replica identity full;
alter table public.tickets replica identity full;
alter table public.qa_scorecards replica identity full;
alter table public.tenant_files replica identity full;
alter table public.ai_visibility_configs replica identity full;
alter table public.ai_visibility_runs replica identity full;
alter table public.ai_visibility_scans replica identity full;
alter table public.ai_territory_events replica identity full;

insert into public.tenant_settings (tenant_id, branding, terminology, workflows, analysis)
select t.id, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
from public.tenants t
where not exists (
  select 1
  from public.tenant_settings ts
  where ts.tenant_id = t.id
    and ts.is_deleted = false
);

-- Optional: create a storage bucket for tenant files manually in Supabase UI
-- or run a separate storage migration once path conventions are finalized.
