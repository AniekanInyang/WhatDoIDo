import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location("eval_runner", Path(__file__).parents[1] / "experiments/user_sim_eval_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture
def case():
    return {"case_id": "deterministic_001", "suite": "deterministic", "scenario_bucket": "career",
            "difficulty": "medium", "persona": "A developer choosing training.",
            "options": ["Evening course", "Weekend workshop"],
            "initial_user_message": "I am deciding between Evening course and Weekend workshop to learn testing.",
            "hidden_state": {"goal": "Learn testing", "values": ["practice"], "constraints": ["$400 budget"],
                             "uncertainties": ["Quality of course feedback"],
                             "facts": {"budget": 400, "hours": 4, "experience": "beginner", "option_details": {
                                 title: {"cost": 200, "time": "4 hours", "upside": "practice", "downside": "limited feedback"}
                                 for title in ("Evening course", "Weekend workshop")}}},
            "deterministic_rules": [{"target": target, "when_contains_any": [key], "reply": reply} for target, key, reply in [
                ("constraints", "budget", "I have $400 available."), ("values", "priority", "I value hands-on practice."),
                ("options", "options", "I am choosing between Evening course and Weekend workshop."),
                ("uncertainties", "unknown", "I do not know how much feedback each course provides.")]]}


def detail(error=None, recommendation=False):
    metadata = {"workflow_error": error, "retry_available": True} if error else {}
    return {"messages": [{"id": "u", "role": "user", "content": "My choice"},
                         {"id": "a", "role": "assistant", "content": "A question?", "structured_data": metadata}],
            "decision_brief": {"phase": "recommended" if recommendation else "clarifying"},
            "options": [{"id": "o", "title": "Evening course"}],
            "recommendation": {"selected_option_id": "o", "selected_option_title": "Evening course",
                               "summary": "Choose the course.", "rationale": ["Fits the schedule."]} if recommendation else None}


class FakeBackend:
    def __init__(self, value, *, timeout_on_send=False, recovered=None):
        self.value = value
        self.requests = []
        self.timeout_on_send = timeout_on_send
        self.recovered = recovered
        self.reconciliations = []

    def request(self, method, path, payload=None):
        self.requests.append({"method": method, "path": path, "payload": payload})
        if path.endswith("/events"):
            return [{"event_type": "llm_turn_metrics", "payload": {"stages": [{"stage": "question"}]}}]
        if path.endswith("/workflow/retry"):
            self.value = self.recovered
        if method == "POST" and path.endswith("/messages") and self.timeout_on_send:
            raise httpx.ReadTimeout("timed out")
        return {}

    def detail(self, decision_id):
        return self.value

    def wait_for_reply(self, decision_id, user_id, deadline):
        self.reconciliations.append(user_id)
        return self.value


def run(backend, case, retries=0):
    return runner.run_case(backend, case, sim=None, max_turns=3, conversation_timeout=30, workflow_retries=retries)


def test_http_success_with_workflow_error_is_failure(case):
    result = run(FakeBackend(detail(error="rate_limited")), case)
    assert result["status"] == "failed"
    assert result["termination_reason"] == "workflow_failure"
    assert result["final_transcript"][-1]["structured_data"]["workflow_error"] == "rate_limited"
    assert result["stage_traces"]


def test_turn_exhaustion_is_incomplete(case):
    result = run(FakeBackend(detail()), case)
    assert result["status"] == "incomplete"
    assert result["termination_reason"] == "turn_limit_without_recommendation"
    assert result["recommendation"] is None


def test_recommendation_requires_saved_option_and_rationale():
    data = detail(recommendation=True)
    assert runner.recommendation_is_valid(data)
    data["recommendation"]["selected_option_id"] = "nonexistent"
    assert not runner.recommendation_is_valid(data)


def test_workflow_failure_retries_workflow_without_another_user_message(case):
    backend = FakeBackend(detail(error="rate_limited"), recovered=detail(recommendation=True))
    result = run(backend, case, retries=1)
    assert result["status"] == "completed"
    assert len(result["recoveries"]) == 1
    assert not any(r["path"].endswith("/messages") for r in backend.requests)
    assert result["snapshots"][0]["messages"][-1]["structured_data"]["workflow_error"]


def test_write_timeout_reconciles_original_message_id_without_resending(case):
    backend = FakeBackend(detail(), timeout_on_send=True)
    result = run(backend, case)
    writes = [r for r in backend.requests if r["path"].endswith("/messages")]
    assert len(writes) == 2  # Two distinct turns, no retry of either timed-out POST.
    assert len({r["payload"]["id"] for r in writes}) == 2
    assert backend.reconciliations[1:] == [r["payload"]["id"] for r in writes]
    assert len(result["turns"]) == 2


def test_deterministic_answers_are_not_changed_by_turn_number(case):
    data = detail()
    data["messages"][-1]["content"] = "What is your budget?"
    assert runner.next_user_message(case, data, 2, None, set()) == "I have $400 available."
    assert runner.next_user_message(case, data, 30, None, set()) == "I have $400 available."


def test_bad_seed_advice_rejected(case):
    case["deterministic_rules"][0]["reply"] = "You should make a budget."
    with pytest.raises(ValueError, match="advice"):
        runner.validate_case(case, "deterministic")


def test_timed_out_exception_classified_without_string_matching():
    assert runner.classify_failure(httpx.ReadTimeout("timed out")) == "timeout_failure"


def test_auth_preflight_failure_exports_zero_attempted_cases(case, tmp_path, monkeypatch):
    import sys
    source = tmp_path / "inputs.jsonl"
    runner.write_jsonl(source, [case])
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["runner", "--run", "--input-path", str(source),
                                     "--date", "2026-11-09", "--run-id", "preflight"])
    def fail_auth(**kwargs):
        raise httpx.ConnectError("DNS resolution failed")
    monkeypatch.setattr(runner, "fetch_supabase_access_token_from_password", fail_auth)
    assert runner.main() == 1
    output = tmp_path / "test_set/2026-11-09/preflight/outputs/preflight.json"
    result = runner.json.loads(output.read_text())
    assert result["total_cases"] == result["created_decisions"] == 0
    assert result["termination_reason"] == "authentication_preflight_failure"
    assert not (output.parent / "cases").exists()


def test_deterministic_response_uses_saved_target_before_overlapping_keywords(case):
    data = detail()
    data["messages"][-1].update(content="What is your budget for these options?",
                               structured_data={"action": {"target_field": "constraints"}})
    case["deterministic_rules"].insert(0, {"target": "options", "when_contains_any": ["budget"],
                                           "reply": "I am comparing the two courses."})
    assert runner.next_user_message(case, data, 2, None, set()) == "I have $400 available."


def test_stochastic_user_is_generated_even_at_late_turns(case):
    case["suite"] = "stochastic"
    class Simulator:
        def chat_json(self, messages, **kwargs):
            assert "hidden_profile" in messages[-1]["content"]
            return {"message": "I can spend up to $400, including materials."}
    assert runner.next_user_message(case, detail(), 30, Simulator(), set()) == "I can spend up to $400, including materials."


def test_no_default_turn_cap_allows_system_to_recommend_after_six_turns(case):
    class Backend(FakeBackend):
        def wait_for_reply(self, decision_id, user_id, deadline):
            self.reconciliations.append(user_id)
            if len(self.reconciliations) == 8:
                self.value = detail(recommendation=True)
            return self.value
    backend = Backend(detail())
    result = runner.run_case(backend, case, sim=None, max_turns=None, conversation_timeout=30, workflow_retries=0)
    assert result["status"] == "completed"
    assert len(result["turns"]) == 7
