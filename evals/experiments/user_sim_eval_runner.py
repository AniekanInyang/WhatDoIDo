#!/usr/bin/env python3
"""Generate validated decision cases and run bounded, observable API conversations.

Generation and execution are separate. Live execution defaults to exactly one case.
"""
from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUCKETS = ("career", "finance", "health", "relationships", "education", "purchase", "travel", "lifestyle")

# Fixed strata describe coverage, not assistant responses or expected winners.
SCENARIOS = [
    ("career", "two paid internships in different business functions"),
    ("finance", "monthly versus annual billing for a software subscription with cancellation uncertainty"),
    ("health", "a beginner walking group versus a beginner yoga class for general activity"),
    ("relationships", "hosting friends at home versus meeting at a restaurant"),
    ("education", "a live evening course versus a self-paced course to learn a specific skill"),
    ("purchase", "repairing an older laptop versus buying a refurbished laptop"),
    ("travel", "taking a train versus renting a car for a weekend trip"),
    ("lifestyle", "a shared coworking desk versus improving a home workspace"),
    ("career", "a higher-paying onsite job versus a lower-paying remote job"),
    ("finance", "buying an appliance upfront versus an interest-free installment plan with a fixed household budget"),
    ("health", "a lunchtime walking routine versus an after-work swimming routine for general activity"),
    ("relationships", "joining a weekly book club versus volunteering to meet new friends"),
    ("education", "a small-group language class versus one-to-one tutoring"),
    ("purchase", "a compact printer versus using a neighborhood print shop"),
    ("travel", "staying near a city center versus a quieter hotel outside town"),
    ("lifestyle", "a meal-prep service versus a weekly home batch-cooking session"),
    ("career", "a technical individual-contributor role versus a first team-lead role"),
    ("finance", "a prepaid transit pass versus pay-per-trip fares with variable office attendance"),
    ("health", "a nearby gym membership versus a community recreation-center pass for general activity"),
    ("relationships", "a family picnic versus a small indoor family gathering"),
    ("education", "a weekend portfolio workshop versus an online mentored project"),
    ("purchase", "a lightweight commuter bicycle versus a folding bicycle"),
    ("travel", "a short guided walking tour versus exploring a city independently"),
    ("lifestyle", "an apartment near work versus a larger apartment with a longer commute"),
    ("career", "taking a funded certification course versus an internal stretch assignment"),
]

