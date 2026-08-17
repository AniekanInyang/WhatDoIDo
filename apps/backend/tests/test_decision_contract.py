from app.main import app


def test_decision_api_exposes_title_only_update() -> None:
    schema = app.openapi()

    assert "patch" in schema["paths"]["/decisions/{decision_id}/title"]
    assert "patch" not in schema["paths"]["/decisions/{decision_id}"]
    assert "put" not in schema["paths"]["/decisions/{decision_id}"]
    assert "delete" not in schema["paths"]["/decisions/{decision_id}"]
