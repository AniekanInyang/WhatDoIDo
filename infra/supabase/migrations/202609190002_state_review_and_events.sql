-- Reviewable Decision Brief history. LangGraph's internal checkpoint tables are
-- created by its official Postgres checkpointer and are not exposed to clients.

create table if not exists public.decision_state_events (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.decisions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  revision integer not null check (revision >= 0),
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists decision_state_events_decision_revision_idx
  on public.decision_state_events (decision_id, revision desc, created_at desc);
create index if not exists decision_state_events_user_created_idx
  on public.decision_state_events (user_id, created_at desc);

alter table public.decision_state_events enable row level security;

create policy "Users can read their own decision state events"
on public.decision_state_events for select to authenticated
using (
  user_id = (select auth.uid())
  and exists (
    select 1 from public.decisions
    where decisions.id = decision_state_events.decision_id
      and decisions.user_id = (select auth.uid())
  )
);

revoke all on table public.decision_state_events from anon, authenticated;
grant select on table public.decision_state_events to authenticated;

-- If the LangGraph checkpointer has already initialized its internal tables,
-- remove Supabase client-role defaults. Runtime initialization repeats this
-- hardening for deployments where the tables are created after this migration.
do $$
declare
  checkpoint_table text;
begin
  foreach checkpoint_table in array array[
    'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations'
  ] loop
    if to_regclass('public.' || checkpoint_table) is not null then
      execute format('alter table public.%I enable row level security', checkpoint_table);
      execute format('revoke all on table public.%I from anon, authenticated', checkpoint_table);
    end if;
  end loop;
end;
$$;
