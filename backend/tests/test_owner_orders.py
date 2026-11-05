"""Private owner order views. Fixture rows stay in the isolated database."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.order import Order, OrderItem, OrderStatusEvent
from app.models.payment import Payment
from app.orders.service import DeliveryAddress, OrderDraft, OrderLine, create_order

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
FORBIDDEN = {
    "password",
    "password_hash",
    "token_hash",
    "csrf_token_hash",
    "idempotency_key",
    "idempotency_fingerprint",
    "notification",
}


def _use_database(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
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
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES (:priced, 'fixture-owner-order', 'Order fixture', 'Automated test row. Not a commercial product.', 'FIX-1', 2500, 'ZAR', true)
                """
            ),
            {"priced": PRICED_ID},
        )
    engine.dispose()
    client.cookies.clear()


def _owner(database_url: str) -> None:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()


def _draft(key: str, quantity: int = 2) -> OrderDraft:
    return OrderDraft(
        idempotency_key=key,
        customer_name="Fixture Customer",
        customer_email="fixture@example.com",
        customer_phone=None,
        delivery=DeliveryAddress(
            name="Fixture Customer",
            line1="1 Fixture Street",
            city="Pretoria",
            region="Gauteng",
            postal_code="0002",
        ),
        lines=[OrderLine(product_id=PRICED_ID, quantity=quantity)],
        shipping_cents=1234,
    )


def _record(database_url: str, key: str, quantity: int = 2):
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(session, _draft(key, quantity))
        order_id = order.id
    engine.dispose()
    return order_id


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


def _login():
    response = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": _csrf()},
    )
    if response.status_code == 200:
        _replace_cookie("autonovent_session", _set_cookie(response, "autonovent_session").split("=", 1)[1].split(";", 1)[0])
        _replace_cookie("autonovent_csrf", _set_cookie(response, "autonovent_csrf").split("=", 1)[1].split(";", 1)[0])
    return response


def _keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_keys(item))
    return found


