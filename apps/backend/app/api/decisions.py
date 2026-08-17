from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.models.decision import (
    ConversationTurn,
    DecisionCreate,
    DecisionDetail,
    DecisionMessageCreate,
    DecisionSummary,
    DecisionTitleUpdate,
)
from app.services.decisions import DecisionStore


router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post("", response_model=DecisionSummary, status_code=status.HTTP_201_CREATED)
async def create_decision(
    values: DecisionCreate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionSummary:
    return await DecisionStore(settings, user).create(values)


@router.get("", response_model=list[DecisionSummary])
async def list_decisions(
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[DecisionSummary]:
    return await DecisionStore(settings, user).list()


@router.get("/{decision_id}", response_model=DecisionDetail)
async def get_decision(
    decision_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionDetail:
    return await DecisionStore(settings, user).get(decision_id)


@router.patch("/{decision_id}/title", response_model=DecisionSummary)
async def rename_decision(
    decision_id: UUID,
    values: DecisionTitleUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionSummary:
    return await DecisionStore(settings, user).rename(decision_id, values)


@router.post("/{decision_id}/messages", response_model=ConversationTurn, status_code=status.HTTP_201_CREATED)
async def add_decision_message(
    decision_id: UUID,
    values: DecisionMessageCreate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationTurn:
    return await DecisionStore(settings, user).add_message(decision_id, values)
