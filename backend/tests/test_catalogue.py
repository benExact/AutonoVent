"""Catalogue tests use fixture rows in autonovent_test only."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from tests.local_db import local_database_url

client = TestClient(app)

PUBLIC_FIELDS = {
    "id",
    "slug",
    "name",
    "description",
    "sku",
    "unit_price_cents",
    "currency",
    "active",
    "price_is_demo",
    "image_url",
    "short_description",
    "in_stock",
    "images",
    "specifications",
    "download_enabled",
    "download_label",
    "download_filename",
    "download_size_bytes",
}


def _use_database(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()
    reset_engine()


def test_empty_catalogue(monkeypatch, isolated_database_url: str) -> None:
    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
    engine.dispose()

    _use_database(monkeypatch, isolated_database_url)
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    assert response.json() == {"products": []}
    reset_engine()
    get_settings.cache_clear()


def test_catalogue_returns_only_priced_active_products(monkeypatch, isolated_database_url: str) -> None:
    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
        connection.execute(
            text(
                """
                INSERT INTO products (slug, name, description, sku, unit_price_cents, currency, active)
                VALUES
                  ('fixture-active', 'Catalogue fixture', 'Automated test row. Not a commercial product.', NULL, 1500, 'ZAR', true),
                  ('fixture-inactive', 'Inactive fixture', 'Automated test row. Not a commercial product.', NULL, 1500, 'ZAR', false),
                  ('fixture-unpriced', 'Unpriced fixture', 'Automated test row. Not a commercial product.', NULL, NULL, 'ZAR', true)
                """
            )
        )
    engine.dispose()

    _use_database(monkeypatch, isolated_database_url)
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    body = response.json()
    assert [item["slug"] for item in body["products"]] == ["fixture-active"]
    product = body["products"][0]
    assert set(product) == PUBLIC_FIELDS
    assert product["name"] == "Catalogue fixture"
    assert product["description"] == "Automated test row. Not a commercial product."
    assert product["sku"] is None
    assert product["unit_price_cents"] == 1500
    assert isinstance(product["unit_price_cents"], int)
    assert product["currency"] == "ZAR"
    assert product["active"] is True
    assert product["price_is_demo"] is False
    assert product["image_url"] is None
    assert product["download_enabled"] is False
    assert product["download_filename"] is None

    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
        remaining = connection.execute(text("SELECT count(*) FROM products")).scalar()
    engine.dispose()
    assert remaining == 0
    reset_engine()
    get_settings.cache_clear()


def test_catalogue_when_database_is_unreachable(monkeypatch) -> None:
    url = local_database_url().set(port=59999).update_query_dict({"connect_timeout": "2"})
    _use_database(monkeypatch, url.render_as_string(hide_password=False))
    response = client.get("/api/v1/products")
    assert response.status_code == 503
    assert response.json() == {"detail": "The catalogue is temporarily unavailable."}
    lowered = response.text.lower()
    assert "postgresql" not in lowered
    assert "password" not in lowered
    reset_engine()
    get_settings.cache_clear()


def test_catalogue_without_database_url(monkeypatch) -> None:
    _use_database(monkeypatch, "")
    response = client.get("/api/v1/products")
    assert response.status_code == 503
    assert response.json() == {"detail": "The catalogue is temporarily unavailable."}
    reset_engine()
    get_settings.cache_clear()


def test_orders_are_not_public() -> None:
    response = client.get("/api/v1/orders")
    assert response.status_code == 401
