from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.state import (
    ActionPlan,
    Assumption,
    ClarificationProfile,
    Contradiction,
    Criterion,
    DecisionBrief,
    DecisionRisk,
    Fact,
    GraphState,
    InformationGap,
    RecommendationResult,
    Readiness,
)
from app.llm.decision_assistant import (
    extract_decision_patch,
    generate_clarification_question,
    generate_grounded_recommendation,
)


class RecommendationGenerationError(RuntimeError):
    pass


def _normalized(value: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())


def _same_option(left: str, right: str) -> bool:
    a, b = _normalized(left), _normalized(right)
    if not a or not b:
        return False
    if a == b or SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True
    a_words, b_words = set(a.split()), set(b.split())
    shorter = a_words if len(a_words) <= len(b_words) else b_words
    longer = b_words if shorter is a_words else a_words
    # Resolve concise selections such as "educational" back to an existing
    # "Educational tutorial" option, without treating generic short words as
    # equivalent options.
    return shorter < longer and shorter.issubset(longer) and all(len(word) >= 5 for word in shorter)


def _prepare_fact(fact: Fact) -> Fact:
    if fact.source in ("explicit", "confirmed"):
        fact.status = "confirmed"
    elif fact.status == "confirmed":
        fact.status = "candidate"
    return fact


def _merge_facts(current: list[Fact], incoming: list[Fact]) -> list[Fact]:
    merged = list(current)
    known = {_normalized(str(fact.value)): fact for fact in current if fact.status != "rejected"}
    for raw in incoming:
        fact = _prepare_fact(raw)
        key = _normalized(str(fact.value))
        if key and key not in known:
            merged.append(fact)
            known[key] = fact
    return merged


def _merge_named(current: list[Any], incoming: list[Any], attribute: str) -> list[Any]:
    merged = list(current)
    known = {_normalized(str(getattr(item, attribute))): item for item in current}
    for item in incoming:
        key = _normalized(str(getattr(item, attribute)))
        if key in known:
            existing = known[key]
            for field in item.model_fields_set:
                if field not in {"id"}:
                    setattr(existing, field, getattr(item, field))
        else:
            merged.append(item)
            known[key] = item
    return merged


def _active(items: list[Any]) -> list[Any]:
    return [item for item in items if getattr(item, "status", "confirmed") not in ("rejected", "superseded")]


def _gaps(brief: DecisionBrief, option_count: int) -> list[InformationGap]:
    gaps: list[InformationGap] = []
    if not brief.goal:
        gaps.append(InformationGap(key="goal", question_category="goal", impact=1, reason="The decision is not yet clear."))
    if option_count < 2:
        gaps.append(InformationGap(key="options", question_category="options", impact=.95, reason="A comparison needs at least two distinct choices."))
    if not _active(brief.values):
        gaps.append(InformationGap(key="values", question_category="values", impact=.9, reason="The recommendation must reflect what matters to the user."))
    if brief.decision_stakes == "low":
        return gaps
    if not _active(brief.criteria):
        gaps.append(InformationGap(key="criteria", question_category="criteria", impact=.86, reason="The options need explicit comparison criteria."))
    if not _active(brief.constraints) and "constraints" not in brief.resolved_absences:
        gaps.append(InformationGap(key="constraints", question_category="constraints", impact=.8, reason="Hard limits can rule out otherwise attractive choices."))
    if brief.decision_stakes != "high":
        return gaps
    if not _active(brief.uncertainties) and "uncertainties" not in brief.resolved_absences:
        gaps.append(InformationGap(key="uncertainties", question_category="uncertainties", impact=.55, reason="Unknowns can change the outcome."))
    if (
        (not brief.risk_tolerance or brief.risk_tolerance.status == "rejected")
        and "risk_tolerance" not in brief.resolved_absences
    ):
        gaps.append(InformationGap(key="risk_tolerance", question_category="risk", impact=.5, reason="Risk tolerance affects how trade-offs should be judged."))
    return gaps


def _personalized_utility(gap: InformationGap, profile: ClarificationProfile) -> float:
    stats = profile.action_stats.get(gap.question_category)
    personal_adjustment = 0.0 if not stats or not stats.asked else max(-.2, min(.2, stats.average_reward * .2))
    return round(gap.impact + personal_adjustment, 3)


