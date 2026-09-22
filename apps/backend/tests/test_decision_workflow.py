import asyncio
from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError, RateLimitError
from langgraph.checkpoint.memory import InMemorySaver
from uuid import uuid4

from app.core.config import Settings
from app.core.auth import AuthenticatedUser
from app.graph.state import (
    ClarificationProfile,
    InformationGap,
    PolicyActionStats,
    QuestionDraft,
    RecommendationResult,
    DecisionStatePatch,
)
from app.graph.workflow import (
    _clarification_limit,
    _personalized_utility,
    _requests_recommendation,
    _same_option,
    build_decision_graph,
)
from app.llm.decision_assistant import (
    DecisionLLMBudgetError,
    _check_budget,
    _compact_brief,
    _complete_with_fallback,
    _merge_contextual_answer,
    _normalize_question_payload,
    _normalize_recommendation_payload,
    _strict_response_format,
)
from app.services.decisions import DecisionStore


@pytest.fixture(autouse=True)
def stub_question_model(monkeypatch):
    """Workflow unit tests isolate policy/state behavior from external phrasing."""
    async def generate(action, brief, options, latest_message, settings):
        target = action.target_field or action.category
        return QuestionDraft(
            question=f"{target.replace('_', ' ')} request {action.attempt}?",
            target_field=target,
            expected_answer_type=action.expected_answer_type or "short_text",
        )

    monkeypatch.setattr("app.graph.workflow.generate_clarification_question", generate)


def test_duplicate_option_detection_normalizes_and_matches_similar_titles() -> None:
    assert _same_option("Stay at my current company", "Stay at current company")
    assert not _same_option("Move to Berlin", "Start a local business")


def test_all_caps_prompt_gets_a_readable_title() -> None:
    assert DecisionStore._title_from_prompt("WHAT SHOULD I COOK TOMORROW") == "What should I cook tomorrow"


def test_compound_priority_answer_is_saved_as_distinct_values() -> None:
    patch = _merge_contextual_answer(
        DecisionStatePatch(),
        "My mental health and financial stability",
        "message-1",
        {"next_action": {"category": "values"}},
    )
    assert [fact.value for fact in patch.values] == ["mental health", "financial stability"]


def test_selected_priority_is_weighted_without_asking_for_importance_again() -> None:
    patch = _merge_contextual_answer(
        DecisionStatePatch(),
        "creativity because I like the freedom",
        "message-creativity",
        {
            "next_action": {
                "category": "values",
                "target_field": "values",
                "expected_answer_type": "short_priority",
            }
        },
    )
    assert [fact.value for fact in patch.values] == ["creativity"]
    assert len(patch.criteria) == 1
    assert patch.criteria[0].name == "creativity"
    assert patch.criteria[0].importance == 5
    assert patch.criteria[0].status == "confirmed"


def test_none_resolves_constraints_without_saving_literal_none() -> None:
    patch = _merge_contextual_answer(
        DecisionStatePatch(constraints=[{
            "value": "none", "source": "explicit", "confidence": "high",
        }]),
        "none",
        "message-none",
        {"next_action": {"category": "constraints"}},
    )
    assert patch.constraints == []
    assert patch.resolved_absences == ["constraints"]


def test_recommendation_provider_shape_drift_is_normalized() -> None:
    normalized = _normalize_recommendation_payload({
        "selected_option_id": "yam",
        "selected_option_title": "Yam",
        "summary": "Choose yam if it is quicker in your kitchen.",
        "rationale": "Time to cook is the stated priority.",
        "option_assessments": [{
            "option_id": "yam", "option_title": "Yam", "fit": "high",
            "strengths": "Could fit the stated priority", "tradeoffs": [],
            "constraint_conflicts": [],
        }],
        "assumptions": [], "unresolved_uncertainties": ["Actual cook times"],
        "key_risks": [], "checks_before_acting": "Compare your preparation times",
        "alternate_recommendation": "Rice if it is quicker",
        "sensitivity_analysis": {
            "factor": "Preparation time", "current_assumption": "Yam is quicker",
            "change_that_could_flip_result": "Rice is quicker",
            "likely_winner_option_id": "rice", "explanation": "The priority would favor rice",
        },
        "robustness": "low", "caveat": "No cook times were provided",
    })
    result = RecommendationResult.model_validate(normalized)
    assert result.rationale == ["Time to cook is the stated priority."]
    assert result.option_assessments[0].fit == "strong"
    assert result.option_assessments[0].strengths == ["Could fit the stated priority"]
    assert len(result.sensitivity_analysis) == 1


