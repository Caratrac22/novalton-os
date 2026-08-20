import re

from fastapi.testclient import TestClient

from novalton_api.main import create_app


def test_valid_incoming_correlation_id_is_propagated() -> None:
    correlation_id = "client-request_123"
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id


def test_missing_correlation_id_is_generated() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    correlation_id = response.headers["X-Correlation-ID"]
    assert re.fullmatch(r"req_[0-9a-f]{32}", correlation_id)


def test_invalid_incoming_correlation_id_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Correlation-ID": "invalid correlation id"},
        )

    correlation_id = response.headers["X-Correlation-ID"]
    assert correlation_id != "invalid correlation id"
    assert correlation_id.startswith("req_")
