from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DecisionCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)


class DecisionTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class DecisionSummary(BaseModel):
    id: UUID
    title: str
    prompt: str
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    collection_id: UUID | None = None
    collection_name: str | None = None


class DecisionPage(BaseModel):
    items: list[DecisionSummary]
    next_cursor: str | None = None


class DecisionCollectionUpdate(BaseModel):
    collection_id: UUID | None = None


class DecisionOption(BaseModel):
    id: UUID
    decision_id: UUID
    title: str
    description: str | None = None
    position: int
    evaluation: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DecisionMessage(BaseModel):
    id: UUID
    decision_id: UUID
    role: str
    content: str
    structured_data: dict[str, Any]
    created_at: datetime


class DecisionMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class ConversationTurn(BaseModel):
    user_message: DecisionMessage
    assistant_message: DecisionMessage


class Evaluation(BaseModel):
    id: UUID
    decision_id: UUID
    summary: str
    confidence: float | None = None
    risk_level: str | None = None
    reasoning: list[Any] | dict[str, Any]
    checks: list[Any] | dict[str, Any]
    created_at: datetime


class DecisionDetail(DecisionSummary):
    decision_brief: dict[str, Any]
    recommendation: dict[str, Any] | None = None
    options: list[DecisionOption] = Field(default_factory=list)
    messages: list[DecisionMessage] = Field(default_factory=list)
    evaluations: list[Evaluation] = Field(default_factory=list)
