"""Owner product management. Fixture rows stay in the isolated database."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.audit import ProductAuditEvent
from app.models.order import OrderItem, OrderStatusEvent
from app.orders.service import DeliveryAddress, OrderDraft, OrderLine, create_order

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"
PRODUCT = {
    "name": "Fixture product",
    "slug": "fixture-product",
    "description": "Automated test row. Not a commercial product.",
    "sku": "FIX-1",
    "currency": "ZAR",
    "active": False,
}


def _use_database(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
    engine.dispose()
    client.cookies.clear()


def _owner(database_url: str) -> None:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()


def _cookie(name: str) -> str:
    matches = [cookie.value for cookie in client.cookies.jar if cookie.name == name]
    return matches[-1] if matches else ""


def _replace_cookie(name: str, value: str) -> None:
    jar = client.cookies.jar
    for cookie in list(jar):
        if cookie.name == name:
            jar.clear(cookie.domain, cookie.path, cookie.name)
    if value:
        client.cookies.set(name, value)


def _csrf() -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    token = response.json()["csrf_token"] or _cookie("autonovent_csrf")
    assert token
    _replace_cookie("autonovent_csrf", token)
    return token


def _set_cookie(response, name: str) -> str:
    matches = [value for value in response.headers.get_list("set-cookie") if value.startswith(name + "=")]
    assert matches
    return matches[-1]


def _login() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": _csrf()},
    )
    assert response.status_code == 200
    _replace_cookie("autonovent_session", _set_cookie(response, "autonovent_session").split("=", 1)[1].split(";", 1)[0])
    _replace_cookie("autonovent_csrf", _set_cookie(response, "autonovent_csrf").split("=", 1)[1].split(";", 1)[0])


def _create(body: dict):
    return client.post("/api/v1/admin/products", json=body, headers={"X-CSRF-Token": _cookie("autonovent_csrf")})


def test_product_management_requires_an_owner(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    assert client.get("/api/v1/admin/products").status_code == 401
    assert client.post("/api/v1/admin/products", json=PRODUCT).status_code == 401
    assert client.patch(f"/api/v1/admin/products/{uuid.uuid4()}", json={"name": "Fixture"}).status_code == 401
    assert client.get("/api/v1/admin/readiness").status_code == 401


def test_owner_can_save_several_products_and_the_catalogue_stays_selective(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    blocked = client.post("/api/v1/admin/products", json=PRODUCT)
    assert blocked.status_code == 403
    first = _create(PRODUCT)
    assert first.status_code == 201
    assert first.json()["unit_price_cents"] is None
    assert first.json()["active"] is False
    second = _create(
        {
            "name": "Second fixture",
            "slug": "fixture-product-two",
            "description": "Automated test row. Not a commercial product.",
            "sku": None,
            "unit_price_cents": 2500,
            "currency": "ZAR",
            "active": True,
        }
    )
    assert second.status_code == 201
    listed = client.get("/api/v1/admin/products")
    assert listed.status_code == 200
    assert {item["slug"] for item in listed.json()["products"]} == {"fixture-product", "fixture-product-two"}
    public = client.get("/api/v1/products")
    assert [item["slug"] for item in public.json()["products"]] == ["fixture-product-two"]
    inactive = _create(
        {
            "name": "Inactive priced fixture",
            "slug": "fixture-inactive",
            "unit_price_cents": 2500,
            "currency": "ZAR",
            "active": False,
        }
    )
    assert inactive.status_code == 201
    public_again = client.get("/api/v1/products")
    assert [item["slug"] for item in public_again.json()["products"]] == ["fixture-product-two"]
    unpriced = _create(
        {
            "name": "Active unpriced fixture",
            "slug": "fixture-unpriced",
            "currency": "ZAR",
            "active": True,
        }
    )
    assert unpriced.status_code == 201
    assert unpriced.json()["unit_price_cents"] is None
    assert [item["slug"] for item in client.get("/api/v1/products").json()["products"]] == ["fixture-product-two"]
    duplicate = _create(dict(PRODUCT, sku="FIX-2"))
    assert duplicate.status_code == 409
    reset_engine()
    get_settings.cache_clear()


def test_price_and_field_validation(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    for price in (-1, 1.5, "2500", True):
        response = _create(dict(PRODUCT, slug=f"fixture-{price}", sku=None, unit_price_cents=price))
        assert response.status_code == 422
    assert _create(dict(PRODUCT, slug="Bad Slug", sku=None)).status_code == 422
    assert _create(dict(PRODUCT, currency="USD", sku=None)).status_code == 422
    assert _create(dict(PRODUCT, name="  ", sku=None)).status_code == 422


def test_product_edits_do_not_change_order_snapshots(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    created = _create(
        dict(PRODUCT, unit_price_cents=2500, active=True, sku="FIX-SNAP")
    )
    assert created.status_code == 201
    product_id = uuid.UUID(created.json()["id"])
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(
            session,
            OrderDraft(
                idempotency_key="fixture-product-edit-key",
                customer_name="Fixture Customer",
                customer_email="fixture@example.com",
                delivery=DeliveryAddress(
                    name="Fixture Customer",
                    line1="1 Fixture Street",
                    city="Pretoria",
                    region="Gauteng",
                    postal_code="0002",
                ),
                lines=[OrderLine(product_id=product_id, quantity=1)],
                shipping_cents=1234,
            ),
        )
        order_id = order.id
    engine.dispose()
    updated = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"name": "Renamed fixture", "unit_price_cents": 2600, "active": False},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    assert updated.json()["unit_price_cents"] == 2600
    assert client.get("/api/v1/products").json()["products"] == []
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        item = session.scalar(select(OrderItem).where(OrderItem.order_id == order_id))
        assert item is not None
        assert item.unit_price_cents == 2500
        assert item.product_name == "Fixture product"
        assert item.line_total_cents == 2500
    engine.dispose()
    reset_engine()
    get_settings.cache_clear()


def test_readiness_checklist_hides_secrets_and_does_not_invent_details(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    monkeypatch.setenv("SHIPLOGIC_API_TOKEN", "fixture-secret-token")
    monkeypatch.setenv("SHIPLOGIC_MODE", "sandbox")
    monkeypatch.setenv("COURIER_PROVIDER", "")
    monkeypatch.setenv("COLLECTION_STREET_ADDRESS", "1 Fixture Street")
    monkeypatch.setenv("COLLECTION_LOCAL_AREA", "Fixture suburb")
    monkeypatch.setenv("COLLECTION_CITY", "Pretoria")
    monkeypatch.setenv("COLLECTION_ZONE", "Gauteng")
    monkeypatch.setenv("COLLECTION_POSTAL_CODE", "0002")
    monkeypatch.setenv("PACKED_PARCEL_DESCRIPTION", "Fixture packed parcel")
    monkeypatch.setenv("PACKED_PARCEL_LENGTH_MM", "200")
    monkeypatch.setenv("PACKED_PARCEL_WIDTH_MM", "150")
    monkeypatch.setenv("PACKED_PARCEL_HEIGHT_MM", "40")
    monkeypatch.setenv("PACKED_PARCEL_WEIGHT_GRAMS", "2000")
    get_settings.cache_clear()
    report = client.get("/api/v1/admin/readiness")
    assert report.status_code == 200
    body = report.json()
    assert body["checkout_enabled"] is False
    assert "fixture-secret-token" not in report.text
    assert "1 Fixture Street" not in report.text
    items = {item["key"]: item for item in body["items"]}
    assert items["selling_price"]["ready"] is False
    assert items["collection_address"]["ready"] is True
    assert items["packed_parcel"]["ready"] is True
    assert items["shiplogic_provider"]["ready"] is False
    assert items["shiplogic_token"]["ready"] is True
    assert "sandbox token is configured" in items["shiplogic_token"]["detail"]
    assert items["shiplogic_quote"]["ready"] is False
    assert "No successful sandbox rate test" in items["shiplogic_quote"]["detail"]
    assert items["payment"]["ready"] is False
    assert "simulated payment flow" in items["payment"]["detail"]
    assert items["payfast_notification_test"]["ready"] is False
    assert "browser return does not count" in items["payfast_notification_test"]["detail"]
    reset_engine()
    get_settings.cache_clear()


def test_payfast_readiness_reports_a_local_notification_url_without_secrets(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("COURIER_PROVIDER", "shiplogic")
    monkeypatch.setenv("PAYMENT_PROVIDER", "payfast")
    monkeypatch.setenv("PAYFAST_MODE", "sandbox")
    monkeypatch.setenv("SHIPLOGIC_MODE", "sandbox")
    monkeypatch.setenv("SHIPLOGIC_API_TOKEN", "fixture-secret-token")
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "10000100")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "fixture-merchant-key")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", "fixture-passphrase")
    monkeypatch.setenv("PAYFAST_NOTIFY_URL", "https://127.0.0.1/api/v1/payments/payfast/itn")
    monkeypatch.setenv("PAYFAST_RETURN_URL", "http://127.0.0.1:8765/checkout.html?payment=return")
    monkeypatch.setenv("PAYFAST_CANCEL_URL", "http://127.0.0.1:8765/checkout.html?payment=cancel")
    get_settings.cache_clear()
    report = client.get("/api/v1/admin/readiness")
    assert report.status_code == 200
    assert "fixture-secret-token" not in report.text
    assert "fixture-merchant-key" not in report.text
    assert "fixture-passphrase" not in report.text
    items = {item["key"]: item for item in report.json()["items"]}
    assert items["payment"]["ready"] is False
    assert "not reachable from PayFast" in items["payment"]["detail"]
    assert items["payfast_notification_test"]["ready"] is False
    reset_engine()
    get_settings.cache_clear()


def test_product_audit_records_owner_changes_and_stays_private(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    created = client.post("/api/v1/admin/products", json=PRODUCT)
    assert created.status_code == 401
    _login()
    saved = _create(PRODUCT)
    assert saved.status_code == 201
    product_id = saved.json()["id"]
    client.cookies.clear()
    assert client.get(f"/api/v1/admin/products/{product_id}/audit").status_code == 401
    _login()
    history = client.get(f"/api/v1/admin/products/{product_id}/audit")
    assert history.status_code == 200
    created_event = history.json()["events"][0]
    assert created_event["actor"] == EMAIL
    price = next(change for change in created_event["changes"] if change["field"] == "unit_price_cents")
    assert price == {"field": "unit_price_cents", "previous": None, "new": None}
    assert {change["field"] for change in created_event["changes"]} <= {
        "name",
        "slug",
        "description",
        "sku",
        "unit_price_cents",
        "currency",
        "active",
    }
    updated = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"name": "Renamed fixture"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    again = client.get(f"/api/v1/admin/products/{product_id}/audit")
    assert again.status_code == 200
    change = again.json()["events"][1]["changes"]
    assert change == [{"field": "name", "previous": "Fixture product", "new": "Renamed fixture"}]
    conflict = _create(dict(PRODUCT, sku="FIX-OTHER"))
    assert conflict.status_code == 409
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        assert session.scalar(select(func.count()).select_from(ProductAuditEvent)) == 2
        assert session.scalar(select(func.count()).select_from(OrderStatusEvent)) == 0
    engine.dispose()
    assert client.get(f"/api/v1/products/{product_id}/audit").status_code == 404
    reset_engine()
    get_settings.cache_clear()
