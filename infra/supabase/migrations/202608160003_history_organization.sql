-- History organization: collections, search/pagination, and recoverable trash.

alter table public.decisions
add column if not exists deleted_at timestamptz;

create index if not exists decisions_user_active_updated_idx
  on public.decisions (user_id, updated_at desc, id desc)
  where deleted_at is null;

create index if not exists decisions_user_trash_updated_idx
  on public.decisions (user_id, updated_at desc, id desc)
  where deleted_at is not null;

create table if not exists public.collections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 100),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists collections_user_lower_name_idx
  on public.collections (user_id, lower(trim(name)));

create table if not exists public.collection_decisions (
  decision_id uuid primary key references public.decisions(id) on delete cascade,
  collection_id uuid not null references public.collections(id) on delete cascade,
  added_at timestamptz not null default timezone('utc', now())
);

create index if not exists collection_decisions_collection_idx
  on public.collection_decisions (collection_id, added_at desc);

drop trigger if exists collections_set_updated_at on public.collections;
create trigger collections_set_updated_at
before update on public.collections
for each row execute function public.set_updated_at();

alter table public.collections enable row level security;
alter table public.collection_decisions enable row level security;

create policy "Users can read their own collections"
on public.collections for select to authenticated
using ((select auth.uid()) = user_id);

create policy "Users can create their own collections"
on public.collections for insert to authenticated
with check ((select auth.uid()) = user_id);

create policy "Users can rename their own collections"
on public.collections for update to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy "Users can delete their own collections"
on public.collections for delete to authenticated
using ((select auth.uid()) = user_id);

create policy "Users can read collection assignments for their decisions"
on public.collection_decisions for select to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = collection_decisions.decision_id
    and decisions.user_id = (select auth.uid())
));

create policy "Users can organize their own decisions"
on public.collection_decisions for insert to authenticated
with check (
  exists (
    select 1 from public.decisions
    where decisions.id = collection_decisions.decision_id
      and decisions.user_id = (select auth.uid())
  )
  and exists (
    select 1 from public.collections
    where collections.id = collection_decisions.collection_id
      and collections.user_id = (select auth.uid())
  )
);

create policy "Users can move their own decisions"
on public.collection_decisions for update to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = collection_decisions.decision_id
    and decisions.user_id = (select auth.uid())
))
with check (
  exists (
    select 1 from public.decisions
    where decisions.id = collection_decisions.decision_id
      and decisions.user_id = (select auth.uid())
  )
  and exists (
    select 1 from public.collections
    where collections.id = collection_decisions.collection_id
      and collections.user_id = (select auth.uid())
  )
);

create policy "Users can remove their own collection assignments"
on public.collection_decisions for delete to authenticated
using (exists (
  select 1 from public.decisions
  where decisions.id = collection_decisions.decision_id
    and decisions.user_id = (select auth.uid())
));

-- Replace permanent deletion policy: a decision must enter Trash first.
drop policy if exists "Users can delete their own decisions" on public.decisions;
create policy "Users can permanently delete their trashed decisions"
on public.decisions for delete to authenticated
using ((select auth.uid()) = user_id and deleted_at is not null);

revoke all on table public.collections from anon, authenticated;
revoke all on table public.collection_decisions from anon, authenticated;
grant select, insert, update (name), delete on table public.collections to authenticated;
grant select, insert, update (collection_id), delete on table public.collection_decisions to authenticated;

-- Preserve title-only content editing while adding lifecycle permission for Trash.
revoke update on table public.decisions from authenticated;
grant update (title, deleted_at) on table public.decisions to authenticated;

create or replace function public.search_user_decisions(
  p_search text default null,
  p_collection_id uuid default null,
  p_uncategorized boolean default false,
  p_trash boolean default false,
  p_cursor_updated_at timestamptz default null,
  p_cursor_id uuid default null,
  p_limit integer default 21
)
returns table (
  id uuid,
  title text,
  prompt text,
  status text,
  created_at timestamptz,
  updated_at timestamptz,
  deleted_at timestamptz,
  collection_id uuid,
  collection_name text
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    d.id,
    d.title,
    d.prompt,
    d.status,
    d.created_at,
    d.updated_at,
    d.deleted_at,
    c.id,
    c.name
  from public.decisions as d
  left join public.collection_decisions as cd on cd.decision_id = d.id
  left join public.collections as c on c.id = cd.collection_id
  where d.user_id = (select auth.uid())
    and case when p_trash then d.deleted_at is not null else d.deleted_at is null end
    and (
      nullif(trim(p_search), '') is null
      or d.title ilike '%' || trim(p_search) || '%'
      or d.prompt ilike '%' || trim(p_search) || '%'
    )
    and (p_collection_id is null or cd.collection_id = p_collection_id)
    and (not p_uncategorized or cd.decision_id is null)
    and (
      p_cursor_updated_at is null
      or (d.updated_at, d.id) < (p_cursor_updated_at, p_cursor_id)
    )
  order by d.updated_at desc, d.id desc
  limit greatest(1, least(p_limit, 51));
$$;

revoke all on function public.search_user_decisions(text, uuid, boolean, boolean, timestamptz, uuid, integer) from public, anon;
grant execute on function public.search_user_decisions(text, uuid, boolean, boolean, timestamptz, uuid, integer) to authenticated;
