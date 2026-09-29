import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError, RateLimitError
from langgraph.checkpoint.memory import InMemorySaver
from uuid import uuid4

from app.core.config import Settings
from app.core.auth import AuthenticatedUser
from app.graph.state import (
    ActionPlan,
    ClarificationProfile,
    DecisionBrief,
    InformationGap,
    OptionObservation,
    PolicyActionStats,
    QuestionDraft,
    RecommendationResult,
    DecisionStatePatch,
)
from app.graph.workflow import (
    _clarification_limit,
    _gaps,
    _personalized_utility,
    _requests_recommendation,
    _signals_repeated_question,
    _same_option,
    build_decision_graph,
)
from app.llm.decision_assistant import (
    DecisionLLMGenerationError,
    DecisionLLMBudgetError,
    ExtractionDraft,
    RecommendationDraft,
    _bind_selected_option,
    _check_budget,
    _compact_brief,
    _compact_extraction_brief,
    _confirmed_actionable_selection,
    _extraction_patch_from_draft,
    _complete_structured,
    _merge_contextual_answer,
    _normalize_question_payload,
    _normalize_recommendation_payload,
    _replace_option_references,
    _preserve_opening_decision,
    _question_advances_target,
    _sanitize_recommendation,
    _safe_completion_token_limit,
    _short_option_label,
    _strict_response_format,
    _fallback_clarification_question,
    generate_grounded_recommendation,
    generate_clarification_question,
    _trim_repeated_acknowledgement,
    _validate_recommendation_selection,
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
    assert _same_option("educational", "Educational tutorial")
    assert not _same_option("Move to Berlin", "Start a local business")
    assert not _same_option("post", "Post content on TikTok")


def test_paraphrased_selection_is_not_persisted_as_another_option() -> None:
    draft = ExtractionDraft(
        selected_option_title="Gourmet Dessert",
        preference_signals=["Prefers something sweet and indulgent"],
        options=[{
            "title": "Sweet indulgence",
            "kind": "alternative",
            "specificity": "actionable",
        }],
    )
    bound = _bind_selected_option(draft, [
        {"id": "dessert", "title": "Gourmet Dessert", "status": "candidate"},
        {
            "id": "cheese",
            "title": "Specialty Cheese or Charcuterie Board",
            "status": "candidate",
        },
    ])
    patch = _extraction_patch_from_draft(bound, "sweet-reply")

    assert patch.options == []
    assert [str(item.value) for item in patch.preference_signals] == [
        "Prefers something sweet and indulgent",
        "Selected option: Gourmet Dessert",
    ]


def test_goal_is_not_persisted_as_an_option(monkeypatch) -> None:
    async def extracted(*args, **kwargs):
        return DecisionStatePatch(
            decision_stakes="low",
            goal={"value": "Post content on TikTok", "source": "explicit", "confidence": "high"},
            options=[
                {"title": "Post content on TikTok", "source": "user_provided"},
                {"title": "Educational tutorial", "source": "ai_generated"},
                {"title": "Entertaining skit", "source": "ai_generated"},
            ],
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content", "user_id": "user-1",
        "user_message": "post content on TikTok", "message_id": "goal-message",
        "brief": {}, "existing_options": [], "profile": {},
    }))
    assert [option["title"] for option in result["new_options"]] == [
        "Educational tutorial", "Entertaining skit",
    ]


def test_goal_refinement_is_not_an_option_when_original_goal_is_preserved(monkeypatch) -> None:
    async def extracted(*args, **kwargs):
        return DecisionStatePatch(
            goal={"value": "Post content on TikTok", "source": "explicit", "confidence": "high"},
            options=[{"title": "Post content on TikTok", "source": "user_provided"}],
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content", "user_id": "user-1",
        "user_message": "post content on TikTok", "message_id": "refinement-message",
        "brief": {
            "goal": {"value": "Decide what to work on today", "source": "explicit", "confidence": "high"},
        },
        "existing_options": [], "profile": {},
    }))
    assert result["new_options"] == []