def test_blank_question_acknowledgement_metadata_is_normalized() -> None:
    payload = _normalize_question_payload({
        "question": "Which alternatives are you weighing?",
        "target_field": "options",
        "expected_answer_type": "list_of_options",
        "acknowledges_answer": "",
    })
    result = QuestionDraft.model_validate(payload)
    assert result.question == "Which alternatives are you weighing?"
    assert result.acknowledges_answer is False
    assert result.suggested_options == []


def test_stakes_bound_the_clarification_limit() -> None:
    from app.graph.state import DecisionBrief

    assert _clarification_limit(DecisionBrief(decision_stakes="low"), 8) == 3
    assert _clarification_limit(DecisionBrief(decision_stakes="medium"), 8) == 5
    assert _clarification_limit(DecisionBrief(decision_stakes="high"), 8) == 8
    assert _clarification_limit(DecisionBrief(decision_stakes="high"), 4) == 4


def test_strict_response_schema_closes_objects_and_requires_every_field() -> None:
    response_format = _strict_response_format("question", QuestionDraft)
    schema = response_format["json_schema"]["schema"]
    assert response_format["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "default" not in schema["properties"]["acknowledges_answer"]


def test_json_validation_failure_retries_same_model_once() -> None:
    calls = []

    class Completions:
        async def create(self, *, model, **kwargs):
            calls.append(model)
            if len(calls) == 1:
                response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
                raise BadRequestError(
                    "invalid JSON",
                    response=response,
                    body={"error": {"code": "json_validate_failed"}},
                )
            return SimpleNamespace(choices=[]), model

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    _, model = asyncio.run(_complete_with_fallback(client, ["openai/gpt-oss-20b", "fallback"]))
    assert model == "openai/gpt-oss-20b"
    assert calls == ["openai/gpt-oss-20b", "openai/gpt-oss-20b"]


def test_compact_brief_excludes_workflow_history_cache_and_evidence() -> None:
    compact = _compact_brief({
        "goal": {"id": "goal-id", "value": "Choose", "evidence_message_ids": ["message-id"]},
        "values": [{"id": "value-id", "value": "Cost", "status": "confirmed", "evidence_message_ids": ["message-id"]}],
        "question_history": [{"question": "Old question"}],
        "llm_cache": {"secret": {"content": "large"}},
    })
    assert "question_history" not in compact
    assert "llm_cache" not in compact
    assert "id" not in compact["values"][0]
    assert "evidence_message_ids" not in compact["values"][0]


def test_decision_token_budget_blocks_call_before_provider_use() -> None:
    brief = {"llm_usage": {"total_tokens": 950, "budget_tokens": 1_000}}
    settings = Settings(_env_file=None, decision_llm_token_budget=1_000)
    with pytest.raises(DecisionLLMBudgetError):
        _check_budget(brief, {"large": "x" * 200}, 100, settings)
    assert brief["llm_usage"]["exhausted"] is True


def test_rate_limited_model_falls_back_once_to_next_model() -> None:
    calls = []

    class Completions:
        async def create(self, *, model, **kwargs):
            calls.append(model)
            if model == "primary":
                response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
                raise RateLimitError("limited", response=response, body={})
            return SimpleNamespace(choices=[]), model

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    completion, model = asyncio.run(_complete_with_fallback(client, ["primary", "fallback"]))
    assert model == "fallback"
    assert calls == ["primary", "fallback"]


def test_policy_uses_only_supplied_users_profile() -> None:
    gap = InformationGap(
        key="values",
        question_category="values",
        reason="Values matter",
        impact=0.8,
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


def test_policy_profile_save_only_upserts_the_current_users_profile(monkeypatch) -> None:
    user = AuthenticatedUser(id=uuid4(), email="person@example.com", access_token="token")
    store = DecisionStore(
        Settings(_env_file=None, supabase_url="https://example.supabase.co", supabase_anon_key="anon"),
        user,
    )
    calls = []

    async def fake_request(client, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return []

    monkeypatch.setattr(store, "_request", fake_request)
    asyncio.run(store._save_policy_profile(None, ClarificationProfile()))
    assert [(method, path) for method, path, _ in calls] == [("POST", "clarification_profiles")]
    assert calls[0][2]["json"]["user_id"] == str(user.id)


def test_explicit_either_or_answer_captures_options_and_advances_question() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-options",
        "user_id": "user-1",
        "user_message": "yes. either take this new job or stay in my current role",
        "message_id": "message-options",
        "brief": {
            "goal": {"value": "I'm considering taking a new job", "source": "explicit", "confidence": "high"},
            "next_action": {
                "action": "ask_clarification", "category": "options",
                "question": "What alternatives are you considering?", "rationale": "Options are missing",
            },
        },
        "existing_options": [],
        "profile": {},
    }))
    assert [option["title"] for option in result["new_options"]] == [
        "Take this new job", "Stay in my current role",
    ]
    assert result["selected_action"]["category"] == "values"
    assert "alternatives" not in result["assistant_reply"].lower()


