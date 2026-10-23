import httpx
import pytest
from pydantic import ValidationError

from app import __version__
from app.config import Settings
from tests.conftest import ORIGIN, TOKEN


async def test_health_reports_components(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["db"] == "ok"
    # The test settings point Ollama at a closed port, so it must be reported as unavailable.
    assert body["providers"]["ollama"]["available"] is False


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},
        {"Authorization": f"Basic {TOKEN}"},
    ],
)
async def test_api_rejects_missing_or_invalid_token(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    client.headers.pop("Authorization")
    for path in ("/api/health", "/api/projects", "/api/providers"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"


async def test_cors_preflight_allows_renderer_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/health",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


async def test_cors_rejects_unknown_origin(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10"])
def test_settings_reject_non_loopback_host(host: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_token=TOKEN, host=host, _env_file=None)


def test_settings_reject_short_token() -> None:
    with pytest.raises(ValidationError):
        Settings(api_token="short", _env_file=None)
