import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings
from app.graph.state import (
    ClarificationProfile,
    InformationGap,
    PolicyActionStats,
    RecommendationResult,
    DecisionStatePatch,
)
from app.graph.workflow import (
    _personalized_utility,
    _requests_recommendation,
    _same_option,
    build_decision_graph,
)


def test_duplicate_option_detection_normalizes_and_matches_similar_titles() -> None:
    assert _same_option("Stay at my current company", "Stay at current company")
    assert not _same_option("Move to Berlin", "Start a local business")


def test_policy_uses_only_supplied_users_profile() -> None:
    gap = InformationGap(
        key="values",
        question_category="values",
        reason="Values matter",
        impact=0.8,
        base_question="What matters?",
    )
    positive = ClarificationProfile(
        action_stats={"values": PolicyActionStats(asked=2, answered=2, reward_sum=2)}
    )
    negative = ClarificationProfile(
        action_stats={"values": PolicyActionStats(asked=2, skipped=2, reward_sum=-1)}
    )
    assert _personalized_utility(gap, positive) > _personalized_utility(gap, negative)


def test_graph_builds_state_and_selects_a_clarification() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(
        graph.ainvoke(
            {
                "decision_id": "decision-1",
                "user_id": "user-1",
                "user_message": "Should I accept the new role?",
                "message_id": "message-1",
                "brief": {},
                "existing_options": [],
                "profile": {},
            }
        )
    )
    assert result["brief"]["goal"]["value"] == "Should I accept the new role?"
    assert result["selected_action"]["action"] == "ask_clarification"
    assert result["selected_action"]["category"] == "options"


def test_recommendation_intent_requires_an_explicit_signal() -> None:
    assert _requests_recommendation("Go ahead and recommend one")
    assert _requests_recommendation("Nothing else")
    assert not _requests_recommendation("Stability is important to me")


def test_ready_graph_generates_recommendation_after_user_confirmation(monkeypatch) -> None:
    async def fake_recommendation(brief, options, settings):
        return RecommendationResult(
            selected_option_id="option-1",
            selected_option_title="Option A",
            summary="Option A best matches the confirmed priorities.",
            rationale=["It satisfies the hard constraint."],
            robustness="moderate",
            sensitivity_analysis=[
                {
                    "factor": "Cost",
                    "current_assumption": "Option A remains within budget.",
                    "change_that_could_flip_result": "Its cost rises beyond the budget.",
                    "likely_winner_option_id": "option-2",
                    "explanation": "Option B would then be the feasible choice.",
                }
            ],
        )

    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", fake_recommendation)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(
        graph.ainvoke(
            {
                "decision_id": "decision-1",
                "user_id": "user-1",
                "user_message": "Go ahead",
                "message_id": "message-2",
                "brief": {
                    "phase": "evaluating",
                    "goal": {"value": "Choose a role", "source": "explicit", "confidence": "high"},
                        "values": [{"value": "Growth", "source": "explicit", "confidence": "high"}],
                        "criteria": [{"name": "Growth", "importance": 5, "source": "explicit", "confidence": "high", "status": "confirmed"}],
                    "constraints": [{"value": "No relocation", "source": "explicit", "confidence": "high"}],
                },
                "existing_options": [
                    {"id": "option-1", "title": "Option A", "description": "Stay local"},
                    {"id": "option-2", "title": "Option B", "description": "Remote role"},
                ],
                "profile": {},
            }
        )
    )
    assert result["selected_action"]["action"] == "recommend"
    assert result["brief"]["phase"] == "completed"
    assert result["recommendation"]["selected_option_id"] == "option-1"
    assert result["recommendation"]["sensitivity_analysis"][0]["likely_winner_option_id"] == "option-2"


def test_unclear_prompt_is_not_saved_as_a_decision_goal() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-1", "user_id": "user-1", "user_message": "hello",
        "message_id": "message-1", "brief": {}, "existing_options": [], "profile": {},
    }))
    assert result["brief"]["goal"] is None
    assert result["selected_action"]["action"] == "clarify_decision"


def test_direction_change_supersedes_previous_state_and_options(monkeypatch) -> None:
    async def changed_direction(*args, **kwargs):
        return DecisionStatePatch(
            direction_change=True,
            direction_change_summary="The user replaced the career decision with a housing decision.",
            goal={"value": "Choose where to live", "source": "explicit", "confidence": "high"},
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", changed_direction)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-1", "user_id": "user-1", "user_message": "Actually, this is now about where to live",
        "message_id": "message-3",
        "brief": {"revision": 2, "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"}},
        "existing_options": [{"id": "old-option", "title": "Old job", "status": "confirmed"}],
        "profile": {},
    }))
    assert result["direction_changed"] is True
    assert result["brief"]["goal"]["value"] == "Choose where to live"
    assert result["brief"]["superseded_states"][0]["goal"]["value"] == "Choose a job"
    assert result["brief"]["option_ids"] == []


def test_assumption_can_be_confirmed_in_conversation() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-1", "user_id": "user-1", "user_message": "Yes",
        "message_id": "message-4",
        "brief": {
            "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"},
            "assumptions": [{"id": "assumption-1", "statement": "Remote work is available", "importance": "high", "status": "candidate"}],
            "next_action": {"action": "confirm_inference", "category": "assumption", "rationale": "Needs confirmation", "question": "Is remote work available?"},
        },
        "existing_options": [], "profile": {},
    }))
    assumption = next(item for item in result["brief"]["assumptions"] if item["id"] == "assumption-1")
    assert assumption["status"] == "confirmed"


def test_failed_recommendation_resumes_from_checkpointed_node(monkeypatch) -> None:
    provider_available = False

    async def unreliable_recommendation(brief, options, settings):
        if not provider_available:
            return None
        return RecommendationResult(
            selected_option_id="option-1",
            selected_option_title="Option A",
            summary="Option A is the stronger fit.",
            rationale=["It best satisfies the confirmed criteria."],
        )

    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", unreliable_recommendation)
    graph = build_decision_graph(
        Settings(_env_file=None, groq_api_key=None), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "user-1:decision-resume"}}
    payload = {
        "decision_id": "decision-resume", "user_id": "user-1", "user_message": "Recommend one",
        "message_id": "message-5",
        "brief": {
            "goal": {"value": "Choose", "source": "explicit", "confidence": "high"},
            "values": [{"value": "Fit", "source": "explicit", "confidence": "high"}],
            "criteria": [{"name": "Fit", "importance": 5, "source": "explicit", "confidence": "high", "status": "confirmed"}],
            "constraints": [{"value": "Budget", "source": "explicit", "confidence": "high"}],
        },
        "existing_options": [
            {"id": "option-1", "title": "Option A", "status": "confirmed"},
            {"id": "option-2", "title": "Option B", "status": "confirmed"},
        ],
        "profile": {},
    }
    with pytest.raises(Exception):
        asyncio.run(graph.ainvoke(payload, config=config))
    provider_available = True
    resumed = asyncio.run(graph.ainvoke(None, config=config))
    assert resumed["brief"]["phase"] == "completed"
    assert resumed["recommendation"]["selected_option_id"] == "option-1"
