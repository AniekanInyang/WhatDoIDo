# Supabase database

The migrations in `migrations/` define the application tables, profile trigger,
indexes, grants, and Row Level Security policies.

## Apply migrations

For the current hosted project, open **Supabase Dashboard → SQL Editor** and run
each file in `migrations/` once, in filename order. Existing projects that have
already run the first three files need to run the three `20260919` migrations
in filename order.

Existing projects that already applied `202609190001_decision_workflow.sql`
must also apply `202609190002_state_review_and_events.sql` and
`202609190003_workflow_idempotency.sql`.

The migrations are safe to apply to a project that already has Auth users: the
initial migration backfills their `public.profiles` rows. Do not run application queries with the
service-role key in a browser; it bypasses all RLS policies.

## Tables

- `profiles`: one application profile per `auth.users` account
- `decisions`: user-owned decision records and current structured brief
- `decision_options`: options belonging to a decision
- `decision_messages`: conversation messages
- `evaluations`: backend-generated evaluation snapshots
- `clarification_profiles`: private per-user policy state
- `clarification_events`: the user's own question/outcome learning history
- `decision_state_events`: user-readable Decision Brief revision and review history
- `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`: backend-only LangGraph state

Authenticated clients can only access records owned by `auth.uid()`. Direct
clients may insert user messages but cannot write assistant/system messages or
evaluations; those are reserved for the trusted backend.

For decisions, authenticated clients receive column-level permission to update
`title` only. Status, prompt, ownership, brief, and recommendation remain
immutable through the user-facing API, including after a decision is completed.
Options are editable while a decision is active and locked after completion.
Policy learning records are readable by their owner for transparency and data
export, but only the trusted backend can write them.
LangGraph checkpoint tables are never exposed through Supabase client roles;
RLS is enabled without browser policies and all `anon`/`authenticated` grants
are revoked.
