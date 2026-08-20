from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from novalton_api.core.database import get_database
from novalton_api.main import create_app


def test_database_dependency_health_success_preserves_correlation_id() -> None:
    app = create_app()
    database = AsyncMock()
    database.check_connection.return_value = True
    app.dependency_overrides[get_database] = lambda: database

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/dependencies",
            headers={"X-Correlation-ID": "database-health-success"},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "database-health-success"
    assert response.json() == {
        "status": "healthy",
        "dependencies": {"postgres": {"status": "healthy"}},
    }


def test_database_dependency_health_failure_is_sanitized() -> None:
    app = create_app()
    database = AsyncMock()
    database.check_connection.return_value = False
    app.dependency_overrides[get_database] = lambda: database

    with TestClient(app) as client:
        response = client.get("/api/v1/health/dependencies")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["dependencies"] == {"postgres": {"status": "unhealthy"}}
    assert "DATABASE_URL" not in response.text
    assert "postgresql" not in response.text
