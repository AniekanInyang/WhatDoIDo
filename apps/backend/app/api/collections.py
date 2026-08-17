from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.models.collection import Collection, CollectionCreate, CollectionUpdate
from app.services.collections import CollectionStore


router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=list[Collection])
async def list_collections(user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]) -> list[Collection]:
    return await CollectionStore(settings, user).list()


@router.post("", response_model=Collection, status_code=status.HTTP_201_CREATED)
async def create_collection(
    values: CollectionCreate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Collection:
    return await CollectionStore(settings, user).create(values)


@router.patch("/{collection_id}", response_model=Collection)
async def rename_collection(
    collection_id: UUID,
    values: CollectionUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Collection:
    return await CollectionStore(settings, user).rename(collection_id, values)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await CollectionStore(settings, user).delete(collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
