from app.main import app


def test_collection_api_contract() -> None:
    paths = app.openapi()["paths"]

    assert {"get", "post"}.issubset(paths["/collections"])
    assert {"patch", "delete"}.issubset(paths["/collections/{collection_id}"])
    assert "put" in paths["/decisions/{decision_id}/collection"]
