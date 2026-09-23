# Decision Workflow Evaluation Plan

## Baselines

1. Generic conversation without structured state.
2. Structured state with the non-personalized heuristic.
3. Structured state with a private per-user clarification profile.
4. A future private per-user contextual-bandit ranker.

## State metrics

- Fact and option extraction precision/recall
- Unsupported-inference and contradiction rates
- Duplicate-option detection precision/recall
- Evidence/provenance coverage
- User correction and rejection rates

## Clarification metrics

- Question answer, skip, and repetition rates
- High-impact uncertainty reduction
- Turns to readiness
- Questions asked after readiness
- User effort and satisfaction
- Safety violations by decision domain

## Recommendation metrics

- Hard-constraint compliance
- Alignment with confirmed values
- Robustness under plausible weight changes
- Unsupported claims
- User-reported confidence and later regret
- Selected-option ID validity
- Sensitivity-driver plausibility and flip accuracy
- Robustness-label agreement with human reviewers

Offline evaluation must show that a learned policy is at least as safe and
complete as the heuristic before deployment. Per-user profiles must never be
pooled into a cross-user training dataset. Account export and deletion include
the profile and event history.