def test_short_option_selection_resolves_existing_option_without_duplication(monkeypatch) -> None:
    async def extracted(*args, **kwargs):
        return DecisionStatePatch(options=[{
            "title": "educational", "source": "user_provided", "kind": "alternative",
        }])

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "content", "user_id": "user-1",
        "user_message": "educational", "message_id": "selection-message",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "Choose TikTok content", "source": "explicit", "confidence": "high"},
        },
        "existing_options": [
            {"id": "education", "title": "Educational tutorial", "status": "confirmed"},
            {"id": "skit", "title": "Entertaining skit", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["new_options"] == []
    assert result["duplicate_options"] == [{
        "candidate": "educational", "existing": "Educational tutorial",
    }]
    assert any(
        item["value"] == "Selected option: Educational tutorial"
        for item in result["brief"]["preference_signals"]
    )


def test_all_caps_prompt_gets_a_readable_title() -> None:
    assert DecisionStore._title_from_prompt("WHAT SHOULD I COOK TOMORROW") == "What should I cook tomorrow"


def test_model_normalized_opening_goal_replaces_provisional_title() -> None:
    brief = {
        "goal": {
            "value": "What should I wear this weekend?",
            "source": "explicit",
            "confidence": "high",
        }
    }

    assert DecisionStore._title_from_brief(brief) == "What should I wear this weekend"


def test_provisional_title_does_not_semantically_rewrite_prompt() -> None:
    assert DecisionStore._title_from_prompt("what should I wea r today") == "What should I wea r today"


def test_provisional_title_preserves_single_letter_choice_labels() -> None:
    assert DecisionStore._title_from_prompt("Should I choose plan B?") == "Should I choose plan B"


def test_compound_priority_answer_is_saved_as_distinct_values() -> None:
    patch = _merge_contextual_answer(
        DecisionStatePatch(),
        "My mental health and financial stability",
        "message-1",
        {"next_action": {"category": "values"}},
    )
    assert [fact.value for fact in patch.values] == ["mental health", "financial stability"]


def test_weather_priority_creates_context_gap_until_conditions_are_known() -> None:
    brief = DecisionBrief.model_validate({
        "decision_stakes": "low",
        "goal": {"value": "Choose what to wear tomorrow", "source": "explicit", "confidence": "high"},
        "values": [{"value": "weather", "source": "explicit", "confidence": "high"}],
    })
    assert any(gap.key == "weather_context" for gap in _gaps(brief, 2))
    brief.constraints.append(brief.values[0].model_copy(update={"value": "55 degrees with a 20-minute walk"}))
    assert not any(gap.key == "weather_context" for gap in _gaps(brief, 2))


def test_context_answer_is_saved_without_replacing_goal() -> None:
    patch = _merge_contextual_answer(
        DecisionStatePatch(),
        "Cold and rainy, and I will walk for 20 minutes",
        "message-weather",
        {"next_action": {"category": "context", "target_field": "weather_context"}},
    )
    assert [fact.value for fact in patch.constraints] == [
        "Cold and rainy, and I will walk for 20 minutes"
    ]
    assert patch.goal is None


def test_opening_decision_survives_an_incomplete_model_extraction() -> None:
    fallback = DecisionStatePatch.model_validate({
        "goal": {
            "value": "What birthday gift should I get my best friend?",
            "source": "explicit",
            "confidence": "high",
            "evidence_message_ids": ["message-gift"],
        },
    })
    incomplete = DecisionStatePatch(is_decision_input=False, non_decision_reason="Unclear")

    result = _preserve_opening_decision(incomplete, fallback, {})

    assert result.goal is not None
    assert result.goal.value == "What birthday gift should I get my best friend?"
    assert result.is_decision_input is True
    assert result.non_decision_reason is None


def test_question_must_advance_its_selected_target() -> None:
    assert not _question_advances_target(QuestionDraft(
        question="What is the most important reason you want to buy a gift?",
        target_field="options",
        expected_answer_type="list_of_options",
    ))
    assert _question_advances_target(QuestionDraft(
        question="That sounds thoughtful. What gift ideas are you already considering?",
        target_field="options",
        expected_answer_type="list_of_options",
    ))
    assert _question_advances_target(QuestionDraft(
        question="Dinner sounds nice. What would you feel best wearing to it?",
        target_field="options",
        expected_answer_type="list_of_options",
    ))
    assert not _question_advances_target(QuestionDraft(
        question="What matters most to you when choosing what to wear?",
        target_field="options",
        expected_answer_type="list_of_options",
    ))
    assert not _question_advances_target(QuestionDraft(
        question="Why do you want help?",
        target_field="goal",
        expected_answer_type="decision_statement",
    ))


def test_nonfirst_question_trims_repeated_decision_framing() -> None:
    question = "I hear you’re looking for a dinner idea—how much time do you have to cook tonight?"
    trimmed = _trim_repeated_acknowledgement(question, is_first_question=False)
    assert trimmed == "how much time do you have to cook tonight?"


def test_first_question_keeps_warm_acknowledgement() -> None:
    question = "I hear you're looking for a dinner idea—do you have any dietary restrictions?"
    assert _trim_repeated_acknowledgement(question, is_first_question=True) == question


def test_invalid_options_question_falls_back_instead_of_failing(monkeypatch) -> None:
    async def fake_complete(client, models, **kwargs):
        raw = {
            "question": "Would you rather oatmeal or eggs tomorrow?",
            "acknowledges_answer": False,
            "suggested_options": [],
        }
        parsed = kwargs["parse"](raw)
        completion = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        ))
        return completion, models[0], parsed, json.dumps(raw)

    monkeypatch.setattr("app.llm.decision_assistant._complete_structured", fake_complete)

    draft = asyncio.run(generate_clarification_question(
        ActionPlan(
            action="ask_clarification",
            category="options",
            target_field="options",
            expected_answer_type="list_of_options",
            rationale="Need concrete choices",
        ),
        {
            "goal": {"value": "What should I have for breakfast tomorrow?"},
            "question_history": [{}],
        },
        [],
        "I'd love to use eggs",
        Settings(_env_file=None, groq_api_key="test-key", llm_stage_delay_seconds=0),
    ))
    assert "want me to evaluate" in draft.question.lower()
    assert draft.target_field == "options"


