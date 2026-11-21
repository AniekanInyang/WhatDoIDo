import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.graph.state import ClarificationProfile, Criterion, DecisionStatePatch, OptionObservation, RecommendationResult
from app.graph.workflow import build_decision_graph
from app.llm.decision_assistant import (
    DecisionLLMGenerationError, ExtractionDraft, _merge_contextual_answer, extract_decision_patch,
)
from app.services.decisions import DecisionStore

FAILED_PRIORITY_REPLIES = [('005',
  'I value interaction and engagement, so the Live Evening Course seems appealing despite the fixed '
  'schedule. However, I also appreciate the flexibility of the Self-Paced Course. Given my beginner '
  'level and evening availability, I might lean towards the Live Evening Course for the real-time '
  'feedback.'),
 ('006',
  'Given my budget and the need for a working device soon, I think I should go with the Buy Refurbished '
  'Laptop option. It fits my budget and offers better performance, even if it may not last as long as a '
  'new one.'),
 ('008',
  'Productivity is my top priority, but I also need to stay within my monthly budget. The Improved Home '
  'Workspace costs less and offers comfort, while the Shared Coworking Desk has networking '
  "opportunities but comes with a monthly fee. I'm leaning towards improving my home setup."),
 ('010',
  'Minimizing the total amount paid is my top priority. The upfront cost is high, but the installment '
  'plan has a slightly higher total cost. I want to stick to my budget and make a cost-effective '
  'decision.'),
 ('011',
  'For me, the physical health benefits and how easily it fits into my existing schedule are the most '
  'important factors. The Lunchtime Walking Routine is cost-free and fits well into my flexible '
  'schedule, but I need to consider the weather. The After-Work Swimming Routine offers a full-body '
  "workout but requires a gym membership. I'm leaning towards the walking routine."),
 ('013',
  'I value cost-effectiveness and personalized learning. The small-group class is more affordable, but '
  "I'm unsure if it suits my interactive learning style. One-to-one tutoring is tailored but exceeds my "
  'budget. I need to weigh the benefits of social interaction against the need for personalized '
  'attention.'),
 ('014',
  'Affordability is my top priority, but convenience is also important since I need to print weekly. '
  'The compact printer costs $150, which fits my budget, while the neighborhood print shop charges '
  '$0.10 per page, which could add up quickly.'),
 ('017',
  "I'm really focused on career growth and job satisfaction. I think opportunities for personal growth "
  "will be key in my decision, especially since I'm considering the Team Lead role for leadership "
  'experience.'),
 ('020',
  'I prioritize family bonding and enjoyment over affordability and comfort. The Family Picnic aligns '
  'perfectly with those values, especially with the sunny weather and ample outdoor space. It sounds '
  'like the best choice for our gathering.'),
 ('023',
  'I value cultural experience and learning from locals, so the Guided Walking Tour appeals to me for '
  'its insights. However, I also appreciate the flexibility of Independent City Exploration. Given my '
  'budget and time constraints, I think the Guided Walking Tour might be the better option.'),
 ('024',
  'The 30-minute commute is manageable, but I worry about how it might impact my personal time. The '
  '$200 savings is nice, but I really want the extra space for entertaining. I think I might lean '
  'towards the Larger Apartment with the longer commute.')]

@pytest.mark.parametrize("case_id,message", FAILED_PRIORITY_REPLIES)
def test_long_priority_answers_preserve_evidence_without_becoming_criterion_names(case_id, message):
    patch = _merge_contextual_answer(
        DecisionStatePatch(), message, "reply-" + case_id,
        {"next_action": {"category": "values"}},
    )
    assert patch.criteria == []
    assert any(f.value == message and f.evidence_message_ids == ["reply-" + case_id]
               for f in patch.preference_signals)


def test_long_answer_keeps_model_extracted_criteria_and_their_weights():
    message = FAILED_PRIORITY_REPLIES[0][1]
    patch = DecisionStatePatch(values=[{"value": "interaction"}], criteria=[Criterion(name="interaction", importance=4)])
    result = _merge_contextual_answer(patch, message, "reply", {"next_action": {"category": "values"}})
    assert [(c.name, c.importance) for c in result.criteria] == [("interaction", 4)]
    assert [f.value for f in result.values] == ["interaction"]
    assert result.preference_signals[-1].value == message


@pytest.mark.parametrize("provider_fails", [False, True])
def test_public_extraction_handles_long_answers_on_success_and_provider_failure(monkeypatch, provider_fails):
    async def complete(*args, **kwargs):
        if provider_fails:
            raise DecisionLLMGenerationError("provider unavailable")
        draft = ExtractionDraft(values=["interaction"], criteria=[{"name": "interaction", "importance": 4}])
        completion = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        return completion, "test-model", draft, draft.model_dump_json()
    monkeypatch.setattr("app.llm.decision_assistant._complete_structured", complete)
    message = FAILED_PRIORITY_REPLIES[0][1]
    patch = asyncio.run(extract_decision_patch(
        message, "reply", {"goal": {"value": "Choose a course"}, "next_action": {"category": "values"}},
        Settings(_env_file=None, groq_api_key="test", llm_stage_delay_seconds=0),
    ))
    assert any(f.value == message for f in patch.preference_signals)
    assert all(len(c.name) <= 200 for c in patch.criteria)
    if not provider_fails:
        assert [(c.name, c.importance) for c in patch.criteria] == [("interaction", 4)]


