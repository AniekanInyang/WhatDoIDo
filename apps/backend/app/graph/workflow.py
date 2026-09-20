from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

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
    Readiness,
)
from app.llm.decision_assistant import extract_decision_patch, generate_grounded_recommendation


class RecommendationGenerationError(RuntimeError):
    pass


def _normalized(value: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())


def _same_option(left: str, right: str) -> bool:
    a, b = _normalized(left), _normalized(right)
    return bool(a and b) and (a == b or SequenceMatcher(None, a, b).ratio() >= 0.88)


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
        gaps.append(InformationGap(key="goal", question_category="goal", impact=1, reason="The decision is not yet clear.", base_question="What specific decision are you trying to make?"))
    if option_count < 2:
        gaps.append(InformationGap(key="options", question_category="options", impact=.95, reason="A comparison needs at least two distinct choices.", base_question="What alternatives are you considering, including keeping things as they are?"))
    if not _active(brief.values):
        gaps.append(InformationGap(key="values", question_category="values", impact=.9, reason="The recommendation must reflect what matters to the user.", base_question="What matters most to you when comparing these options?"))
    if not _active(brief.criteria):
        gaps.append(InformationGap(key="criteria", question_category="criteria", impact=.86, reason="The options need explicit comparison criteria.", base_question="Which factors should decide this, and how important is each from 1 to 5?"))
    if not _active(brief.constraints):
        gaps.append(InformationGap(key="constraints", question_category="constraints", impact=.8, reason="Hard limits can rule out otherwise attractive choices.", base_question="Are there any non-negotiable limits—such as time, money, location, or responsibilities?"))
    if not _active(brief.uncertainties):
        gaps.append(InformationGap(key="uncertainties", question_category="uncertainties", impact=.55, reason="Unknowns can change the outcome.", base_question="What important uncertainty makes this decision hardest right now?"))
    if not brief.risk_tolerance or brief.risk_tolerance.status == "rejected":
        gaps.append(InformationGap(key="risk_tolerance", question_category="risk", impact=.5, reason="Risk tolerance affects how trade-offs should be judged.", base_question="How much risk or uncertainty are you comfortable accepting here?"))
    return gaps


def _personalized_utility(gap: InformationGap, profile: ClarificationProfile) -> float:
    stats = profile.action_stats.get(gap.question_category)
    personal_adjustment = 0.0 if not stats or not stats.asked else max(-.2, min(.2, stats.average_reward * .2))
    return round(gap.impact + personal_adjustment, 3)


