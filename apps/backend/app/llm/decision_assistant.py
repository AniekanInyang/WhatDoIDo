import asyncio
import json
import hashlib
import logging
import re
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from groq import AsyncGroq, BadRequestError, RateLimitError
from pydantic import BaseModel, Field

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
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ExtractionCriterionDraft(BaseModel):
    name: str
    importance: int = Field(default=3, ge=1, le=5)


class ExtractionRiskDraft(BaseModel):
    title: str
    description: str = ""
    severity: str = "moderate"
    likelihood: str = "unknown"
    mitigation: str | None = None


class ExtractionOptionDraft(BaseModel):
    title: str
    description: str | None = None
    kind: str = "alternative"
    specificity: str = "actionable"


class ExtractionDraft(BaseModel):
    is_decision_input: bool = True
    non_decision_reason: str | None = None
    direction_change: bool = False
    direction_change_summary: str | None = None
    decision_stakes: str | None = None
    goal: str | None = None
    domain: str | None = None
    deadline: str | None = None
    values: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    criteria: list[ExtractionCriterionDraft] = Field(default_factory=list)
    risk_tolerance: str | None = None
    preference_signals: list[str] = Field(default_factory=list)
    selected_option_title: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    risks: list[ExtractionRiskDraft] = Field(default_factory=list)
    options: list[ExtractionOptionDraft] = Field(default_factory=list)
    resolved_absences: list[str] = Field(default_factory=list)


class QuestionOptionDraft(BaseModel):
    title: str
    description: str | None = None
    specificity: Literal["direction", "actionable"]


class QuestionResponseDraft(BaseModel):
    question: str
    acknowledges_answer: bool = False
    suggested_options: list[QuestionOptionDraft] = Field(default_factory=list)


class ImmediateOptionSetDraft(BaseModel):
    options: list[QuestionOptionDraft] = Field(min_length=2, max_length=3)


class RecommendationAssessmentDraft(BaseModel):
    option_id: str
    fit: str
    strengths: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    constraint_conflicts: list[str] = Field(default_factory=list)


class RecommendationRiskDraft(BaseModel):
    title: str
    description: str = ""
    severity: str = "moderate"
    likelihood: str = "unknown"
    option_ids: list[str] = Field(default_factory=list)
    mitigation: str | None = None


class SensitivityDraft(BaseModel):
    factor: str
    current_assumption: str
    change_that_could_flip_result: str
    likely_winner_option_id: str | None = None
    explanation: str


class RecommendationDraft(BaseModel):
    selected_option_id: str
    summary: str
    concrete_example: str = Field(min_length=3)
    rationale: list[str] = Field(default_factory=list)
    option_assessments: list[RecommendationAssessmentDraft] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    key_risks: list[RecommendationRiskDraft] = Field(default_factory=list)
    checks_before_acting: list[str] = Field(default_factory=list)
    alternate_recommendation: str | None = None
    sensitivity_analysis: list[SensitivityDraft] = Field(default_factory=list)
    robustness: str = "low"
    caveat: str | None = None


class RecommendationCompactDraft(BaseModel):
    selected_option_id: str
    summary: str
    concrete_example: str = Field(min_length=3)
    rationale: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    robustness: str = "low"
    caveat: str | None = None


class RevisionIntentDraft(BaseModel):
    action: Literal["revise", "uphold"]
    acknowledgement: str
    reasoning: str
    extracted_feedback: list[str] = Field(default_factory=list)


class TitleNormalizationDraft(BaseModel):
    title: str


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


def _is_truncation_validation_failure(exc: Exception) -> bool:
    if not _is_json_validation_failure(exc):
        return False
    _status, _code, message, _headers = _provider_error_details(exc)
    lowered = message.lower()
    return "max completion tokens reached" in lowered or "truncated" in lowered


def _provider_error_details(exc: Exception) -> tuple[int | None, str | None, str, dict[str, str]]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    body = getattr(exc, "body", None)
    error = body.get("error", {}) if isinstance(body, dict) else {}
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    safe_headers: dict[str, str] = {}
    headers = getattr(response, "headers", {}) or {}
    for name in (
        "retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens", "x-request-id",
    ):
        if headers.get(name) is not None:
            safe_headers[name] = str(headers[name])
    return status, str(code) if code else None, str(message or exc), safe_headers


def _log_provider_error(model: str, exc: Exception, *, stage: str) -> None:
    status, code, message, headers = _provider_error_details(exc)
    logger.warning(
        "Groq %s request failed model=%s status=%s code=%s message=%s rate_headers=%s",
        stage, model, status, code, message, headers,
    )


def _retry_after_seconds(exc: Exception) -> float:
    response = getattr(exc, "response", None)
    raw = (getattr(response, "headers", {}) or {}).get("retry-after")
    try:
        # A long provider reset should surface to the user rather than hold an
        # application worker indefinitely. Short reset windows are respected.
        return min(5.0, max(0.5, float(raw)))
    except (TypeError, ValueError):
        return 1.0


def _failed_generation(exc: Exception) -> str | None:
    """Extract Groq's rejected generation without logging user content."""
    body = getattr(exc, "body", None)

    def find(node: Any) -> str | None:
        if isinstance(node, dict):
            for key in ("failed_generation", "generated", "output"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in node.values():
                found = find(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value)
                if found:
                    return found
        return None

    return find(body)


def _repair_messages(name: str, failed_generation: str, model: type[BaseModel]) -> list[dict[str, str]]:
    required = list(model.model_fields)
    return [
        {
            "role": "system",
            "content": (
                "Repair the supplied malformed JSON. Return one JSON object only. "
                "Preserve its meaning, use the required keys, use null or [] for missing values, "
                "and do not add commentary."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "object": name,
                "required_keys": required,
                "malformed_json": failed_generation[:4_000],
            }),
        },
    ]


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


def _compact_extraction_brief(brief: dict) -> dict:
    """Minimal state needed to interpret only the newest user message."""
    compact: dict[str, Any] = {}
    for key in ("goal", "domain", "deadline", "risk_tolerance"):
        value = brief.get(key)
        if isinstance(value, dict) and value.get("value"):
            compact[key] = str(value["value"])[:500]
    if brief.get("decision_stakes"):
        compact["decision_stakes"] = brief["decision_stakes"]
    for key in ("values", "constraints", "uncertainties", "preference_signals"):
        values = [
            str(item.get("value"))[:300]
            for item in brief.get(key, [])
            if item.get("value") and item.get("status") not in {"rejected", "superseded"}
        ][:8]
        if values:
            compact[key] = values
    criteria = [
        {"name": str(item.get("name"))[:200], "importance": item.get("importance", 3)}
        for item in brief.get("criteria", [])
        if item.get("name") and item.get("status") not in {"rejected", "superseded"}
    ][:8]
    if criteria:
        compact["criteria"] = criteria
    action = brief.get("next_action") or {}
    if action:
        compact["pending_question"] = {
            key: action.get(key) for key in ("category", "target_field", "expected_answer_type", "question")
            if action.get(key) is not None
        }
    if brief.get("resolved_absences"):
        compact["resolved_absences"] = list(brief["resolved_absences"])
    return compact


def _compact_options(options: list[dict]) -> list[dict]:
    return [
        {
            **{key: option.get(key) for key in ("id", "title", "description", "source", "status") if option.get(key) is not None},
            "display_label": _short_option_label(str(option.get("title") or "Option")),
            "specificity": option.get("specificity") or (option.get("metadata") or {}).get("specificity", "actionable"),
        }
        for option in options if option.get("status") != "rejected"
    ]


