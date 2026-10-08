from fastapi.testclient import TestClient

from novalton_api.core.config import get_settings
from novalton_api.main import app


def test_health_endpoint() -> None:
    assert get_settings().environment == "test"
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["service"] == "novalton-api"
    assert body["version"]
    assert body["environment"] == "test"
