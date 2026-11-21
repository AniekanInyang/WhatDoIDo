# Conversation evaluation inputs and runner

The runner is in experiments/user_sim_eval_runner.py. Run from the repository root
using .venv/bin/python. Backend credentials and simulator configuration come from
apps/backend/.env; never copy those secrets into run artifacts.

Generate 25 new validated inputs per suite (no backend conversations):

    .venv/bin/python evals/experiments/user_sim_eval_runner.py --generate-only --input-count 25

Run exactly one deterministic input from an existing generated file:

    .venv/bin/python evals/experiments/user_sim_eval_runner.py --run --suite deterministic --input-path <generated-file> --max-cases 1

For stochastic execution, use --suite stochastic and its matching input file.
The deterministic simulator uses only fixed first-person user replies; the
stochastic simulator receives the complete profile and conversation. Neither has
a recommendation deadline or automatically reveals all hidden facts. These user-simulator replies
are distinct from the removed assistant decision-content fallbacks.

Each invocation creates test_set/<date>/<unique-run-id> and refuses overwrites.
Use --date to set the user's local date explicitly. Generation uses an actual
bucket/difficulty schedule and validates the alternatives, hidden facts, reply
rules. Partial generation is saved with a .partial.jsonl suffix.

Outcome semantics:

- completed: a saved recommendation references an active saved option, includes
  its title, summary and rationale, and no unresolved latest workflow error exists.
- incomplete: an explicitly configured safety turn cap or runtime budget was reached without a recommendation.
- failed: workflow, transport, authentication, simulator or persistence failure.

Exports include the input, raw messages with structured metadata, state snapshots,
recommendation, state events, stage traces, request records, recovery attempts,
and explicit termination reason. Successful HTTP status is not conversation success.
A recovered operational message remains in snapshots even if the backend removes
it from the final display transcript.

GET requests have bounded transient retries. POST requests are never blindly
retried. New decisions and messages use client-generated UUID primary keys; replay
with the same ID returns the saved record or a conflict if pending/different.
After ambiguous write failure the runner polls the original ID, so it cannot
silently duplicate a turn. Retryable workflow failures use /workflow/retry, with
one retry per case by default. It does not send another user message to recover.
Default read timeout is 180s and conversation deadline 900s; both are configurable.

Run unit checks:

    PYTHONPATH=apps/backend .venv/bin/python -m pytest apps/backend/tests evals/tests -q

Input generation can resume validated partial files with --resume-generation and
the same --date / --run-id. It cannot resume or overwrite a live-run directory.
The two suites generate independently, with progress retained per suite. An
unavailable authentication service produces outputs/preflight.json with zero
attempted cases and zero created decisions, rather than a misleading case result.

For the November 9 investigation, see test_set/2026-11-09/diagnostics/FINDINGS.md.

There is no default turn cap. --max-turns is an optional resource guard, not a
recommendation target. The simulator is not told about resource limits. The
backend follows its normal user-facing policy; this runner does not override it.
