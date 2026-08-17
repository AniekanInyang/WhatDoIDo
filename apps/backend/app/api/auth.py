from fastapi import APIRouter

from app.core.auth import CurrentUser


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def read_current_user(user: CurrentUser) -> dict[str, str | None]:
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
    }
