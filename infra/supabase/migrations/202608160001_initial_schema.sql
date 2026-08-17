-- WhatDoIDo initial application schema.
-- Run this migration in the Supabase SQL editor or with `supabase db push`.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 1 and 100),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.decisions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  prompt text not null check (char_length(prompt) between 1 and 10000),
  status text not null default 'draft'
    check (status in ('draft', 'exploring', 'evaluating', 'completed', 'archived')),
  decision_brief jsonb not null default '{}'::jsonb,
  recommendation jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.decision_options (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.decisions(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  description text,
  position integer not null default 0 check (position >= 0),
  evaluation jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (decision_id, title)
);

create table if not exists public.decision_messages (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.decisions(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null check (char_length(content) between 1 and 50000),
  structured_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.evaluations (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.decisions(id) on delete cascade,
  summary text not null,
  confidence numeric(4, 3) check (confidence between 0 and 1),
  risk_level text check (risk_level in ('low', 'moderate', 'high', 'unknown')),
  reasoning jsonb not null default '[]'::jsonb,
  checks jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists decisions_user_updated_idx
  on public.decisions (user_id, updated_at desc);
create index if not exists decision_options_decision_position_idx
  on public.decision_options (decision_id, position);
create index if not exists decision_messages_decision_created_idx
  on public.decision_messages (decision_id, created_at);
create index if not exists evaluations_decision_created_idx
  on public.evaluations (decision_id, created_at desc);

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists decisions_set_updated_at on public.decisions;
create trigger decisions_set_updated_at
before update on public.decisions
for each row execute function public.set_updated_at();

drop trigger if exists decision_options_set_updated_at on public.decision_options;
create trigger decision_options_set_updated_at
before update on public.decision_options
for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(
      nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
      nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
      'User'
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- Backfill profiles for accounts created before this migration.
insert into public.profiles (id, display_name)
select
  users.id,
  coalesce(
    nullif(trim(users.raw_user_meta_data ->> 'display_name'), ''),
    nullif(split_part(coalesce(users.email, ''), '@', 1), ''),
    'User'
  )
from auth.users as users
on conflict (id) do nothing;

alter table public.profiles enable row level security;
alter table public.decisions enable row level security;
alter table public.decision_options enable row level security;
alter table public.decision_messages enable row level security;
alter table public.evaluations enable row level security;

-- Profiles
create policy "Users can read their own profile"
on public.profiles for select
to authenticated
using ((select auth.uid()) = id);

create policy "Users can create their own profile"
on public.profiles for insert
to authenticated
with check ((select auth.uid()) = id);

create policy "Users can update their own profile"
on public.profiles for update
to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

-- Decisions
create policy "Users can read their own decisions"
on public.decisions for select
to authenticated
using ((select auth.uid()) = user_id);

create policy "Users can create their own decisions"
on public.decisions for insert
to authenticated
with check ((select auth.uid()) = user_id);

create policy "Users can update their own decisions"
on public.decisions for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy "Users can delete their own decisions"
on public.decisions for delete
to authenticated
using ((select auth.uid()) = user_id);

-- Child records inherit ownership from their decision.
create policy "Users can read options for their decisions"
on public.decision_options for select
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = decision_options.decision_id
    and decisions.user_id = (select auth.uid())
));

create policy "Users can create options for their decisions"
on public.decision_options for insert
to authenticated
with check (exists (
  select 1 from public.decisions
  where decisions.id = decision_options.decision_id
    and decisions.user_id = (select auth.uid())
));

create policy "Users can update options for their decisions"
on public.decision_options for update
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = decision_options.decision_id
    and decisions.user_id = (select auth.uid())
))
with check (exists (
  select 1 from public.decisions
  where decisions.id = decision_options.decision_id
    and decisions.user_id = (select auth.uid())
));

create policy "Users can delete options for their decisions"
on public.decision_options for delete
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = decision_options.decision_id
    and decisions.user_id = (select auth.uid())
));

create policy "Users can read messages for their decisions"
on public.decision_messages for select
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = decision_messages.decision_id
    and decisions.user_id = (select auth.uid())
));

-- Direct clients may add user messages only. Assistant/system messages are
-- written by the trusted backend using its server-side credential.
create policy "Users can add messages to their decisions"
on public.decision_messages for insert
to authenticated
with check (
  role = 'user'
  and exists (
    select 1 from public.decisions
    where decisions.id = decision_messages.decision_id
      and decisions.user_id = (select auth.uid())
  )
);

create policy "Users can delete messages from their decisions"
on public.decision_messages for delete
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = decision_messages.decision_id
    and decisions.user_id = (select auth.uid())
));

-- Evaluations are generated by the trusted backend and read by their owner.
create policy "Users can read evaluations for their decisions"
on public.evaluations for select
to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = evaluations.decision_id
    and decisions.user_id = (select auth.uid())
));

revoke all on table public.profiles from anon;
revoke all on table public.decisions from anon;
revoke all on table public.decision_options from anon;
revoke all on table public.decision_messages from anon;
revoke all on table public.evaluations from anon;

revoke all on table public.profiles from authenticated;
revoke all on table public.decisions from authenticated;
revoke all on table public.decision_options from authenticated;
revoke all on table public.decision_messages from authenticated;
revoke all on table public.evaluations from authenticated;

grant select, insert, update on table public.profiles to authenticated;
grant select, delete on table public.decisions to authenticated;
grant insert (user_id, title, prompt) on table public.decisions to authenticated;
grant update (title) on table public.decisions to authenticated;
grant select, insert, update, delete on table public.decision_options to authenticated;
grant select, insert, delete on table public.decision_messages to authenticated;
grant select on table public.evaluations to authenticated;
