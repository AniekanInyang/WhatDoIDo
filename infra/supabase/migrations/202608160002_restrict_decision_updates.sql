-- Enforce the product rule that a user may rename a decision but may not
-- modify its prompt, owner, status, brief, or recommendation.
-- This migration is separate so projects that already ran 0001 are hardened.

revoke all on table public.decisions from authenticated;

grant select, delete on table public.decisions to authenticated;
grant insert (user_id, title, prompt) on table public.decisions to authenticated;
grant update (title) on table public.decisions to authenticated;
