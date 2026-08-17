from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.models.account import AccountDeletion, AccountOverview, DataExport, Profile, ProfileUpdate


class AccountService:
    def __init__(self, settings: Settings, user: AuthenticatedUser) -> None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise HTTPException(status_code=503, detail="Supabase is not configured")
        self.settings = settings
        self.user = user
        self.rest_url = f"{settings.supabase_url.rstrip('/')}/rest/v1"
        self.user_headers = {
            "apikey": settings.supabase_anon_key.get_secret_value(),
            "Authorization": f"Bearer {user.access_token}",
            "Accept": "application/json",
        }

    async def _rows(
        self,
        client: httpx.AsyncClient,
        table: str,
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        headers = self.user_headers.copy()
        if method != "GET":
            headers["Prefer"] = "return=representation"
        try:
            response = await client.request(
                method,
                f"{self.rest_url}/{table}",
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="Supabase is unavailable") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail="Supabase rejected the account request")
        return response.json() if response.content else []

    async def overview(self) -> AccountOverview:
        async with httpx.AsyncClient(timeout=10.0) as client:
            profiles = await self._rows(
                client, "profiles", params={"id": f"eq.{self.user.id}", "select": "*", "limit": "1"}
            )
        if not profiles:
            raise HTTPException(status_code=404, detail="Profile not found")
        return AccountOverview(
            id=str(self.user.id),
            email=self.user.email,
            created_at=self.user.created_at,
            last_sign_in_at=self.user.last_sign_in_at,
            profile=Profile.model_validate(profiles[0]),
        )

    async def update_profile(self, values: ProfileUpdate) -> Profile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._rows(
                client,
                "profiles",
                method="PATCH",
                params={"id": f"eq.{self.user.id}"},
                json={"display_name": values.display_name},
            )
        if not rows:
            raise HTTPException(status_code=404, detail="Profile not found")
        return Profile.model_validate(rows[0])

    async def export(self) -> DataExport:
        async with httpx.AsyncClient(timeout=20.0) as client:
            profile = await self._rows(client, "profiles", params={"select": "*"})
            decisions = await self._rows(client, "decisions", params={"select": "*", "order": "created_at.asc"})
            options = await self._rows(client, "decision_options", params={"select": "*", "order": "created_at.asc"})
            messages = await self._rows(client, "decision_messages", params={"select": "*", "order": "created_at.asc"})
            evaluations = await self._rows(client, "evaluations", params={"select": "*", "order": "created_at.asc"})
            collections = await self._rows(client, "collections", params={"select": "*", "order": "created_at.asc"})
            collection_decisions = await self._rows(client, "collection_decisions", params={"select": "*", "order": "added_at.asc"})
        return DataExport(
            exported_at=datetime.now(UTC).isoformat(),
            account={
                "id": str(self.user.id),
                "email": self.user.email,
                "created_at": self.user.created_at,
                "last_sign_in_at": self.user.last_sign_in_at,
            },
            profile=profile[0] if profile else None,
            decisions=decisions,
            decision_options=options,
            decision_messages=messages,
            evaluations=evaluations,
            collections=collections,
            collection_decisions=collection_decisions,
        )

    async def delete(self, values: AccountDeletion) -> None:
        if not self.user.email:
            raise HTTPException(status_code=400, detail="This account cannot be password-verified")
        if not self.settings.supabase_service_role_key:
            raise HTTPException(status_code=503, detail="Account deletion is not configured")

        anon_key = self.settings.supabase_anon_key.get_secret_value()
        service_key = self.settings.supabase_service_role_key.get_secret_value()
        base_url = self.settings.supabase_url.rstrip("/")
        async with httpx.AsyncClient(timeout=15.0) as client:
            verification = await client.post(
                f"{base_url}/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": anon_key, "Content-Type": "application/json"},
                json={"email": self.user.email, "password": values.password},
            )
            if verification.status_code != status.HTTP_200_OK:
                raise HTTPException(status_code=401, detail="Current password is incorrect")

            deletion = await client.delete(
                f"{base_url}/auth/v1/admin/users/{self.user.id}",
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                },
            )
            if deletion.status_code >= 400:
                raise HTTPException(status_code=502, detail="Supabase could not delete the account")