def _clarification_limit(brief: DecisionBrief, configured_maximum: int) -> int:
    stakes_limit = {"low": 3, "medium": 5, "high": 8}.get(brief.decision_stakes, 5)
    return max(1, min(configured_maximum, stakes_limit))


def _clarification_count(brief: DecisionBrief) -> int:
    return sum(
        1 for item in brief.question_history
        if item.get("action") in {
            "clarify_decision", "ask_clarification", "confirm_inference", "resolve_contradiction",
        }
    )


def _requests_recommendation(message: str) -> bool:
    normalized = _normalized(message)
    direct_phrases = (
        "recommend", "give me your recommendation", "what should i choose",
        "which should i choose", "which should i", "which one", "go ahead", "evaluate them", "nothing else",
        "nothing to add", "i am ready", "im ready", "you tell me",
    )
    return any(phrase in normalized for phrase in direct_phrases)


def _signals_repeated_question(message: str) -> bool:
    normalized = _normalized(message)
    return any(phrase in normalized for phrase in (
        "i already answered", "already told you", "i just answered",
        "you asked me that", "same question", "stop repeating",
    ))


def _snapshot_for_supersession(brief: DecisionBrief) -> dict[str, Any]:
    return {
        "revision": brief.revision,
        "goal": brief.goal.model_dump(mode="json") if brief.goal else None,
        "domain": brief.domain.model_dump(mode="json") if brief.domain else None,
        "values": [item.model_dump(mode="json") for item in brief.values],
        "constraints": [item.model_dump(mode="json") for item in brief.constraints],
        "criteria": [item.model_dump(mode="json") for item in brief.criteria],
        "option_ids": brief.option_ids,
    }