def test_options_embedded_in_initial_decision_are_captured_immediately() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-food", "user_id": "user-1",
        "user_message": "should I eat yam or rice tomorrow?", "message_id": "message-food",
        "brief": {}, "existing_options": [], "profile": {},
    }))
    assert [option["title"] for option in result["new_options"]] == ["Yam", "Rice"]
    assert result["selected_action"]["category"] == "values"


def test_meal_conversation_accepts_and_separated_options_and_short_priority() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    first = asyncio.run(graph.ainvoke({
        "decision_id": "meal", "user_id": "user-1",
        "user_message": "what should I eat today", "message_id": "one",
        "brief": {}, "existing_options": [], "profile": {},
    }))
    assert first["selected_action"]["category"] == "options"

    second = asyncio.run(graph.ainvoke({
        "decision_id": "meal", "user_id": "user-1",
        "user_message": "rice and yam", "message_id": "two",
        "brief": {**first["brief"], "decision_stakes": "low"},
        "existing_options": [], "profile": {},
    }))
    assert [option["title"] for option in second["new_options"]] == ["Rice", "Yam"]
    assert second["selected_action"]["category"] == "values"

    persisted_options = [
        {"id": "rice", "title": "Rice", "status": "confirmed"},
        {"id": "yam", "title": "Yam", "status": "confirmed"},
    ]
    third = asyncio.run(graph.ainvoke({
        "decision_id": "meal", "user_id": "user-1",
        "user_message": "time to cook", "message_id": "three",
        "brief": second["brief"], "existing_options": persisted_options, "profile": {},
    }))
    assert third["brief"]["values"][0]["value"] == "time to cook"
    assert third["selected_action"]["action"] == "evaluate"
    assert third["selected_action"]["target_field"] == "recommendation_consent"
    assert "recommendation" in third["assistant_reply"].lower()
    assert third["selected_action"]["action"] != "clarify_decision"