def test_question_generation_provider_failure_uses_fallback(monkeypatch) -> None:
    async def fail_complete(*args, **kwargs):
        raise DecisionLLMGenerationError("provider unavailable")

    monkeypatch.setattr("app.llm.decision_assistant._complete_structured", fail_complete)

    draft = asyncio.run(generate_clarification_question(
        ActionPlan(
            action="ask_clarification",
            category="values",
            target_field="values",
            expected_answer_type="short_priority",
            rationale="Need values",
        ),
        {"goal": {"value": "Choose breakfast"}, "question_history": []},
        [],
        "eggs",
        Settings(_env_file=None, groq_api_key="test-key", llm_stage_delay_seconds=0),
    ))
    assert "matters most" in draft.question.lower()
    assert draft.target_field == "values"


def test_question_generation_budget_exhaustion_uses_fallback() -> None:
    draft = asyncio.run(generate_clarification_question(
        ActionPlan(
            action="ask_clarification",
            category="constraints",
            target_field="constraints",
            expected_answer_type="short_text",
            rationale="Need limits",
        ),
        {
            "goal": {"value": "Choose breakfast"},
            "question_history": [],
            "llm_usage": {"total_tokens": 5_000, "budget_tokens": 1_000},
        },
        [],
        "eggs",
        Settings(_env_file=None, groq_api_key="test-key", llm_stage_delay_seconds=0),
    ))
    assert "hard limits" in draft.question.lower()
    assert draft.target_field == "constraints"


def test_options_fallback_for_meal_goal_suggests_actionable_candidates() -> None:
    draft = _fallback_clarification_question(
        ActionPlan(
            action="ask_clarification",
            category="options",
            target_field="options",
            expected_answer_type="list_of_options",
            rationale="Need options",
        ),
        {
            "goal": {"value": "What should I have for breakfast?"},
            "preference_signals": [{"value": "something healthy"}],
        },
    )
    assert len(draft.suggested_options) == 2
    assert all(item.specificity == "actionable" for item in draft.suggested_options)
    assert "want me to evaluate" in draft.question.lower()


