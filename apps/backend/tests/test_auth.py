from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedUser, get_current_user
from app.main import app


client = TestClient(app)


def test_auth_me_requires_bearer_token() -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_returns_verified_user() -> None:
    user_id = uuid4()

    async def override_current_user() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=user_id,
            email="person@example.com",
            role="authenticated",
            access_token="test-access-token",
        )

    app.dependency_overrides[get_current_user] = override_current_user
    try:
        response = client.get("/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "email": "person@example.com",
        "role": "authenticated",
    }
