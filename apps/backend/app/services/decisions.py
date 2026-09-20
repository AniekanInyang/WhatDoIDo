import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

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
    DecisionOption,
    DecisionOptionCreate,
    DecisionOptionUpdate,
    DecisionOptionStatusUpdate,
    DecisionStateItemReview,
    ContradictionResolution,
    DecisionSummary,
    DecisionTitleUpdate,
)
from app.graph.state import ClarificationProfile, PolicyActionStats
from app.graph.workflow import _same_option, build_decision_graph


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
            await self._run_conversation_turn(client, decision.id, user_message, {}, [])
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
        structured_data: dict[str, Any] | None = None,
    ) -> DecisionMessage:
        rows = await self._request(
            client,
            "POST",
            "decision_messages",
            json={
                "decision_id": str(decision_id),
                "role": role,
                "content": content,
                "structured_data": structured_data or {},
            },
            prefer_representation=True,
            trusted_backend=trusted_backend,
        )
        return DecisionMessage.model_validate(rows[0])

    async def add_message(
        self, decision_id: UUID, values: DecisionMessageCreate
    ) -> ConversationTurn:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(
                status_code=409,
                detail="Completed decisions are read-only; only the title can be changed",
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_message = await self._insert_message(
                client, decision_id, "user", values.content, trusted_backend=False
            )
            assistant_message = await self._run_conversation_turn(
                client,
                decision_id,
                user_message,
                decision.decision_brief,
                [option.model_dump(mode="json") for option in decision.options],
            )
        return ConversationTurn(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    async def _load_policy_profile(self, client: httpx.AsyncClient) -> ClarificationProfile:
        rows = await self._request(
            client,
            "GET",
            "clarification_profiles",
            params={"user_id": f"eq.{self.user.id}", "select": "profile", "limit": "1"},
            trusted_backend=True,
        )
        return ClarificationProfile.model_validate(rows[0]["profile"] if rows else {})

    async def _learn_from_previous_question(
        self,
        client: httpx.AsyncClient,
        decision_id: UUID,
        response: str,
        profile: ClarificationProfile,
    ) -> ClarificationProfile:
        rows = await self._request(
            client,
            "GET",
            "clarification_events",
            params={
                "user_id": f"eq.{self.user.id}",
                "decision_id": f"eq.{decision_id}",
                "outcome": "is.null",
                "select": "id,action_category",
                "order": "created_at.desc",
                "limit": "1",
            },
            trusted_backend=True,
        )
        if not rows:
            return profile

        skipped_words = {"skip", "pass", "not sure", "i don't know", "idk"}
        normalized = " ".join(response.lower().strip().split())
        skipped = normalized in skipped_words
        reward = -0.5 if skipped else 1.0
        category = rows[0]["action_category"]
        stats = profile.action_stats.setdefault(category, PolicyActionStats())
        stats.skipped += int(skipped)
        stats.answered += int(not skipped)
        stats.reward_sum += reward
        profile.total_interactions += 1
        await self._request(
            client,
            "PATCH",
            "clarification_events",
            params={"id": f"eq.{rows[0]['id']}", "user_id": f"eq.{self.user.id}"},
            json={"outcome": "skipped" if skipped else "answered", "reward": reward},
            trusted_backend=True,
        )
        return profile

    async def _save_policy_profile(
        self, client: httpx.AsyncClient, profile: ClarificationProfile
    ) -> None:
        existing = await self._request(
            client,
            "GET",
            "decision_state_events",
            params={
                "decision_id": f"eq.{decision_id}",
                "revision": f"eq.{revision}",
                "event_type": f"eq.{event_type}",
                "select": "id",
                "limit": "1",
            },
            trusted_backend=True,
        )
        if existing:
            return
        await self._request(
            client,
            "POST",
            "clarification_profiles",
            params={"on_conflict": "user_id"},
            json={"user_id": str(self.user.id), "profile": profile.model_dump(mode="json")},
            trusted_backend=True,
            prefer="resolution=merge-duplicates",
        )

    async def _run_conversation_turn(
        self,
        client: httpx.AsyncClient,
        decision_id: UUID,
        user_message: DecisionMessage,
        brief: dict[str, Any],
        options: list[dict[str, Any]],
    ) -> DecisionMessage:
        profile = await self._load_policy_profile(client)
        profile = await self._learn_from_previous_question(
            client, decision_id, user_message.content, profile
        )
        await self._save_policy_profile(client, profile)
        payload = {
                "decision_id": str(decision_id),
                "user_id": str(self.user.id),
                "user_message": user_message.content,
                "message_id": str(user_message.id),
                "brief": brief,
                "existing_options": options,
                "profile": profile.model_dump(mode="json"),
                "recommendation": {},
                "recommendation_error": "",
            }
        try:
            result = await self._invoke_graph(decision_id, payload)
        except Exception:
            await self._record_state_event(
                client, decision_id, "workflow_failed", int(brief.get("revision", 0)),
                {"message_id": str(user_message.id), "retryable": True},
            )
            return await self._insert_message(
                client, decision_id, "assistant",
                "The workflow was interrupted after retrying. Your progress is saved at the failed stage; use Retry workflow to continue.",
                trusted_backend=True,
                structured_data={"workflow_error": "retryable", "retry_available": True},
            )
        try:
            return await self._persist_graph_result(
                client, decision_id, user_message, options, profile, result
            )
        except Exception:
            return await self._insert_message(
                client, decision_id, "assistant",
                "The workflow finished, but saving its result was interrupted. Use Retry workflow to safely finish saving it.",
                trusted_backend=True,
                structured_data={"workflow_error": "persistence", "retry_available": True},
            )

    async def _invoke_graph(
        self, decision_id: UUID, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": f"{self.user.id}:{decision_id}"}}
        if not self.settings.database_url:
            if payload is None:
                raise HTTPException(status_code=503, detail="Durable workflow checkpoints are not configured")
            return await build_decision_graph(self.settings).ainvoke(payload)
        connection_string = self.settings.database_url.get_secret_value()
        async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:
            await checkpointer.setup()
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"):
                await checkpointer.conn.execute(
                    f"alter table public.{table} enable row level security"
                )
                await checkpointer.conn.execute(
                    f"revoke all on table public.{table} from anon, authenticated"
                )
            graph = build_decision_graph(self.settings, checkpointer=checkpointer)
            return await graph.ainvoke(payload, config=config)

    async def retry_workflow(self, decision_id: UUID) -> DecisionMessage:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="This decision is already completed")
        try:
            result = await self._invoke_graph(decision_id, None)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="The saved workflow could not be resumed") from exc
        message_id = result.get("message_id")
        user_message = next(
            (message for message in decision.messages if str(message.id) == message_id), None
        )
        if not user_message:
            raise HTTPException(status_code=409, detail="The checkpoint does not reference a valid user message")
        async with httpx.AsyncClient(timeout=15.0) as client:
            profile = await self._load_policy_profile(client)
            return await self._persist_graph_result(
                client,
                decision_id,
                user_message,
                [option.model_dump(mode="json") for option in decision.options],
                profile,
                result,
            )

    async def _persist_graph_result(
        self,
        client: httpx.AsyncClient,
        decision_id: UUID,
        user_message: DecisionMessage,
        options: list[dict[str, Any]],
        profile: ClarificationProfile,
        result: dict[str, Any],
    ) -> DecisionMessage:

        if result.get("direction_changed"):
            await self._request(
                client,
                "PATCH",
                "decision_options",
                params={"decision_id": f"eq.{decision_id}", "status": "neq.rejected"},
                json={"status": "rejected"},
                trusted_backend=True,
            )
        persisted_option_ids = [] if result.get("direction_changed") else [
            str(option["id"]) for option in options if option.get("status") != "rejected"
        ]
        for position, option in enumerate(result.get("new_options", []), start=len(options)):
            rows = await self._request(
                client,
                "POST",
                "decision_options",
                params={"on_conflict": "decision_id,title"},
                json={
                    "decision_id": str(decision_id),
                    "title": option["title"],
                    "description": option.get("description"),
                    "position": position,
                    "source": option.get("source", "ai_extracted"),
                    "metadata": {"evidence_message_id": str(user_message.id)},
                },
                prefer_representation=True,
                trusted_backend=True,
                prefer="resolution=merge-duplicates",
            )
            persisted_option_ids.append(str(rows[0]["id"]))

        updated_brief = result["brief"]
        updated_brief["option_ids"] = persisted_option_ids
        recommendation = result.get("recommendation")
        phase_status = {
            "clarifying": "exploring",
            "evaluating": "evaluating",
            "completed": "completed",
        }.get(updated_brief["phase"], "exploring")
        await self._record_state_event(
            client,
            decision_id,
            "direction_changed" if result.get("direction_changed") else "conversation_turn",
            updated_brief["revision"],
            {
                "message_id": str(user_message.id),
                "patch": result.get("patch", {}),
                "duplicate_options": result.get("duplicate_options", []),
            },
        )

        if recommendation:
            severities = [risk.get("severity", "moderate") for risk in recommendation.get("key_risks", [])]
            risk_level = "high" if any(level in ("high", "critical") for level in severities) else "moderate" if severities else "unknown"
            existing_evaluations = await self._request(
                client, "GET", "evaluations",
                params={"decision_id": f"eq.{decision_id}", "select": "id", "limit": "1"},
                trusted_backend=True,
            )
            if not existing_evaluations:
                await self._request(
                    client,
                    "POST",
                    "evaluations",
                    json={
                        "decision_id": str(decision_id),
                        "summary": recommendation["summary"],
                        "confidence": None,
                        "risk_level": risk_level,
                        "reasoning": recommendation["rationale"],
                        "checks": {
                            "robustness": recommendation["robustness"],
                            "sensitivity_analysis": recommendation["sensitivity_analysis"],
                            "assumptions": recommendation["assumptions"],
                            "unresolved_uncertainties": recommendation["unresolved_uncertainties"],
                            "key_risks": recommendation.get("key_risks", []),
                            "checks_before_acting": recommendation.get("checks_before_acting", []),
                            "alternate_recommendation": recommendation.get("alternate_recommendation"),
                        },
                    },
                    trusted_backend=True,
                )

        selected = result["selected_action"]
        if selected["action"] == "ask_clarification":
            stats = profile.action_stats.setdefault(selected["category"], PolicyActionStats())
            stats.asked += 1
            await self._request(
                client,
                "POST",
                "clarification_events",
                params={"on_conflict": "user_id,message_id,action_category"},
                json={
                    "user_id": str(self.user.id),
                    "decision_id": str(decision_id),
                    "message_id": str(user_message.id),
                    "action_category": selected["category"],
                    "selected_question": selected.get("question"),
                    "context": {"utility": selected["utility"], "state_revision": updated_brief["revision"]},
                },
                trusted_backend=True,
                prefer="resolution=ignore-duplicates",
            )
        await self._request(
            client,
            "PATCH",
            "decisions",
            params={"id": f"eq.{decision_id}", "user_id": f"eq.{self.user.id}"},
            json={
                "decision_brief": updated_brief,
                "status": phase_status,
                **({"recommendation": recommendation} if recommendation else {}),
            },
            trusted_backend=True,
        )
        return await self._insert_message(
            client,
            decision_id,
            "assistant",
            result["assistant_reply"],
            trusted_backend=True,
            structured_data={
                "action": selected,
                "duplicate_options": result.get("duplicate_options", []),
                "state_revision": updated_brief["revision"],
                "workflow_error": result.get("recommendation_error"),
            },
        )

    async def _record_state_event(
        self,
        client: httpx.AsyncClient,
        decision_id: UUID,
        event_type: str,
        revision: int,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            client,
            "POST",
            "decision_state_events",
            json={
                "decision_id": str(decision_id),
                "user_id": str(self.user.id),
                "revision": revision,
                "event_type": event_type,
                "payload": payload,
            },
            trusted_backend=True,
        )

    async def create_option(
        self, decision_id: UUID, values: DecisionOptionCreate
    ) -> DecisionOption:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        if any(_same_option(values.title, item.title) for item in decision.options):
            raise HTTPException(status_code=409, detail="A similar option already exists")
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client, "POST", "decision_options",
                json={"decision_id": str(decision_id), "title": values.title, "description": values.description, "position": len(decision.options), "source": "user_provided", "status": "confirmed"},
                prefer_representation=True,
            )
        return DecisionOption.model_validate(rows[0])

    async def update_option(
        self, decision_id: UUID, option_id: UUID, values: DecisionOptionUpdate
    ) -> DecisionOption:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        if any(item.id != option_id and _same_option(values.title, item.title) for item in decision.options):
            raise HTTPException(status_code=409, detail="A similar option already exists")
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(client, "PATCH", "decision_options", params={"id": f"eq.{option_id}", "decision_id": f"eq.{decision_id}"}, json={"title": values.title, "description": values.description}, prefer_representation=True)
        if not rows:
            raise HTTPException(status_code=404, detail="Option not found")
        return DecisionOption.model_validate(rows[0])

    async def delete_option(self, decision_id: UUID, option_id: UUID) -> None:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        if not any(item.id == option_id for item in decision.options):
            raise HTTPException(status_code=404, detail="Option not found")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await self._request(client, "DELETE", "decision_options", params={"id": f"eq.{option_id}", "decision_id": f"eq.{decision_id}"})

    async def review_option(
        self, decision_id: UUID, option_id: UUID, values: DecisionOptionStatusUpdate
    ) -> DecisionOption:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        if not any(item.id == option_id for item in decision.options):
            raise HTTPException(status_code=404, detail="Option not found")
        async with httpx.AsyncClient(timeout=10.0) as client:
            rows = await self._request(
                client, "PATCH", "decision_options",
                params={"id": f"eq.{option_id}", "decision_id": f"eq.{decision_id}"},
                json={"status": values.status}, prefer_representation=True,
            )
        return DecisionOption.model_validate(rows[0])

    async def review_state_item(
        self, decision_id: UUID, values: DecisionStateItemReview
    ) -> DecisionDetail:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        brief = dict(decision.decision_brief)
        items = list(brief.get(values.collection, []))
        item = next((candidate for candidate in items if candidate.get("id") == values.item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Decision Brief item not found")
        item["status"] = values.status
        if values.replacement:
            field = {
                "criteria": "name", "assumptions": "statement", "risks": "title",
            }.get(values.collection, "value")
            item[field] = values.replacement
            item["source"] = "confirmed"
            item["confidence"] = "high"
        brief[values.collection] = items
        brief["revision"] = int(brief.get("revision", 0)) + 1
        brief["phase"] = "clarifying"
        brief["readiness"] = {"score": 0, "enough_to_recommend": False, "blockers": ["Decision Brief changed; reassessment required."]}
        async with httpx.AsyncClient(timeout=10.0) as client:
            await self._request(
                client, "PATCH", "decisions",
                params={"id": f"eq.{decision_id}", "user_id": f"eq.{self.user.id}"},
                json={"decision_brief": brief, "status": "exploring"}, trusted_backend=True,
            )
            await self._record_state_event(client, decision_id, "item_reviewed", brief["revision"], values.model_dump(mode="json"))
        return await self.get(decision_id)

    async def resolve_contradiction(
        self, decision_id: UUID, values: ContradictionResolution
    ) -> DecisionDetail:
        decision = await self.get(decision_id)
        if decision.status == "completed":
            raise HTTPException(status_code=409, detail="Completed decisions cannot be changed")
        brief = dict(decision.decision_brief)
        contradictions = list(brief.get("contradictions", []))
        contradiction = next((item for item in contradictions if item.get("id") == values.contradiction_id), None)
        if not contradiction:
            raise HTTPException(status_code=404, detail="Contradiction not found")
        if values.resolution == "custom" and not values.custom_value:
            raise HTTPException(status_code=422, detail="A custom resolution value is required")
        chosen = {
            "previous": contradiction["previous_value"],
            "new": contradiction["new_value"],
            "custom": values.custom_value,
        }[values.resolution]
        topic = contradiction["topic"]
        current = dict(brief.get(topic) or {})
        current.update({"value": chosen, "source": "confirmed", "confidence": "high", "status": "confirmed"})
        brief[topic] = current
        contradiction["status"] = "resolved"
        contradiction["resolution"] = str(chosen)
        brief["contradictions"] = contradictions
        brief["revision"] = int(brief.get("revision", 0)) + 1
        brief["phase"] = "clarifying"
        brief["readiness"] = {"score": 0, "enough_to_recommend": False, "blockers": ["Contradiction resolved; reassessment required."]}
        async with httpx.AsyncClient(timeout=10.0) as client:
            await self._request(
                client, "PATCH", "decisions",
                params={"id": f"eq.{decision_id}", "user_id": f"eq.{self.user.id}"},
                json={"decision_brief": brief, "status": "exploring"}, trusted_backend=True,
            )
            await self._record_state_event(client, decision_id, "contradiction_resolved", brief["revision"], values.model_dump(mode="json"))
        return await self.get(decision_id)


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