def test_options_fallback_rejection_reframes_and_avoids_repeat() -> None:
    draft = _fallback_clarification_question(
        ActionPlan(
            action="ask_clarification",
            category="options",
            target_field="options",
            expected_answer_type="list_of_options",
            rationale="Need options",
        ),
        {"goal": {"value": "What should I have for lunch?"}},
        latest_message="these are not lunch options",
        forbidden=[
            "I can compare Chicken and veggie grain bowl vs Salmon salad with avocado and quinoa. Want me to evaluate these now, or do you want to share two specific options of your own?"
        ],
    )
    assert "please share two specific lunch options" in draft.question.lower()
    assert draft.suggested_options == []


def test_recommendation_generation_uses_budget_fallback_without_error() -> None:
    result = asyncio.run(generate_grounded_recommendation(
        {
            "goal": {"value": "Choose lunch", "status": "confirmed"},
            "values": [{"value": "healthy", "status": "confirmed"}],
            "constraints": [{"value": "quick prep", "status": "confirmed"}],
            "llm_usage": {"total_tokens": 9_900, "budget_tokens": 10_000},
        },
        [
            {"id": "opt-1", "title": "Chicken wrap", "status": "confirmed"},
            {"id": "opt-2", "title": "Veggie bowl", "status": "confirmed"},
        ],
        Settings(
            _env_file=None,
            groq_api_key="test-key",
            decision_llm_token_budget=10_000,
            recommendation_max_tokens=400,
            llm_stage_delay_seconds=0,
        ),
    ))
    assert result is not None
    assert result.selected_option_id == "opt-1"
    assert result.caveat and "budget" in result.caveat.lower()


def test_appreciation_after_recommendation_gets_short_acknowledgement(monkeypatch) -> None:
    assert DecisionStore._is_appreciation_message("thank you") is True
    assert DecisionStore._is_appreciation_message("thanks") is True
    assert DecisionStore._is_appreciation_message("this is too formal") is False


def test_user_facing_recommendation_replaces_option_ids_and_deduplicates() -> None:
    selected_id = "79162cf5-1111-4111-8111-111111111111"
    alternate_id = "8b1ed06c-2222-4222-8222-222222222222"
    options = {
        selected_id: {"title": "Polished, business-casual look that balances comfort with a professional appearance"},
        alternate_id: {"title": "Relaxed, casual look that maximizes comfort"},
    }
    result = RecommendationResult.model_validate({
        "selected_option_id": selected_id,
        "selected_option_title": options[selected_id]["title"],
        "summary": "Option 79162cf5 best matches the user's preference.",
        "concrete_example": "For example: Option 79162cf5 with breathable fabric.",
        "rationale": [
            "Option 79162cf5 balances comfort and professionalism.",
            "Option 79162cf5 balances comfort and professionalism.",
            "Option 8b1ed06c is more relaxed.",
        ],
        "assumptions": ["You prefer sweet flavors over savory ones."],
        "unresolved_uncertainties": [
            "Your specific flavor preference (sweet vs. savory).",
            "Whether you are buying for yourself or others.",
        ],
        "option_assessments": [],
        "alternate_recommendation": "Choose Option 8b1ed06c if comfort matters more.",
    })
    cleaned = _sanitize_recommendation(result, options)
    assert "79162cf5" not in cleaned.summary
    assert "79162cf5" not in (cleaned.concrete_example or "")
    assert cleaned.concrete_example == "Polished, business-casual look with breathable fabric"
    assert "8b1ed06c" not in (cleaned.alternate_recommendation or "")
    assert "the user" not in cleaned.summary.lower()
    assert len(cleaned.rationale) == 2
    assert cleaned.unresolved_uncertainties == ["Whether you are buying for yourself or others."]
    assert _short_option_label(options[selected_id]["title"]) == "Polished, business-casual look"
    assert _replace_option_references("Option 8b1ed06c is viable", options) == "Relaxed, casual look is viable"


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


