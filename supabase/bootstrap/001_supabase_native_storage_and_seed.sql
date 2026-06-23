begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
select
  'tenant-files',
  'tenant-files',
  false,
  52428800,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'image/png',
    'image/jpeg',
    'image/webp'
  ]::text[]
where not exists (
  select 1 from storage.buckets where id = 'tenant-files'
);

drop policy if exists "tenant_files_bucket_select" on storage.objects;
create policy "tenant_files_bucket_select" on storage.objects
for select to authenticated
using (
  bucket_id = 'tenant-files'
  and (storage.foldername(name))[1] = public.current_tenant_id()::text
);

drop policy if exists "tenant_files_bucket_insert" on storage.objects;
create policy "tenant_files_bucket_insert" on storage.objects
for insert to authenticated
with check (
  bucket_id = 'tenant-files'
  and (storage.foldername(name))[1] = public.current_tenant_id()::text
);

drop policy if exists "tenant_files_bucket_update" on storage.objects;
create policy "tenant_files_bucket_update" on storage.objects
for update to authenticated
using (
  bucket_id = 'tenant-files'
  and (storage.foldername(name))[1] = public.current_tenant_id()::text
)
with check (
  bucket_id = 'tenant-files'
  and (storage.foldername(name))[1] = public.current_tenant_id()::text
);

drop policy if exists "tenant_files_bucket_delete" on storage.objects;
create policy "tenant_files_bucket_delete" on storage.objects
for delete to authenticated
using (
  bucket_id = 'tenant-files'
  and (storage.foldername(name))[1] = public.current_tenant_id()::text
);

create or replace function public.bootstrap_new_project(
  p_owner_user_id uuid,
  p_tenant_name text,
  p_tenant_slug text
)
returns table(tenant_id uuid, membership_id uuid)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_tenant_id uuid;
  v_membership_id uuid;
  v_email text;
  v_full_name text;
begin
  if p_owner_user_id is null then
    raise exception 'p_owner_user_id is required';
  end if;

  if coalesce(trim(p_tenant_name), '') = '' then
    raise exception 'p_tenant_name is required';
  end if;

  if coalesce(trim(p_tenant_slug), '') = '' then
    raise exception 'p_tenant_slug is required';
  end if;

  select au.email, coalesce(au.raw_user_meta_data ->> 'name', au.raw_user_meta_data ->> 'full_name', '')
    into v_email, v_full_name
  from auth.users au
  where au.id = p_owner_user_id;

  if v_email is null then
    raise exception 'Auth user % does not exist', p_owner_user_id;
  end if;

  insert into public.user_profiles (id, email, full_name, auth_provider, system_role)
  values (
    p_owner_user_id,
    v_email,
    nullif(v_full_name, ''),
    'email',
    'platform_admin'
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(excluded.full_name, public.user_profiles.full_name),
        system_role = 'platform_admin',
        updated_at = now();

  select t.id
    into v_tenant_id
  from public.tenants t
  where t.slug = p_tenant_slug
    and t.is_deleted = false
  limit 1;

  if v_tenant_id is null then
    insert into public.tenants (slug, name, owner_user_id, created_by, subscription_status)
    values (p_tenant_slug, p_tenant_name, p_owner_user_id, p_owner_user_id, 'active')
    returning id into v_tenant_id;
  end if;

  if not exists (
    select 1 from public.tenant_settings ts
    where ts.tenant_id = v_tenant_id
      and ts.is_deleted = false
  ) then
    insert into public.tenant_settings (tenant_id, created_by)
    values (v_tenant_id, p_owner_user_id);
  end if;

  update public.tenant_members
     set is_default = false,
         updated_at = now()
   where user_id = p_owner_user_id
     and is_default = true
     and is_deleted = false;

  select tm.id
    into v_membership_id
  from public.tenant_members tm
  where tm.tenant_id = v_tenant_id
    and tm.user_id = p_owner_user_id
    and tm.is_deleted = false
  limit 1;

  if v_membership_id is null then
    insert into public.tenant_members (
      tenant_id,
      user_id,
      role,
      status,
      is_default,
      joined_at,
      created_by
    )
    values (
      v_tenant_id,
      p_owner_user_id,
      'tenant_owner',
      'active',
      true,
      now(),
      p_owner_user_id
    )
    returning id into v_membership_id;
  else
    update public.tenant_members
       set role = 'tenant_owner',
           status = 'active',
           is_default = true,
           joined_at = coalesce(joined_at, now()),
           updated_at = now()
     where id = v_membership_id;
  end if;

  update public.tenants
     set owner_user_id = p_owner_user_id,
         status = 'active',
         updated_at = now()
   where id = v_tenant_id;

  return query select v_tenant_id, v_membership_id;
end;
$$;

comment on function public.bootstrap_new_project(uuid, text, text) is
'Creates the first tenant and owner membership for a brand-new Supabase MTOS project.';

commit;
