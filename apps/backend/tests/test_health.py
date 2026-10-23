import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import __version__
from app.config import Settings
from app.main import create_app

TOKEN = "test-token-0123456789abcdef"
ORIGIN = "http://localhost:5173"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(api_token=TOKEN, cors_origins=[ORIGIN], _env_file=None)
    return TestClient(create_app(settings))


def test_health_with_valid_token(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},
        {"Authorization": f"Basic {TOKEN}"},
    ],
)
def test_health_rejects_missing_or_invalid_token(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/health", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_cors_preflight_allows_renderer_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get(
        "/api/health",
        headers={"Origin": "https://evil.example", "Authorization": f"Bearer {TOKEN}"},
    )
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10"])
def test_settings_reject_non_loopback_host(host: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_token=TOKEN, host=host, _env_file=None)


def test_settings_reject_short_token() -> None:
    with pytest.raises(ValidationError):
        Settings(api_token="short", _env_file=None)
