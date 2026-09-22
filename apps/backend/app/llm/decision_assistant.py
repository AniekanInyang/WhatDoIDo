import json
import hashlib
import logging
import re

from groq import AsyncGroq, BadRequestError, RateLimitError
from pydantic import BaseModel

from app.core.config import Settings
from app.graph.state import (
    ActionPlan,
    DecisionRisk,
    DecisionStatePatch,
    Criterion,
    Fact,
    OptionObservation,
    QuestionDraft,
    RecommendationResult,
)


logger = logging.getLogger(__name__)


def _strict_response_format(name: str, model: type[BaseModel]) -> dict:
    """Build a Groq-compatible strict JSON schema from a Pydantic model."""
    schema = model.model_json_schema()

    def close_objects(node) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                close_objects(value)
        elif isinstance(node, list):
            for value in node:
                close_objects(value)

    close_objects(schema)
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def _is_json_validation_failure(exc: Exception) -> bool:
    if not isinstance(exc, BadRequestError):
        return False
    body = getattr(exc, "body", None)
    return "json_validate_failed" in json.dumps(body or {}).lower() or "json" in str(exc).lower()


class DecisionLLMRateLimitError(RuntimeError):
    pass


class DecisionLLMBudgetError(RuntimeError):
    pass


class DecisionLLMGenerationError(RuntimeError):
    pass


def _active_payload(items: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in item.items() if key not in {"id", "evidence_message_ids"}}
        for item in items
        if item.get("status") not in {"rejected", "superseded"}
    ]


def _compact_brief(brief: dict) -> dict:
    """Keep only decision semantics needed by the models."""
    compact = {
        key: brief.get(key)
        for key in (
            "goal", "domain", "deadline", "risk_tolerance", "decision_stakes",
            "resolved_absences", "readiness", "next_action",
        )
        if brief.get(key) is not None
    }
    for key in ("values", "constraints", "uncertainties", "criteria", "preference_signals", "assumptions", "risks"):
        if brief.get(key):
            compact[key] = _active_payload(brief[key])
    return compact


def _compact_options(options: list[dict]) -> list[dict]:
    return [
        {key: option.get(key) for key in ("id", "title", "description", "source", "status") if option.get(key) is not None}
        for option in options if option.get("status") != "rejected"
    ]


def _usage(brief: dict, settings: Settings) -> dict:
    usage = brief.setdefault("llm_usage", {})
    usage.setdefault("prompt_tokens", 0)
    usage.setdefault("completion_tokens", 0)
    usage.setdefault("total_tokens", 0)
    usage.setdefault("calls", 0)
    usage.setdefault("cache_hits", 0)
    usage.setdefault("budget_tokens", settings.decision_llm_token_budget)
    usage["budget_tokens"] = min(int(usage["budget_tokens"]), settings.decision_llm_token_budget)
    usage.setdefault("exhausted", False)
    return usage


