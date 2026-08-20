from fastapi import Query
from fastapi.testclient import TestClient

from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app


def test_application_error_uses_deterministic_envelope() -> None:
    app = create_app()

    @app.get("/test/application-error")
    def raise_application_error() -> None:
        raise ApplicationError("example_error", "Safe public message", status_code=409)

    with TestClient(app) as client:
        response = client.get(
            "/test/application-error",
            headers={"X-Correlation-ID": "error-request"},
        )

    assert response.status_code == 409
    assert response.headers["X-Correlation-ID"] == "error-request"
    assert response.json() == {
        "error": {"code": "example_error", "message": "Safe public message"},
        "correlation_id": "error-request",
    }


def test_not_found_uses_deterministic_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/missing",
            headers={"X-Correlation-ID": "not-found-request"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "http_error", "message": "Not Found"},
        "correlation_id": "not-found-request",
    }


def test_validation_error_does_not_echo_rejected_input() -> None:
    app = create_app()

    @app.get("/test/validated")
    def validated_endpoint(value: int = Query()) -> dict[str, int]:
        return {"value": value}

    rejected_value = "secret-looking-invalid-value"
    with TestClient(app) as client:
        response = client.get(
            "/test/validated",
            params={"value": rejected_value},
            headers={"X-Correlation-ID": "validation-request"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Request validation failed"},
        "correlation_id": "validation-request",
    }
    assert rejected_value not in response.text


def test_unexpected_error_hides_internal_details() -> None:
    app = create_app()

    @app.get("/test/unexpected-error")
    def raise_unexpected_error() -> None:
        raise RuntimeError("internal-secret-value")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/test/unexpected-error",
            headers={"X-Correlation-ID": "unexpected-request"},
        )

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "unexpected-request"
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"},
        "correlation_id": "unexpected-request",
    }
    assert "internal-secret-value" not in response.text