@pytest.mark.parametrize("reply,attempt", [("5", 1), ("yes", 3)])
def test_weighting_old_long_values_does_not_create_oversized_criterion(reply, attempt):
    patch = _merge_contextual_answer(DecisionStatePatch(), reply, "rating", {
        "next_action": {"category": "criteria", "attempt": attempt},
        "values": [{"value": FAILED_PRIORITY_REPLIES[0][1], "status": "confirmed"},
                   {"value": "reliability", "status": "confirmed"}],
    })
    assert [c.name for c in patch.criteria] == ["reliability"]


@pytest.mark.parametrize("infer_second_option", [False, True])
def test_new_options_have_stable_ids_through_evaluation_and_persistence(monkeypatch, infer_second_option):
    async def extracted(*args, **kwargs):
        options = [{"title": "Walking group", "specificity": "actionable", "source": "user_provided"}]
        if not infer_second_option:
            options.append({"title": "Beginner yoga class", "specificity": "actionable", "source": "user_provided"})
        return DecisionStatePatch(goal={"value": "Choose general activity"}, decision_stakes="low", options=options)
    async def infer(*args, **kwargs):
        assert infer_second_option, "Already-complete alternatives must not trigger extra inference"
        return [OptionObservation(title="Beginner yoga class", source="ai_generated")]
    seen = []
    async def recommend(brief, options, settings):
        assert len(options) == 2
        assert len({o["id"] for o in options}) == 2
        seen.append([(o["id"], o["title"]) for o in options])
        return RecommendationResult(
            selected_option_id=options[0]["id"], selected_option_title=options[0]["title"],
            summary="The walking group fits the supplied context.", rationale=["Fits the available time."],
            option_assessments=[{"option_id": o["id"], "option_title": o["title"], "fit": "mixed"} for o in options],
        )
    monkeypatch.setattr("app.graph.workflow.extract_decision_patch", extracted)
    monkeypatch.setattr("app.graph.workflow.generate_immediate_options", infer)
    monkeypatch.setattr("app.graph.workflow.generate_grounded_recommendation", recommend)
    graph = build_decision_graph(Settings(_env_file=None))
    payload = {"decision_id": str(uuid4()), "user_id": str(uuid4()), "message_id": "new-options",
               "user_message": "Please recommend an option now", "brief": {}, "existing_options": [], "profile": {}}
    result = asyncio.run(graph.ainvoke(payload))
    replay = asyncio.run(graph.ainvoke(payload))
    assert seen[0] == seen[1], "Retrying the same turn must not change temporary IDs"
    assert len(result["new_options"]) == 2
    assert {o["id"] for o in result["new_options"]} == {key for key, _ in seen[0]}
    assert replay["recommendation"]["selected_option_id"] == result["recommendation"]["selected_option_id"]

    store = DecisionStore(Settings(_env_file=None, supabase_url="https://example.test", supabase_anon_key="key"),
                          AuthenticatedUser(id=uuid4(), access_token="token"))
    saved_ids, updates = [], []
    async def request(client, method, path, **kwargs):
        if method == "POST" and path == "decision_options":
            saved_ids.append(str(uuid4()))
            return [{"id": saved_ids[-1]}]
        if method == "PATCH" and path == "decisions":
            updates.append(kwargs["json"])
        return []
    async def record(*args, **kwargs):
        pass
    async def insert(*args, **kwargs):
        return SimpleNamespace(content=args[3])
    monkeypatch.setattr(store, "_request", request)
    monkeypatch.setattr(store, "_record_state_event", record)
    monkeypatch.setattr(store, "_insert_message", insert)
    asyncio.run(store._persist_graph_result(None, uuid4(), SimpleNamespace(id=uuid4()), [], ClarificationProfile(), result))
    saved = updates[0]
    assert set(saved["decision_brief"]["option_ids"]) == set(saved_ids)
    assert saved["recommendation"]["selected_option_id"] == saved_ids[0]
    assert {a["option_id"] for a in saved["recommendation"]["option_assessments"]} == set(saved_ids)


@pytest.mark.parametrize("stale_oversized_name", [False, True])
def test_cached_extraction_keeps_valid_labels_or_regenerates_invalid_legacy_labels(monkeypatch, stale_oversized_name):
    message = FAILED_PRIORITY_REPLIES[0][1]
    cached = {"values": ["interaction"], "criteria": [{"name": message if stale_oversized_name else "interaction", "importance": 4}]}
    monkeypatch.setattr("app.llm.decision_assistant._cached_content", lambda *args: json.dumps(cached))
    regenerated = []
    async def complete(*args, **kwargs):
        assert stale_oversized_name, "A valid cached extraction should not call a provider"
        regenerated.append(True)
        draft = ExtractionDraft(values=["interaction"], criteria=[{"name": "interaction", "importance": 4}])
        completion = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        return completion, "test-model", draft, draft.model_dump_json()
    monkeypatch.setattr("app.llm.decision_assistant._complete_structured", complete)
    patch = asyncio.run(extract_decision_patch(
        message, "reply", {"goal": {"value": "Choose a course"}, "next_action": {"category": "values"}},
        Settings(_env_file=None, groq_api_key="test"),
    ))
    assert [(c.name, c.importance) for c in patch.criteria] == [("interaction", 4)]
    assert patch.preference_signals[-1].value == message
    assert bool(regenerated) == stale_oversized_name
