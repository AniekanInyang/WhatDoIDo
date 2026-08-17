from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.models.account import AccountDeletion, AccountOverview, DataExport, Profile, ProfileUpdate
from app.services.account import AccountService


router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountOverview)
async def get_account(user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]) -> AccountOverview:
    return await AccountService(settings, user).overview()


@router.patch("/profile", response_model=Profile)
async def update_profile(
    values: ProfileUpdate,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Profile:
    return await AccountService(settings, user).update_profile(values)


@router.get("/export", response_model=DataExport)
async def export_account(user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]) -> DataExport:
    return await AccountService(settings, user).export()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    values: AccountDeletion,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    await AccountService(settings, user).delete(values)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
