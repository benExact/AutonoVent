"""Connectivity checks against an isolated local PostgreSQL database."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from tests.local_db import local_database_url

client = TestClient(app)


def test_isolated_database_has_migrated_tables(isolated_database_url: str) -> None:
    engine = create_engine(isolated_database_url)
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars().all()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    assert revision == "20261109_0019"
    assert tables == [
        "admin_sessions",
        "admin_users",
        "alembic_version",
        "auth_login_attempts",
        "carousel_slides",
        "email_notifications",
        "file_cleanups",
        "order_items",
        "order_status_events",
        "orders",
        "payments",
        "product_audit_events",
        "product_images",
        "product_slug_aliases",
        "product_specifications",
        "products",
        "shipments",
    ]


def test_transaction_commits_and_rolls_back(isolated_database_url: str) -> None:
    engine = create_engine(isolated_database_url)
    with engine.connect() as connection:
        rolled_back = connection.begin()
        connection.execute(
            text("INSERT INTO products (slug, name) VALUES ('txn-probe', 'transaction probe')")
        )
        visible = connection.execute(
            text("SELECT count(*) FROM products WHERE slug = 'txn-probe'")
        ).scalar()
        assert visible == 1
        rolled_back.rollback()

    with engine.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM products")).scalar()
        assert remaining == 0

    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                text("INSERT INTO products (slug, name) VALUES ('txn-probe', 'transaction probe')")
            )

    with Session(engine) as session:
        stored = session.execute(
            text("SELECT count(*) FROM products WHERE slug = 'txn-probe'")
        ).scalar()
        assert stored == 1
        session.execute(text("DELETE FROM product_audit_events WHERE product_id IN (SELECT id FROM products WHERE slug = 'txn-probe')"))
        session.execute(text("DELETE FROM products WHERE slug = 'txn-probe'"))
        session.commit()
        cleared = session.execute(text("SELECT count(*) FROM products")).scalar()
        assert cleared == 0
    engine.dispose()


def test_readiness_when_postgres_is_reachable(monkeypatch, isolated_database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", isolated_database_url)
    get_settings.cache_clear()
    reset_engine()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}
    reset_engine()
    get_settings.cache_clear()


def test_readiness_when_postgres_refuses_connection(monkeypatch) -> None:
    url = local_database_url().set(port=59999).update_query_dict({"connect_timeout": "2"})
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    reset_engine()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not reachable."
    reset_engine()
    get_settings.cache_clear()