def test_low_stakes_turn_limit_stops_discovery_questions() -> None:
    graph = build_decision_graph(Settings(
        _env_file=None, groq_api_key=None, decision_max_clarification_turns=8,
    ))
    history = [
        {"question": f"Question {index}?", "action": "ask_clarification"}
        for index in range(3)
    ]
    result = asyncio.run(graph.ainvoke({
        "decision_id": "bounded", "user_id": "user-1",
        "user_message": "not sure", "message_id": "turn-limit",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "Choose an outfit", "source": "explicit", "confidence": "high"},
            "question_history": history,
        },
        "existing_options": [
            {"id": "formal", "title": "Formal suit", "status": "confirmed"},
            {"id": "casual", "title": "Smart casual", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["selected_action"]["action"] == "evaluate"
    assert result["selected_action"]["target_field"] == "recommendation_consent"


def test_confirmation_after_turn_limit_proceeds_despite_missing_details(monkeypatch) -> None:
    async def provisional_recommendation(brief, options, settings):
        return RecommendationResult(
            selected_option_id="formal", selected_option_title="Formal dress",
            summary="It is a provisional choice based on the limited information.",
            concrete_example="A floor-length emerald green satin gown with a structured bodice",
            rationale=["It is one of the confirmed alternatives."],
            option_assessments=[
                {"option_id": "formal", "option_title": "Formal dress", "fit": "mixed"},
                {"option_id": "casual", "option_title": "Smart casual", "fit": "mixed"},
            ],
        )

    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", provisional_recommendation)
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "bounded", "user_id": "user-1",
        "user_message": "yes", "message_id": "consent",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "Choose an outfit", "source": "explicit", "confidence": "high"},
            "next_action": {
                "action": "evaluate", "category": "evaluation",
                "target_field": "recommendation_consent", "rationale": "Turn limit reached",
            },
        },
        "existing_options": [
            {"id": "formal", "title": "Formal dress", "status": "confirmed"},
            {"id": "casual", "title": "Smart casual", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["selected_action"]["action"] == "recommend"
    assert result["recommendation"]["robustness"] == "low"
    assert "Remaining uncertainty" in result["recommendation"]["caveat"]
    assert result["assistant_reply"].startswith(
        "I recommend A floor-length emerald green satin gown with a structured bodice."
    )
    assert "I recommend Formal dress" not in result["assistant_reply"]


def test_strict_response_schema_closes_objects_and_requires_every_field() -> None:
    response_format = _strict_response_format("question", QuestionDraft)
    schema = response_format["json_schema"]["schema"]
    assert response_format["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "default" not in schema["properties"]["acknowledges_answer"]


def test_json_validation_failure_uses_one_compact_repair() -> None:
    calls: list[dict] = []

    class Completions:
        async def create(self, *, model, **kwargs):
            calls.append({"model": model, **kwargs})
            if len(calls) == 1:
                response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
                raise BadRequestError(
                    "invalid JSON",
                    response=response,
                    body={"error": {
                        "code": "json_validate_failed",
                        "failed_generation": '{"goal":"Choose lunch"}',
                    }},
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"goal":"Choose lunch"}'))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    _, model, draft, _ = asyncio.run(_complete_structured(
        client,
        ["openai/gpt-oss-20b", "fallback"],
        stage="extraction",
        schema_name="decision_extraction",
        response_model=ExtractionDraft,
        parse=ExtractionDraft.model_validate,
        messages=[{"role": "system", "content": "a deliberately long original prompt"}],
        max_completion_tokens=500,
    ))
    assert model == "openai/gpt-oss-20b"
    assert draft.goal == "Choose lunch"
    assert [call["model"] for call in calls] == ["openai/gpt-oss-20b", "openai/gpt-oss-20b"]
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert "a deliberately long original prompt" not in json.dumps(calls[1]["messages"])


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


def test_extraction_brief_keeps_only_current_semantics() -> None:
    compact = _compact_extraction_brief({
        "goal": {"value": "Choose lunch", "id": "goal-id"},
        "values": [{"value": "Nutrition", "status": "confirmed", "id": "value-id"}],
        "criteria": [{"name": "Nutrition", "importance": 5, "status": "confirmed"}],
        "next_action": {
            "category": "options", "target_field": "options",
            "question": "Which meals?", "rationale": "large internal rationale",
        },
        "assumptions": [{"statement": "A large unused assumption"}],
        "risks": [{"title": "A large unused risk"}],
        "readiness": {"score": 0.5, "blockers": ["unused"]},
        "question_history": [{"question": "unused"}],
    })
    assert compact == {
        "goal": "Choose lunch",
        "values": ["Nutrition"],
        "criteria": [{"name": "Nutrition", "importance": 5}],
        "pending_question": {
            "category": "options", "target_field": "options", "question": "Which meals?",
        },
    }


def test_decision_token_budget_blocks_call_before_provider_use() -> None:
    brief = {"llm_usage": {"total_tokens": 950, "budget_tokens": 1_000}}
    settings = Settings(_env_file=None, decision_llm_token_budget=1_000)
    with pytest.raises(DecisionLLMBudgetError):
        _check_budget(brief, {"large": "x" * 200}, 100, settings)
    assert brief["llm_usage"]["exhausted"] is True


def test_rate_limited_model_waits_and_falls_back_once(monkeypatch) -> None:
    calls = []
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("app.llm.decision_assistant.asyncio.sleep", fake_sleep)

    class Completions:
        async def create(self, *, model, **kwargs):
            calls.append(model)
            if model == "primary":
                response = httpx.Response(
                    429, request=httpx.Request("POST", "https://api.groq.com"),
                    headers={"retry-after": "2", "x-ratelimit-remaining-tokens": "0"},
                )
                raise RateLimitError("limited", response=response, body={})
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"goal":"Choose lunch"}'))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    _, model, _, _ = asyncio.run(_complete_structured(
        client, ["primary", "fallback"], stage="extraction",
        schema_name="decision_extraction", response_model=ExtractionDraft,
        parse=ExtractionDraft.model_validate, messages=[], max_completion_tokens=500,
    ))
    assert model == "fallback"
    assert calls == ["primary", "fallback"]
    assert waits == [2.0]