def test_numeric_reply_sets_importance_for_the_pending_known_criterion() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "career", "user_id": "user-1",
        "user_message": "5", "message_id": "importance",
        "brief": {
            "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"},
            "values": [{"value": "stability", "source": "explicit", "confidence": "high"}],
            "next_action": {
                "action": "ask_clarification", "category": "criteria",
                "target_field": "criterion_importance", "attempt": 1,
                "question": "How important is stability from 1 to 5?", "rationale": "Weight it",
            },
        },
        "existing_options": [
            {"id": "one", "title": "Stay", "status": "confirmed"},
            {"id": "two", "title": "Leave", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["brief"]["criteria"][0]["name"] == "stability"
    assert result["brief"]["criteria"][0]["importance"] == 5
    assert result["selected_action"]["category"] == "constraints"


def test_which_should_i_requests_an_early_recommendation(monkeypatch) -> None:
    async def fake_recommendation(brief, options, settings):
        return RecommendationResult(
            selected_option_id="rice", selected_option_title="Rice",
            summary="Rice is quicker to prepare.", rationale=["It best fits the stated priority."],
        )

    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", fake_recommendation)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "meal", "user_id": "user-1",
        "user_message": "which should I cook", "message_id": "four",
        "brief": {
            "goal": {"value": "Choose a meal", "source": "explicit", "confidence": "high"},
            "values": [{"value": "time to cook", "source": "explicit", "confidence": "high"}],
            "next_action": {"action": "ask_clarification", "category": "criteria", "rationale": "Criteria missing"},
        },
        "existing_options": [
            {"id": "rice", "title": "Rice", "status": "confirmed"},
            {"id": "yam", "title": "Yam", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["selected_action"]["action"] == "recommend"
    assert result["brief"]["phase"] == "completed"


def test_failed_gap_extraction_does_not_repeat_identical_question() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-options",
        "user_id": "user-1",
        "user_message": "yes",
        "message_id": "message-options",
        "brief": {
            "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"},
            "next_action": {
                "action": "ask_clarification", "category": "options",
                "question": "What alternatives are you considering, including keeping things as they are?",
                "rationale": "Options are missing",
            },
        },
        "existing_options": [],
        "profile": {},
    }))
    assert result["assistant_reply"] != "What alternatives are you considering, including keeping things as they are?"
    assert result["selected_action"]["attempt"] == 2


def test_short_reply_is_resolved_against_pending_semantic_target() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-values", "user_id": "user-1",
        "user_message": "stability", "message_id": "message-values",
        "brief": {
            "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"},
            "next_action": {
                "action": "ask_clarification", "category": "values", "target_field": "values",
                "question": "What matters most?", "rationale": "Values are missing",
            },
        },
        "existing_options": [
            {"id": "one", "title": "Take the new role", "status": "confirmed"},
            {"id": "two", "title": "Stay", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["brief"]["values"][0]["value"] == "stability"
    assert result["brief"]["values"][0]["source"] == "explicit"
    assert result["brief"]["criteria"][0]["name"] == "stability"
    assert result["brief"]["criteria"][0]["importance"] == 5
    assert result["selected_action"]["category"] != "values"
    assert result["selected_action"]["category"] != "criteria"


def test_low_stakes_choice_stops_after_real_options_and_priority() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content-choice", "user_id": "user-1",
        "user_message": "creativity because I like the freedom", "message_id": "priority",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "What should I post on TikTok?", "source": "explicit", "confidence": "high"},
            "next_action": {
                "action": "ask_clarification", "category": "values", "target_field": "values",
                "question": "What matters most when choosing?", "rationale": "Values are missing",
            },
        },
        "existing_options": [
            {"id": "wedding", "title": "Wedding content", "status": "confirmed"},
            {"id": "travel", "title": "Travel content", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["brief"]["goal"]["value"] == "What should I post on TikTok?"
    assert result["brief"]["readiness"]["enough_to_recommend"] is True
    assert result["selected_action"]["action"] == "evaluate"


def test_clarification_detail_cannot_silently_replace_existing_goal(monkeypatch) -> None:
    async def extracted_detail(*args, **kwargs):
        return DecisionStatePatch(
            goal={"value": "Create carousel content on TikTok", "source": "explicit", "confidence": "high"},
            options=[
                {"title": "Wedding content", "source": "user_provided"},
                {"title": "Travel content", "source": "user_provided"},
            ],
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted_detail)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content-choice", "user_id": "user-1",
        "user_message": "wedding content or travel", "message_id": "options",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "What should I post on TikTok?", "source": "explicit", "confidence": "high"},
            "next_action": {"action": "ask_clarification", "category": "options", "rationale": "Options missing"},
        },
        "existing_options": [], "profile": {},
    }))
    assert result["brief"]["goal"]["value"] == "What should I post on TikTok?"
    assert [option["title"] for option in result["new_options"]] == ["Wedding content", "Travel content"]


