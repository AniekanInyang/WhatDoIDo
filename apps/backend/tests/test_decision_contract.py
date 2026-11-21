from app.main import app


def test_decision_api_exposes_title_only_update() -> None:
    schema = app.openapi()

    assert "patch" in schema["paths"]["/decisions/{decision_id}/title"]
    assert "patch" not in schema["paths"]["/decisions/{decision_id}"]
    assert "put" not in schema["paths"]["/decisions/{decision_id}"]
    assert "delete" in schema["paths"]["/decisions/{decision_id}"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/trash"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/restore"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/options"]
    assert "patch" in schema["paths"]["/decisions/{decision_id}/options/{option_id}"]
    assert "delete" in schema["paths"]["/decisions/{decision_id}/options/{option_id}"]
    assert "patch" in schema["paths"]["/decisions/{decision_id}/options/{option_id}/status"]
    assert "patch" in schema["paths"]["/decisions/{decision_id}/brief/items"]
    assert "patch" in schema["paths"]["/decisions/{decision_id}/brief/contradictions"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/workflow/retry"]


def test_create_id_replay_does_not_schedule_another_workflow(monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from uuid import uuid4
    from fastapi import BackgroundTasks, HTTPException
    from app.api.decisions import create_decision
    from app.models.decision import DecisionCreate, DecisionSummary
    now = datetime.now(timezone.utc)
    decision_id = uuid4()
    saved = DecisionSummary(id=decision_id, title="Training", prompt="Choose training", status="exploring",
                            created_at=now, updated_at=now)
    class Store:
        def __init__(self, *args):
            pass
        async def get(self, requested_id):
            assert requested_id == decision_id
            return saved
        async def create_pending(self, values):
            raise AssertionError("An ID replay must not insert another decision")
    monkeypatch.setattr("app.api.decisions.DecisionStore", Store)
    tasks = BackgroundTasks()
    response = asyncio.run(create_decision(DecisionCreate(id=decision_id, prompt="Choose training"), tasks, None, None))
    assert response.id == decision_id
    assert tasks.tasks == []
    with __import__("pytest").raises(HTTPException) as conflict:
        asyncio.run(create_decision(DecisionCreate(id=decision_id, prompt="Different prompt"), tasks, None, None))
    assert conflict.value.status_code == 409