def test_qwen_completion_limit_stays_below_provider_otpm_ceiling() -> None:
    assert _safe_completion_token_limit("qwen/qwen3.8-27b", 1_500) == 900
    assert _safe_completion_token_limit("qwen/another-model", 700) == 700
    assert _safe_completion_token_limit("openai/gpt-oss-20b", 1_500) == 1_500


def test_recommendation_requires_a_concrete_user_facing_choice() -> None:
    with pytest.raises(ValueError):
        RecommendationDraft(
            selected_option_id="semi-formal",
            summary="A semi-formal outfit fits the dinner.",
        )


def test_structured_completion_applies_model_specific_output_limit() -> None:
    calls = []

    class Completions:
        async def create(self, *, model, **kwargs):
            calls.append({"model": model, **kwargs})
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"goal":"Choose lunch"}'))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    asyncio.run(_complete_structured(
        client, ["qwen/qwen3.8-27b"], stage="extraction",
        schema_name="decision_extraction", response_model=ExtractionDraft,
        parse=ExtractionDraft.model_validate, messages=[], max_completion_tokens=1_500,
    ))
    assert calls[0]["max_completion_tokens"] == 900


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
    assert result["selected_action"]["category"] == "preferences"
    assert result["selected_action"]["target_field"] == "decision_context"


def test_recommendation_intent_requires_an_explicit_signal() -> None:
    assert _requests_recommendation("Go ahead and recommend one")
    assert _requests_recommendation("Nothing else")
    assert not _requests_recommendation("Stability is important to me")


def test_repeated_question_signal_is_detected() -> None:
    assert _signals_repeated_question("I already answered you")
    assert _signals_repeated_question("Please stop repeating the same question")
    assert not _signals_repeated_question("My answer is stability")


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
    assert result["brief"]["phase"] == "recommended"
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
    assert resumed["brief"]["phase"] == "recommended"
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
        "brief": {
            "preference_signals": [{
                "value": "I am choosing dinner for myself", "source": "explicit", "confidence": "high",
            }],
        },
        "existing_options": [], "profile": {},
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
    assert result["brief"]["phase"] == "recommended"