def test_context_is_not_persisted_as_a_decision_option(monkeypatch) -> None:
    async def classified_context(*args, **kwargs):
        return DecisionStatePatch(
            decision_stakes="low",
            options=[{"title": "Carousel", "source": "user_provided", "kind": "context"}],
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", classified_context)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content-choice", "user_id": "user-1",
        "user_message": "carousel", "message_id": "format",
        "brief": {
            "goal": {"value": "What should I post on TikTok?", "source": "explicit", "confidence": "high"},
            "next_action": {"action": "ask_clarification", "category": "options", "rationale": "Options missing"},
        },
        "existing_options": [], "profile": {},
    }))
    assert result["new_options"] == []
    assert result["brief"]["preference_signals"][0]["value"] == "Carousel"
    assert result["selected_action"]["category"] == "options"


def test_assistant_suggested_options_are_returned_for_persistence(monkeypatch) -> None:
    async def generated_options(action, brief, options, latest_message, settings):
        return QuestionDraft(
            question="Would you rather wear a formal suit or a smart casual outfit?",
            target_field="options",
            expected_answer_type="list_of_options",
            suggested_options=[
                {"title": "Formal suit", "source": "ai_generated", "kind": "alternative"},
                {"title": "Smart casual outfit", "source": "ai_generated", "kind": "alternative"},
            ],
        )

    monkeypatch.setattr("app.graph.workflow.generate_clarification_question", generated_options)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "workwear", "user_id": "user-1",
        "user_message": "What should I wear to work?", "message_id": "initial",
        "brief": {}, "existing_options": [], "profile": {},
    }))
    assert [option["title"] for option in result["new_options"]] == [
        "Formal suit", "Smart casual outfit",
    ]
    assert all(option["source"] == "ai_generated" for option in result["new_options"])


def test_policy_selects_target_before_question_is_generated(monkeypatch) -> None:
    captured = {}

    async def fake_question(action, brief, options, latest_message, settings):
        from app.graph.state import QuestionDraft
        captured["target_field"] = action.target_field
        captured["policy_question"] = action.question
        return QuestionDraft(
            question="Which parts of stability matter most for this job choice?",
            target_field=action.target_field,
            expected_answer_type=action.expected_answer_type,
        )

    monkeypatch.setattr("app.graph.workflow.generate_clarification_question", fake_question)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-1", "user_id": "user-1",
        "user_message": "Choose a job", "message_id": "message-1",
        "brief": {}, "existing_options": [], "profile": {},
    }))
    assert captured["target_field"] == "options"
    assert captured["policy_question"] is None
    assert result["assistant_reply"] == "Which parts of stability matter most for this job choice?"


def test_policy_reward_requires_the_requested_target_to_change() -> None:
    before = {"values": [], "next_action": {"category": "values", "target_field": "values"}}
    unresolved = {"brief": {"values": []}, "new_options": []}
    resolved = {"brief": {"values": [{"value": "Stability"}]}, "new_options": []}
    action = before["next_action"]
    assert not DecisionStore._target_was_resolved(action, before, unresolved, [])
    assert DecisionStore._target_was_resolved(action, before, resolved, [])


def test_third_criteria_attempt_can_confirm_existing_values_without_repeating() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-food", "user_id": "user-1",
        "user_message": "yes", "message_id": "message-confirm",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "Choose dinner", "source": "explicit", "confidence": "high"},
            "values": [{"value": "nutrition", "source": "explicit", "confidence": "high"}],
            "next_action": {
                "action": "ask_clarification", "category": "criteria", "target_field": "criteria",
                "attempt": 3, "question": "Should I use nutrition as an equally important comparison criterion?",
                "rationale": "Criteria are missing",
            },
        },
        "existing_options": [
            {"id": "one", "title": "Yam", "status": "confirmed"},
            {"id": "two", "title": "Rice", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["brief"]["criteria"][0]["name"] == "nutrition"
    assert result["brief"]["criteria"][0]["status"] == "confirmed"
    assert result["selected_action"]["category"] == "evaluation"
