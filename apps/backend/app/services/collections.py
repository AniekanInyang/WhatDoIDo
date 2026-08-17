from uuid import UUID

import httpx
from fastapi import HTTPException, status

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.models.collection import Collection, CollectionCreate, CollectionUpdate


class CollectionStore:
    def __init__(self, settings: Settings, user: AuthenticatedUser) -> None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise HTTPException(status_code=503, detail="Supabase is not configured")
        self.url = f"{settings.supabase_url.rstrip('/')}/rest/v1/collections"
        self.headers = {
            "apikey": settings.supabase_anon_key.get_secret_value(),
            "Authorization": f"Bearer {user.access_token}",
            "Accept": "application/json",
        }
        self.user = user

    async def _request(
        self,
        method: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
        representation: bool = False,
    ) -> list[dict]:
        headers = self.headers.copy()
        if representation:
            headers["Prefer"] = "return=representation"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.request(method, self.url, params=params, json=json, headers=headers)
            except httpx.RequestError as exc:
                raise HTTPException(status_code=503, detail="Supabase is unavailable") from exc
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail="A collection with this name already exists")
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail="Supabase rejected the collection request")
        return response.json() if response.content else []

    async def list(self) -> list[Collection]:
        rows = await self._request("GET", params={"select": "*", "order": "name.asc"})
        return [Collection.model_validate(row) for row in rows]

    async def create(self, values: CollectionCreate) -> Collection:
        rows = await self._request(
            "POST",
            json={"user_id": str(self.user.id), "name": values.name.strip()},
            representation=True,
        )
        return Collection.model_validate(rows[0])

    async def rename(self, collection_id: UUID, values: CollectionUpdate) -> Collection:
        rows = await self._request(
            "PATCH",
            params={"id": f"eq.{collection_id}"},
            json={"name": values.name.strip()},
            representation=True,
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
        return Collection.model_validate(rows[0])

    async def delete(self, collection_id: UUID) -> None:
        await self._request("DELETE", params={"id": f"eq.{collection_id}"})