INITIAL_CASES_PROMPT = """Create synthetic decision-support eval inputs, not assistant answers.
Return one JSON object {"cases": [...]} with exactly the requested number of cases.
Each case has: scenario_bucket, difficulty (easy|medium|hard), persona,
options (exactly two distinct concrete option titles), initial_user_message,
hidden_state {goal, values (list), constraints (list), facts (object with at least
four concrete user facts INCLUDING option_details: {each option title: {cost, time, upside, downside}}),
uncertainties (list of specific missing facts), uncertainty_level, patience_level}.
For deterministic cases also provide deterministic_rules: exactly four objects
{target: options|values|constraints|uncertainties, when_contains_any: [question keywords], reply: first-person factual user answer}.
Use each target once. Every rule reply must restate facts in hidden_state, never introduce new facts.
Make keywords broad enough to match ordinary questions (budget, time, priority, limits, unknown).
Rules must cover priorities, constraints, options and uncertainties. Replies answer
questions AS THE USER; never instruct the assistant/user how to solve the problem.
Use short noun phrases for option titles and copy them into initial_user_message.
The opening must describe a real choice between BOTH named options, in at most
40 words, with some context but leave meaningful facts for follow-up questions.
Provide realistic quantities, time limits, priorities and tradeoffs in the hidden
profile. No real personal data. Keep all messages consistent with that profile.
Avoid generic advice requests, placeholder alternatives, fabricated expert claims,
medical treatment choices, investment picks, or legal decisions. For health use
low-stakes lifestyle choices only. Do not ask the assistant to blindly pick a
preselected winner; the point is a grounded recommendation from the supplied facts.
Honor the supplied scenario descriptions, buckets and difficulties IN ORDER, one case per slot.
Do not use calendar dates or years; use relative dates such as next month.
Every option must have a cost, time requirement, upside and downside in option_details.
For uncertainties, name a concrete unknown (for example future attendance), not a numeric uncertainty rating.
Keep each case compact. Do not include assistant conversations or recommendations.
"""
FOLLOW_UP_PROMPT = """Act as the user described by the hidden profile in this decision chat.
Return JSON {"message": "..."}, containing exactly one first-person user message.
Answer the assistant's latest question directly using the supplied facts. Preserve
all earlier facts and the two original options. Reveal relevant facts rather than
asking more questions. Never invent facts or give advice as if you were the assistant.
Respond naturally to repetition, according to the persona and patience level.
You may ask for a recommendation when it makes sense in context, but never because
of the turn number. Do not dump the hidden profile or force a recommendation.
Keep the response below 65 words. Do not mention simulation or evaluation.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


class AzureSimulator:
    def __init__(self) -> None:
        names = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_VERSION", "AZURE_OPENAI_GPT4_O_MINI_MODEL")
        values = [os.getenv(name, "") for name in names]
        missing = [name for name, value in zip(names, values) if not value]
        if missing:
            raise RuntimeError("Missing Azure configuration: " + ", ".join(missing))
        endpoint, self.api_key, self.api_version, self.deployment = values
        self.url = endpoint.rstrip("/") + f"/openai/deployments/{self.deployment}/chat/completions"

    def chat_json(self, messages: list[dict], *, temperature: float, max_tokens: int, timeout_seconds: float) -> dict:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(self.url, params={"api-version": self.api_version},
                                   headers={"api-key": self.api_key},
                                   json={"messages": messages, "temperature": temperature,
                                         "max_tokens": max_tokens, "response_format": {"type": "json_object"}})
        response.raise_for_status()
        body = response.json()
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Simulator output truncated; refusing partial cases")
        return json.loads(choice["message"]["content"])


def fetch_supabase_access_token_from_password(*, allow_direct_token: bool = True) -> str | None:
    direct = os.getenv("DECISION_EVAL_ACCESS_TOKEN")
    if direct and allow_direct_token:
        return direct
    email = os.getenv("DECISION_EVAL_EMAIL") or os.getenv("TEST_EMAIL")
    password = os.getenv("DECISION_EVAL_PASSWORD") or os.getenv("TEST_PASSWORD")
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if not all((email, password, url, key)):
        return None
    response = httpx.post(url.rstrip("/") + "/auth/v1/token", params={"grant_type": "password"},
                          headers={"apikey": key}, json={"email": email, "password": password}, timeout=30)
    response.raise_for_status()
    return response.json()["access_token"]


def option_is_named(title: str, opening: str) -> bool:
    # Accept grammatical inflections, but require every substantive title word.
    stopwords = {"a", "an", "the", "to", "of", "for", "with", "my", "her", "his", "our", "out", "and", "in", "at"}
    def words(text):
        return [re.sub(r"([a-z])\1$", r"\1", re.sub(r"(ing|ed|s)$", "", word)) for word in re.findall(r"[a-z0-9]+", text.casefold())
                if word not in stopwords]
    title_words, opening_words = words(title), words(opening)
    return bool(title_words) and all(any(word == other or (len(word) >= 4 and len(other) >= 4 and
                SequenceMatcher(None, word, other).ratio() >= .85) for other in opening_words)
                for word in title_words)


def validate_case(case: dict, suite: str) -> None:
    if case.get("suite") != suite:
        raise ValueError("Suite mismatch")
    if case.get("scenario_bucket") not in BUCKETS or case.get("difficulty") not in {"easy", "medium", "hard"}:
        raise ValueError("Invalid scenario bucket or difficulty")
    options = case.get("options", [])
    if len(options) != 2 or any(not isinstance(x, str) or len(x.strip()) < 3 for x in options) or options[0].casefold() == options[1].casefold():
        raise ValueError("Need two distinct concrete option titles")
    opening = case.get("initial_user_message", "")
    if not opening or len(opening.split()) > 65 or not all(option_is_named(x, opening) for x in options):
        raise ValueError(f"Opening must name both alternatives in <=65 words. options={options!r}; opening={opening!r}")
    profile = case.get("hidden_state", {})
    if not profile.get("goal") or not profile.get("values") or not isinstance(profile.get("constraints"), list) or not isinstance(profile.get("facts"), dict):
        raise ValueError("Incomplete hidden user profile")
    option_details = profile["facts"].get("option_details", {})
    if not all(title in option_details and all(option_details[title].get(k) is not None for k in ("cost", "time", "upside", "downside")) for title in options):
        raise ValueError("Each option needs factual cost, time, upside and downside")
    if not profile.get("uncertainties"):
        raise ValueError("Need specific unknowns in the hidden profile")
    if suite == "deterministic":
        rules = case.get("deterministic_rules", [])
        if len(rules) != 4 or {r.get("target") for r in rules} != {"options", "values", "constraints", "uncertainties"}:
            raise ValueError("Deterministic cases need exactly four answer rules covering options, values, constraints, uncertainties")
        for rule in rules:
            reply = rule.get("reply", "").strip()
            if not rule.get("when_contains_any") or not reply or len(reply.split()) > 90:
                raise ValueError("Invalid deterministic response rule")
            if reply.lower().startswith(("you should", "consider ", "focus on ", "list your ", "try ")):
                raise ValueError("Deterministic response is advice, not a user answer")


def generate_cases(sim: AzureSimulator, suite: str, total: int, progress_path: Path | None = None) -> list[dict]:
    cases = read_jsonl(progress_path) if progress_path and progress_path.exists() else []
    for case in cases:
        validate_case(case, suite)
    for offset in range(len(cases), total):
        bucket, description = SCENARIOS[offset % len(SCENARIOS)]
        slot = {"scenario_bucket": bucket, "scenario_description": description,
                "difficulty": ("easy", "medium", "hard")[offset % 3]}
        error = ""
        for attempt in range(5):
            try:
                payload = sim.chat_json([
                    {"role": "system", "content": INITIAL_CASES_PROMPT},
                    {"role": "user", "content": json.dumps({"suite": suite, "slots": [slot],
                     "count": 1, "previous_validation_error": error,
                     "avoid_goals": [c["hidden_state"]["goal"] for c in cases]})}],
                    temperature=0.55, max_tokens=8000, timeout_seconds=90)
                batch = payload["cases"]
                if len(batch) != 1:
                    raise ValueError("Incorrect batch length")
                case = batch[0]
                case.update(suite=suite, case_id=f"{suite}_{offset + 1:03d}", scenario_description=description)
                # Explicit labels preserve generated context without inventing alternatives.
                if not all(title.casefold() in case.get("initial_user_message", "").casefold() for title in case.get("options", [])):
                    case["initial_user_message"] += " My options are " + " or ".join(case["options"]) + "."
                validate_case(case, suite)
                if any(case[k] != slot[k] for k in ("scenario_bucket", "difficulty")):
                    raise ValueError("Generated case did not honor assigned stratum")
                break
            except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                error = str(exc)
                print(f"{suite} case {offset + 1} generation attempt {attempt + 1} rejected: {error[:400]}", flush=True)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 404}:
                    raise
                if isinstance(exc, httpx.HTTPError):
                    time.sleep(2 ** attempt)
        else:
            raise ValueError("Input generation failed validation: " + error)
        cases.append(case)
        if progress_path:
            write_jsonl(progress_path, cases)
        print(f"Generated and validated {len(cases)}/{total} {suite} inputs", flush=True)
    return cases


def recommendation_is_valid(detail: dict) -> bool:
    rec = detail.get("recommendation") or {}
    options = {str(o["id"]) for o in detail.get("options", []) if o.get("status") != "rejected"}
    return bool(rec.get("selected_option_id") in options and rec.get("summary", "").strip()
                and rec.get("rationale") and rec.get("selected_option_title"))


def latest_error(detail: dict) -> dict | None:
    last = next((m for m in reversed(detail.get("messages", [])) if m.get("role") == "assistant"), {})
    data = last.get("structured_data") or {}
    return data if data.get("workflow_error") else None


def classify_failure(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout_failure"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return {401: "auth_failure", 403: "auth_failure", 429: "rate_limit_failure"}.get(code, "http_failure")
    return "runtime_failure"


class Backend:
    def __init__(self, base_url: str, token: str, request_timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(request_timeout, connect=10),
                                   headers={"Authorization": "Bearer " + token})
        self.requests: list[dict] = []

    def request(self, method: str, path: str, payload: dict | None = None) -> Any:
        # Writes are NEVER blindly retried. Callers reconcile using client-chosen IDs.
        for attempt in range(3 if method == "GET" else 1):
            started = time.monotonic()
            entry = {"method": method, "path": path, "started_at": utc_now()}
            try:
                response = self.client.request(method, self.base_url + path, json=payload)
                entry["status_code"] = response.status_code
                if response.status_code == 401:
                    token = fetch_supabase_access_token_from_password(allow_direct_token=False)
                    if token:
                        self.client.headers["Authorization"] = "Bearer " + token
                        # A rejected authentication request has not executed a write.
                        response = self.client.request(method, self.base_url + path, json=payload)
                        entry["status_after_refresh"] = response.status_code
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                entry["error_type"] = type(exc).__name__
                transient = isinstance(exc, httpx.TimeoutException) or exc.response.status_code in {408, 429, 500, 502, 503, 504}
                if method != "GET" or not transient or attempt == 2:
                    raise
                time.sleep(1 + attempt)
            finally:
                entry["duration_seconds"] = round(time.monotonic() - started, 3)
                self.requests.append(entry)

    def detail(self, decision_id: str) -> dict:
        return self.request("GET", f"/decisions/{decision_id}")

    def wait_for_reply(self, decision_id: str, user_id: str | None, deadline: float) -> dict:
        while time.monotonic() < deadline:
            try:
                detail = self.detail(decision_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                time.sleep(2)
                continue
            messages = detail.get("messages", [])
            if user_id is None:
                if any(m.get("role") == "assistant" for m in messages):
                    return detail
            else:
                position = next((i for i, m in enumerate(messages) if m["id"] == user_id), None)
                if position is not None:
                    for m in messages[position + 1:]:
                        if m.get("role") == "user":
                            break
                        if m.get("role") == "assistant":
                            return detail
            time.sleep(2)
        raise TimeoutError("No saved assistant reply before reconciliation deadline")


def next_user_message(case: dict, detail: dict, turn_number: int, sim: AzureSimulator | None, used_rules: set[int]) -> str:
    transcript = [{"role": m["role"], "content": m["content"]} for m in detail.get("messages", [])]
    if case["suite"] == "deterministic":
        assistant = next((m for m in reversed(detail.get("messages", [])) if m["role"] == "assistant"), {})
        action = (assistant.get("structured_data") or {}).get("action") or {}
        target = action.get("target_field") or action.get("category")
        target = {"concrete_options": "options", "criteria": "values", "criterion_importance": "values"}.get(target, target)
        for index, rule in enumerate(case["deterministic_rules"]):
            if rule["target"] == target:
                if index in used_rules:
                    return "I already answered: " + rule["reply"]
                used_rules.add(index)
                return rule["reply"]
        question = assistant.get("content", "").casefold()
        for index, rule in enumerate(case["deterministic_rules"]):
            if index not in used_rules and any(k.casefold() in question for k in rule["when_contains_any"]):
                used_rules.add(index)
                return rule["reply"]
        # Stable, complete user facts when the assistant asks an unanticipated question.
        return " ".join(rule["reply"] for rule in case["deterministic_rules"])
    if sim is None:
        raise ValueError("Stochastic cases require a simulator")
    result = sim.chat_json([
        {"role": "system", "content": FOLLOW_UP_PROMPT},
        {"role": "user", "content": json.dumps({"hidden_profile": case["hidden_state"],
         "options": case["options"], "persona": case["persona"], "transcript": transcript})}],
        temperature=0.35, max_tokens=220, timeout_seconds=45)
    message = result.get("message", "").strip()
    if not message or len(message.split()) > 65:
        raise ValueError("Invalid simulator follow-up; refusing to substitute a canned response")
    return message


def run_case(backend: Backend, case: dict, *, sim: AzureSimulator | None, max_turns: int | None,
             conversation_timeout: float, workflow_retries: int) -> dict:
    validate_case(case, case["suite"])
    started = time.monotonic()
    deadline = started + conversation_timeout
    decision_id = str(uuid4())
    result = {"case_id": case["case_id"], "suite": case["suite"], "started_at": utc_now(),
              "decision_id": decision_id, "status": "running", "failure_class": None,
              "termination_reason": None, "error": None, "turns": [], "recoveries": [],
              "snapshots": [], "input": case}
    detail: dict = {}
    try:
        try:
            backend.request("POST", "/decisions", {"id": decision_id, "prompt": case["initial_user_message"]})
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {409, 500, 502, 503, 504}:
                raise
            result["recoveries"].append({"operation": "create", "reason": type(exc).__name__, "action": "reconcile_saved_state"})
        detail = backend.wait_for_reply(decision_id, None, deadline)
        used_rules: set[int] = set()
        retries_used = 0
        turn_number = 1
        while True:
            result["snapshots"].append(detail)
            failure = latest_error(detail)
            if failure:
                if failure.get("retry_available") and retries_used < workflow_retries:
                    retries_used += 1
                    recovery = {"operation": "workflow_retry", "failure": failure, "attempt": retries_used}
                    result["recoveries"].append(recovery)
                    delays = []
                    for stage in failure.get("stages", []):
                        raw = (stage.get("rate_headers") or {}).get("retry-after")
                        try:
                            delays.append(max(0.0, float(raw)))
                        except (TypeError, ValueError):
                            pass
                    delay = max(delays, default=0)
                    recovery["retry_after_seconds"] = delay
                    if time.monotonic() + delay >= deadline:
                        raise TimeoutError("Provider retry window exceeds the conversation deadline")
                    if delay:
                        time.sleep(delay)
                    try:
                        backend.request("POST", f"/decisions/{decision_id}/workflow/retry")
                    except httpx.TimeoutException:
                        old_ids = {m["id"] for m in detail.get("messages", [])}
                        while time.monotonic() < deadline:
                            detail = backend.detail(decision_id)
                            if any(m["role"] == "assistant" and m["id"] not in old_ids for m in detail.get("messages", [])):
                                break
                            time.sleep(2)
                        else:
                            raise TimeoutError("Workflow retry did not produce a saved reply")
                    detail = backend.detail(decision_id)
                    continue
                result.update(status="failed", failure_class=failure["workflow_error"],
                              termination_reason="workflow_failure", error=failure["workflow_error"])
                break
            if recommendation_is_valid(detail):
                result.update(status="completed", termination_reason="recommendation_delivered")
                break
            if max_turns is not None and turn_number >= max_turns:
                result.update(status="incomplete", termination_reason="turn_limit_without_recommendation")
                break
            if time.monotonic() >= deadline:
                result.update(status="incomplete", termination_reason="safety_time_limit_without_recommendation")
                break
            turn_number += 1
            content = next_user_message(case, detail, turn_number, sim, used_rules)
            message_id = str(uuid4())
            entry = {"turn_index": turn_number, "user_message_id": message_id, "content": content}
            result["turns"].append(entry)  # Persist attempted turns even when transport fails.
            try:
                backend.request("POST", f"/decisions/{decision_id}/messages", {"id": message_id, "content": content})
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {409, 500, 502, 503, 504}:
                    raise
                result["recoveries"].append({"operation": "message", "message_id": message_id,
                                             "reason": type(exc).__name__, "action": "reconcile_saved_state"})
            detail = backend.wait_for_reply(decision_id, message_id, deadline)
    except Exception as exc:
        result.update(status="failed", failure_class=classify_failure(exc),
                      termination_reason="operational_failure", error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            detail = backend.detail(decision_id)
        except Exception as exc:
            result["detail_export_error"] = type(exc).__name__
        try:
            result["state_events"] = backend.request("GET", f"/decisions/{decision_id}/events")
        except Exception as exc:
            result["state_events"] = []
            result["events_export_error"] = type(exc).__name__
        result["final_state"] = detail
        result["final_transcript"] = detail.get("messages", [])
        result["recommendation"] = detail.get("recommendation")
        result["stage_traces"] = [e for e in result["state_events"] if e.get("event_type") == "llm_turn_metrics"]
        result["requests"] = backend.requests
        result["finished_at"] = utc_now()
        result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def main() -> int:
    load_dotenv(PROJECT_ROOT / "apps/backend/.env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--regenerate-inputs", action="store_true")
    parser.add_argument("--resume-generation", action="store_true", help="Resume validated partial inputs; never resume or overwrite live runs")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-stochastic", action="store_true", help="Compatibility alias for --run --suite stochastic")
    parser.add_argument("--suite", choices=["deterministic", "stochastic"], default="deterministic")
    parser.add_argument("--max-cases", type=int, default=1)
    parser.add_argument("--input-count", type=int, default=25, help="Cases per suite when generating inputs")
    parser.add_argument("--max-turns", type=int, default=None, help="Optional safety cap; no default turn limit and never forces a recommendation")
    parser.add_argument("--request-timeout", type=float, default=180)
    parser.add_argument("--conversation-timeout", type=float, default=900)
    parser.add_argument("--workflow-retries", type=int, default=1)
    parser.add_argument("--input-path", type=Path)
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.run_stochastic:
        args.run, args.suite = True, "stochastic"
    if args.max_cases < 1 or args.input_count < 1 or (args.max_turns is not None and args.max_turns < 2) or args.workflow_retries < 0:
        parser.error("Counts must be positive; max-turns must be >=2; retries must be >=0")
    run_root = PROJECT_ROOT / "test_set" / args.date / args.run_id
    if run_root.exists() and (not args.resume_generation or (run_root / "outputs").exists() or args.run):
        parser.error("Run directory already exists; choose a new --run-id to preserve history")
    run_root.mkdir(parents=True, exist_ok=args.resume_generation)
    sim = None
    if args.regenerate_inputs or args.generate_only or (args.run and not args.input_path):
        sim = AzureSimulator()
        def generate_suite(suite):
            if args.resume_generation and (run_root / "inputs" / f"{suite}_cases.jsonl").exists():
                return
            cases = generate_cases(sim, suite, args.input_count, run_root / "inputs" / f"{suite}_cases.partial.jsonl")
            write_jsonl(run_root / "inputs" / f"{suite}_cases.jsonl", cases)
            (run_root / "inputs" / f"{suite}_cases.partial.jsonl").unlink(missing_ok=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(generate_suite, suite) for suite in ("deterministic", "stochastic")]
            for future in futures:
                future.result()
        write_json(run_root / "inputs" / "manifest.json", {"generated_at": utc_now(), "model": sim.deployment,
                   "count_per_suite": args.input_count, "case_prompt": INITIAL_CASES_PROMPT,
                   "follow_up_prompt": FOLLOW_UP_PROMPT})
    if args.generate_only or not args.run:
        print(f"Validated inputs saved to {run_root / 'inputs'}")
        return 0
    path = args.input_path or run_root / "inputs" / f"{args.suite}_cases.jsonl"
    cases = read_jsonl(path)[:args.max_cases]
    if not cases:
        raise ValueError("No input cases")
    for case in cases:
        validate_case(case, args.suite)
    if args.suite == "stochastic" and sim is None:
        sim = AzureSimulator()
    try:
        token = fetch_supabase_access_token_from_password()
        if not token:
            raise RuntimeError("Missing backend evaluation credentials")
    except Exception as exc:
        preflight = {"status": "failed", "termination_reason": "authentication_preflight_failure",
                     "error_type": type(exc).__name__, "error": str(exc),
                     "total_cases": 0, "created_decisions": 0, "checked_at": utc_now()}
        write_json(run_root / "outputs" / "preflight.json", preflight)
        print(json.dumps(preflight), flush=True)
        return 1
    results = []
    for case in cases:
        backend = Backend(args.backend_base_url, token, args.request_timeout)
        try:
            result = run_case(backend, case, sim=sim, max_turns=args.max_turns,
                              conversation_timeout=args.conversation_timeout, workflow_retries=args.workflow_retries)
        finally:
            backend.client.close()
        write_json(run_root / "outputs" / "cases" / f"{case['case_id']}.json", result)
        results.append(result)
        print(json.dumps({k: result[k] for k in ("case_id", "status", "termination_reason", "decision_id", "error")}), flush=True)
    summary = {"started_at": results[0]["started_at"], "finished_at": utc_now(), "total_cases": len(results),
               "completed_cases": sum(r["status"] == "completed" for r in results),
               "incomplete_cases": sum(r["status"] == "incomplete" for r in results),
               "failed_cases": sum(r["status"] == "failed" for r in results),
               "mean_duration_seconds": statistics.mean(r["duration_seconds"] for r in results)}
    write_json(run_root / "outputs" / "summary.json", summary)
    print(f"Run artifacts: {run_root}")
    return 0 if all(r["status"] == "completed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
