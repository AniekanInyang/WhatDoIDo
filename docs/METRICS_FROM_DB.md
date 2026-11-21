# Metrics You Can Get From the Current DB

This document summarizes what can be measured today from existing tables.

## decisions

1. Decisions created per day/week/month
2. Active decisions vs completed decisions
3. Completion rate
4. Time to completion using `created_at` to `updated_at` for completed records
5. Decision status distribution (`draft`, `exploring`, `evaluating`, `completed`, `archived`)
6. Recommendation coverage (`recommendation` null vs non-null)
7. Per-user decision volume (trusted backend queries)

## decision_messages

1. Total message volume
2. User vs assistant message ratio
3. Messages per decision
4. Conversation length distribution
5. Assistant workflow error frequency from `structured_data.workflow_error`
6. Retry-available frequency from `structured_data.retry_available`
7. Per-turn LLM summary metrics from `structured_data.llm_metrics`:
   - `calls`
   - `cache_hits`
   - `prompt_tokens`
   - `completion_tokens`
   - `total_tokens`
   - `estimated_cost_usd`
   - `stage_count`
8. Stalled decision detection (latest message is user with no assistant follow-up)
9. Message length distribution by role

## decision_state_events

1. Workflow step timeline via `event_type` and `revision`
2. Direction-change frequency
3. Recommendation lifecycle events:
   - `recommendation_upheld`
   - `recommendation_revised`
   - `revision_saved_pending`
4. Failure and recovery events:
   - `workflow_rate_limited`
   - `workflow_budget_exhausted`
   - `question_generation_unavailable`
   - `workflow_failed`
5. Per-turn stage telemetry from `llm_turn_metrics` payload:
   - `stage`
   - `requested_model`
   - `provider_model`
   - `prompt_tokens`
   - `completion_tokens`
   - `total_tokens`
   - `latency_ms`
   - `estimated_cost_usd`
   - `cached`
6. Stage latency metrics (p50/p95) by stage/model
7. Per-turn cost metrics by decision/user/time window
8. Cache effectiveness by stage and overall

## decision_options

1. Options per decision
2. Source mix (`user_provided`, `ai_extracted`, `ai_generated`)
3. Status mix (`candidate`, `confirmed`, `rejected`)
4. Option churn across revisions (via event correlation)
5. Duplicate-option pressure (from state event payloads + writes)
6. Position/order usage patterns

## evaluations

1. Evaluations generated per period
2. Risk-level distribution (`low`, `moderate`, `high`, `unknown`)
3. Frequency of checks/assumptions/sensitivity-analysis artifacts
4. Recommendation robustness proxy from checks payload content
5. Post-evaluation completion conversion (join with `decisions`)

## clarification_events

1. Clarification volume by `action_category`
2. Outcome mix (`answered`, `skipped`, `unresolved`)
3. Skip and unresolved rates by category
4. Reward trend and average reward by category
5. Clarification efficiency per decision (answered per asked)
6. Question phrasing inventory via `selected_question`

## clarification_profiles

1. Profile coverage (how many users have profile state)
2. Aggregate interaction counts from profile payload
3. Category-level learned preference usage from `action_stats`
4. Profile drift/change over time using `updated_at`

## What Is Now Covered vs Not Covered

### Covered now

1. True per-turn token usage
2. Per-turn estimated cost
3. Exact model identifier per call (`requested_model` + `provider_model`)
4. Stage-level latency inside a turn

### Still not covered (without labeled eval process)

1. Ground-truth correctness (requires human-labeled or benchmark rubric)
