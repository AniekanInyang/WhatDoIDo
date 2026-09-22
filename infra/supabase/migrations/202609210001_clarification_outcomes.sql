-- Distinguish a genuine answer from a response that did not resolve the
-- clarification target. This keeps per-user policy rewards evidence-based.

alter table public.clarification_events
  drop constraint if exists clarification_events_outcome_check;

alter table public.clarification_events
  add constraint clarification_events_outcome_check
  check (outcome in ('answered', 'skipped', 'unresolved'));