def _short_option_label(title: str, maximum: int = 64) -> str:
    """Turn a descriptive option sentence into a readable UI label."""
    cleaned = " ".join(title.strip().split())
    for marker in (" that ", " which ", " while ", " because ", " in order to "):
        head = re.split(marker, cleaned, maxsplit=1, flags=re.IGNORECASE)[0].rstrip(" ,;:-")
        if 4 <= len(head) <= maximum:
            return head
    if len(cleaned) <= maximum:
        return cleaned
    return cleaned[:maximum].rsplit(" ", 1)[0].rstrip(" ,;:-") or cleaned[:maximum]


def _replace_option_references(text: str | None, option_by_id: dict[str, dict]) -> str | None:
    """Replace provider-facing option IDs with labels before text reaches users."""
    if not text:
        return text
    rendered = str(text)
    for option_id, option in sorted(option_by_id.items(), key=lambda item: len(item[0]), reverse=True):
        label = _short_option_label(str(option.get("title") or "Option"))
        references = {option_id}
        if len(option_id) >= 8:
            references.add(option_id[:8])
        for reference in references:
            rendered = re.sub(
                rf"\bOption\s+{re.escape(reference)}\b",
                label,
                rendered,
                flags=re.IGNORECASE,
            )
            rendered = re.sub(rf"\b{re.escape(reference)}\b", label, rendered, flags=re.IGNORECASE)
    # Never expose an unresolved UUID-like provider identifier.
    rendered = re.sub(r"\bOption\s+[0-9a-f]{8}(?:-[0-9a-f-]{27})?\b", "the option", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\bthe user(?:'s|’s)\b", "your", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\bthe user\b", "you", rendered, flags=re.IGNORECASE)
    return " ".join(rendered.split())


def _unique_text(values: list[str]) -> list[str]:
    """Remove exact and near-duplicate generated statements while preserving order."""
    unique: list[str] = []
    normalized: list[str] = []
    for raw in values:
        value = " ".join(str(raw).strip().split())
        key = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        if not key:
            continue
        words = set(key.split())
        duplicate = False
        for previous in normalized:
            previous_words = set(previous.split())
            overlap = len(words & previous_words) / max(1, min(len(words), len(previous_words)))
            if key == previous or (overlap >= .9 and abs(len(words) - len(previous_words)) <= 4):
                duplicate = True
                break
        if not duplicate:
            unique.append(value)
            normalized.append(key)
    return unique


def _sanitize_recommendation(result: RecommendationResult, option_by_id: dict[str, dict]) -> RecommendationResult:
    def clean(value: str | None) -> str | None:
        return _replace_option_references(value, option_by_id)

    result.summary = clean(result.summary) or ""
    result.concrete_example = clean(result.concrete_example)
    if result.concrete_example:
        # The presentation layer promotes this value to the recommendation
        # headline, so keep only the actionable noun/action phrase.
        result.concrete_example = re.sub(
            r"^(?:for example\s*[:,.-]?\s*|for instance\s*[:,.-]?\s*|try\s+|i recommend\s+)",
            "",
            result.concrete_example,
            flags=re.IGNORECASE,
        ).strip().rstrip(".") or None
    result.rationale = _unique_text([clean(item) or "" for item in result.rationale])[:3]
    result.assumptions = _unique_text([clean(item) or "" for item in result.assumptions])[:4]
    result.unresolved_uncertainties = _unique_text(
        [clean(item) or "" for item in result.unresolved_uncertainties]
    )[:4]
    result.unresolved_uncertainties = _remove_uncertainties_resolved_by_assumptions(
        result.assumptions, result.unresolved_uncertainties
    )
    result.checks_before_acting = _unique_text(
        [clean(item) or "" for item in result.checks_before_acting]
    )[:4]
    result.alternate_recommendation = clean(result.alternate_recommendation)
    result.caveat = clean(result.caveat)
    for assessment in result.option_assessments:
        assessment.strengths = _unique_text([clean(item) or "" for item in assessment.strengths])[:3]
        assessment.tradeoffs = _unique_text([clean(item) or "" for item in assessment.tradeoffs])[:3]
        assessment.constraint_conflicts = _unique_text(
            [clean(item) or "" for item in assessment.constraint_conflicts]
        )[:3]
    for risk in result.key_risks:
        risk.title = clean(risk.title) or risk.title
        risk.description = clean(risk.description) or risk.description
        risk.mitigation = clean(risk.mitigation)
    for driver in result.sensitivity_analysis:
        driver.factor = clean(driver.factor) or driver.factor
        driver.current_assumption = clean(driver.current_assumption) or driver.current_assumption
        driver.change_that_could_flip_result = clean(driver.change_that_could_flip_result) or driver.change_that_could_flip_result
        driver.explanation = clean(driver.explanation) or driver.explanation
    return result


def _semantic_tokens(value: str) -> set[str]:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "because", "for", "from",
        "if", "in", "is", "it", "of", "on", "or", "over", "rather", "than",
        "that", "the", "their", "this", "to", "vs", "whether", "you", "your",
    }
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if token.endswith("s") and len(token) > 4:
            token = token[:-1]
        if token not in stopwords and len(token) > 2:
            tokens.add(token)
    return tokens


def _remove_uncertainties_resolved_by_assumptions(
    assumptions: list[str], uncertainties: list[str]
) -> list[str]:
    """Do not present the same proposition as both assumed and unresolved."""
    assumption_tokens = [_semantic_tokens(item) for item in assumptions]
    kept: list[str] = []
    for uncertainty in uncertainties:
        tokens = _semantic_tokens(uncertainty)
        alternative_question = bool(
            re.search(r"\b(?:whether|versus|vs\.?)\b|\bor\b", uncertainty.lower())
        )
        resolved = any(
            tokens
            and (
                tokens <= assumed
                or assumed <= tokens
                or (alternative_question and len(tokens & assumed) >= 2)
            )
            for assumed in assumption_tokens
        )
        if not resolved:
            kept.append(uncertainty)
    return kept


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


def _safe_completion_token_limit(model: str, requested: int) -> int:
    """Keep requests below known provider/model output-token ceilings."""
    if model.startswith("qwen/"):
        # Groq currently enforces a 1,000 OTPM ceiling for these on-demand
        # models. Leave headroom so the request is accepted before generation.
        return min(requested, 900)
    return requested


async def _complete_structured(
    client: AsyncGroq,
    models: list[str | None],
    *,
    stage: str,
    schema_name: str,
    response_model: type[StructuredModel],
    parse: Callable[[dict[str, Any]], StructuredModel],
    **kwargs,
) -> tuple[Any, str, StructuredModel, str]:
    """Use strict output once, then at most one compact JSON repair globally."""
    last_error: Exception | None = None
    rate_limited = False
    repair_used = False
    for model in dict.fromkeys(model for model in models if model):
        request_kwargs = dict(kwargs)
        requested_tokens = int(request_kwargs.get("max_completion_tokens", 500))
        request_kwargs["max_completion_tokens"] = _safe_completion_token_limit(
            model, requested_tokens
        )
        request_kwargs["response_format"] = _strict_response_format(schema_name, response_model)
        if model.startswith("openai/gpt-oss-"):
            request_kwargs.setdefault("reasoning_effort", "low")
        try:
            completion = await client.chat.completions.create(model=model, **request_kwargs)
            content = completion.choices[0].message.content or "{}"
            return completion, model, parse(json.loads(content)), content
        except RateLimitError as exc:
            rate_limited = True
            last_error = exc
            _log_provider_error(model, exc, stage=stage)
            await asyncio.sleep(_retry_after_seconds(exc))
            continue
        except Exception as exc:
            last_error = exc
            _log_provider_error(model, exc, stage=stage)
            if _is_truncation_validation_failure(exc):
                # A truncated strict JSON response is unlikely to repair well on
                # the same constrained model and often burns extra OTPM. Move
                # to the next configured model immediately.
                continue
            failed = _failed_generation(exc) if _is_json_validation_failure(exc) else None
            if repair_used or not failed:
                continue
            repair_used = True
            repair_limit = min(int(kwargs.get("max_completion_tokens", 500)), 600)
            repair_limit = _safe_completion_token_limit(model, repair_limit)
            if model.startswith("qwen/"):
                repair_limit = min(repair_limit, 260)
            repair_kwargs = {
                "messages": _repair_messages(schema_name, failed, response_model),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "max_completion_tokens": repair_limit,
            }
            if model.startswith("openai/gpt-oss-"):
                repair_kwargs["reasoning_effort"] = "low"
            try:
                completion = await client.chat.completions.create(model=model, **repair_kwargs)
                content = completion.choices[0].message.content or "{}"
                parsed = parse(json.loads(content))
                logger.info("Groq %s JSON repaired successfully with model=%s", stage, model)
                return completion, model, parsed, content
            except RateLimitError as repair_exc:
                rate_limited = True
                last_error = repair_exc
                _log_provider_error(model, repair_exc, stage=f"{stage}_repair")
                await asyncio.sleep(_retry_after_seconds(repair_exc))
            except Exception as repair_exc:
                last_error = repair_exc
                _log_provider_error(model, repair_exc, stage=f"{stage}_repair")
    if rate_limited:
        raise DecisionLLMRateLimitError("The AI provider's usage limit has been reached") from last_error
    raise DecisionLLMGenerationError(f"No configured model produced valid {stage} JSON") from last_error


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
    elif category == "preferences" and not patch.preference_signals:
        patch.preference_signals.append(fact)
    elif category == "context" and not patch.constraints:
        # Situational details (for example expected weather and exposure) affect
        # feasibility, but must not replace the user's central goal or priority.
        patch.constraints.append(fact)
    elif category == "constraints" and not patch.constraints:
        patch.constraints.append(fact)
    elif category == "uncertainties" and not patch.uncertainties:
        patch.uncertainties.append(fact)
    elif category == "risk" and patch.risk_tolerance is None:
        patch.risk_tolerance = fact
    if category in {"values", "preferences", "context", "constraints", "uncertainties", "risk"}:
        patch.is_decision_input = True
        patch.non_decision_reason = None
    return patch


EXTRACTION_PROMPT = """Extract only facts stated or directly implied by the newest
message into the requested compact JSON object. Treat a short reply as decision
input when pending_question shows that it answers the coach. Use plain strings for
facts and string arrays for fact lists. Do not copy unchanged facts from current_state.
When setting goal, return a concise, polished UI heading that preserves the user's
meaning. Proofread spelling, grammar, capitalization, punctuation, transposed
letters, and accidental whitespace inside words. Do not merely copy malformed
input into goal. Do not apply that rewriting to options, preferences, names,
brands, or other user-provided facts.
Set is_decision_input=false for greetings, unrelated requests, incoherent text,
or content that does not describe or advance a decision. Set direction_change
only when the user explicitly replaces the central decision, not when they add
or correct one detail. Never rewrite the existing goal merely because the user
supplies a format, channel, attribute, example, preference, constraint, or option.
Classify decision_stakes from consequence and reversibility: low for readily
reversible choices with minor consequences, medium for meaningful but manageable
tradeoffs, and high for serious financial, health, safety, legal, career, or
relationship consequences. Criteria have only name and importance from 1 to 5;
use 3 when unspecified. Assumptions are unconfirmed claims required to reason.
Risks contain title, description, severity, likelihood, and optional mitigation.
Each option has title, optional description, kind=alternative or context, and
specificity=direction or actionable. An alternative
must be a mutually selectable alternative that could answer the central decision.
A format, channel, medium, feature, attribute, criterion, audience, or topic is
kind=context—not an alternative—unless the user is explicitly comparing choices of
that same kind. A direction is a broad category that still needs refinement; an
actionable option is specific enough to choose and act on. For example, in “what
should I post?” carousel is a format while
wedding content and travel content can be alternatives. Extract every actual
option the user supplies, including alternatives embedded directly in the central
question (for example, "should I choose A or B"). Never generate new options in
the extraction step. User options use source=user_provided. If the newest reply
selects, abbreviates, or semantically paraphrases an option already present in
existing_options, set selected_option_title to that option's exact existing title
and do not add the reply as a new option. For example, a preference-like reply
that clearly chooses one offered direction belongs to the existing option even
when it uses different words. A selected option and a newly introduced alternative
are different concepts; never duplicate the selected option under the user's
wording. When the user says
there are no constraints, uncertainties, or risk preference, leave that fact list
empty and add the corresponding field to resolved_absences. Do not recommend an option."""


def _extraction_patch_from_draft(draft: ExtractionDraft, message_id: str) -> DecisionStatePatch:
    def fact(value: str | None, *, inferred: bool = False) -> dict | None:
        if not value or not str(value).strip():
            return None
        return {
            "value": str(value).strip(),
            "source": "inferred" if inferred else "explicit",
            "confidence": "medium" if inferred else "high",
            "status": "candidate" if inferred else "confirmed",
            "evidence_message_ids": [message_id],
        }

    stakes = draft.decision_stakes if draft.decision_stakes in {"low", "medium", "high"} else None
    resolved = [
        value for value in draft.resolved_absences
        if value in {"constraints", "uncertainties", "risk_tolerance"}
    ]
    def facts(values: list[str]) -> list[dict]:
        return [item for value in values if (item := fact(value)) is not None]

    preference_signals = list(draft.preference_signals)
    if draft.selected_option_title:
        preference_signals.append(f"Selected option: {draft.selected_option_title}")

    return DecisionStatePatch.model_validate({
        "is_decision_input": draft.is_decision_input,
        "non_decision_reason": draft.non_decision_reason,
        "direction_change": draft.direction_change,
        "direction_change_summary": draft.direction_change_summary,
        "decision_stakes": stakes,
        "goal": fact(draft.goal),
        "domain": fact(draft.domain),
        "deadline": fact(draft.deadline),
        "values": facts(draft.values),
        "constraints": facts(draft.constraints),
        "uncertainties": facts(draft.uncertainties),
        "criteria": [{
            "name": item.name,
            "importance": item.importance,
            "source": "explicit",
            "confidence": "high",
            "status": "confirmed",
            "evidence_message_ids": [message_id],
        } for item in draft.criteria],
        "risk_tolerance": fact(draft.risk_tolerance),
        "preference_signals": facts(preference_signals),
        "assumptions": [{
            "statement": value,
            "importance": "medium",
            "confidence": "low",
            "source": "inferred",
            "status": "candidate",
            "evidence_message_ids": [message_id],
        } for value in draft.assumptions if value.strip()],
        "risks": [{
            "title": item.title,
            "description": item.description or item.title,
            "severity": item.severity if item.severity in {"low", "moderate", "high", "critical"} else "moderate",
            "likelihood": item.likelihood if item.likelihood in {"unlikely", "possible", "likely", "unknown"} else "unknown",
            "mitigation": item.mitigation,
            "source": "inferred",
            "status": "candidate",
            "evidence_message_ids": [message_id],
        } for item in draft.risks],
        "options": [{
            "title": item.title,
            "description": item.description,
            "source": "user_provided",
            "kind": item.kind if item.kind in {"alternative", "context"} else "context",
            "specificity": item.specificity if item.specificity in {"direction", "actionable"} else "actionable",
        } for item in ([] if draft.selected_option_title else draft.options)],
        "resolved_absences": resolved,
    })


def _bind_selected_option(
    draft: ExtractionDraft,
    current_options: list[dict],
) -> ExtractionDraft:
    """Accept a model selection only when it names a real option canonically."""
    if not draft.selected_option_title:
        return draft
    canonical = {
        " ".join(str(option.get("title", "")).lower().split()): str(option.get("title", ""))
        for option in current_options
        if option.get("title") and option.get("status") != "rejected"
    }
    matched = canonical.get(" ".join(draft.selected_option_title.lower().split()))
    draft.selected_option_title = matched
    return draft


def _preserve_opening_decision(
    patch: DecisionStatePatch,
    fallback: DecisionStatePatch,
    current_brief: dict,
) -> DecisionStatePatch:
    """Never let an incomplete opening extraction erase the user's decision."""
    if current_brief.get("goal") or fallback.goal is None:
        return patch
    if patch.goal is None:
        patch.goal = fallback.goal
    patch.is_decision_input = True
    patch.non_decision_reason = None
    return patch


async def extract_decision_patch(
    message: str,
    message_id: str,
    current_brief: dict,
    settings: Settings,
    current_options: list[dict] | None = None,
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
                "value": " ".join(message.strip().split()),
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
    if pending_category in {"values", "context", "constraints", "uncertainties", "risk"} and len(message.split()) <= 16:
        return _merge_contextual_answer(fallback, message, message_id, current_brief)
    if pending_category == "criteria" and re.search(r"\b[1-5]\b", message):
        return _merge_contextual_answer(fallback, message, message_id, current_brief)
    if not settings.groq_api_key:
        fallback = _merge_explicit_options(fallback, message, current_brief)
        return _merge_contextual_answer(fallback, message, message_id, current_brief)

    payload = {
        "current_state": _compact_extraction_brief(current_brief),
        "existing_options": _compact_options(current_options or []),
        "new_message": message,
    }
    key = _cache_key("extraction", payload)
    cached = _cached_content(current_brief, key, settings)
    if cached:
        draft = ExtractionDraft.model_validate_json(cached)
        draft = _bind_selected_option(draft, current_options or [])
        parsed = _extraction_patch_from_draft(draft, message_id)
        parsed = _preserve_opening_decision(parsed, fallback, current_brief)
        if not draft.selected_option_title:
            parsed = _merge_explicit_options(parsed, message, current_brief)
        return _merge_contextual_answer(parsed, message, message_id, current_brief)
    try:
        _check_budget(current_brief, payload, settings.extraction_max_tokens, settings)
        client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
        )
        completion, used_model, draft, content = await _complete_structured(
            client, [settings.groq_light_model, settings.groq_light_fallback_model],
            stage="extraction",
            schema_name="decision_extraction",
            response_model=ExtractionDraft,
            parse=ExtractionDraft.model_validate,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            temperature=0,
            max_completion_tokens=settings.extraction_max_tokens,
        )
        _record_completion(current_brief, completion, key, content, used_model, settings)
        draft = _bind_selected_option(draft, current_options or [])
        parsed = _extraction_patch_from_draft(draft, message_id)
        parsed = _preserve_opening_decision(parsed, fallback, current_brief)
        if not draft.selected_option_title:
            parsed = _merge_explicit_options(parsed, message, current_brief)
        return _merge_contextual_answer(parsed, message, message_id, current_brief)
    except (DecisionLLMRateLimitError, DecisionLLMBudgetError, DecisionLLMGenerationError):
        fallback = _merge_explicit_options(fallback, message, current_brief)
        return _merge_contextual_answer(fallback, message, message_id, current_brief)
    except Exception:
        fallback = _merge_explicit_options(fallback, message, current_brief)
        return _merge_contextual_answer(fallback, message, message_id, current_brief)


QUESTION_PROMPT = """Write one concise, natural clarification question for a
personal decision. Sound like a warm, perceptive decision coach rather than a
form or an interviewer. If this is the first question, briefly acknowledge what
the person is trying to do before asking it. If this is not the first question,
do not restate the decision framing with openers such as "I hear you're looking
for..." or "You're deciding...". For a meaningful personal choice,
the acknowledgment may be gently encouraging, but never invent an emotion or
overdo enthusiasm. The workflow has already selected what information to seek;
do not choose a different target and do not evaluate or recommend. Use the goal,
options, known facts, latest answer, and rationale to make the wording specific.
Do not ask for information already present. Do not repeat any forbidden question.
Never ask the person to justify an intention that is already obvious from the
decision. Ask for information that could actually distinguish the alternatives,
such as relevant preferences, recipient or situational context, constraints, or
candidate choices. Avoid sterile phrasings such as “what is the most important
reason you want to...”.
When semantic_target is options or concrete_options, ask for two or more mutually exclusive choices
that could directly answer the central decision. Do not ask for a format, channel,
feature, audience, style, or general category unless those are themselves the
alternatives being compared.
Every suggested option must be a concrete, actionable endpoint—not a broad
direction, dress code, format, or category. Its title must name what the person
could actually choose, buy, wear, do, or try and include enough defining detail
that a person would understand it without asking what the label means. If a
selected direction appears in the preference signals, generate concrete candidates
inside that direction rather than switching to another direction.
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
When semantic_target is recommendation_consent because the clarification budget
is exhausted, plainly say that enough information exists for a provisional
recommendation, acknowledge that some details remain uncertain, and ask whether
the user wants the recommendation now. Do not ask another discovery question.
When the latest answer advanced the state, briefly acknowledge it before asking.
Return JSON only with question, acknowledges_answer, and suggested_options. Each
suggested option must include specificity, which must be actionable for an options
or concrete_options target. The
target and answer type are already controlled by the workflow. The question must
contain exactly one primary question."""


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


def _trim_repeated_acknowledgement(question: str, *, is_first_question: bool) -> str:
    """Remove repetitive framing openers from non-first clarifications."""
    cleaned = " ".join(question.strip().split())
    if is_first_question:
        return cleaned
    patterns = (
        r"^i hear you(?:'|’)?re looking for[^,.!?—-]*[,.!?—-]\s*",
        r"^you(?:'|’)?re looking for[^,.!?—-]*[,.!?—-]\s*",
        r"^you are looking for[^,.!?—-]*[,.!?—-]\s*",
        r"^you(?:'|’)?re deciding[^,.!?—-]*[,.!?—-]\s*",
        r"^you are deciding[^,.!?—-]*[,.!?—-]\s*",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE).strip()
        if candidate and candidate != cleaned:
            cleaned = candidate
            break
    return cleaned


def _question_advances_target(draft: QuestionDraft) -> bool:
    """Reject questions that clearly gather a different kind of information.

    Do not require target-specific keywords here. Natural questions can elicit
    alternatives without saying ``option`` or ``choice`` (for example, "What
    would you feel best wearing to dinner?"). Keyword requirements caused valid
    provider output to be rejected by both models and surfaced as a false 503.
    """
    question = " ".join(draft.question.lower().split())
    if draft.target_field in {"options", "concrete_options"}:
        if draft.suggested_options:
            return all(option.specificity == "actionable" for option in draft.suggested_options)
        asks_for_another_target = any(
            re.search(pattern, question)
            for pattern in (
                r"\bwhy\b|\breason\b",
                r"\bmost important\b|\bmatters most\b|\bhow important\b|\bimportance\b|\brank(?:ing)?\b",
                r"\bhard limit\b|\bnon-negotiable\b|\bconstraint\b|\bbudget limit\b",
                r"\bwhat (?:are you|is) worried about\b|\bwhat could go wrong\b",
            )
        )
        return not asks_for_another_target
    if draft.target_field == "goal":
        return not bool(re.search(r"\b(why|reason)\b", question))
    return True


def _question_validation_errors(
    draft: QuestionDraft,
    forbidden: list[str | None],
) -> list[str]:
    """Return actionable reasons a generated question is unsafe or off-target."""
    question = " ".join(draft.question.lower().split())
    previous = {" ".join(str(item).lower().split()) for item in forbidden if item}
    errors: list[str] = []
    if question in previous:
        errors.append("it repeats a previous question")
    elif any(_lexical_similarity(question, item) >= 0.9 for item in previous):
        errors.append("it nearly repeats a previous question")
    if "?" not in draft.question:
        errors.append("it is not phrased as a question")
    if draft.target_field == "uncertainties" and any(
        phrase in question for phrase in ("hard limit", "non-negotiable", "infeasible")
    ):
        errors.append("it asks for a constraint instead of an uncertainty")
    if draft.target_field == "constraints" and any(
        phrase in question for phrase in ("how important", "rank the importance")
    ):
        errors.append("it asks for criterion importance instead of a constraint")

    normalized_question = re.sub(r"[^a-z0-9]+", " ", question).strip()
    missing_titles = [
        option.title for option in draft.suggested_options
        if re.sub(r"[^a-z0-9]+", " ", option.title.lower()).strip()
        not in normalized_question
    ]
    if missing_titles:
        errors.append("it does not mention every persisted suggested option")
    if (
        draft.target_field in {"options", "concrete_options"}
        and " or " in question
        and not draft.suggested_options
    ):
        errors.append("it introduces alternatives that were not persisted")
    if not _question_advances_target(draft):
        errors.append(f"it asks for information outside the {draft.target_field} target")
    return errors


def _normalized_sentence(value: str) -> str:
    return " ".join(value.lower().split())


def _lexical_similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / max(1, min(len(left_tokens), len(right_tokens)))


def _message_rejects_previous_suggestions(message: str) -> bool:
    normalized = _normalized_sentence(message)
    if not normalized:
        return False
    rejection_patterns = (
        "these are not",
        "those are not",
        "not lunch",
        "not breakfast",
        "not dinner",
        "wrong options",
        "different options",
        "other options",
    )
    return any(pattern in normalized for pattern in rejection_patterns)


def _meal_type_from_context(goal_text: str, latest_message: str) -> str | None:
    context = f"{goal_text} {latest_message}".lower()
    if "lunch" in context:
        return "lunch"
    if "dinner" in context:
        return "dinner"
    if "breakfast" in context:
        return "breakfast"
    if any(term in context for term in ("meal", "eat", "cook", "food")):
        return "meal"
    return None


def _fallback_clarification_question(
    action: ActionPlan,
    brief: dict,
    *,
    latest_message: str = "",
    forbidden: list[str | None] | None = None,
) -> QuestionDraft:
    """Return a safe deterministic question when model output is invalid."""
    target = action.target_field or action.category
    goal_text = ""
    goal = brief.get("goal")
    if isinstance(goal, dict):
        goal_text = str(goal.get("value") or "").strip()
    forbidden_normalized = {
        _normalized_sentence(str(item))
        for item in (forbidden or [])
        if item
    }

    def fallback_meal_suggestions(meal_type: str | None) -> list[OptionObservation]:
        preference_text = " ".join(
            str(item.get("value") or "")
            for item in brief.get("preference_signals", [])
            if isinstance(item, dict)
        ).lower()
        if meal_type == "lunch":
            candidates = [
                "Chicken and veggie grain bowl",
                "Salmon salad with avocado and quinoa",
            ]
        elif meal_type == "dinner":
            candidates = [
                "Baked salmon with roasted vegetables",
                "Turkey chili with mixed beans",
            ]
        elif "egg" in preference_text:
            candidates = [
                "Scrambled eggs with spinach",
                "Egg-and-avocado whole-grain toast",
            ]
        elif "healthy" in preference_text:
            candidates = [
                "Oatmeal with berries and nuts",
                "Veggie omelet with whole-grain toast",
            ]
        else:
            candidates = [
                "Greek yogurt bowl with fruit",
                "Peanut-butter banana whole-grain toast",
            ]
        return [
            OptionObservation(
                title=title,
                description=None,
                source="ai_generated",
                kind="alternative",
                specificity="actionable",
            )
            for title in candidates
        ]

    suggested_options: list[OptionObservation] = []
    if target in {"options", "concrete_options"}:
        meal_type = _meal_type_from_context(goal_text, latest_message)
        if _message_rejects_previous_suggestions(latest_message):
            meal_label = f" {meal_type}" if meal_type in {"breakfast", "lunch", "dinner"} else ""
            question = (
                "Understood. Please share two specific"
                f"{meal_label} options you would actually choose between, and I will compare them directly."
            )
        elif meal_type:
            suggested_options = fallback_meal_suggestions(meal_type)
            left, right = suggested_options[0].title, suggested_options[1].title
            question = (
                f"I can compare {left} vs {right}. Want me to evaluate these now, "
                "or do you want to share two specific options of your own?"
            )
        elif goal_text:
            question = (
                f"To decide \"{goal_text}\", what are two specific options you want compared?"
            )
        else:
            question = "What are two specific options you want compared?"
    elif target == "criterion_importance":
        question = "How important is each of the factors you already named, on a 1-5 scale?"
    elif target == "constraints":
        question = "What hard limits should any good option respect?"
    elif target == "uncertainties":
        question = "What unknowns could still change your choice?"
    elif target == "values":
        question = "What matters most to you for this decision right now?"
    elif target == "risk_tolerance":
        question = "How much downside risk are you comfortable with for this choice?"
    elif target == "decision_context":
        question = "What one detail about your situation would most change this decision?"
    elif target == "recommendation_consent":
        question = "I have enough context for a provisional recommendation. Do you want it now?"
    else:
        question = "What single detail would most help narrow this decision?"

    if (
        _normalized_sentence(question) in forbidden_normalized
        or any(_lexical_similarity(question, item) >= 0.9 for item in forbidden_normalized)
    ):
        if target in {"options", "concrete_options"}:
            question = "Please share two concrete options you actually want compared right now."
            suggested_options = []
        else:
            question = "Could you share one new detail that would help narrow the decision?"

    return QuestionDraft(
        question=question,
        target_field=target,
        expected_answer_type=action.expected_answer_type or "short_text",
        acknowledges_answer=False,
        suggested_options=[item.model_dump(mode="json") for item in suggested_options],
    )


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
        "is_first_question": not bool(brief.get("question_history")),
        "decision_brief": _compact_brief(brief),
        "options": _compact_options(options),
        "latest_user_message": latest_message,
        "forbidden_questions": forbidden,
    }
    key = _cache_key("question", payload)
    cached = _cached_content(brief, key, settings)
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
    )

    def parse_question(raw: dict[str, Any]) -> QuestionDraft:
        provider = QuestionResponseDraft.model_validate(_normalize_question_payload(raw))
        question_text = _trim_repeated_acknowledgement(
            provider.question,
            is_first_question=bool(payload["is_first_question"]),
        )
        draft = QuestionDraft(
            question=question_text,
            target_field=action.target_field or action.category,
            expected_answer_type=action.expected_answer_type or "short_text",
            acknowledges_answer=provider.acknowledges_answer,
            suggested_options=[{
                "title": option.title,
                "description": option.description,
                "source": "ai_generated",
                "kind": "alternative",
                "specificity": option.specificity,
            } for option in provider.suggested_options],
        )
        validation_errors = _question_validation_errors(draft, forbidden)
        if validation_errors:
            logger.warning(
                "Question validation failed for target=%s: %s; using deterministic fallback",
                draft.target_field,
                "; ".join(validation_errors),
            )
            return _fallback_clarification_question(
                action,
                brief,
                latest_message=latest_message,
                forbidden=forbidden,
            )
        return draft

    if cached:
        try:
            return parse_question(json.loads(cached))
        except Exception:
            logger.warning("Ignoring invalid cached clarification question")

    try:
        _check_budget(brief, payload, settings.question_max_tokens, settings)
        await asyncio.sleep(settings.llm_stage_delay_seconds)
        completion, model, draft, content = await _complete_structured(
            client, [settings.groq_light_model, settings.groq_light_fallback_model],
            stage="question",
            schema_name="clarification_question",
            response_model=QuestionResponseDraft,
            parse=parse_question,
            messages=[
                {"role": "system", "content": QUESTION_PROMPT},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            temperature=0.35,
            max_completion_tokens=settings.question_max_tokens,
        )
        _record_completion(brief, completion, key, content, model, settings)
        return draft
    except (DecisionLLMRateLimitError, DecisionLLMBudgetError, DecisionLLMGenerationError):
        return _fallback_clarification_question(
            action,
            brief,
            latest_message=latest_message,
            forbidden=forbidden,
        )


IMMEDIATE_OPTIONS_PROMPT = """Infer two or three concrete, mutually exclusive
options that can be evaluated immediately for the supplied personal decision.
The person explicitly asked to stop clarification and receive a best-effort
recommendation now. Do not ask a question. Use only the supplied decision brief
and existing options. Preserve any direction or preference the person already
selected. Fill in reasonable gaps conservatively, but do not invent factual
claims about prices, availability, outcomes, or the person's circumstances.
Each option must be an actionable endpoint that directly answers the decision,
not a broad category, goal, format, or restatement of the decision. Do not repeat
an existing option. Return JSON only with an options array. Every option must
include a concise title, an optional description, and specificity="actionable"."""


def _fallback_immediate_options(
    brief: dict,
    options: list[dict],
) -> list[OptionObservation]:
    """Deterministic fallback for assistive mode when provider calls fail.

    Uses lightweight domain cues so users who do not know specific options can
    still receive concrete alternatives instead of another dead-end prompt.
    """
    existing_titles = {
        " ".join(str(option.get("title", "")).lower().split())
        for option in options if option.get("status") != "rejected"
    }
    goal_text = ""
    goal = brief.get("goal") or {}
    if isinstance(goal, dict):
        goal_text = str(goal.get("value") or "").lower()
    preference_text = " ".join(
        str(item.get("value") or "")
        for item in brief.get("preference_signals", [])
        if isinstance(item, dict) and item.get("status") != "rejected"
    ).lower()
    value_text = " ".join(
        str(item.get("value") or "")
        for item in brief.get("values", [])
        if isinstance(item, dict) and item.get("status") != "rejected"
    ).lower()
    context = f"{goal_text} {preference_text} {value_text}"

    if "music" in context or "song" in context or "audio" in context:
        if any(term in context for term in ("romantic", "calm", "soft", "gentle")):
            candidates = [
                ("Romantic piano instrumental", "Soft piano with warm ambient strings"),
                ("Calm lo-fi groove", "Low-tempo lo-fi beat with mellow chords"),
            ]
        elif any(term in context for term in ("energetic", "hype", "fast", "upbeat")):
            candidates = [
                ("Upbeat pop instrumental", "Bright tempo with rhythmic hooks"),
                ("Energetic electronic beat", "Driving percussion and bold synth layers"),
            ]
        else:
            candidates = [
                ("Cinematic ambient track", "Atmospheric score for emotional storytelling"),
                ("Minimal acoustic instrumental", "Clean guitar-led bed with light rhythm"),
            ]
    elif any(term in context for term in ("breakfast", "lunch", "dinner", "meal", "eat", "cook")):
        candidates = [
            ("Chicken and veggie grain bowl", "Balanced bowl with lean protein and vegetables"),
            ("Salmon salad with avocado", "Light salad with healthy fats and protein"),
        ]
    else:
        candidates = [
            ("Conservative practical choice", "Safer option prioritizing reliability and low downside"),
            ("Higher-upside experimental choice", "Bolder option prioritizing potential upside"),
        ]

    inferred: list[OptionObservation] = []
    for title, description in candidates:
        normalized = " ".join(title.lower().split())
        if normalized in existing_titles:
            continue
        inferred.append(OptionObservation(
            title=title,
            description=description,
            source="ai_generated",
            kind="alternative",
            specificity="actionable",
        ))
    return inferred[:3]


async def generate_immediate_options(
    brief: dict,
    options: list[dict],
    settings: Settings,
) -> list[OptionObservation]:
    """Infer provisional choices so an explicit recommend-now request can proceed."""
    if not settings.groq_api_key:
        return _fallback_immediate_options(brief, options)
    payload = {
        "decision_brief": _compact_brief(brief),
        "existing_options": _compact_options(options),
    }
    key = _cache_key("immediate_options", payload)
    existing_titles = {
        " ".join(str(option.get("title", "")).lower().split())
        for option in options if option.get("status") != "rejected"
    }

    def parse_options(raw: dict[str, Any]) -> list[OptionObservation]:
        draft = ImmediateOptionSetDraft.model_validate(raw)
        inferred: list[OptionObservation] = []
        seen = set(existing_titles)
        for option in draft.options:
            normalized = " ".join(option.title.lower().split())
            if not normalized or normalized in seen or option.specificity != "actionable":
                continue
            inferred.append(OptionObservation(
                title=option.title,
                description=option.description,
                source="ai_generated",
                kind="alternative",
                specificity="actionable",
            ))
            seen.add(normalized)
        if len(options) + len(inferred) < 2:
            raise ValueError("Immediate recommendation requires at least two distinct options")
        return inferred

    cached = _cached_content(brief, key, settings)
    if cached:
        try:
            return parse_options(json.loads(cached))
        except Exception:
            logger.warning("Ignoring invalid cached immediate option set")

    try:
        _check_budget(brief, payload, settings.question_max_tokens, settings)
        client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
        )
        await asyncio.sleep(settings.llm_stage_delay_seconds)
        completion, model, inferred, content = await _complete_structured(
            client, [settings.groq_light_model, settings.groq_light_fallback_model],
            stage="immediate_options",
            schema_name="immediate_decision_options",
            response_model=ImmediateOptionSetDraft,
            parse=parse_options,
            messages=[
                {"role": "system", "content": IMMEDIATE_OPTIONS_PROMPT},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            temperature=0.25,
            max_completion_tokens=settings.question_max_tokens,
        )
        _record_completion(brief, completion, key, content, model, settings)
        return inferred
    except (DecisionLLMRateLimitError, DecisionLLMBudgetError, DecisionLLMGenerationError):
        return _fallback_immediate_options(brief, options)


RECOMMENDATION_PROMPT = """Produce a grounded recommendation from the supplied
decision brief and persisted options. Select exactly one supplied option ID.
If confirmed_selection is supplied, select that option. It is the user's explicit
choice and remains binding unless the input explicitly says they changed or
rejected it. A later value, criterion, or preference must explain the chosen
option's trade-offs; it must not silently replace the choice.
Respect hard constraints before preferences. Do not invent facts, scores,
probabilities, or evidence. Compare every option. Keep all text concise. Option
IDs exist only for structured linkage: never include an ID in prose. Use each
option's display_label whenever naming it. Return
the requested compact JSON containing summary, rationale, option assessments,
assumptions, unresolved uncertainties, risks, checks, alternate recommendation,
sensitivity_analysis (factor, current_assumption, change_that_could_flip_result,
likely_winner_option_id or null, explanation), robustness (low/moderate/high),
and caveat. Sensitivity analysis must explain concrete plausible changes that
could change the winner. All fields described as lists must be JSON arrays.
Always set concrete_example to one concise, practical, self-contained action or
choice. This value becomes the user-facing recommendation headline. When the
selected option is a broad category, instantiate it as a concrete item, outfit,
action, or plan with enough defining detail to be useful. Do not merely repeat or
paraphrase the category label. When the selected option is already concrete, use
a concise actionable rendering of it. Return a direct noun or action phrase
without prefixes such as "For example", "Try", or "I recommend". Do not claim
availability or objective superiority. Do not repeat concrete_example in summary.
The only allowed option-assessment fit values are weak, mixed, or strong.
Acknowledge insufficient evidence through assumptions, uncertainties, caveat,
and lower robustness. If readiness.enough_to_recommend is false or blockers are
present, robustness must be low, and unresolved blockers must appear in assumptions
or uncertainties. Keep caveat to one short sentence and do not repeat it elsewhere.
Assumptions and unresolved uncertainties must be mutually consistent. Never
state a proposition as an assumption while also saying that same proposition is
unknown (for example, do not assume a sweet preference and then list sweet versus
savory as unresolved). If it is genuinely uncertain, omit the assumption.
Never invent measurements, durations, prices, outcomes,
or comparisons that do not appear in the supplied data. If the evidence cannot
distinguish the options, say so plainly and make the selection conditional on a
clearly named assumption rather than fabricating support. A stated criterion by
itself is not evidence that any option performs better on that criterion. Treat
an explicit option selection or preference signal as the user's preference, not
as proof of an objective advantage. Address the user directly as "you"; never
refer to them as "the user". The summary must explain the choice without
restating "X is recommended" because the presentation layer already names it.
Use at most three distinct rationale bullets. Name a useful alternate when at
least two options exist, and say briefly when it would fit better. Do not repeat
the same limitation across caveat, assumptions, uncertainties, checks, or risks.
Keep the complete response small: at most two strengths and two trade-offs per
option; one constraint conflict per option; two assumptions; two unresolved
uncertainties; two risks; two checks; and two sensitivity factors. Each item and
the summary must be a single concise sentence."""


REVISION_INTENT_PROMPT = """You are classifying feedback on an existing
recommendation. Return JSON only.
Choose action=revise when the person reports mismatch with stated preferences,
constraints, tone, specificity, or usefulness (for example: too formal, too
generic, not actionable, not aligned with their responses).
Choose action=uphold when the feedback does not conflict with the available
facts/preferences or asks to ignore important constraints.
acknowledgement must validate the feedback respectfully in one sentence.
reasoning must be brief, specific, and grounded in the provided decision brief.
extracted_feedback should contain short bullet-like strings that can be merged as
preference signals or constraints for a revision."""


REVISION_RECOMMENDATION_PROMPT = """Revise the recommendation after user
feedback using only supplied options and decision brief. Return JSON matching the
same recommendation schema as initial recommendations.
Honor explicit corrections from feedback. Do not invent new options, facts, or
objective claims. Keep the response concise and actionable. The selected option
ID must reference a supplied option.
If the current recommendation is still best, keep it but improve specificity and
alignment with feedback context."""


TITLE_NORMALIZATION_PROMPT = """Rewrite the title as a concise, polished
decision heading. Fix typos, broken spacing inside words, capitalization, and
punctuation while preserving meaning. Do not add new facts. Keep it under
60 characters when possible. Return JSON only with {\"title\": \"...\"}."""


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


def _recommendation_from_draft(draft: RecommendationDraft) -> RecommendationResult:
    raw = draft.model_dump(mode="json")
    raw["selected_option_title"] = draft.selected_option_id
    for assessment in raw["option_assessments"]:
        assessment["option_title"] = assessment["option_id"]
    raw["key_risks"] = [{
        **risk,
        "source": "inferred",
        "status": "candidate",
        "evidence_message_ids": [],
    } for risk in raw["key_risks"]]
    return RecommendationResult.model_validate(_normalize_recommendation_payload(raw))


def _recommendation_from_compact_draft(draft: RecommendationCompactDraft) -> RecommendationResult:
    return RecommendationResult(
        selected_option_id=draft.selected_option_id,
        selected_option_title=draft.selected_option_id,
        summary=draft.summary,
        concrete_example=draft.concrete_example,
        rationale=draft.rationale or ["This option is the strongest fit based on the available evidence."],
        assumptions=draft.assumptions,
        unresolved_uncertainties=draft.unresolved_uncertainties,
        robustness=(
            draft.robustness.lower()
            if draft.robustness.lower() in {"low", "moderate", "high"}
            else "low"
        ),
        caveat=draft.caveat,
    )


def _parse_recommendation_cached_result(
    content: str,
    confirmed_selection: dict | None = None,
) -> RecommendationResult:
    try:
        draft = RecommendationDraft.model_validate_json(content)
        draft = _validate_recommendation_selection(draft, confirmed_selection)
        return _recommendation_from_draft(draft)
    except Exception:
        compact = RecommendationCompactDraft.model_validate_json(content)
        if confirmed_selection and compact.selected_option_id != str(confirmed_selection["id"]):
            raise ValueError("The recommendation must preserve the user's confirmed option selection.")
        return _recommendation_from_compact_draft(compact)


def _confirmed_actionable_selection(brief: dict, options: list[dict]) -> dict | None:
    """Resolve the newest explicit option selection to a concrete persisted option."""
    option_by_title = {
        " ".join(str(option.get("title", "")).lower().split()): option
        for option in options
        if option.get("status") != "rejected"
        and (option.get("specificity") or (option.get("metadata") or {}).get("specificity", "actionable")) == "actionable"
    }
    for signal in reversed(brief.get("preference_signals") or []):
        if signal.get("status") in {"rejected", "superseded"}:
            continue
        value = str(signal.get("value") or "")
        if not value.lower().startswith("selected option:"):
            continue
        title = " ".join(value.split(":", 1)[1].strip().lower().split())
        if title in option_by_title:
            return option_by_title[title]
    return None


def _validate_recommendation_selection(
    draft: RecommendationDraft,
    confirmed_selection: dict | None,
) -> RecommendationDraft:
    if confirmed_selection and draft.selected_option_id != str(confirmed_selection["id"]):
        raise ValueError(
            "The recommendation must preserve the user's confirmed option selection."
        )
    return draft


def _fallback_recommendation_from_options(
    brief: dict,
    options: list[dict],
    *,
    caveat: str,
) -> RecommendationResult | None:
    actionable = [option for option in options if option.get("status") != "rejected"]
    if len(actionable) < 2:
        return None
    selected = actionable[0]
    selected_id = str(selected.get("id") or "")
    selected_title = str(selected.get("title") or "the first option")
    values = [
        str(item.get("value") or "")
        for item in brief.get("values", [])
        if isinstance(item, dict) and item.get("status") != "rejected"
    ]
    constraints = [
        str(item.get("value") or "")
        for item in brief.get("constraints", [])
        if isinstance(item, dict) and item.get("status") != "rejected"
    ]
    value_hint = values[0] if values else "your stated priorities"
    constraint_hint = constraints[0] if constraints else "your practical constraints"
    alternative = next(
        (str(option.get("title") or "") for option in actionable[1:] if option.get("title")),
        "the other option",
    )
    return RecommendationResult(
        selected_option_id=selected_id,
        selected_option_title=selected_title,
        summary=(
            f"Start with {_short_option_label(selected_title)} as a provisional choice while we stay within the current AI usage limit."
        ),
        concrete_example=selected_title,
        rationale=[
            f"It is the safest default given {value_hint}.",
            f"It is less likely to violate {constraint_hint}.",
        ],
        alternate_recommendation=f"If this underperforms, switch to {_short_option_label(alternative)}.",
        robustness="low",
        caveat=caveat,
    )


async def generate_grounded_recommendation(
    brief: dict,
    options: list[dict],
    settings: Settings,
) -> RecommendationResult | None:
    if not settings.groq_api_key or len(options) < 2:
        return None
    confirmed_selection = _confirmed_actionable_selection(brief, options)
    payload = {
        "decision_brief": _compact_brief(brief),
        "options": _compact_options(options),
        "confirmed_selection": (
            {
                "option_id": str(confirmed_selection["id"]),
                "display_label": _short_option_label(str(confirmed_selection["title"])),
            }
            if confirmed_selection else None
        ),
    }
    key = _cache_key("recommendation", payload)
    recommendation_token_limit = min(settings.recommendation_max_tokens, 520)
    cached = _cached_content(brief, key, settings)
    if cached:
        try:
            result = _parse_recommendation_cached_result(cached, confirmed_selection)
        except Exception:
            logger.warning("Ignoring cached recommendation that no longer satisfies the output contract")
            cached = None
    if not cached:
        try:
            _check_budget(brief, payload, recommendation_token_limit, settings)
        except DecisionLLMBudgetError:
            logger.warning("Recommendation budget exhausted; using deterministic fallback recommendation")
            return _fallback_recommendation_from_options(
                brief,
                options,
                caveat="AI token budget reached for this decision, so this is a conservative provisional recommendation.",
            )
        client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(), timeout=30.0, max_retries=0
        )
        try:
            await asyncio.sleep(settings.llm_stage_delay_seconds)
            completion, used_model, draft, content = await _complete_structured(
                client, [settings.groq_model, settings.groq_recommendation_fallback_model],
                stage="recommendation",
                schema_name="decision_recommendation_compact",
                response_model=RecommendationCompactDraft,
                parse=lambda value: _validate_recommendation_selection(
                    RecommendationCompactDraft.model_validate(value), confirmed_selection
                ),
                messages=[
                    {"role": "system", "content": RECOMMENDATION_PROMPT},
                    {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
                ],
                temperature=0.1,
                max_completion_tokens=recommendation_token_limit,
            )
            _record_completion(brief, completion, key, content, used_model, settings)
            result = _recommendation_from_compact_draft(draft)
        except (DecisionLLMRateLimitError, DecisionLLMBudgetError):
            raise
        except Exception as exc:
            logger.warning("Recommendation generation failed (%s): %s", type(exc).__name__, exc)
            return None

    option_by_id = {str(option["id"]): option for option in options}
    selected = option_by_id.get(result.selected_option_id)
    if not selected:
        return None
    if confirmed_selection and result.selected_option_id != str(confirmed_selection["id"]):
        logger.warning(
            "Discarding recommendation that overrode confirmed option %s with %s",
            confirmed_selection["id"], result.selected_option_id,
        )
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
    return _sanitize_recommendation(result, option_by_id)


async def classify_revision_feedback(
    brief: dict,
    options: list[dict],
    feedback: str,
    recommendation: dict,
    settings: Settings,
) -> RevisionIntentDraft:
    if not settings.groq_api_key:
        raise DecisionLLMGenerationError("Revision classification requires an AI provider")
    payload = {
        "decision_brief": _compact_brief(brief),
        "options": _compact_options(options),
        "current_recommendation": recommendation,
        "feedback": feedback,
    }
    key = _cache_key("revision_intent", payload)
    cached = _cached_content(brief, key, settings)
    if cached:
        try:
            return RevisionIntentDraft.model_validate_json(cached)
        except Exception:
            logger.warning("Ignoring invalid cached revision intent")

    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=0
    )
    completion, model, draft, content = await _complete_structured(
        client, [settings.groq_light_model, settings.groq_light_fallback_model],
        stage="revision_intent",
        schema_name="revision_intent",
        response_model=RevisionIntentDraft,
        parse=RevisionIntentDraft.model_validate,
        messages=[
            {"role": "system", "content": REVISION_INTENT_PROMPT},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
        ],
        temperature=0.1,
        max_completion_tokens=min(settings.question_max_tokens, 260),
    )
    _record_completion(brief, completion, key, content, model, settings)
    return draft


