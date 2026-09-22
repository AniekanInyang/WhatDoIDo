from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.models.decision import (
    ConversationTurn,
    DecisionCreate,
    DecisionCollectionUpdate,
    DecisionDetail,
    DecisionPage,
    DecisionMessageCreate,
    DecisionMessage,
    DecisionOption,
    DecisionOptionCreate,
    DecisionOptionUpdate,
    DecisionOptionStatusUpdate,
    DecisionStateItemReview,
    ContradictionResolution,
    DecisionSummary,
    DecisionTitleUpdate,
)
from app.services.decisions import DecisionStore


router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post("", response_model=DecisionSummary, status_code=status.HTTP_201_CREATED)
async def create_decision(
    values: DecisionCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionSummary:
    store = DecisionStore(settings, user)
    decision, user_message = await store.create_pending(values)
    background_tasks.add_task(store.process_initial_turn, decision.id, user_message)
    return decision


@router.get("", response_model=DecisionPage)
async def list_decisions(
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    q: str | None = Query(default=None, max_length=200),
    collection_id: UUID | None = None,
    uncategorized: bool = False,
    trash: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> DecisionPage:
    return await DecisionStore(settings, user).list(
        search=q,
        collection_id=collection_id,
        uncategorized=uncategorized,
        trash=trash,
        cursor=cursor,
        limit=limit,
    )


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


@router.post("/{decision_id}/options", response_model=DecisionOption, status_code=status.HTTP_201_CREATED)
async def create_decision_option(
    decision_id: UUID,
    values: DecisionOptionCreate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionOption:
    return await DecisionStore(settings, user).create_option(decision_id, values)


@router.patch("/{decision_id}/options/{option_id}", response_model=DecisionOption)
async def update_decision_option(
    decision_id: UUID,
    option_id: UUID,
    values: DecisionOptionUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionOption:
    return await DecisionStore(settings, user).update_option(decision_id, option_id, values)


@router.delete("/{decision_id}/options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision_option(
    decision_id: UUID,
    option_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await DecisionStore(settings, user).delete_option(decision_id, option_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{decision_id}/options/{option_id}/status", response_model=DecisionOption)
async def review_decision_option(
    decision_id: UUID,
    option_id: UUID,
    values: DecisionOptionStatusUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionOption:
    return await DecisionStore(settings, user).review_option(decision_id, option_id, values)


@router.patch("/{decision_id}/brief/items", response_model=DecisionDetail)
async def review_decision_state_item(
    decision_id: UUID,
    values: DecisionStateItemReview,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionDetail:
    return await DecisionStore(settings, user).review_state_item(decision_id, values)


@router.patch("/{decision_id}/brief/contradictions", response_model=DecisionDetail)
async def resolve_decision_contradiction(
    decision_id: UUID,
    values: ContradictionResolution,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionDetail:
    return await DecisionStore(settings, user).resolve_contradiction(decision_id, values)


@router.post("/{decision_id}/workflow/retry", response_model=DecisionMessage)
async def retry_decision_workflow(
    decision_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionMessage:
    return await DecisionStore(settings, user).retry_workflow(decision_id)


@router.put("/{decision_id}/collection", status_code=status.HTTP_204_NO_CONTENT)
async def move_decision(
    decision_id: UUID,
    values: DecisionCollectionUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await DecisionStore(settings, user).set_collection(decision_id, values)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{decision_id}/trash", response_model=DecisionSummary)
async def trash_decision(
    decision_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionSummary:
    return await DecisionStore(settings, user).trash(decision_id)


@router.post("/{decision_id}/restore", response_model=DecisionSummary)
async def restore_decision(
    decision_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DecisionSummary:
    return await DecisionStore(settings, user).restore(decision_id)


@router.delete("/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_decision(
    decision_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await DecisionStore(settings, user).permanently_delete(decision_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
