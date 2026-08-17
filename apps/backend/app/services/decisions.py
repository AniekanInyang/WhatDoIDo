import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.models.decision import (
    ConversationTurn,
    DecisionCreate,
    DecisionCollectionUpdate,
    DecisionDetail,
    DecisionPage,
    DecisionMessage,
    DecisionMessageCreate,
    DecisionSummary,
    DecisionTitleUpdate,
)
from app.llm.decision_assistant import generate_assistant_reply


class DecisionStore:
    def __init__(self, settings: Settings, user: AuthenticatedUser) -> None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase database is not configured on the backend",
            )

        self.base_url = f"{settings.supabase_url.rstrip('/')}/rest/v1"
        self.headers = {
            "apikey": settings.supabase_anon_key.get_secret_value(),
            "Authorization": f"Bearer {user.access_token}",
            "Accept": "application/json",
        }
        self.user = user
        self.settings = settings

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        prefer_representation: bool = False,
        trusted_backend: bool = False,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        headers = self.headers.copy()
        if trusted_backend:
            if not self.settings.supabase_service_role_key:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Trusted database access is not configured",
                )
            service_key = self.settings.supabase_service_role_key.get_secret_value()
            headers["apikey"] = service_key
            headers["Authorization"] = f"Bearer {service_key}"
        preferences = []
        if prefer_representation:
            preferences.append("return=representation")
        if prefer:
            preferences.append(prefer)
        if preferences:
            headers["Prefer"] = ",".join(preferences)

        try:
            response = await client.request(
                method,
                f"{self.base_url}/{path}",
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase database is unavailable",
            ) from exc

        if response.status_code >= 400:
            if response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
                raise HTTPException(status_code=response.status_code, detail="Database access denied")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supabase rejected the database request",
            )

        if not response.content:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else [payload]

    async def create(self, values: DecisionCreate) -> DecisionSummary:
        title = self._title_from_prompt(values.prompt)
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "POST",
                "decisions",
                json={
                    "user_id": str(self.user.id),
                    "title": title,
                    "prompt": values.prompt,
                },
                prefer_representation=True,
            )
            decision = DecisionSummary.model_validate(rows[0])
            user_message = await self._insert_message(
                client, decision.id, "user", values.prompt, trusted_backend=False
            )
            reply = await generate_assistant_reply(
                [{"role": "user", "content": user_message.content}], self.settings
            )
            await self._insert_message(
                client, decision.id, "assistant", reply, trusted_backend=True
            )
        return decision

    @staticmethod
    def _title_from_prompt(prompt: str) -> str:
        normalized = " ".join(prompt.strip().split())
        words = normalized.rstrip("?.!").split()
        title = " ".join(words[:8])
        if len(words) > 8:
            title += "…"
        return title[:1].upper() + title[1:]

    async def _insert_message(
        self,
        client: httpx.AsyncClient,
        decision_id: UUID,
        role: str,
        content: str,
        *,
        trusted_backend: bool,
    ) -> DecisionMessage:
        rows = await self._request(
            client,
            "POST",
            "decision_messages",
            json={"decision_id": str(decision_id), "role": role, "content": content},
            prefer_representation=True,
            trusted_backend=trusted_backend,
        )
        return DecisionMessage.model_validate(rows[0])

    async def add_message(
        self, decision_id: UUID, values: DecisionMessageCreate
    ) -> ConversationTurn:
        decision = await self.get(decision_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_message = await self._insert_message(
                client, decision_id, "user", values.content, trusted_backend=False
            )
            history = [
                {"role": message.role, "content": message.content}
                for message in decision.messages
                if message.role in ("user", "assistant")
            ]
            history.append({"role": "user", "content": user_message.content})
            reply = await generate_assistant_reply(history[-20:], self.settings)
            assistant_message = await self._insert_message(
                client, decision_id, "assistant", reply, trusted_backend=True
            )
        return ConversationTurn(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    @staticmethod
    def _encode_cursor(updated_at: datetime, decision_id: UUID) -> str:
        raw = json.dumps({"updated_at": updated_at.isoformat(), "id": str(decision_id)}).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[str | None, str | None]:
        if not cursor:
            return None, None
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode())
            return str(datetime.fromisoformat(payload["updated_at"]).isoformat()), str(UUID(payload["id"]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc

    async def list(
        self,
        *,
        search: str | None = None,
        collection_id: UUID | None = None,
        uncategorized: bool = False,
        trash: bool = False,
        cursor: str | None = None,
        limit: int = 20,
    ) -> DecisionPage:
        cursor_updated_at, cursor_id = self._decode_cursor(cursor)
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "POST",
                "rpc/search_user_decisions",
                json={
                    "p_search": search,
                    "p_collection_id": str(collection_id) if collection_id else None,
                    "p_uncategorized": uncategorized,
                    "p_trash": trash,
                    "p_cursor_updated_at": cursor_updated_at,
                    "p_cursor_id": cursor_id,
                    "p_limit": limit + 1,
                },
            )
        has_more = len(rows) > limit
        items = [DecisionSummary.model_validate(row) for row in rows[:limit]]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = self._encode_cursor(last.updated_at, last.id)
        return DecisionPage(items=items, next_cursor=next_cursor)

    async def get(self, decision_id: UUID) -> DecisionDetail:
        async with httpx.AsyncClient(timeout=10.0) as client:
            decisions = await self._request(
                client,
                "GET",
                "decisions",
                params={"id": f"eq.{decision_id}", "select": "*", "limit": "1"},
            )
            if not decisions:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")

            options = await self._request(
                client,
                "GET",
                "decision_options",
                params={"decision_id": f"eq.{decision_id}", "select": "*", "order": "position.asc"},
            )
            messages = await self._request(
                client,
                "GET",
                "decision_messages",
                params={"decision_id": f"eq.{decision_id}", "select": "*", "order": "created_at.asc"},
            )
            evaluations = await self._request(
                client,
                "GET",
                "evaluations",
                params={"decision_id": f"eq.{decision_id}", "select": "*", "order": "created_at.desc"},
            )

        return DecisionDetail.model_validate(
            {
                **decisions[0],
                "options": options,
                "messages": messages,
                "evaluations": evaluations,
            }
        )

    async def rename(self, decision_id: UUID, values: DecisionTitleUpdate) -> DecisionSummary:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "PATCH",
                "decisions",
                params={"id": f"eq.{decision_id}"},
                json={"title": values.title},
                prefer_representation=True,
            )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
        return DecisionSummary.model_validate(rows[0])

    async def set_collection(self, decision_id: UUID, values: DecisionCollectionUpdate) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Confirm ownership of the decision before changing its organization.
            decisions = await self._request(
                client, "GET", "decisions", params={"id": f"eq.{decision_id}", "select": "id", "limit": "1"}
            )
            if not decisions:
                raise HTTPException(status_code=404, detail="Decision not found")

            if values.collection_id is None:
                await self._request(
                    client, "DELETE", "collection_decisions", params={"decision_id": f"eq.{decision_id}"}
                )
                return

            collections = await self._request(
                client,
                "GET",
                "collections",
                params={"id": f"eq.{values.collection_id}", "select": "id", "limit": "1"},
            )
            if not collections:
                raise HTTPException(status_code=404, detail="Collection not found")
            await self._request(
                client,
                "POST",
                "collection_decisions",
                params={"on_conflict": "decision_id"},
                json={"decision_id": str(decision_id), "collection_id": str(values.collection_id)},
                prefer="resolution=merge-duplicates",
            )

    async def trash(self, decision_id: UUID) -> DecisionSummary:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "PATCH",
                "decisions",
                params={"id": f"eq.{decision_id}", "deleted_at": "is.null"},
                json={"deleted_at": datetime.now().astimezone().isoformat()},
                prefer_representation=True,
            )
        if not rows:
            raise HTTPException(status_code=404, detail="Decision not found")
        return DecisionSummary.model_validate(rows[0])

    async def restore(self, decision_id: UUID) -> DecisionSummary:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "PATCH",
                "decisions",
                params={"id": f"eq.{decision_id}", "deleted_at": "not.is.null"},
                json={"deleted_at": None},
                prefer_representation=True,
            )
        if not rows:
            raise HTTPException(status_code=404, detail="Trashed decision not found")
        return DecisionSummary.model_validate(rows[0])

    async def permanently_delete(self, decision_id: UUID) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client,
                "GET",
                "decisions",
                params={"id": f"eq.{decision_id}", "deleted_at": "not.is.null", "select": "id", "limit": "1"},
            )
            if not rows:
                raise HTTPException(status_code=404, detail="Trashed decision not found")
            await self._request(client, "DELETE", "decisions", params={"id": f"eq.{decision_id}"})
