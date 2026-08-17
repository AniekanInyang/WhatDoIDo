from app.main import app


def test_decision_api_exposes_title_only_update() -> None:
    schema = app.openapi()

    assert "patch" in schema["paths"]["/decisions/{decision_id}/title"]
    assert "patch" not in schema["paths"]["/decisions/{decision_id}"]
    assert "put" not in schema["paths"]["/decisions/{decision_id}"]
    assert "delete" in schema["paths"]["/decisions/{decision_id}"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/trash"]
    assert "post" in schema["paths"]["/decisions/{decision_id}/restore"]
