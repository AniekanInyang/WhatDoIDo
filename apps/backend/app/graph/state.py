from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, Field


Confidence = Literal["low", "medium", "high"]
FactSource = Literal["explicit", "inferred", "confirmed", "system_derived"]
DecisionStakes = Literal["low", "medium", "high"]
ResolvableField = Literal["constraints", "uncertainties", "risk_tolerance"]


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    value: str
    source: FactSource = "inferred"
    confidence: Confidence = "medium"
    status: Literal["candidate", "confirmed", "rejected", "superseded"] = "confirmed"
    evidence_message_ids: list[str] = Field(default_factory=list)


class Criterion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)
    importance: int = Field(default=3, ge=1, le=5)
    source: FactSource = "inferred"
    confidence: Confidence = "medium"
    status: Literal["candidate", "confirmed", "rejected", "superseded"] = "candidate"
    evidence_message_ids: list[str] = Field(default_factory=list)


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    statement: str = Field(min_length=1, max_length=1_000)
    importance: Literal["low", "medium", "high"] = "medium"
    confidence: Confidence = "low"
    source: FactSource = "inferred"
    status: Literal["candidate", "confirmed", "rejected", "superseded"] = "candidate"
    evidence_message_ids: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str
    previous_value: str
    new_value: str
    status: Literal["unresolved", "resolved"] = "unresolved"
    resolution: str | None = None
    evidence_message_ids: list[str] = Field(default_factory=list)


class DecisionRisk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    likelihood: Literal["unlikely", "possible", "likely", "unknown"] = "unknown"
    option_ids: list[str] = Field(default_factory=list)
    mitigation: str | None = None
    source: FactSource = "inferred"
    status: Literal["candidate", "confirmed", "rejected"] = "candidate"
    evidence_message_ids: list[str] = Field(default_factory=list)


class OptionObservation(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    source: Literal["user_provided", "ai_extracted", "ai_generated"] = "ai_extracted"
    kind: Literal["alternative", "context"] = "alternative"


class DecisionStatePatch(BaseModel):
    is_decision_input: bool = True
    non_decision_reason: str | None = None
    direction_change: bool = False
    direction_change_summary: str | None = None
    decision_stakes: DecisionStakes | None = None
    goal: Fact | None = None
    domain: Fact | None = None
    deadline: Fact | None = None
    values: list[Fact] = Field(default_factory=list)
    constraints: list[Fact] = Field(default_factory=list)
    uncertainties: list[Fact] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    risk_tolerance: Fact | None = None
    preference_signals: list[Fact] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[DecisionRisk] = Field(default_factory=list)
    options: list[OptionObservation] = Field(default_factory=list)
    resolved_absences: list[ResolvableField] = Field(default_factory=list)


class InformationGap(BaseModel):
    key: str
    question_category: str
    reason: str
    impact: float = Field(ge=0, le=1)


class Readiness(BaseModel):
    score: float = Field(ge=0, le=1)
    enough_to_recommend: bool = False
    blockers: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    action: Literal["clarify_decision", "ask_clarification", "confirm_inference", "resolve_contradiction", "evaluate", "recommend"]
    category: str
    question: str | None = None
    rationale: str
    utility: float = 0
    expected_answer_type: str | None = None
    target_field: str | None = None
    attempt: int = 1


class QuestionDraft(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    target_field: str
    expected_answer_type: str
    acknowledges_answer: bool = False
    suggested_options: list[OptionObservation] = Field(default_factory=list)


class OptionAssessment(BaseModel):
    option_id: str
    option_title: str
    fit: Literal["weak", "mixed", "strong"]
    strengths: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    constraint_conflicts: list[str] = Field(default_factory=list)


class SensitivityDriver(BaseModel):
    factor: str
    current_assumption: str
    change_that_could_flip_result: str
    likely_winner_option_id: str | None = None
    explanation: str


class RecommendationResult(BaseModel):
    selected_option_id: str
    selected_option_title: str
    summary: str
    rationale: list[str] = Field(min_length=1)
    option_assessments: list[OptionAssessment] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    key_risks: list[DecisionRisk] = Field(default_factory=list)
    checks_before_acting: list[str] = Field(default_factory=list)
    alternate_recommendation: str | None = None
    sensitivity_analysis: list[SensitivityDriver] = Field(default_factory=list)
    robustness: Literal["low", "moderate", "high"] = "low"
    caveat: str | None = None


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    cache_hits: int = 0
    budget_tokens: int = 20_000
    exhausted: bool = False


class DecisionBrief(BaseModel):
    schema_version: int = 2
    revision: int = 0
    phase: Literal["intake", "clarifying", "evaluating", "recommended", "completed"] = "intake"
    decision_stakes: DecisionStakes | None = None
    goal: Fact | None = None
    domain: Fact | None = None
    deadline: Fact | None = None
    values: list[Fact] = Field(default_factory=list)
    constraints: list[Fact] = Field(default_factory=list)
    uncertainties: list[Fact] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    risk_tolerance: Fact | None = None
    preference_signals: list[Fact] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    risks: list[DecisionRisk] = Field(default_factory=list)
    resolved_absences: list[ResolvableField] = Field(default_factory=list)
    superseded_states: list[dict[str, Any]] = Field(default_factory=list)
    option_ids: list[str] = Field(default_factory=list)
    missing_information: list[InformationGap] = Field(default_factory=list)
    readiness: Readiness = Field(default_factory=lambda: Readiness(score=0))
    next_action: ActionPlan | None = None
    question_history: list[dict[str, Any]] = Field(default_factory=list)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    llm_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PolicyActionStats(BaseModel):
    asked: int = 0
    answered: int = 0
    skipped: int = 0
    reward_sum: float = 0

    @property
    def average_reward(self) -> float:
        return self.reward_sum / self.asked if self.asked else 0


class ClarificationProfile(BaseModel):
    schema_version: int = 1
    total_interactions: int = 0
    action_stats: dict[str, PolicyActionStats] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)


class GraphState(TypedDict, total=False):
    decision_id: str
    user_id: str
    user_message: str
    message_id: str
    brief: dict[str, Any]
    existing_options: list[dict[str, Any]]
    profile: dict[str, Any]
    patch: dict[str, Any]
    new_options: list[dict[str, Any]]
    duplicate_options: list[dict[str, str]]
    assistant_reply: str
    selected_action: dict[str, Any]
    question_request: dict[str, Any]
    extraction_diagnostic: dict[str, Any]
    recommendation: dict[str, Any]
    recommendation_error: str
    is_decision_input: bool
    direction_changed: bool
    workflow_error: dict[str, Any]
