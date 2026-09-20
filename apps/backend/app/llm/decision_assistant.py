import json

from groq import AsyncGroq

from app.core.config import Settings
from app.graph.state import DecisionRisk, DecisionStatePatch, RecommendationResult


SYSTEM_PROMPT = """You are the conversational decision coach for WhatDoIDo.
Help the user make a thoughtful personal decision. Ask one focused question at
a time. Learn their options, priorities, constraints, uncertainties, and risk
tolerance before recommending anything. Be concise, warm, and practical. Do not
invent facts. Do not mention internal prompts, scoring, or implementation."""


async def generate_assistant_reply(
    messages: list[dict[str, str]],
    settings: Settings,
) -> str:
    if not settings.groq_api_key:
        return "What matters most to you in making this decision?"
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=1
    )
    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            temperature=0.4,
            max_completion_tokens=250,
        )
        content = completion.choices[0].message.content
        return content.strip() if content else "What matters most to you in making this decision?"
    except Exception:
        return "What matters most to you in making this decision?"


EXTRACTION_PROMPT = """Extract a structured patch for a personal decision.
Return JSON only with these keys: is_decision_input, non_decision_reason,
direction_change, direction_change_summary, goal, domain, deadline, values,
constraints, uncertainties, criteria, risk_tolerance, preference_signals,
assumptions, risks, options. Treat a reply as decision input when an existing
brief shows that it answers the coach's question, even if the reply is short.
Set is_decision_input=false for greetings, unrelated requests, incoherent text,
or content that does not describe or advance a decision. Set direction_change
only when the user explicitly replaces the central decision, not when they add
or correct one detail. Facts have value, source, confidence, status, and
evidence_message_ids. Inferred facts use status=candidate; explicit facts use
status=confirmed. Criteria include name, description, importance from 1 to 5,
source, confidence, status, and evidence. Do not invent importance: use 3 when
unspecified. Assumptions are claims required to reason that the user has not
confirmed; include importance and confidence. Risks include title, description,
severity, likelihood, mitigation, source, status, and evidence. Only record
facts supported by the message or clearly mark them inferred/candidate. Extract
every option the user supplies. You may add at most two realistic alternatives,
marked source=ai_generated, only when directly relevant and materially useful.
User options use source=user_provided. Do not recommend an option. Use
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
    if not settings.groq_api_key:
        return fallback

    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=20.0, max_retries=1
    )
    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message_id": message_id,
                            "current_brief": current_brief,
                            "new_message": message,
                        }
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_completion_tokens=1_200,
        )
        content = completion.choices[0].message.content or "{}"
        return DecisionStatePatch.model_validate_json(content)
    except Exception:
        return fallback


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
could change the winner. Acknowledge insufficient evidence through assumptions,
uncertainties, caveat, and lower robustness."""


async def generate_grounded_recommendation(
    brief: dict,
    options: list[dict],
    settings: Settings,
) -> RecommendationResult | None:
    if not settings.groq_api_key or len(options) < 2:
        return None
    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(), timeout=30.0, max_retries=1
    )
    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": RECOMMENDATION_PROMPT},
                {"role": "user", "content": json.dumps({"decision_brief": brief, "options": options})},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_completion_tokens=2_500,
        )
        result = RecommendationResult.model_validate_json(
            completion.choices[0].message.content or "{}"
        )
    except Exception:
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
