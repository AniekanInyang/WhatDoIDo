-- Permit client-chosen UUIDs for idempotent decision creation.
-- Existing row-level policies still require user_id = auth.uid().
grant insert (id) on table public.decisions to authenticated;
