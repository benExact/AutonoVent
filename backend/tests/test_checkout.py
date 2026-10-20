"""Simulated checkout tests. Fixture rows stay in the isolated database."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.order import Order
from app.models.payment import Payment
from app.orders.service import DeliveryAddress, OrderDraft, OrderLine, create_order

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000031")
RATES = "standard:8500,express:14500"


def _cleanup(database_url: str) -> None:
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


@pytest.fixture(autouse=True)
def _clear_checkout_rows(isolated_database_url: str):
    yield
    _cleanup(isolated_database_url)


def _prepare(monkeypatch, database_url: str, *, enabled: bool = True) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_RATES", RATES)
    monkeypatch.setenv("CHECKOUT_SIMULATION_REGION_EXTRAS", "Western Cape:2000")
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
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES (
                  :priced, 'fixture-checkout', 'Checkout fixture',
                  'Automated test row. Not a commercial product.', NULL, 150000, 'ZAR', true
                )
                """
            ),
            {"priced": PRICED_ID},
        )
    engine.dispose()
    client.cookies.clear()


def _address(region: str = "Gauteng", country: str = "ZA") -> dict:
    return {
        "name": "Fixture Customer",
        "line1": "1 Fixture Street",
        "line2": None,
        "local_area": "Arcadia",
        "city": "Pretoria",
        "region": region,
        "postal_code": "0002",
        "country": country,
    }


def _lines(quantity: int = 1) -> list[dict]:
    return [{"product_id": str(PRICED_ID), "quantity": quantity}]


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
    _replace_cookie("autonovent_csrf", "")
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


def _post(path: str, payload: dict, token: str | None = None):
    headers = {"X-CSRF-Token": token if token is not None else _csrf()}
    return client.post(path, json=payload, headers=headers)


def _order_payload(**overrides) -> dict:
    payload = {
        "idempotency_key": "fixture-checkout-order-01",
        "customer_name": "Fixture Customer",
        "customer_email": "fixture@example.com",
        "customer_phone": "0820000000",
        "delivery": _address(),
        "lines": _lines(),
        "service_code": "standard",
        "expected_shipping_cents": 8500,
        "accept_terms": True,
        "terms_version": "v1.0-draft",
    }
    payload.update(overrides)
    return payload


def test_simulated_quote_uses_configured_test_rates_and_not_shiplogic(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)

    def refuse_client(*args, **kwargs):
        raise AssertionError("ShipLogic HTTP was called")

    monkeypatch.setattr("app.shipping.shiplogic.httpx.Client", refuse_client)
    response = _post("/api/v1/checkout/quotes", {"delivery": _address(), "lines": _lines()})
    assert response.status_code == 200
    body = response.json()
    assert body["simulation"] is True
    assert body["provider"] == "simulated-courier"
    assert "not a ShipLogic price" in body["label"]
    assert body["subtotal_cents"] == 150000
    assert body["lines"][0]["unit_price_cents"] == 150000
    assert body["lines"][0]["price_is_demo"] is False
    assert [(quote["service_code"], quote["shipping_cents"], quote["total_cents"]) for quote in body["quotes"]] == [
        ("standard", 8500, 158500),
        ("express", 14500, 164500),
    ]
    coastal = _post("/api/v1/checkout/quotes", {"delivery": _address("Western Cape"), "lines": _lines()})
    assert coastal.status_code == 200
    assert coastal.json()["quotes"][0]["shipping_cents"] == 10500
    assert coastal.json()["quotes"][0]["quote_reference"] == "sim-standard-10500"