def test_failed_gap_extraction_does_not_repeat_identical_question() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-options",
        "user_id": "user-1",
        "user_message": "yes",
        "message_id": "message-options",
        "brief": {
            "goal": {"value": "Choose a job", "source": "explicit", "confidence": "high"},
            "preference_signals": [{
                "value": "I want meaningful work", "source": "explicit", "confidence": "high",
            }],
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


def test_rejecting_bad_suggested_options_does_not_force_recommendation_consent() -> None:
    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "decision-lunch",
        "user_id": "user-1",
        "user_message": "these are not lunch options",
        "message_id": "message-lunch",
        "brief": {
            "decision_stakes": "low",
            "goal": {"value": "What should I have for lunch?", "source": "explicit", "confidence": "high"},
            "values": [{"value": "healthy", "source": "explicit", "confidence": "high"}],
            "missing_information": [{
                "key": "options",
                "question_category": "options",
                "impact": 0.95,
                "reason": "Need concrete options",
            }],
            "question_history": [
                {"action": "ask_clarification", "category": "options"},
                {"action": "ask_clarification", "category": "values"},
                {"action": "ask_clarification", "category": "options"},
            ],
            "next_action": {
                "action": "ask_clarification",
                "category": "options",
                "target_field": "options",
                "attempt": 2,
                "question": "I can compare breakfast options...",
                "rationale": "Need options",
            },
        },
        "existing_options": [
            {"id": "opt-1", "title": "Greek yogurt bowl with fruit", "status": "confirmed"},
            {"id": "opt-2", "title": "Peanut-butter banana whole-grain toast", "status": "confirmed"},
        ],
        "profile": {},
    }))
    assert result["selected_action"]["action"] == "ask_clarification"
    assert result["selected_action"]["category"] == "options"


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
        "brief": {
            "preference_signals": [{
                "value": "The office is client-facing", "source": "explicit", "confidence": "high",
            }],
        },
        "existing_options": [], "profile": {},
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
    assert captured["target_field"] == "decision_context"
    assert captured["policy_question"] is None
    assert result["assistant_reply"] == "Which parts of stability matter most for this job choice?"


def test_policy_reward_requires_the_requested_target_to_change() -> None:
    before = {"values": [], "next_action": {"category": "values", "target_field": "values"}}
    unresolved = {"brief": {"values": []}, "new_options": []}
    resolved = {"brief": {"values": [{"value": "Stability"}]}, "new_options": []}
    action = before["next_action"]
    assert not DecisionStore._target_was_resolved(action, before, unresolved, [])
    assert DecisionStore._target_was_resolved(action, before, resolved, [])


def test_selected_direction_requires_concrete_candidates_before_evaluation() -> None:
    brief = DecisionBrief.model_validate({
        "goal": {"value": "Choose a birthday gift", "source": "explicit", "confidence": "high"},
        "values": [{"value": "sentimental", "source": "explicit", "confidence": "high"}],
        "preference_signals": [{
            "value": "Selected option: Personalized keepsake",
            "source": "explicit",
            "confidence": "high",
        }],
    })
    gaps = _gaps(brief, 0, selected_direction="Personalized keepsake")
    concrete_gap = next(gap for gap in gaps if gap.key == "concrete_options")
    assert "within that direction" in concrete_gap.reason


def test_confirmed_selection_ignores_broad_direction_and_binds_concrete_item() -> None:
    options = [
        {
            "id": "direction", "title": "Personalized keepsake", "status": "confirmed",
            "metadata": {"specificity": "direction"},
        },
        {
            "id": "photo-book", "title": "Custom photo book", "status": "confirmed",
            "metadata": {"specificity": "actionable"},
        },
        {
            "id": "engraved", "title": "Engraved bracelet", "status": "confirmed",
            "metadata": {"specificity": "actionable"},
        },
    ]
    direction_only = {"preference_signals": [{"value": "Selected option: Personalized keepsake"}]}
    assert _confirmed_actionable_selection(direction_only, options) is None

    concrete = {"preference_signals": [{"value": "Selected option: Custom photo book"}]}
    selected = _confirmed_actionable_selection(concrete, options)
    assert selected and selected["id"] == "photo-book"

    draft = RecommendationDraft(
        selected_option_id="engraved",
        summary="A bracelet would work.",
        concrete_example="An engraved bracelet with her initials and a meaningful date",
    )
    with pytest.raises(ValueError, match="confirmed option selection"):
        _validate_recommendation_selection(draft, selected)


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


