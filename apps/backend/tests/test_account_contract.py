from app.main import app


def test_account_api_contract() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/account"]
    assert "delete" in paths["/account"]
    assert "patch" in paths["/account/profile"]
    assert "get" in paths["/account/export"]