def test_unsupported_delivery_address_is_rejected(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    abroad = _post("/api/v1/checkout/quotes", {"delivery": _address(country="US"), "lines": _lines()})
    assert abroad.status_code == 422
    province = _post("/api/v1/checkout/quotes", {"delivery": _address("Texas"), "lines": _lines()})
    assert province.status_code == 422
    assert client.post("/api/v1/checkout/quotes", json={"delivery": _address(), "lines": _lines()}).status_code == 403


def test_server_rejects_tampered_prices_and_stores_the_database_total(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    tampered_line = _post(
        "/api/v1/checkout/orders",
        {
            "idempotency_key": "fixture-checkout-order-01",
            "customer_name": "Fixture Customer",
            "customer_email": "fixture@example.com",
            "delivery": _address(),
            "lines": [{"product_id": str(PRICED_ID), "quantity": 1, "unit_price_cents": 1}],
            "service_code": "standard",
        },
    )
    assert tampered_line.status_code == 422
    tampered_total = _post("/api/v1/checkout/orders", _order_payload(total_cents=1, payment_status="paid"))
    assert tampered_total.status_code == 422
    tampered_shipping = _post("/api/v1/checkout/orders", _order_payload(expected_shipping_cents=1))
    assert tampered_shipping.status_code == 422
    created = _post("/api/v1/checkout/orders", _order_payload())
    assert created.status_code == 200
    body = created.json()
    assert body["subtotal_cents"] == 150000
    assert body["shipping_cents"] == 8500
    assert body["total_cents"] == 158500
    assert body["payment_status"] == "pending"
    assert body["fulfilment_status"] == "unfulfilled"
    assert body["simulation"] is True
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1
    engine.dispose()


def test_repeated_order_submission_is_idempotent(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    first = _post("/api/v1/checkout/orders", _order_payload())
    second = _post("/api/v1/checkout/orders", _order_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    conflict = _post("/api/v1/checkout/orders", _order_payload(service_code="express", expected_shipping_cents=14500))
    assert conflict.status_code == 409
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1
    engine.dispose()


def _pay(order_id: str, outcome: str, key: str):
    return _post(
        f"/api/v1/checkout/orders/{order_id}/payment",
        {"outcome": outcome, "idempotency_key": key},
    )


def test_simulated_payment_success_failure_cancel_and_replay(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    created = _post("/api/v1/checkout/orders", _order_payload())
    order_id = created.json()["id"]
    failed = _pay(order_id, "failure", "fixture-payment-failure1")
    assert failed.status_code == 200
    assert failed.json()["payment_status"] == "failed"
    assert failed.json()["fulfilment_status"] == "unfulfilled"
    assert failed.json()["payment_provider"] == "simulated"
    assert failed.json()["payment_reference"].startswith("sim-")
    assert failed.json()["payment_provider"] != "payfast"
    assert "not a PayFast payment" in failed.json()["payment_label"]
    replay_failed = _pay(order_id, "failure", "fixture-payment-failure1")
    assert replay_failed.status_code == 200
    assert replay_failed.json()["payment_reference"] == failed.json()["payment_reference"]
    cancelled = _post(
        "/api/v1/checkout/orders",
        _order_payload(idempotency_key="fixture-checkout-order-02"),
    )
    cancel = _pay(cancelled.json()["id"], "cancel", "fixture-payment-cancel001")
    assert cancel.status_code == 200
    assert cancel.json()["payment_status"] == "cancelled"
    assert cancel.json()["payment_status"] != "paid"
    paid = _pay(order_id, "success", "fixture-payment-success1")
    assert paid.status_code == 200
    assert paid.json()["payment_status"] == "paid"
    assert paid.json()["fulfilment_status"] == "unfulfilled"
    assert paid.json()["payment_reference"].startswith("sim-")
    replay_paid = _pay(order_id, "success", "fixture-payment-success1")
    assert replay_paid.json()["payment_reference"] == paid.json()["payment_reference"]
    again = _pay(order_id, "success", "fixture-payment-success2")
    assert again.status_code == 409
    spoofed = _post(
        f"/api/v1/checkout/orders/{order_id}/payment",
        {"outcome": "success", "idempotency_key": "fixture-payment-success3", "paid": True, "amount_cents": 1},
    )
    assert spoofed.status_code == 422
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        order = session.get(Order, uuid.UUID(order_id))
        assert order is not None
        assert order.payment_status == "paid"
        assert order.fulfilment_status == "unfulfilled"
        assert order.shipping_cents == 8500
        assert order.shipping_provider == "simulated-courier"
        assert order.shipping_quote_reference == "sim-standard-8500"
        payments = session.scalars(select(Payment).where(Payment.order_id == order.id)).all()
        assert len(payments) == 2
        assert {payment.status for payment in payments} == {"failed", "paid"}
        assert all(payment.provider == "simulated" for payment in payments)
    engine.dispose()


def test_owner_can_see_a_simulated_order_and_the_public_cannot(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    created = _post("/api/v1/checkout/orders", _order_payload())
    order_id = created.json()["id"]
    _pay(order_id, "success", "fixture-payment-success1")
    assert client.get(f"/api/v1/orders/{order_id}").status_code == 401
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    token = _csrf()
    logged_in = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": token})
    assert logged_in.status_code == 200
    _replace_cookie("autonovent_session", _set_cookie(logged_in, "autonovent_session").split("=", 1)[1].split(";", 1)[0])
    _replace_cookie("autonovent_csrf", _set_cookie(logged_in, "autonovent_csrf").split("=", 1)[1].split(";", 1)[0])
    detail = client.get(f"/api/v1/orders/{order_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["is_simulation"] is True
    assert body["payment_provider"] == "simulated"
    assert body["payment_reference"].startswith("sim-")
    assert body["shipping_cents"] == 8500
    assert body["shipping_provider"] == "simulated-courier"
    assert body["subtotal_cents"] == 150000
    assert body["total_cents"] == 158500
    assert body["delivery_suburb"] == "Arcadia"
    assert body["items"][0]["price_is_demo"] is False
    assert "notification" not in detail.text
    internal = create_engine(isolated_database_url)
    with Session(internal, expire_on_commit=False) as session:
        plain = create_order(
            session,
            OrderDraft(
                idempotency_key="fixture-checkout-internal1",
                customer_name="Fixture Customer",
                customer_email="fixture@example.com",
                delivery=DeliveryAddress(
                    name="Fixture Customer",
                    line1="1 Fixture Street",
                    city="Pretoria",
                    region="Gauteng",
                    postal_code="0002",
                ),
                lines=[OrderLine(product_id=PRICED_ID, quantity=1)],
                shipping_cents=1234,
            ),
        )
        plain_id = plain.id
    internal.dispose()
    hidden = _post(
        f"/api/v1/checkout/orders/{plain_id}/payment",
        {"outcome": "success", "idempotency_key": "fixture-payment-internal1"},
        token=_cookie("autonovent_csrf"),
    )
    assert hidden.status_code == 404


def test_production_and_disabled_simulation_reject_checkout(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url, enabled=False)
    assert _post("/api/v1/checkout/quotes", {"delivery": _address(), "lines": _lines()}).status_code == 404
    assert _post("/api/v1/checkout/orders", _order_payload()).status_code == 404
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("CHECKOUT_SIMULATION_RATES", RATES)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "100000")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("EMAIL_FROM", "Autonovent <orders@example.com>")
    get_settings.cache_clear()
    assert client.get("/api/v1/checkout/status").json()["simulation_enabled"] is False
    assert _post("/api/v1/checkout/orders", _order_payload()).status_code == 404
    get_settings.cache_clear()


def test_demo_price_is_snapshotted_without_changing_the_product(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "100000")
    get_settings.cache_clear()
    unpriced_id = uuid.UUID("00000000-0000-4000-8000-000000000032")
    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES
                  (:unpriced, 'fixture-unpriced', 'Unpriced fixture', 'Automated test row. Not a commercial product.', NULL, NULL, 'ZAR', true),
                  (:inactive, 'fixture-inactive', 'Inactive fixture', 'Automated test row. Not a commercial product.', NULL, NULL, 'ZAR', false)
                """
            ),
            {"unpriced": unpriced_id, "inactive": uuid.uuid4()},
        )
    engine.dispose()

    listed = client.get("/api/v1/products")
    assert listed.status_code == 200
    rows = {item["slug"]: item for item in listed.json()["products"]}
    assert "fixture-inactive" not in rows
    assert rows["fixture-unpriced"]["price_is_demo"] is True
    assert rows["fixture-unpriced"]["unit_price_cents"] == 100000
    assert rows["fixture-checkout"]["price_is_demo"] is False
    assert rows["fixture-checkout"]["unit_price_cents"] == 150000

    created = _post(
        "/api/v1/checkout/orders",
        _order_payload(
            idempotency_key="fixture-checkout-demo-price1",
            lines=[{"product_id": str(unpriced_id), "quantity": 2}],
        ),
    )
    assert created.status_code == 200
    assert created.json()["subtotal_cents"] == 200000
    assert created.json()["shipping_cents"] == 8500
    assert created.json()["total_cents"] == 208500
    tampered = _post(
        "/api/v1/checkout/orders",
        _order_payload(
            idempotency_key="fixture-checkout-demo-price2",
            lines=[{"product_id": str(unpriced_id), "quantity": 1, "unit_price_cents": 1}],
        ),
    )
    assert tampered.status_code == 422

    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        stored_price = connection.execute(
            text("SELECT unit_price_cents FROM products WHERE id = :id"),
            {"id": unpriced_id},
        ).scalar()
        snapshot = connection.execute(
            text("SELECT unit_price_cents, price_is_demo FROM order_items WHERE product_id = :id"),
            {"id": unpriced_id},
        ).one()
    engine.dispose()
    assert stored_price is None
    assert snapshot[0] == 100000
    assert snapshot[1] is True


def test_terms_must_be_accepted_and_are_stored_on_the_order(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    missing = _order_payload()
    missing.pop("accept_terms")
    assert _post("/api/v1/checkout/orders", missing).status_code == 422
    assert _post("/api/v1/checkout/orders", _order_payload(accept_terms=False)).status_code == 422
    assert _post("/api/v1/checkout/orders", _order_payload(terms_version="tampered")).status_code == 422
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 0
    engine.dispose()

    first = _post("/api/v1/checkout/orders", _order_payload())
    second = _post("/api/v1/checkout/orders", _order_payload())
    assert first.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        orders = session.scalars(select(Order)).all()
        assert len(orders) == 1
        order = orders[0]
        assert order.terms_accepted is True
        assert order.terms_version == "v1.0-draft"
        assert order.terms_accepted_at is not None
        assert order.terms_accepted_at.tzinfo is not None
        accepted_at = order.terms_accepted_at
        order_id = order.id
    engine.dispose()
    repeated = _post("/api/v1/checkout/orders", _order_payload())
    assert repeated.json()["id"] == str(order_id)
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        stored = session.get(Order, order_id)
        assert stored is not None
        assert stored.terms_accepted_at == accepted_at
    engine.dispose()

    with Session(create_engine(isolated_database_url), expire_on_commit=False) as session:
        plain = create_order(
            session,
            OrderDraft(
                idempotency_key="fixture-checkout-no-terms1",
                customer_name="Fixture Customer",
                customer_email="fixture@example.com",
                customer_phone="0820000000",
                delivery=DeliveryAddress(
                    name="Fixture Customer",
                    line1="1 Fixture Street",
                    line2=None,
                    city="Pretoria",
                    region="Gauteng",
                    postal_code="0002",
                    suburb="Arcadia",
                    country="ZA",
                ),
                lines=[OrderLine(product_id=PRICED_ID, quantity=1)],
                shipping_cents=8500,
                is_simulation=True,
                shipping_provider="simulated-courier",
                shipping_service_code="standard",
                shipping_quote_reference="sim-standard-8500",
            ),
        )
        plain_id = plain.id
    refused = _post(
        f"/api/v1/checkout/orders/{plain_id}/payment",
        {"outcome": "success", "idempotency_key": "fixture-payment-no-terms1"},
    )
    assert refused.status_code == 422
    detail = client.get("/api/v1/orders/" + first.json()["id"])
    assert detail.status_code == 401