def _requests_recommendation(message: str) -> bool:
    normalized = _normalized(message)
    direct_phrases = (
        "recommend", "give me your recommendation", "what should i choose",
        "which should i choose", "go ahead", "evaluate them", "nothing else",
        "nothing to add", "i am ready", "im ready",
    )
    return normalized in {"no", "yes"} or any(phrase in normalized for phrase in direct_phrases)


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

        contradictions = list(brief.contradictions)
        for scalar in ("goal", "domain", "deadline", "risk_tolerance"):
            value = patch.get(scalar)
            if not value:
                continue
            incoming = _prepare_fact(Fact.model_validate(value))
            current = getattr(brief, scalar)
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
        for candidate in patch.get("options", []):
            duplicate = next((title for title in all_titles if _same_option(candidate["title"], title)), None)
            if duplicate:
                duplicates.append({"candidate": candidate["title"], "existing": duplicate})
            else:
                accepted.append(candidate)
                all_titles.append(candidate["title"])

        option_count = len(existing) + len(accepted)
        gaps = _gaps(brief, option_count)
        core_coverage = (
            brief.goal is not None,
            option_count >= 2,
            bool(_active(brief.values)),
            bool(_active(brief.criteria)),
            bool(_active(brief.constraints)),
        )
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
        brief = DecisionBrief.model_validate(state["brief"])
        profile = ClarificationProfile.model_validate(state.get("profile") or {})
        if not state.get("is_decision_input", True):
            action = ActionPlan(action="clarify_decision", category="decision", rationale=state.get("patch", {}).get("non_decision_reason") or "The message did not describe a decision.", utility=1)
            reply = "I can help once we have a decision to work through. What choice or dilemma are you facing?"
        else:
            unresolved = next((item for item in brief.contradictions if item.status == "unresolved"), None)
            assumption = next((item for item in brief.assumptions if item.status == "candidate" and item.importance == "high"), None)
            if unresolved:
                action = ActionPlan(action="resolve_contradiction", category="contradiction", rationale=f"Two different answers were recorded for {unresolved.topic}.", question=f"You previously said “{unresolved.previous_value}” and now said “{unresolved.new_value}.” Which should I use?", utility=1)
                reply = action.question or "Which answer should I use?"
            elif assumption:
                action = ActionPlan(action="confirm_inference", category="assumption", rationale="An important assumption should not influence the recommendation without confirmation.", question=f"I’m currently assuming: “{assumption.statement}.” Is that correct?", utility=.98)
                reply = action.question or "Is that assumption correct?"
            elif brief.readiness.enough_to_recommend and _requests_recommendation(state["user_message"]):
                action = ActionPlan(action="recommend", category="recommendation", rationale="The state is ready and the user explicitly requested the recommendation.", utility=1)
                reply = "I’m evaluating the options against what you told me."
            elif brief.readiness.enough_to_recommend:
                action = ActionPlan(action="evaluate", category="evaluation", rationale="The core goal, options, criteria, values, and constraints are present.", utility=1)
                reply = "I have enough to compare the options. Is there anything important to add or correct, or should I give you my recommendation?"
            else:
                ranked = sorted(
                    ((_personalized_utility(gap, profile), gap) for gap in brief.missing_information),
                    key=lambda item: item[0], reverse=True,
                )
                utility, gap = ranked[0]
                action = ActionPlan(action="ask_clarification", category=gap.question_category, question=gap.base_question, rationale=gap.reason, utility=utility)
                reply = gap.base_question
        brief.next_action = action
        return {"brief": brief.model_dump(mode="json"), "assistant_reply": reply, "selected_action": action.model_dump(mode="json")}

    async def recommend(state: GraphState) -> dict[str, Any]:
        options = [option for option in state.get("existing_options", []) if option.get("status") != "rejected"]
        result = await generate_grounded_recommendation(state["brief"], options, settings)
        if not result:
            raise RecommendationGenerationError("The provider returned no valid grounded recommendation")
        brief = DecisionBrief.model_validate(state["brief"])
        brief.phase = "completed"
        reply = f"My recommendation is {result.selected_option_title}. {result.summary}"
        if result.caveat:
            reply += f"\n\nImportant caveat: {result.caveat}"
        return {"brief": brief.model_dump(mode="json"), "recommendation": result.model_dump(mode="json"), "assistant_reply": reply}

    def route_after_action(state: GraphState) -> str:
        return "generate_recommendation" if state["selected_action"]["action"] == "recommend" else END

    retry = RetryPolicy(initial_interval=.5, backoff_factor=2, max_interval=4, max_attempts=3, jitter=True, retry_on=Exception)
    graph = StateGraph(GraphState)
    graph.add_node("extract_observations", extract, retry_policy=retry)
    graph.add_node("update_decision_state", update_state)
    graph.add_node("choose_next_action", choose_action)
    graph.add_node("generate_recommendation", recommend, retry_policy=retry)
    graph.add_edge(START, "extract_observations")
    graph.add_edge("extract_observations", "update_decision_state")
    graph.add_edge("update_decision_state", "choose_next_action")
    graph.add_conditional_edges("choose_next_action", route_after_action)
    graph.add_edge("generate_recommendation", END)
    return graph.compile(checkpointer=checkpointer)
