# Supabase database

The migrations in `migrations/` define the application tables, profile trigger,
indexes, grants, and Row Level Security policies.

## Apply the initial migration

For the current hosted project, open **Supabase Dashboard → SQL Editor**, paste
the contents of `migrations/202608160001_initial_schema.sql`, and run it once.

The migration is safe to apply to a project that already has Auth users: it
backfills their `public.profiles` rows. Do not run application queries with the
service-role key in a browser; it bypasses all RLS policies.

## Tables

- `profiles`: one application profile per `auth.users` account
- `decisions`: user-owned decision records and current structured brief
- `decision_options`: options belonging to a decision
- `decision_messages`: conversation messages
- `evaluations`: backend-generated evaluation snapshots

Authenticated clients can only access records owned by `auth.uid()`. Direct
clients may insert user messages but cannot write assistant/system messages or
evaluations; those are reserved for the trusted backend.

For decisions, authenticated clients receive column-level permission to update
`title` only. Status, prompt, ownership, brief, and recommendation remain
immutable through the user-facing API, including after a decision is completed.
