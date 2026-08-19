from fastapi.testclient import TestClient

from novalton_api.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["service"] == "novalton-api"
    assert body["version"]
    assert body["environment"] == "development"
