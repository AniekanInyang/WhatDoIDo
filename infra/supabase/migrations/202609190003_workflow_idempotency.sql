-- Idempotency keys for retrying a checkpointed workflow after partial
-- persistence without duplicating learning or state-history records.

create unique index if not exists clarification_events_user_message_category_idx
  on public.clarification_events (user_id, message_id, action_category);

create unique index if not exists decision_state_events_revision_type_idx
  on public.decision_state_events (decision_id, revision, event_type);