async def generate_revised_recommendation(
    brief: dict,
    options: list[dict],
    current_recommendation: dict,
    feedback: str,
    settings: Settings,
) -> RecommendationResult | None:
    if not settings.groq_api_key or len(options) < 2:
        return None
    payload = {
        "decision_brief": _compact_brief(brief),
        "options": _compact_options(options),
        "current_recommendation": current_recommendation,
        "feedback": feedback,
    }
    key = _cache_key("revision_recommendation", payload)
    recommendation_token_limit = min(settings.recommendation_max_tokens, 520)
    cached = _cached_content(brief, key, settings)
    if cached:
        try:
            result = _parse_recommendation_cached_result(cached)
        except Exception:
            logger.warning("Ignoring invalid cached revised recommendation")
            cached = None
    if not cached:
        client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(), timeout=30.0, max_retries=0
        )
        try:
            completion, model, draft, content = await _complete_structured(
                client, [settings.groq_model, settings.groq_recommendation_fallback_model],
                stage="revision_recommendation",
                schema_name="revision_recommendation_compact",
                response_model=RecommendationCompactDraft,
                parse=RecommendationCompactDraft.model_validate,
                messages=[
                    {"role": "system", "content": REVISION_RECOMMENDATION_PROMPT},
                    {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
                ],
                temperature=0.15,
                max_completion_tokens=recommendation_token_limit,
            )
            _record_completion(brief, completion, key, content, model, settings)
            result = _recommendation_from_compact_draft(draft)
        except (DecisionLLMRateLimitError, DecisionLLMBudgetError):
            raise
        except Exception as exc:
            logger.warning("Revision recommendation generation failed (%s): %s", type(exc).__name__, exc)
            return None

    option_by_id = {str(option["id"]): option for option in options if option.get("status") != "rejected"}
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
    return _sanitize_recommendation(result, option_by_id)


async def normalize_title_with_ai(
    title: str,
    settings: Settings,
) -> str | None:
    if not settings.groq_api_key:
        return None
    candidate = " ".join(title.strip().split())
    if not candidate:
        return None
    payload = {"title": candidate}
    key = _cache_key("title_normalization", payload)
    # Reuse a small temporary brief-like cache container so this call can use
    # the same strict JSON helper without touching decision token budgets.
    ephemeral: dict[str, Any] = {"llm_cache": {}}
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=15.0, max_retries=0
    )
    completion, model, draft, content = await _complete_structured(
        client, [settings.groq_light_model, settings.groq_light_fallback_model],
        stage="title_normalization",
        schema_name="title_normalization",
        response_model=TitleNormalizationDraft,
        parse=TitleNormalizationDraft.model_validate,
        messages=[
            {"role": "system", "content": TITLE_NORMALIZATION_PROMPT},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
        ],
        temperature=0,
        max_completion_tokens=settings.title_normalization_max_tokens,
    )
    _record_completion(ephemeral, completion, key, content, model, settings)
    normalized = " ".join(draft.title.strip().split())
    if not normalized:
        return None
    return normalized[:200]
