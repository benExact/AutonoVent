"""Customer notification tests stay in the isolated database and the capture transport."""

import uuid

import pytest
import smtplib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.email_notification import EmailNotification
from app.models.order import Order
from app.notifications.service import deliver_pending
from app.notifications.transport import CAPTURED, EmailDeliveryError, clear_captured

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000041")
CUSTOMER_EMAIL = "fixture-customer@example.com"


def _cleanup(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
    engine.dispose()


@pytest.fixture(autouse=True)
def _clear_notification_rows(isolated_database_url: str):
    clear_captured()
    yield
    clear_captured()
    _cleanup(isolated_database_url)


def _prepare(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_TRANSPORT", "capture")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("CHECKOUT_SIMULATION_RATES", "standard:8500")
    monkeypatch.setenv("CHECKOUT_SIMULATION_REGION_EXTRAS", "")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES (:priced, 'fixture-email', 'Email fixture', 'Automated test row. Not a commercial product.', NULL, 150000, 'ZAR', true)
                """
            ),
            {"priced": PRICED_ID},
        )
    engine.dispose()
    client.cookies.clear()


def _csrf() -> str:
    response = client.get("/api/v1/auth/csrf")
    token = response.json()["csrf_token"]
    assert token
    return token


def _post(path: str, payload: dict, token: str | None = None):
    return client.post(path, json=payload, headers={"X-CSRF-Token": token if token is not None else _csrf()})


def _address() -> dict:
    return {
        "name": "Fixture Customer",
        "line1": "1 Fixture Street",
        "line2": None,
        "local_area": "Arcadia",
        "city": "Pretoria",
        "region": "Gauteng",
        "postal_code": "0002",
        "country": "ZA",
    }


def _order(key: str = "fixture-email-order-0001") -> dict:
    response = _post(
        "/api/v1/checkout/orders",
        {
            "idempotency_key": key,
            "customer_name": "Fixture Customer",
            "customer_email": CUSTOMER_EMAIL,
            "customer_phone": "0820000000",
            "delivery": _address(),
            "lines": [{"product_id": str(PRICED_ID), "quantity": 1}],
            "service_code": "standard",
            "expected_shipping_cents": 8500,
            "accept_terms": True,
            "terms_version": "v1.0-draft",
        },
    )
    assert response.status_code == 200
    return response.json()


def _pay(order_id: str, outcome: str, key: str) -> dict:
    response = _post(
        f"/api/v1/checkout/orders/{order_id}/payment",
        {"outcome": outcome, "idempotency_key": key},
    )
    return {"status": response.status_code, "body": response.json()}


def _notifications(database_url: str, order_id: str | None = None) -> list[EmailNotification]:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        statement = select(EmailNotification).order_by(EmailNotification.created_at, EmailNotification.id)
        if order_id is not None:
            statement = statement.where(EmailNotification.order_id == uuid.UUID(order_id))
        rows = list(session.scalars(statement).all())
    engine.dispose()
    return rows


def _owner(database_url: str) -> None:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()


def _login() -> None:
    token = _csrf()
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200


def _fulfil(order_id: str, status: str, *, email: str | None = None):
    payload = {"status": status}
    if email is not None:
        payload["customer_email"] = email
    return client.patch(
        f"/api/v1/orders/{order_id}/fulfilment",
        json=payload,
        headers={"X-CSRF-Token": client.cookies.get("autonovent_csrf") or ""},
    )


def test_paid_simulation_queues_one_confirmation_and_capture_does_not_open_smtp(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)

    def refuse_smtp(*args, **kwargs):
        raise AssertionError("SMTP was opened")

    monkeypatch.setattr(smtplib, "SMTP", refuse_smtp)
    order = _order()
    paid = _pay(order["id"], "success", "fixture-email-payment-0001")
    assert paid["status"] == 200
    assert paid["body"]["payment_status"] == "paid"
    assert paid["body"]["fulfilment_status"] == "unfulfilled"
    replay = _pay(order["id"], "success", "fixture-email-payment-0001")
    assert replay["status"] == 200
    rows = _notifications(isolated_database_url, order["id"])
    assert len(rows) == 1
    assert rows[0].kind == "payment_confirmation"
    assert rows[0].status == "accepted"
    assert rows[0].provider == "capture"
    assert rows[0].recipient == CUSTOMER_EMAIL
    assert rows[0].provider_message_id.startswith("capture-")
    assert order["order_number"] in rows[0].text_body
    assert "payment is confirmed" in rows[0].text_body.lower() or "Payment confirmed" in rows[0].html_body
    assert "R1,500.00" in rows[0].text_body
    assert "R85.00" in rows[0].text_body
    assert "does not book a courier shipment" in rows[0].text_body.lower()
    assert len(CAPTURED) == 1
    assert "<html" in rows[0].html_body.lower()


def test_failed_and_cancelled_payments_do_not_confirm_the_order(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    failed_order = _order("fixture-email-order-failed1")
    failed = _pay(failed_order["id"], "failure", "fixture-email-payment-failed")
    assert failed["body"]["payment_status"] == "failed"
    cancelled_order = _order("fixture-email-order-cancel1")
    cancelled = _pay(cancelled_order["id"], "cancel", "fixture-email-payment-cancel")
    assert cancelled["body"]["payment_status"] == "cancelled"
    rows = _notifications(isolated_database_url)
    assert rows == []
    assert CAPTURED == []


def test_owner_status_change_notifies_the_saved_customer_once(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    order = _order("fixture-email-order-status1")
    anonymous = client.patch(f"/api/v1/orders/{order['id']}/fulfilment", json={"status": "processing"})
    assert anonymous.status_code == 401
    _login()
    updated = _fulfil(order["id"], "processing", email="other@example.com")
    assert updated.status_code == 200
    assert updated.json()["payment_status"] == "pending"
    assert updated.json()["fulfilment_status"] == "processing"
    repeated = _fulfil(order["id"], "processing")
    assert repeated.status_code == 422
    invalid = _fulfil(order["id"], "shipped")
    assert invalid.status_code == 422
    rows = _notifications(isolated_database_url, order["id"])
    assert len(rows) == 1
    assert rows[0].kind == "fulfilment_update"
    assert rows[0].recipient == CUSTOMER_EMAIL
    assert rows[0].status == "accepted"
    assert "preparing your order" in rows[0].text_body.lower()
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        stored = session.get(Order, uuid.UUID(order["id"]))
        assert stored is not None
        assert stored.fulfilment_status == "processing"
        assert stored.payment_status == "pending"
        assert session.scalar(select(func.count()).select_from(EmailNotification)) == 1
    engine.dispose()


def test_provider_failure_keeps_the_order_and_can_be_retried(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    order = _order("fixture-email-order-retry01")

    class Broken:
        name = "smtp"

        def send(self, message):
            del message
            raise EmailDeliveryError("The mailbox refused the test message.")

    monkeypatch.setattr("app.notifications.service.build_transport", lambda settings: Broken())
    paid = _pay(order["id"], "success", "fixture-email-payment-retry1")
    assert paid["status"] == 200
    assert paid["body"]["payment_status"] == "paid"
    failed_rows = _notifications(isolated_database_url, order["id"])
    assert len(failed_rows) == 1
    assert failed_rows[0].status == "failed"
    assert failed_rows[0].attempt_count == 1
    assert CAPTURED == []

    monkeypatch.setattr("app.notifications.service.build_transport", lambda settings: __import__("app.notifications.transport", fromlist=["CaptureTransport"]).CaptureTransport())
    get_settings.cache_clear()
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        assert deliver_pending(session) == 1
        stored = session.get(Order, uuid.UUID(order["id"]))
        assert stored is not None
        assert stored.payment_status == "paid"
        assert stored.fulfilment_status == "unfulfilled"
        rows = list(session.scalars(select(EmailNotification)).all())
    engine.dispose()
    assert len(rows) == 1
    assert rows[0].status == "accepted"
    assert rows[0].attempt_count == 2
    assert len(CAPTURED) == 1