def build_decision_graph(settings: Settings, *, checkpointer=None):
    async def extract(state: GraphState) -> dict[str, Any]:
        patch = await extract_decision_patch(
            state["user_message"], state["message_id"], state.get("brief", {}), settings
        )
        patch_data = patch.model_dump(mode="json")
        brief = DecisionBrief.model_validate(state.get("brief") or {})
        normalized_reply = _normalized(state["user_message"])
        if brief.next_action and brief.next_action.action == "confirm_inference":
            pending = next((item for item in brief.assumptions if item.status == "candidate" and item.importance == "high"), None)
            if pending and normalized_reply in {"yes", "correct", "thats correct", "that is correct"}:
                patch_data["assumption_resolution"] = {"id": pending.id, "status": "confirmed"}
            elif pending and normalized_reply in {"no", "incorrect", "thats wrong", "that is wrong"}:
                patch_data["assumption_resolution"] = {"id": pending.id, "status": "rejected"}
        if brief.next_action and brief.next_action.action == "resolve_contradiction":
            pending_contradiction = next((item for item in brief.contradictions if item.status == "unresolved"), None)
            if pending_contradiction:
                if any(word in normalized_reply for word in ("latest", "new", "second")):
                    patch_data["contradiction_resolution"] = {"id": pending_contradiction.id, "choice": "new"}
                elif any(word in normalized_reply for word in ("earlier", "previous", "first")):
                    patch_data["contradiction_resolution"] = {"id": pending_contradiction.id, "choice": "previous"}
        return {
            "patch": patch_data,
            "is_decision_input": patch.is_decision_input,
        }

    def update_state(state: GraphState) -> dict[str, Any]:
        brief = DecisionBrief.model_validate(state.get("brief") or {})
        patch = state["patch"]
        if not patch.get("is_decision_input", True):
            return {
                "brief": brief.model_dump(mode="json"),
                "new_options": [],
                "duplicate_options": [],
                "direction_changed": False,
            }

        direction_changed = bool(patch.get("direction_change")) and brief.goal is not None
        if direction_changed:
            history = [*brief.superseded_states, _snapshot_for_supersession(brief)][-10:]
            brief = DecisionBrief(superseded_states=history, revision=brief.revision)

        incoming_stakes = patch.get("decision_stakes")
        if incoming_stakes:
            stakes_order = {"low": 0, "medium": 1, "high": 2}
            if (
                direction_changed
                or brief.decision_stakes is None
                or stakes_order[incoming_stakes] > stakes_order[brief.decision_stakes]
            ):
                brief.decision_stakes = incoming_stakes
        brief.resolved_absences = list(dict.fromkeys([
            *brief.resolved_absences,
            *patch.get("resolved_absences", []),
        ]))

        contradictions = list(brief.contradictions)
        for scalar in ("goal", "domain", "deadline", "risk_tolerance"):
            value = patch.get(scalar)
            if not value:
                continue
            incoming = _prepare_fact(Fact.model_validate(value))
            current = getattr(brief, scalar)
            # A detail supplied during clarification must not silently replace the
            # user's central decision. Goal replacement requires an explicit
            # direction-change signal from extraction.
            if scalar == "goal" and current and not direction_changed:
                continue
            if current and _normalized(str(current.value)) != _normalized(str(incoming.value)):
                contradictions.append(Contradiction(
                    topic=scalar,
                    previous_value=str(current.value),
                    new_value=str(incoming.value),
                    evidence_message_ids=list(dict.fromkeys([*current.evidence_message_ids, *incoming.evidence_message_ids])),
                ))
                current.status = "superseded"
            setattr(brief, scalar, incoming)

        for collection in ("values", "constraints", "uncertainties", "preference_signals"):
            incoming = [Fact.model_validate(item) for item in patch.get(collection, [])]
            setattr(brief, collection, _merge_facts(getattr(brief, collection), incoming))
        brief.criteria = _merge_named(
            brief.criteria,
            [Criterion.model_validate(item) for item in patch.get("criteria", [])],
            "name",
        )
        brief.assumptions = _merge_named(
            brief.assumptions,
            [Assumption.model_validate(item) for item in patch.get("assumptions", [])],
            "statement",
        )
        brief.risks = _merge_named(
            brief.risks,
            [DecisionRisk.model_validate(item) for item in patch.get("risks", [])],
            "title",
        )
        brief.contradictions = contradictions
        assumption_resolution = patch.get("assumption_resolution")
        if assumption_resolution:
            for assumption in brief.assumptions:
                if assumption.id == assumption_resolution["id"]:
                    assumption.status = assumption_resolution["status"]
                    assumption.confidence = "high"
        contradiction_resolution = patch.get("contradiction_resolution")
        if contradiction_resolution:
            for contradiction in brief.contradictions:
                if contradiction.id == contradiction_resolution["id"]:
                    selected = contradiction.new_value if contradiction_resolution["choice"] == "new" else contradiction.previous_value
                    current = getattr(brief, contradiction.topic, None)
                    if current:
                        current.value = selected
                        current.source = "confirmed"
                        current.confidence = "high"
                        current.status = "confirmed"
                    contradiction.status = "resolved"
                    contradiction.resolution = selected

        existing = [] if direction_changed else [option for option in state.get("existing_options", []) if option.get("status") != "rejected"]
        accepted: list[dict[str, Any]] = []
        duplicates: list[dict[str, str]] = []
        all_titles = [str(option["title"]) for option in existing]
        observed_goal = str((patch.get("goal") or {}).get("value") or "")
        for candidate in patch.get("options", []):
            if candidate.get("kind", "alternative") != "alternative":
                context_fact = Fact(
                    value=candidate["title"], source="explicit", confidence="high",
                    status="confirmed", evidence_message_ids=[state.get("message_id", "")],
                )
                brief.preference_signals = _merge_facts(brief.preference_signals, [context_fact])
                continue
            if (
                (brief.goal and _same_option(candidate["title"], str(brief.goal.value)))
                or (observed_goal and _same_option(candidate["title"], observed_goal))
            ):
                # A refined goal is context for the choice, not one of the
                # mutually selectable alternatives.
                continue
            duplicate = next((title for title in all_titles if _same_option(candidate["title"], title)), None)
            if duplicate:
                duplicates.append({"candidate": candidate["title"], "existing": duplicate})
                if candidate.get("source") == "user_provided":
                    selection = Fact(
                        value=f"Selected option: {duplicate}", source="explicit",
                        confidence="high", status="confirmed",
                        evidence_message_ids=[state.get("message_id", "")],
                    )
                    brief.preference_signals = _merge_facts(brief.preference_signals, [selection])
            else:
                accepted.append(candidate)
                all_titles.append(candidate["title"])

        option_count = len(existing) + len(accepted)
        gaps = _gaps(brief, option_count)
        constraints_resolved = bool(_active(brief.constraints)) or "constraints" in brief.resolved_absences
        uncertainty_resolved = bool(_active(brief.uncertainties)) or "uncertainties" in brief.resolved_absences
        risk_resolved = (
            bool(brief.risk_tolerance and brief.risk_tolerance.status != "rejected")
            or "risk_tolerance" in brief.resolved_absences
        )
        core_coverage = [
            brief.goal is not None,
            option_count >= 2,
            bool(_active(brief.values)),
            bool(_active(brief.criteria)),
        ]
        if brief.decision_stakes in {None, "medium", "high"}:
            core_coverage.append(constraints_resolved)
        if brief.decision_stakes == "high":
            core_coverage.extend([uncertainty_resolved, risk_resolved])
        unresolved_contradictions = [item for item in brief.contradictions if item.status == "unresolved"]
        important_assumptions = [item for item in brief.assumptions if item.status == "candidate" and item.importance == "high"]
        coverage = sum(core_coverage)
        enough = coverage == len(core_coverage) and not unresolved_contradictions and not important_assumptions
        blockers = [gap.reason for gap in gaps if gap.impact >= .8]
        blockers.extend(f"Resolve changed answer: {item.topic}" for item in unresolved_contradictions)
        blockers.extend(f"Confirm assumption: {item.statement}" for item in important_assumptions)
        brief.readiness = Readiness(score=round(coverage / len(core_coverage), 2), enough_to_recommend=enough, blockers=blockers)
        brief.revision += 1
        brief.phase = "evaluating" if enough else "clarifying"
        brief.missing_information = gaps
        return {
            "brief": brief.model_dump(mode="json"),
            "new_options": accepted,
            "duplicate_options": duplicates,
            "direction_changed": direction_changed,
        }

    def choose_action(state: GraphState) -> dict[str, Any]:
        """Policy node: select what to learn next, never how to phrase it."""
        brief = DecisionBrief.model_validate(state["brief"])
        profile = ClarificationProfile.model_validate(state.get("profile") or {})
        if not state.get("is_decision_input", True) and not brief.goal:
            action = ActionPlan(
                action="clarify_decision", category="decision", target_field="goal",
                expected_answer_type="decision_statement",
                rationale=state.get("patch", {}).get("non_decision_reason") or "The message did not describe a decision.", utility=1,
            )
        else:
            unresolved = next((item for item in brief.contradictions if item.status == "unresolved"), None)
            assumption = next((item for item in brief.assumptions if item.status == "candidate" and item.importance == "high"), None)
            active_option_count = len([
                option for option in state.get("existing_options", [])
                if option.get("status") != "rejected"
            ])
            if _requests_recommendation(state["user_message"]) and active_option_count >= 2:
                action = ActionPlan(
                    action="recommend", category="recommendation",
                    rationale="The user explicitly requested an immediate recommendation; unresolved details must be disclosed as caveats.",
                    utility=1,
                )
            elif _signals_repeated_question(state["user_message"]) and active_option_count >= 2:
                action = ActionPlan(
                    action="recommend", category="recommendation",
                    rationale="The user reported a repeated question; stop interviewing and proceed using the saved information with caveats.",
                    utility=1,
                )
            elif unresolved:
                action = ActionPlan(
                    action="resolve_contradiction", category="contradiction",
                    target_field=unresolved.topic, expected_answer_type="choose_previous_or_new",
                    rationale=f"Resolve the conflict between “{unresolved.previous_value}” and “{unresolved.new_value}” for {unresolved.topic}.", utility=1,
                )
            elif assumption:
                action = ActionPlan(
                    action="confirm_inference", category="assumption",
                    target_field="assumptions", expected_answer_type="yes_no_with_correction",
                    rationale=f"Confirm or reject this important assumption: {assumption.statement}", utility=.98,
                )
            elif (
                brief.next_action is not None
                and brief.next_action.action == "evaluate"
                and _normalized(state["user_message"]) in {"yes", "go ahead"}
                and active_option_count >= 2
            ):
                action = ActionPlan(
                    action="recommend", category="recommendation",
                    rationale="The user confirmed they want the offered evaluation; disclose any missing information as caveats.",
                    utility=1,
                )
            elif brief.readiness.enough_to_recommend:
                action = ActionPlan(
                    action="evaluate", category="evaluation", target_field="recommendation_consent",
                    expected_answer_type="recommend_or_correct",
                    rationale="The core goal, options, criteria, values, and constraints are present.", utility=1,
                )
            elif (
                _clarification_count(brief)
                >= _clarification_limit(brief, settings.decision_max_clarification_turns)
                and len([
                    option for option in state.get("existing_options", [])
                    if option.get("status") != "rejected"
                ]) >= 2
            ):
                action = ActionPlan(
                    action="evaluate", category="evaluation", target_field="recommendation_consent",
                    expected_answer_type="recommend_or_correct",
                    rationale="The clarification-turn budget is exhausted; offer an appropriately caveated evaluation.",
                    utility=1,
                )
            else:
                ranked = sorted(
                    ((_personalized_utility(gap, profile), gap) for gap in brief.missing_information),
                    key=lambda item: item[0], reverse=True,
                )
                utility, gap = ranked[0]
                previous_action = brief.next_action
                repeated_category = (
                    previous_action is not None
                    and previous_action.action == "ask_clarification"
                    and previous_action.category == gap.question_category
                )
                known_values = [str(item.value) for item in _active(brief.values)]
                criteria_weighting = gap.question_category == "criteria" and bool(known_values)
                action = ActionPlan(
                    action="ask_clarification", category=gap.question_category,
                    target_field="criterion_importance" if criteria_weighting else gap.key,
                    expected_answer_type={
                        "options": "list_of_options", "criteria": "factors_with_importance",
                        "risk": "risk_tolerance", "values": "short_priority",
                    }.get(gap.question_category, "short_text") if not criteria_weighting else "importance_for_known_values",
                    rationale=(
                        f"{gap.reason} The previous attempt did not resolve this target; reframe it without repeating the question."
                        if repeated_category else gap.reason
                    ) if not criteria_weighting else (
                        f"The user already named these decision factors: {', '.join(known_values)}. "
                        "Ask only how important they are; do not ask for the factors again."
                    ),
                    utility=utility,
                    attempt=(previous_action.attempt + 1 if repeated_category else 1),
                )
        return {
            "brief": brief.model_dump(mode="json"),
            "selected_action": action.model_dump(mode="json"),
            "question_request": {
                "target_field": action.target_field or action.category,
                "expected_answer_type": action.expected_answer_type,
                "attempt": action.attempt,
            },
        }

    async def formulate_question(state: GraphState) -> dict[str, Any]:
        """Language node: phrase the policy's semantic target contextually."""
        brief = DecisionBrief.model_validate(state["brief"])
        action = ActionPlan.model_validate(state["selected_action"])
        brief_payload = brief.model_dump(mode="json")
        draft = await generate_clarification_question(
            action, brief_payload, state.get("existing_options", []),
            state["user_message"], settings,
        )
        brief.llm_usage = brief.llm_usage.model_validate(brief_payload.get("llm_usage") or {})
        brief.llm_cache = brief_payload.get("llm_cache") or {}
        action.question = draft.question
        existing_titles = {
            _normalized(str(option.get("title", "")))
            for option in [*state.get("existing_options", []), *state.get("new_options", [])]
            if option.get("status") != "rejected"
        }
        suggested_options: list[dict[str, Any]] = []
        if action.category == "options":
            for option in draft.suggested_options:
                title_key = _normalized(option.title)
                if title_key and title_key not in existing_titles:
                    option.source = "ai_generated"
                    option.kind = "alternative"
                    suggested_options.append(option.model_dump(mode="json"))
                    existing_titles.add(title_key)
        history = [*brief.question_history, {
            "question": draft.question,
            "target_field": draft.target_field,
            "action": action.action,
            "attempt": action.attempt,
            "message_id": state.get("message_id"),
            "suggested_options": [item["title"] for item in suggested_options],
        }][-25:]
        brief.question_history = history
        brief.next_action = action
        return {
            "brief": brief.model_dump(mode="json"),
            "assistant_reply": draft.question,
            "selected_action": action.model_dump(mode="json"),
            "new_options": [*state.get("new_options", []), *suggested_options],
        }

    async def evaluate_options(state: GraphState) -> dict[str, Any]:
        """Decision engine: compare persisted options against the typed brief."""
        options = [option for option in state.get("existing_options", []) if option.get("status") != "rejected"]
        result = await generate_grounded_recommendation(state["brief"], options, settings)
        if not result:
            raise RecommendationGenerationError("The provider returned no valid grounded recommendation")
        return {"recommendation": result.model_dump(mode="json"), "brief": state["brief"]}

    def critique_recommendation(state: GraphState) -> dict[str, Any]:
        """Stress-test grounding before any recommendation reaches the user."""
        result = state.get("recommendation") or {}

        def add_caveat(warning: str) -> None:
            current = str(result.get("caveat") or "").strip()
            if warning not in current:
                result["caveat"] = f"{current} {warning}".strip()

        options = {
            str(option["id"]): option for option in state.get("existing_options", [])
            if option.get("status") != "rejected"
        }
        selected_id = str(result.get("selected_option_id") or "")
        if selected_id not in options:
            raise RecommendationGenerationError("The recommendation selected an unknown option")
        result["selected_option_title"] = str(options[selected_id]["title"])
        result["option_assessments"] = [
            assessment for assessment in result.get("option_assessments", [])
            if str(assessment.get("option_id")) in options
        ]
        for driver in result.get("sensitivity_analysis", []):
            if driver.get("likely_winner_option_id") not in options:
                driver["likely_winner_option_id"] = None
        brief = DecisionBrief.model_validate(state["brief"])
        active_preferences = [str(item.value) for item in _active(brief.preference_signals)]
        has_option_specific_evidence = any(
            any(_normalized(str(option["title"])) in _normalized(preference) for option in options.values())
            for preference in active_preferences
        )
        if not has_option_specific_evidence:
            evidence_warning = (
                "The information gathered does not establish that one option will perform better than the others. "
                "Treat this as a conditional recommendation, not a factual comparison."
            )
            add_caveat(evidence_warning)
            result["robustness"] = "low"
        if not brief.readiness.enough_to_recommend:
            unresolved = brief.readiness.blockers or [
                gap.reason for gap in brief.missing_information
            ]
            warning = (
                "This recommendation was made before every useful detail was resolved. "
                + ("Remaining uncertainty: " + "; ".join(unresolved[:3]) if unresolved else "Treat it as provisional.")
            )
            add_caveat(warning)
            result["robustness"] = "low"
        if len(result["option_assessments"]) < len(options):
            warning = "Some options lack a complete assessment; review the comparison before acting."
            add_caveat(warning)
            result["robustness"] = "low"
        return {"recommendation": result}

    def write_recommendation(state: GraphState) -> dict[str, Any]:
        """Presentation node: explain the validated result without re-evaluating it."""
        result = RecommendationResult.model_validate(state["recommendation"])
        brief = DecisionBrief.model_validate(state["brief"])
        brief.phase = "recommended"
        summary = result.summary.strip()
        redundant_prefixes = (
            f"the {result.selected_option_title} option is recommended",
            f"{result.selected_option_title} is recommended",
            f"my recommendation is {result.selected_option_title}",
        )
        lowered = summary.lower().lstrip("'\"’‘")
        for prefix in redundant_prefixes:
            if lowered.startswith(prefix.lower()):
                sentence_end = summary.find(".")
                summary = summary[sentence_end + 1:].strip() if sentence_end >= 0 else ""
                break
        reply = f"My recommendation is {result.selected_option_title}."
        if summary:
            reply += f" {summary}"
        if result.caveat:
            reply += f"\n\nImportant caveat: {result.caveat}"
        return {"brief": brief.model_dump(mode="json"), "recommendation": result.model_dump(mode="json"), "assistant_reply": reply}

    def route_after_action(state: GraphState) -> str:
        return "evaluate_options" if state["selected_action"]["action"] == "recommend" else "generate_question"

    graph = StateGraph(GraphState)
    graph.add_node("extract_observations", extract)
    graph.add_node("update_decision_state", update_state)
    graph.add_node("choose_next_action", choose_action)
    graph.add_node("generate_question", formulate_question)
    graph.add_node("evaluate_options", evaluate_options)
    graph.add_node("critique_recommendation", critique_recommendation)
    graph.add_node("write_recommendation", write_recommendation)
    graph.add_edge(START, "extract_observations")
    graph.add_edge("extract_observations", "update_decision_state")
    graph.add_edge("update_decision_state", "choose_next_action")
    graph.add_conditional_edges("choose_next_action", route_after_action)
    graph.add_edge("generate_question", END)
    graph.add_edge("evaluate_options", "critique_recommendation")
    graph.add_edge("critique_recommendation", "write_recommendation")
    graph.add_edge("write_recommendation", END)
    return graph.compile(checkpointer=checkpointer)