def test_recommend_now_infers_options_and_recommends_without_more_questions(monkeypatch) -> None:
    async def extracted(*args, **kwargs):
        return DecisionStatePatch()

    async def inferred(*args, **kwargs):
        return [
            OptionObservation(
                title="Custom photo book",
                description="A compact book built from shared photos and captions.",
                source="ai_generated",
                specificity="actionable",
            ),
            OptionObservation(
                title="Engraved bracelet",
                description="A wearable keepsake with a short personal inscription.",
                source="ai_generated",
                specificity="actionable",
            ),
        ]

    async def recommended(brief, options, settings):
        assert len(options) == 2
        assert all(str(option["id"]).startswith("provisional-") for option in options)
        return RecommendationResult(
            selected_option_id=options[0]["id"],
            selected_option_title=options[0]["title"],
            summary="It is the strongest provisional fit for the limited context.",
            rationale=["It directly answers the gift decision with a concrete item."],
            option_assessments=[
                {
                    "option_id": option["id"],
                    "option_title": option["title"],
                    "fit": "strong" if index == 0 else "mixed",
                }
                for index, option in enumerate(options)
            ],
            robustness="low",
        )

    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted)
    monkeypatch.setattr("app.graph.workflow.generate_immediate_options", inferred)
    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", recommended)

    graph = build_decision_graph(Settings(_env_file=None, groq_api_key=None))
    result = asyncio.run(graph.ainvoke({
        "decision_id": "early-exit",
        "user_id": "user-1",
        "user_message": "Give me a recommendation now",
        "message_id": "force-recommendation",
        "brief": {
            "decision_stakes": "low",
            "goal": {
                "value": "Choose a birthday gift",
                "source": "explicit",
                "confidence": "high",
            },
        },
        "existing_options": [],
        "profile": {},
    }))

    assert result["selected_action"]["action"] == "recommend"
    assert len(result["new_options"]) == 2
    assert result["recommendation"]["selected_option_title"] == "Custom photo book"
    assert result["recommendation"]["robustness"] == "low"
    assert result["assistant_reply"].startswith("I recommend Custom photo book")
    assert any(
        "alternatives used for this immediate recommendation were inferred" in item["statement"]
        for item in result["brief"]["assumptions"]
    )


def test_retry_workflow_replays_saved_revision_feedback(monkeypatch) -> None:
    user = AuthenticatedUser(id=uuid4(), email="person@example.com", access_token="token")
    store = DecisionStore(
        Settings(_env_file=None, supabase_url="https://example.supabase.co", supabase_anon_key="anon"),
        user,
    )
    decision_id = uuid4()
    option_payload = {"id": "opt-1", "title": "Smart casual look", "status": "confirmed"}
    decision = SimpleNamespace(
        status="evaluating",
        decision_brief={
            "phase": "revision_pending",
            "revision_policy": {
                "revision_budget_total": 2,
                "revision_budget_used": 1,
                "pending_feedback": "this feels too formal for casual dinner",
            },
        },
        recommendation={"selected_option_title": "Classic and polished"},
        options=[SimpleNamespace(model_dump=lambda mode="json", data=option_payload: data)],
        messages=[],
    )

    calls: dict[str, str] = {}

    async def fake_get(target_decision_id):
        assert target_decision_id == decision_id
        return decision

    async def fake_insert_message(client, target_decision_id, role, content, **kwargs):
        assert target_decision_id == decision_id
        assert role == "user"
        calls["content"] = content
        return SimpleNamespace(id="retry-user-message", content=content)

    async def fake_handle_revision(client, target_decision_id, user_message, brief, options, recommendation):
        assert target_decision_id == decision_id
        assert user_message.id == "retry-user-message"
        assert brief["phase"] == "revision_pending"
        assert recommendation["selected_option_title"] == "Classic and polished"
        assert options[0]["title"] == "Smart casual look"
        return SimpleNamespace(role="assistant", content="revised")

    monkeypatch.setattr(store, "get", fake_get)
    monkeypatch.setattr(store, "_insert_message", fake_insert_message)
    monkeypatch.setattr(store, "_handle_recommendation_revision", fake_handle_revision)

    message = asyncio.run(store.retry_workflow(decision_id))
    assert message.content == "revised"
    assert calls["content"] == "this feels too formal for casual dinner"