def test_private_order_routes_require_an_owner(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    assert client.get("/api/v1/orders").status_code == 401
    assert client.get("/api/v1/orders/summary").status_code == 401
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/orders/{missing}").status_code == 401
    assert client.patch(f"/api/v1/orders/{missing}/fulfilment", json={"status": "processing"}).status_code == 401


def test_owner_sees_an_empty_list_and_summary(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    assert _login().status_code == 200
    listed = client.get("/api/v1/orders")
    assert listed.status_code == 200
    assert listed.json() == {"orders": [], "total": 0, "limit": 20, "offset": 0}
    summary = client.get("/api/v1/orders/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["orders"] == 0
    assert body["payment"]["pending"] == 0
    assert body["payment"]["paid"] == 0
    assert body["fulfilment"]["unfulfilled"] == 0


def test_owner_can_read_order_detail_without_sensitive_fields(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    order_id = _record(isolated_database_url, "fixture-owner-order-key1")
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            Payment(
                order_id=order_id,
                provider="fixture",
                provider_reference="fixture-reference",
                status="pending",
                amount_cents=6234,
                currency="ZAR",
                notification={"card": "must-not-appear"},
            )
        )
        session.commit()
    engine.dispose()
    assert _login().status_code == 200
    response = client.get(f"/api/v1/orders/{order_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["order_number"]
    assert body["customer_name"] == "Fixture Customer"
    assert body["customer_email"] == "fixture@example.com"
    assert body["customer_phone"] is None
    assert body["delivery_line1"] == "1 Fixture Street"
    assert body["items"][0]["product_name"] == "Order fixture"
    assert body["items"][0]["sku"] == "FIX-1"
    assert body["items"][0]["unit_price_cents"] == 2500
    assert body["subtotal_cents"] == 5000
    assert body["shipping_cents"] == 1234
    assert body["total_cents"] == 6234
    assert body["payment_status"] == "pending"
    assert body["payment_reference"] == "fixture-reference"
    assert body["fulfilment_status"] == "unfulfilled"
    assert {event["field_name"] for event in body["status_events"]} == {"payment_status", "fulfilment_status"}
    assert FORBIDDEN.isdisjoint(_keys(body))
    assert "must-not-appear" not in response.text
    reset_engine()
    get_settings.cache_clear()


def test_order_list_is_paginated(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _record(isolated_database_url, "fixture-owner-order-key1", 1)
    _record(isolated_database_url, "fixture-owner-order-key2", 2)
    _record(isolated_database_url, "fixture-owner-order-key3", 3)
    assert _login().status_code == 200
    first = client.get("/api/v1/orders", params={"limit": 2, "offset": 0})
    second = client.get("/api/v1/orders", params={"limit": 2, "offset": 2})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total"] == 3
    assert len(first.json()["orders"]) == 2
    assert len(second.json()["orders"]) == 1
    assert client.get("/api/v1/orders", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/orders", params={"fulfilment_status": "paid"}).status_code == 422


def test_fulfilment_update_requires_csrf_and_keeps_payment_pending(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    order_id = _record(isolated_database_url, "fixture-owner-order-key1")
    assert _login().status_code == 200
    blocked = client.patch(f"/api/v1/orders/{order_id}/fulfilment", json={"status": "processing"})
    assert blocked.status_code == 403
    updated = client.patch(
        f"/api/v1/orders/{order_id}/fulfilment",
        json={"status": "processing"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["fulfilment_status"] == "processing"
    assert body["payment_status"] == "pending"
    change = next(event for event in body["status_events"] if event["to_status"] == "processing")
    assert change["from_status"] == "unfulfilled"
    assert change["actor"] == EMAIL
    assert change["created_at"]
    rejected = client.patch(
        f"/api/v1/orders/{order_id}/fulfilment",
        json={"status": "delivered"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert rejected.status_code == 422
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        stored = session.get(Order, order_id)
        assert stored is not None
        assert stored.fulfilment_status == "processing"
        assert stored.payment_status == "pending"
        assert session.scalar(
            select(func.count()).select_from(OrderStatusEvent).where(OrderStatusEvent.to_status == "delivered")
        ) == 0
    engine.dispose()
    reset_engine()
    get_settings.cache_clear()


def test_order_pdf_matches_the_stored_order_and_stays_private(monkeypatch, isolated_database_url: str) -> None:
    from datetime import datetime, timezone
    from pypdf import PdfReader
    import io

    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    order_id = _record(isolated_database_url, "fixture-owner-order-pdf")
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        stored = session.get(Order, order_id)
        assert stored is not None
        stored.customer_name = "José Möller"
        stored.customer_phone = "+27 82 000 0000"
        stored.delivery_line1 = "12 Long Address Road, " + ("North " * 20) + "Estate"
        stored.shipping_provider = "shiplogic"
        stored.shipping_service_code = "ECO"
        stored.shipping_quote_reference = "rate-fixture"
        stored.is_simulation = False
        session.add(
            OrderItem(
                order_id=order_id,
                product_name="Second fixture",
                sku=None,
                quantity=1,
                unit_price_cents=500,
                line_total_cents=500,
            )
        )
        stored.subtotal_cents = 5500
        stored.total_cents = 6734
        session.add(
            Payment(
                order_id=order_id,
                provider="payfast",
                provider_reference="pf-fixture",
                status="paid",
                amount_cents=6734,
                currency="ZAR",
                created_at=datetime(2026, 10, 22, 16, 5, tzinfo=timezone.utc),
                notification={"secret": "must-not-appear"},
            )
        )
        session.add(
            OrderStatusEvent(
                order_id=order_id,
                field_name="payment_status",
                from_status="pending",
                to_status="paid",
                note="Leave at the gate.",
                created_at=datetime(2026, 10, 22, 16, 6, tzinfo=timezone.utc),
            )
        )
        stored.payment_status = "paid"
        session.commit()
        session.refresh(stored)
        before = (stored.payment_status, stored.fulfilment_status, stored.updated_at, stored.total_cents)
        order_number = stored.order_number
    engine.dispose()
    assert client.get(f"/api/v1/orders/{order_id}/document").status_code == 401
    assert _login().status_code == 200
    response = client.get(f"/api/v1/orders/{order_id}/document")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="Omniprod-Order-{order_number}.pdf"'
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert order_number in text
    assert "José Möller" in text
    assert "Second fixture" in text
    assert "Order fixture" in text
    assert "Economy (ECO)" in text
    assert "R 67,34" in text
    assert "R 55,00" in text
    assert "R 12,34" in text
    assert "pf-fixture" in text
    assert "Leave at the gate." in text
    assert "must-not-appear" not in text
    assert "A separate VAT amount is not recorded." in text
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        stored = session.get(Order, order_id)
        assert stored is not None
        assert (stored.payment_status, stored.fulfilment_status, stored.updated_at, stored.total_cents) == before
    engine.dispose()
    missing = client.get(f"/api/v1/orders/{uuid.uuid4()}/document")
    assert missing.status_code == 404
    reset_engine()
    get_settings.cache_clear()