def _cache_key(task: str, payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{task}:{hashlib.sha256(encoded).hexdigest()}"


def _cached_content(brief: dict, key: str, settings: Settings) -> str | None:
    cached = (brief.setdefault("llm_cache", {})).get(key)
    if cached and isinstance(cached.get("content"), str):
        usage = _usage(brief, settings)
        usage["cache_hits"] += 1
        return cached["content"]
    return None


def _check_budget(brief: dict, payload: dict, max_tokens: int, settings: Settings) -> None:
    usage = _usage(brief, settings)
    estimated_prompt = max(1, len(json.dumps(payload, default=str)) // 4)
    if usage["total_tokens"] + estimated_prompt + max_tokens > usage["budget_tokens"]:
        usage["exhausted"] = True
        raise DecisionLLMBudgetError("This decision has reached its AI token budget")


def _record_completion(brief: dict, completion, cache_key: str, content: str, model: str, settings: Settings) -> None:
    usage = _usage(brief, settings)
    provider_usage = completion.usage
    prompt_tokens = int(getattr(provider_usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(provider_usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(provider_usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    usage["prompt_tokens"] += prompt_tokens
    usage["completion_tokens"] += completion_tokens
    usage["total_tokens"] += total_tokens
    usage["calls"] += 1
    cache = brief.setdefault("llm_cache", {})
    cache[cache_key] = {"content": content, "model": model}
    if len(cache) > 16:
        del cache[next(iter(cache))]


async def _complete_with_fallback(client: AsyncGroq, models: list[str | None], **kwargs):
    last_error: Exception | None = None
    rate_limited = False
    for model in dict.fromkeys(model for model in models if model):
        for attempt in range(2):
            request_kwargs = dict(kwargs)
            if model.startswith("openai/gpt-oss-"):
                request_kwargs.setdefault("reasoning_effort", "low")
            try:
                return await client.chat.completions.create(model=model, **request_kwargs), model
            except RateLimitError as exc:
                rate_limited = True
                last_error = exc
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0 and _is_json_validation_failure(exc):
                    logger.warning("Model %s returned invalid JSON; retrying once", model)
                    continue
                break
    if rate_limited:
        raise DecisionLLMRateLimitError("The AI provider's usage limit has been reached") from last_error
    if last_error:
        raise last_error
    raise RuntimeError("No LLM model is configured")


def _normalize_option_title(value: str) -> str:
    cleaned = re.sub(r"^[\s,.;:!-]+|[\s,.;:!?-]+$", "", value.strip())
    cleaned = re.sub(r"^(?:yes|yeah|yep|no)[,.!]?\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(?:today|tomorrow|tonight|this\s+(?:morning|afternoon|evening|week|weekend))$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _explicit_options_from_answer(message: str, current_brief: dict) -> list[dict[str, str | None]]:
    previous_action = current_brief.get("next_action") or {}
    normalized = " ".join(message.strip().split())
    match = re.search(r"\beither\s+(.+?)\s+or\s+(.+)$", normalized, flags=re.IGNORECASE)
    framed_decision = bool(match)
    if not match:
        match = re.search(r"\bshould\s+i\s+(.+?)\s+or\s+(.+?)[?.!]*$", normalized, flags=re.IGNORECASE)
        framed_decision = bool(match)
    if not match:
        match = re.search(r"\bwhether\s+(?:to\s+)?(.+?)\s+or\s+(.+?)[?.!]*$", normalized, flags=re.IGNORECASE)
        framed_decision = bool(match)
    if not match:
        match = re.search(r"\b(?:choose|decide)\s+between\s+(.+?)\s+and\s+(.+?)[?.!]*$", normalized, flags=re.IGNORECASE)
        framed_decision = bool(match)
    if not match:
        if previous_action.get("category") == "options":
            match = re.search(r"^(.+?)\s+or\s+(.+)$", normalized, flags=re.IGNORECASE)
            if not match:
                match = re.search(r"^(.+?)\s+(?:and|versus|vs\.?|/)\s+(.+)$", normalized, flags=re.IGNORECASE)
    if not match and previous_action.get("category") != "options":
        return []
    candidates = list(match.groups()) if match else []
    if framed_decision and candidates:
        action_verbs = {
            "accept", "apply", "buy", "choose", "cook", "eat", "get", "go", "have",
            "leave", "make", "move", "order", "rent", "sell", "stay", "take", "use", "visit", "wear",
        }
        left_words = candidates[0].split()
        right_words = candidates[1].split()
        if (
            len(left_words) > 1
            and left_words[0].lower() in action_verbs
            and right_words
            and right_words[0].lower() not in action_verbs
        ):
            candidates[0] = " ".join(left_words[1:])
    if not candidates:
        lines = [
            re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line).strip()
            for line in message.splitlines()
            if line.strip()
        ]
        if len(lines) >= 2:
            candidates = lines

    titles = [_normalize_option_title(candidate) for candidate in candidates]
    titles = [title for title in titles if 1 < len(title) <= 200]
    return [
        {"title": title, "description": None, "source": "user_provided", "kind": "alternative"}
        for title in dict.fromkeys(titles)
    ]


def _merge_explicit_options(
    patch: DecisionStatePatch, message: str, current_brief: dict
) -> DecisionStatePatch:
    extracted = _explicit_options_from_answer(message, current_brief)
    known = {option.title.lower().strip() for option in patch.options}
    for option in extracted:
        if str(option["title"]).lower().strip() not in known:
            patch.options.append(OptionObservation.model_validate(option))
            known.add(str(option["title"]).lower().strip())
    if extracted:
        patch.is_decision_input = True
        patch.non_decision_reason = None
    return patch


def _meaningful_short_answer(message: str) -> bool:
    normalized = " ".join(message.strip().split())
    lowered = normalized.lower()
    return bool(normalized) and lowered not in {
        "yes", "no", "none", "nothing", "no constraints", "no constraint",
        "maybe", "i don't know", "i dont know", "not sure", "skip"
    } and not any(phrase in lowered for phrase in ("you tell me", "i said i don't know", "i said i dont know"))


def _split_compound_values(message: str) -> list[str]:
    """Split a short explicit priority answer without attempting broad NLP."""
    normalized = " ".join(message.strip().split())
    normalized = re.split(r"\s+because\b", normalized, maxsplit=1, flags=re.IGNORECASE)[0]
    normalized = re.sub(r"^(?:my|the)\s+", "", normalized, flags=re.IGNORECASE)
    parts = re.split(r"\s*(?:,|\band\b|&)\s*", normalized, flags=re.IGNORECASE)
    cleaned = [part.strip(" .!?") for part in parts if part.strip(" .!?")]
    if 2 <= len(cleaned) <= 4 and all(len(part.split()) <= 6 for part in cleaned):
        return cleaned
    return [normalized] if normalized else []


def _merge_contextual_answer(
    patch: DecisionStatePatch, message: str, message_id: str, current_brief: dict
) -> DecisionStatePatch:
    """Resolve terse replies against the semantic target of the pending question.

    This guardrail complements LLM extraction. It intentionally handles only fields
    where the user's exact text can be saved without inventing an interpretation.
    """
    action = current_brief.get("next_action") or {}
    category = action.get("category")
    normalized_answer = " ".join(message.lower().split())
    absent_answer = normalized_answer.strip(" .!?") in {
        "none", "nothing", "no constraints", "no constraint", "no hard limits",
        "no uncertainties", "no major uncertainties", "no particular risk preference",
    }
    if absent_answer and category in {"constraints", "uncertainties", "risk"}:
        field = "risk_tolerance" if category == "risk" else category
        patch.resolved_absences = list(dict.fromkeys([*patch.resolved_absences, field]))
        patch.constraints = [
            item for item in patch.constraints
            if " ".join(str(item.value).lower().split()) not in {"none", "nothing"}
        ]
        patch.uncertainties = [
            item for item in patch.uncertainties
            if " ".join(str(item.value).lower().split()) not in {"none", "nothing"}
        ]
        if (
            patch.risk_tolerance
            and " ".join(str(patch.risk_tolerance.value).lower().split()) in {"none", "nothing"}
        ):
            patch.risk_tolerance = None
        patch.is_decision_input = True
        patch.non_decision_reason = None
        return patch
    importance_match = re.search(r"\b([1-5])\b", normalized_answer)
    if category == "criteria" and importance_match and not patch.criteria:
        importance = int(importance_match.group(1))
        for value in current_brief.get("values", []):
            if value.get("status") not in {"rejected", "superseded"}:
                patch.criteria.append(Criterion(
                    name=str(value.get("value")), importance=importance, source="explicit",
                    confidence="high", status="confirmed", evidence_message_ids=[message_id],
                ))
        if patch.criteria:
            patch.is_decision_input = True
            patch.non_decision_reason = None
        return patch
    if (
        category == "criteria"
        and int(action.get("attempt", 1)) >= 3
        and normalized_answer in {"yes", "yes please", "correct", "that works"}
        and not patch.criteria
    ):
        for value in current_brief.get("values", []):
            if value.get("status") not in {"rejected", "superseded"}:
                patch.criteria.append(Criterion(
                    name=str(value.get("value")), importance=3, source="confirmed",
                    confidence="high", status="confirmed", evidence_message_ids=[message_id],
                ))
        if patch.criteria:
            patch.is_decision_input = True
            patch.non_decision_reason = None
        return patch
    if not _meaningful_short_answer(message):
        return patch
    fact = Fact(value=message.strip(), source="explicit", confidence="high", status="confirmed",
                evidence_message_ids=[message_id])
    if category == "values":
        values = _split_compound_values(message)
        combined = " ".join(message.lower().split())
        normalized_values = {" ".join(value.lower().split()) for value in values}
        if len(values) > 1 or combined not in normalized_values:
            patch.values = [
                item for item in patch.values
                if " ".join(str(item.value).lower().split()) != combined
            ]
        known = {" ".join(str(item.value).lower().split()) for item in patch.values}
        for value in values:
            if value.lower() not in known:
                patch.values.append(Fact(
                    value=value, source="explicit", confidence="high", status="confirmed",
                    evidence_message_ids=[message_id],
                ))
                known.add(value.lower())
        known_criteria = {" ".join(item.name.lower().split()): item for item in patch.criteria}
        for value in values:
            key = " ".join(value.lower().split())
            criterion = known_criteria.get(key)
            if criterion:
                criterion.importance = 5
                criterion.source = "explicit"
                criterion.confidence = "high"
                criterion.status = "confirmed"
                criterion.evidence_message_ids = list(dict.fromkeys([
                    *criterion.evidence_message_ids, message_id,
                ]))
            else:
                patch.criteria.append(Criterion(
                    name=value,
                    importance=5,
                    source="explicit",
                    confidence="high",
                    status="confirmed",
                    evidence_message_ids=[message_id],
                ))
    elif category == "constraints" and not patch.constraints:
        patch.constraints.append(fact)
    elif category == "uncertainties" and not patch.uncertainties:
        patch.uncertainties.append(fact)
    elif category == "risk" and patch.risk_tolerance is None:
        patch.risk_tolerance = fact
    if category in {"values", "constraints", "uncertainties", "risk"}:
        patch.is_decision_input = True
        patch.non_decision_reason = None
    return patch


EXTRACTION_PROMPT = """Extract a structured patch for a personal decision.
Return JSON only with these keys: is_decision_input, non_decision_reason,
direction_change, direction_change_summary, decision_stakes, goal, domain, deadline, values,
constraints, uncertainties, criteria, risk_tolerance, preference_signals,
assumptions, risks, options, resolved_absences. Treat a reply as decision input when an existing
brief shows that it answers the coach's question, even if the reply is short.
Set is_decision_input=false for greetings, unrelated requests, incoherent text,
or content that does not describe or advance a decision. Set direction_change
only when the user explicitly replaces the central decision, not when they add
or correct one detail. Never rewrite the existing goal merely because the user
supplies a format, channel, attribute, example, preference, constraint, or option.
Classify decision_stakes from consequence and reversibility: low for readily
reversible choices with minor consequences, medium for meaningful but manageable
tradeoffs, and high for decisions with serious financial, health, safety, legal,
career, or relationship consequences. Facts have value, source, confidence, status, and
evidence_message_ids. Inferred facts use status=candidate; explicit facts use
status=confirmed. Criteria include name, description, importance from 1 to 5,
source, confidence, status, and evidence. Do not invent importance: use 3 when
unspecified. Assumptions are claims required to reason that the user has not
confirmed; include importance and confidence. Risks include title, description,
severity, likelihood, mitigation, source, status, and evidence. Only record
facts supported by the message or clearly mark them inferred/candidate. Each
option observation has kind=alternative or kind=context. An alternative
must be a mutually selectable alternative that could answer the central decision.
A format, channel, medium, feature, attribute, criterion, audience, or topic is
kind=context—not an alternative—unless the user is explicitly comparing choices of
that same kind. For example, in “what should I post?” carousel is a format while
wedding content and travel content can be alternatives. Extract every actual
option the user supplies, including alternatives embedded directly in the central
question (for example, "should I choose A or B"). Never generate new options in
the extraction step. User options use source=user_provided. When the user says
there are no constraints, uncertainties, or risk preference, leave that fact list
empty and add the corresponding field to resolved_absences. Do not recommend an option. Use
low/medium/high confidence and explicit/inferred/confirmed/system_derived source."""


async def extract_decision_patch(
    message: str,
    message_id: str,
    current_brief: dict,
    settings: Settings,
) -> DecisionStatePatch:
    """Extract observations; return a safe minimal patch when the provider is unavailable."""
    fallback = DecisionStatePatch()
    normalized = " ".join(message.lower().strip().split())
    non_decision = not current_brief and (
        normalized in {"hi", "hello", "hey", "thanks", "thank you"}
        or len(normalized.split()) < 2
    )
    if non_decision:
        fallback = DecisionStatePatch(
            is_decision_input=False,
            non_decision_reason="The message does not yet describe a decision.",
        )
    elif not current_brief.get("goal"):
        fallback = DecisionStatePatch(
            goal={
                "value": message.strip(),
                "source": "explicit",
                "confidence": "high",
                "evidence_message_ids": [message_id],
            }
        )
    # Straight answers to a known question do not need a provider round trip.
    # This also makes these common turns deterministic instead of allowing an
    # extraction model to reinterpret the user's exact words.
    pending_category = (current_brief.get("next_action") or {}).get("category")
    if pending_category == "options" and _explicit_options_from_answer(message, current_brief):
        return _merge_explicit_options(fallback, message, current_brief)
    if pending_category in {"values", "constraints", "uncertainties", "risk"} and len(message.split()) <= 16:
        return _merge_contextual_answer(fallback, message, message_id, current_brief)
    if pending_category == "criteria" and re.search(r"\b[1-5]\b", message):
        return _merge_contextual_answer(fallback, message, message_id, current_brief)
    if not settings.groq_api_key:
        fallback = _merge_explicit_options(fallback, message, current_brief)
        return _merge_contextual_answer(fallback, message, message_id, current_brief)

    payload = {
        "message_id": message_id,
        "current_brief": _compact_brief(current_brief),
        "new_message": message,
    }
    key = _cache_key("extraction", payload)
    cached = _cached_content(current_brief, key, settings)
    if cached:
        parsed = DecisionStatePatch.model_validate_json(cached)
        parsed = _merge_explicit_options(parsed, message, current_brief)
        return _merge_contextual_answer(parsed, message, message_id, current_brief)
    _check_budget(current_brief, payload, settings.extraction_max_tokens, settings)
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
    )
    try:
        completion, used_model = await _complete_with_fallback(
            client, [settings.groq_light_model, settings.groq_light_fallback_model],
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0,
            response_format=_strict_response_format("decision_state_patch", DecisionStatePatch),
            max_completion_tokens=settings.extraction_max_tokens,
        )
        content = completion.choices[0].message.content or "{}"
        _record_completion(current_brief, completion, key, content, used_model, settings)
        parsed = DecisionStatePatch.model_validate_json(content)
        parsed = _merge_explicit_options(parsed, message, current_brief)
        return _merge_contextual_answer(parsed, message, message_id, current_brief)
    except (DecisionLLMRateLimitError, DecisionLLMBudgetError):
        raise
    except Exception:
        fallback = _merge_explicit_options(fallback, message, current_brief)
        return _merge_contextual_answer(fallback, message, message_id, current_brief)


QUESTION_PROMPT = """Write one concise, natural clarification question for a
personal decision. The workflow has already selected what information to seek;
do not choose a different target and do not evaluate or recommend. Use the goal,
options, known facts, latest answer, and rationale to make the wording specific.
Do not ask for information already present. Do not repeat any forbidden question.
When semantic_target is options, ask for two or more mutually exclusive choices
that could directly answer the central decision. Do not ask for a format, channel,
feature, audience, style, or general category unless those are themselves the
alternatives being compared.
Never introduce an alternative only in the prose. If you offer concrete
alternatives, return every one in suggested_options with source=ai_generated and
kind=alternative, and mention those exact titles in the question. Otherwise ask
an open-ended question and return an empty suggested_options array. Do not use an
“A or B” construction unless both A and B are in suggested_options.
Mention maintaining the status quo or "keeping things as they are" only when it
is a genuinely possible option for this specific decision. Never suggest it for
time-bound consumption or selection decisions such as choosing a meal.
When semantic_target is criterion_importance, the factors are already known.
Ask only for their importance, weighting, or ranking; never ask which factors
the user wants to compare.
When the latest answer advanced the state, briefly acknowledge it before asking.
Return JSON only with question, target_field, expected_answer_type,
acknowledges_answer, and suggested_options. The question must contain exactly one
primary question."""


def _normalize_question_payload(payload: dict) -> dict:
    normalized = dict(payload)
    acknowledgement = normalized.get("acknowledges_answer", False)
    if isinstance(acknowledgement, str):
        normalized["acknowledges_answer"] = acknowledgement.strip().lower() in {
            "true", "yes", "1",
        }
    elif not isinstance(acknowledgement, bool):
        normalized["acknowledges_answer"] = False
    return normalized


async def generate_clarification_question(
    action: ActionPlan,
    brief: dict,
    options: list[dict],
    latest_message: str,
    settings: Settings,
) -> QuestionDraft:
    if not settings.groq_api_key:
        raise DecisionLLMGenerationError("Question generation requires an AI provider")
    forbidden = [item.get("question") for item in brief.get("question_history", [])[-8:]]
    if (brief.get("next_action") or {}).get("question"):
        forbidden.append(brief["next_action"]["question"])
    payload = {
        "semantic_target": action.target_field or action.category,
        "expected_answer_type": action.expected_answer_type,
        "rationale": action.rationale,
        "decision_brief": _compact_brief(brief),
        "options": _compact_options(options),
        "latest_user_message": latest_message,
        "forbidden_questions": forbidden,
    }
    key = _cache_key("question", payload)
    cached = _cached_content(brief, key, settings)
    if cached:
        try:
            return QuestionDraft.model_validate_json(cached)
        except Exception:
            pass
    try:
        _check_budget(brief, payload, settings.question_max_tokens, settings)
    except DecisionLLMBudgetError:
        raise
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
    )
    last_error: Exception | None = None
    rate_limited = False
    for model in dict.fromkeys(
        model for model in [settings.groq_light_model, settings.groq_light_fallback_model] if model
    ):
        for attempt in range(2):
            try:
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": QUESTION_PROMPT},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                    temperature=0.35,
                    response_format=_strict_response_format("clarification_question", QuestionDraft),
                    max_completion_tokens=settings.question_max_tokens,
                    **({"reasoning_effort": "low"} if model.startswith("openai/gpt-oss-") else {}),
                )
                content = completion.choices[0].message.content or "{}"
                draft = QuestionDraft.model_validate(_normalize_question_payload(json.loads(content)))
                draft.target_field = action.target_field or action.category
                previous = {" ".join(str(question).lower().split()) for question in forbidden if question}
                normalized_question = " ".join(draft.question.lower().split())
                semantic_mismatch = (
                    draft.target_field == "uncertainties"
                    and any(phrase in normalized_question for phrase in ("hard limit", "non-negotiable", "infeasible"))
                ) or (
                    draft.target_field == "constraints"
                    and any(phrase in normalized_question for phrase in ("how important", "rank the importance"))
                )
                suggested_titles = {
                    " ".join(option.title.lower().split()) for option in draft.suggested_options
                }
                suggestion_mismatch = bool(draft.suggested_options) and any(
                    title not in normalized_question for title in suggested_titles
                )
                untracked_choice = (
                    draft.target_field == "options"
                    and " or " in normalized_question
                    and not draft.suggested_options
                )
                if (
                    normalized_question in previous
                    or "?" not in draft.question
                    or semantic_mismatch
                    or suggestion_mismatch
                    or untracked_choice
                ):
                    raise ValueError("The generated question did not satisfy the selected semantic target")
                _record_completion(brief, completion, key, content, model, settings)
                return draft
            except RateLimitError as exc:
                rate_limited = True
                last_error = exc
                logger.warning("Question model %s was rate limited: %s", model, exc)
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0 and _is_json_validation_failure(exc):
                    logger.warning("Question model %s returned invalid JSON; retrying once", model)
                    continue
                logger.warning("Question model %s failed (%s): %s", model, type(exc).__name__, exc)
                break
    if rate_limited and isinstance(last_error, RateLimitError):
        raise DecisionLLMRateLimitError("All configured question models are rate limited") from last_error
    raise DecisionLLMGenerationError("No configured model produced a valid clarification question") from last_error


RECOMMENDATION_PROMPT = """Produce a grounded recommendation from the supplied
decision brief and persisted options. Return JSON only. Select exactly one of
the supplied option IDs. Respect hard constraints before preferences. Do not
invent facts, scores, probabilities, or evidence. Compare every option. Include:
selected_option_id, selected_option_title, summary, rationale,
option_assessments (option_id, option_title, fit, strengths, tradeoffs,
constraint_conflicts), assumptions, unresolved_uncertainties,
key_risks (title, description, severity, likelihood, option_ids, mitigation,
source, status, evidence_message_ids), checks_before_acting,
alternate_recommendation,
sensitivity_analysis (factor, current_assumption, change_that_could_flip_result,
likely_winner_option_id or null, explanation), robustness (low/moderate/high),
and caveat. Sensitivity analysis must explain concrete plausible changes that
could change the winner. All fields described as lists must be JSON arrays.
The only allowed option-assessment fit values are weak, mixed, or strong.
Acknowledge insufficient evidence through assumptions, uncertainties, caveat,
and lower robustness. Never invent measurements, durations, prices, outcomes,
or comparisons that do not appear in the supplied data. If the evidence cannot
distinguish the options, say so plainly and make the selection conditional on a
clearly named assumption rather than fabricating support."""


def _as_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return [str(value)]


def _normalize_recommendation_payload(payload: dict) -> dict:
    """Coerce harmless provider shape drift before strict domain validation."""
    normalized = dict(payload)
    for field in ("rationale", "assumptions", "unresolved_uncertainties", "checks_before_acting"):
        normalized[field] = _as_string_list(normalized.get(field))

    assessments = normalized.get("option_assessments") or []
    if isinstance(assessments, dict):
        assessments = list(assessments.values())
    fit_aliases = {
        "high": "strong", "good": "strong", "best": "strong",
        "moderate": "mixed", "medium": "mixed", "partial": "mixed",
        "low": "weak", "poor": "weak",
    }
    for assessment in assessments:
        if not isinstance(assessment, dict):
            continue
        fit = str(assessment.get("fit", "mixed")).lower()
        assessment["fit"] = fit_aliases.get(fit, fit if fit in {"weak", "mixed", "strong"} else "mixed")
        for field in ("strengths", "tradeoffs", "constraint_conflicts"):
            assessment[field] = _as_string_list(assessment.get(field))
    normalized["option_assessments"] = [item for item in assessments if isinstance(item, dict)]

    sensitivity = normalized.get("sensitivity_analysis") or []
    if isinstance(sensitivity, dict):
        sensitivity = [sensitivity]
    normalized["sensitivity_analysis"] = sensitivity

    risks = normalized.get("key_risks") or []
    if isinstance(risks, dict):
        risks = [risks]
    normalized_risks = []
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        risk = dict(risk)
        # These are generated analytical risks, not verbatim user facts.
        risk["source"] = "inferred"
        risk["status"] = "candidate"
        likelihood = str(risk.get("likelihood", "unknown")).lower()
        risk["likelihood"] = likelihood if likelihood in {"unlikely", "possible", "likely", "unknown"} else "unknown"
        severity = str(risk.get("severity", "moderate")).lower()
        risk["severity"] = severity if severity in {"low", "moderate", "high", "critical"} else "moderate"
        risk["option_ids"] = _as_string_list(risk.get("option_ids"))
        risk["evidence_message_ids"] = _as_string_list(risk.get("evidence_message_ids"))
        normalized_risks.append(risk)
    normalized["key_risks"] = normalized_risks
    robustness = str(normalized.get("robustness", "low")).lower()
    normalized["robustness"] = robustness if robustness in {"low", "moderate", "high"} else "low"
    return normalized


async def generate_grounded_recommendation(
    brief: dict,
    options: list[dict],
    settings: Settings,
) -> RecommendationResult | None:
    if not settings.groq_api_key or len(options) < 2:
        return None
    payload = {"decision_brief": _compact_brief(brief), "options": _compact_options(options)}
    key = _cache_key("recommendation", payload)
    cached = _cached_content(brief, key, settings)
    if cached:
        raw = json.loads(cached)
        result = RecommendationResult.model_validate(_normalize_recommendation_payload(raw))
    else:
        _check_budget(brief, payload, settings.recommendation_max_tokens, settings)
        client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(), timeout=30.0, max_retries=0
        )
        try:
            completion, used_model = await _complete_with_fallback(
                client, [settings.groq_model, settings.groq_recommendation_fallback_model],
                messages=[
                    {"role": "system", "content": RECOMMENDATION_PROMPT},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                temperature=0.1,
                response_format=_strict_response_format("recommendation_result", RecommendationResult),
                max_completion_tokens=settings.recommendation_max_tokens,
            )
            content = completion.choices[0].message.content or "{}"
            _record_completion(brief, completion, key, content, used_model, settings)
            raw = json.loads(content)
            result = RecommendationResult.model_validate(_normalize_recommendation_payload(raw))
        except (DecisionLLMRateLimitError, DecisionLLMBudgetError):
            raise
        except Exception as exc:
            logger.warning("Recommendation generation failed (%s): %s", type(exc).__name__, exc)
            return None

    option_by_id = {str(option["id"]): option for option in options}
    selected = option_by_id.get(result.selected_option_id)
    if not selected:
        return None
    result.selected_option_title = str(selected["title"])
    valid_assessments = []
    for assessment in result.option_assessments:
        option = option_by_id.get(assessment.option_id)
        if option:
            assessment.option_title = str(option["title"])
            valid_assessments.append(assessment)
    result.option_assessments = valid_assessments
    for driver in result.sensitivity_analysis:
        if driver.likely_winner_option_id not in option_by_id:
            driver.likely_winner_option_id = None
    for risk in result.key_risks:
        risk.option_ids = [option_id for option_id in risk.option_ids if option_id in option_by_id]
    if not result.key_risks:
        result.key_risks = [
            DecisionRisk.model_validate(risk)
            for risk in brief.get("risks", [])
            if risk.get("status") != "rejected"
        ]
    return result
