"""Health endpoints do not require a configured database."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "autonovent-api"}


def test_readiness_without_database(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "The database is not configured."
    reset_engine()
    get_settings.cache_clear()
