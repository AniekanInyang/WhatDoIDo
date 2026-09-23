# Decision State and Clarification Workflow

WhatDoIDo uses a POMDP-inspired belief state. It does not claim that model
confidence values are calibrated probabilities or that the initial policy is a
fully solved POMDP.

## Sources of truth

- `decision_messages` is the canonical conversation and evidence record.
- `decisions.decision_brief` is the current materialized understanding.
- `decision_options` is the canonical option store; the brief contains IDs.
- `clarification_profiles` contains one user's private learned policy profile.
- `clarification_events` contains that user's action/outcome history.
- `decision_state_events` is the append-only revision and review trail.
- LangGraph Postgres checkpoint tables preserve the exact completed node and
  pending task for interrupted execution.

No user's clarification events or profile are used to select questions for a
different user. RLS permits users to read only their own learning data; only the
trusted backend writes rewards and profile updates.

## State

The brief tracks a version and revision, phase, goal, domain, deadline, values,
constraints, uncertainties, explicit criteria and importance, risk tolerance,
preference signals, assumptions, contradictions, formal risks, superseded
states, option IDs, missing information, readiness, and the next action. Facts
include status, source, qualitative confidence, and evidence message IDs.
Qualitative confidence is intentionally not presented as a calibrated
probability.

## Turn lifecycle

1. Save the user's message.
2. Score the response to the preceding clarification, if one exists.
3. Extract a validated state patch and candidate options.
4. Merge facts without replacing the entire state.
5. Detect direction changes, contradictions, duplicate options, and assumptions.
6. Calculate deterministic readiness and information gaps.
7. Rank safe clarification actions with the user's own policy profile.
8. Save the state, action event, and assistant message.

The initial question policy is transparent:

`utility = decision impact + bounded per-user response adjustment`

This can later become a per-user contextual bandit, after enough observations
exist for that user. Deterministic safety and readiness rules remain in force.

## Options

Options can be user-provided, extracted from user text, or AI-generated. They
have stable IDs, editable titles/descriptions, provenance, status, ordering, and
metadata. Similar titles are detected before insertion. The application never
silently merges or deletes ambiguous duplicates. Options cannot change after a
decision is completed.

## Recommendation and completion

Readiness requires a goal, at least two options, at least one value, explicit
criteria, and at least one constraint. Unresolved contradictions and unconfirmed
high-importance assumptions block evaluation. Uncertainties and risk tolerance
are requested but do not independently block evaluation. Once ready, the system
asks the user to add or correct anything.
Only an explicit signal such as “recommend,” “go ahead,” or “nothing else” runs
the recommendation node.

The recommendation generator receives only the validated brief and persisted
options. Its structured output must select a real option ID and is rejected if
it does not. The saved result contains comparisons, assumptions, unresolved
uncertainties, qualitative robustness, and concrete sensitivity drivers showing
what plausible change could alter the winner. Numeric model confidence is not
stored because it is not calibrated. A successful result creates an immutable
evaluation snapshot and completes the decision.

## Recovery and failure behavior

Provider nodes use exponential backoff with three attempts. The official
LangGraph Postgres checkpointer stores progress after graph supersteps under a
thread ID composed of `user_id:decision_id`. If execution still fails, the UI
offers Retry workflow; retry invokes the saved pending task without replaying
successful nodes. Checkpoint tables have RLS enabled and all Supabase browser
role grants revoked. Account deletion removes that user's checkpoint rows.

## Direction changes and unclear input

Greetings and unrelated or incoherent input are routed to a prompt asking for a
specific decision rather than being stored as the goal. An explicit replacement
of the central decision creates a bounded superseded-state snapshot, rejects the
old decision's options, and starts clarification for the new goal. Conflicting
scalar answers create a reviewable contradiction instead of silently choosing
one; users can resolve these in conversation or in the Decision Brief.
