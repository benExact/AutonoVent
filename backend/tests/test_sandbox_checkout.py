"""Sandbox checkout tests. ShipLogic and PayFast are mocked."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import Settings, get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.email_notification import EmailNotification
from app.models.order import Order
from app.models.payment import Payment
from app.models.shipment import Shipment
from app.payments.payfast import itn_parameter_string, payfast_encode
import hashlib

client = TestClient(app)
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000041")


def _sandbox_env(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_RATES", "")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    monkeypatch.setenv("EMAIL_TRANSPORT", "capture")
    monkeypatch.setenv("COURIER_PROVIDER", "shiplogic")
    monkeypatch.setenv("PAYMENT_PROVIDER", "payfast")
    monkeypatch.setenv("PAYFAST_MODE", "sandbox")
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "10000100")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "sandbox-merchant-key")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", "sandbox-pass")
    monkeypatch.setenv("PAYFAST_NOTIFY_URL", "https://example.test/api/v1/payments/payfast/itn")
    monkeypatch.setenv("PAYFAST_RETURN_URL", "http://127.0.0.1:8765/checkout.html?payment=return")
    monkeypatch.setenv("PAYFAST_CANCEL_URL", "http://127.0.0.1:8765/checkout.html?payment=cancel")
    monkeypatch.setenv("SHIPLOGIC_MODE", "sandbox")
    monkeypatch.setenv("SHIPLOGIC_API_TOKEN", "sandbox-token")
    monkeypatch.setenv("COLLECTION_STREET_ADDRESS", "1 Warehouse Road")
    monkeypatch.setenv("COLLECTION_LOCAL_AREA", "Pretoria Central")
    monkeypatch.setenv("COLLECTION_CITY", "Pretoria")
    monkeypatch.setenv("COLLECTION_ZONE", "Gauteng")
    monkeypatch.setenv("COLLECTION_POSTAL_CODE", "0002")
    monkeypatch.setenv("PACKED_PARCEL_DESCRIPTION", "Packed Autonovent carton")
    monkeypatch.setenv("PACKED_PARCEL_LENGTH_MM", "200")
    monkeypatch.setenv("PACKED_PARCEL_WIDTH_MM", "160")
    monkeypatch.setenv("PACKED_PARCEL_HEIGHT_MM", "50")
    monkeypatch.setenv("PACKED_PARCEL_WEIGHT_GRAMS", "2200")
    get_settings.cache_clear()
    reset_engine()


def _prepare(monkeypatch, database_url: str) -> str:
    _sandbox_env(monkeypatch, database_url)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM products WHERE slug = 'fixture-sandbox'"))
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES (:priced, 'fixture-sandbox', 'Sandbox fixture', 'Automated test row.', NULL, 150000, 'ZAR', true)
                """
            ),
            {"priced": PRICED_ID},
        )
    engine.dispose()
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return token


def _delivery() -> dict:
    return {
        "name": "Sandbox Buyer",
        "line1": "160 Jan Smuts Avenue",
        "line2": "Unit 4",
        "local_area": "Rosebank",
        "city": "Sandton",
        "region": "Gauteng",
        "postal_code": "2196",
        "country": "ZA",
    }


def _install_shiplogic(monkeypatch, price: float = 85.00):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["base"] = kwargs["base_url"]
            seen["token"] = kwargs["api_token"]

        def quote(self, **kwargs):
            from app.shipping.shiplogic import ShippingQuote, ShippingRate

            seen["collection"] = kwargs["collection"]
            seen["delivery"] = kwargs["delivery"]
            seen["parcels"] = kwargs["parcels"]
            seen["declared"] = kwargs.get("declared_value_cents")
            return ShippingQuote(
                rates=[
                    ShippingRate(
                        provider_slug="shiplogic",
                        service_level_code="ECO",
                        service_name="Economy",
                        total_price_cents=int(price * 100),
                        rate_id="rate-2",
                    )
                ]
            )

    monkeypatch.setattr("app.checkout.sandbox.ShipLogicSandboxClient", FakeClient)
    return seen


@pytest.fixture(autouse=True)
def _clear(isolated_database_url: str):
    yield
    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM products WHERE slug = 'fixture-sandbox'"))
    engine.dispose()


def test_signed_in_owner_quote_uses_the_session_cookie_not_the_empty_csrf_body(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    _install_shiplogic(monkeypatch)
    engine = create_engine(isolated_database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
    with Session(engine) as session:
        create_initial_owner(session, "fixture-owner@example.com", "fixture-password-1")
    engine.dispose()
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "fixture-owner@example.com", "password": "fixture-password-1"},
        headers={"X-CSRF-Token": token},
    )
    assert logged_in.status_code == 200
    issued = client.get("/api/v1/auth/csrf")
    assert issued.status_code == 200
    assert issued.json()["csrf_token"] == ""
    session_csrf = client.cookies.get("autonovent_csrf")
    assert session_csrf
    payload = {"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]}
    try:
        blocked = client.post("/api/v1/checkout/quotes", headers={"X-CSRF-Token": ""}, json=payload)
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "This request could not be verified."
        mismatched = client.post("/api/v1/checkout/quotes", headers={"X-CSRF-Token": "not-the-session-token"}, json=payload)
        assert mismatched.status_code == 403
        assert mismatched.json()["detail"] == "This request could not be verified."
        allowed = client.post("/api/v1/checkout/quotes", headers={"X-CSRF-Token": session_csrf}, json=payload)
        assert allowed.status_code == 200
        assert allowed.json()["quotes"][0]["service_code"] == "ECO"
        assert allowed.json()["quotes"][0]["shipping_cents"] == 8500
    finally:
        client.cookies.clear()


def test_quote_uses_configured_address_and_parcel_and_skips_unpriced_rates(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    seen = _install_shiplogic(monkeypatch)
    response = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["simulation"] is False
    assert body["provider"] == "shiplogic"
    assert len(body["quotes"]) == 1
    assert body["quotes"][0]["shipping_cents"] == 8500
    assert body["quotes"][0]["total_cents"] == 158500
    assert body["quotes"][0]["quote_reference"] == "rate-2"
    assert seen["base"] == "https://api.shiplogic.com"
    assert seen["collection"].street_address == "1 Warehouse Road"
    assert seen["delivery"].street_address == "160 Jan Smuts Avenue, Unit 4"
    assert seen["parcels"][0].length_mm == 200
    assert seen["parcels"][0].weight_grams == 2200
    assert seen["declared"] is None
    assert "187" not in str(seen["parcels"][0])


def test_missing_parcel_does_not_call_shiplogic_or_invent_a_price(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    monkeypatch.setenv("PACKED_PARCEL_WEIGHT_GRAMS", "")
    get_settings.cache_clear()

    def refuse(**kwargs):
        raise AssertionError("ShipLogic was called")

    monkeypatch.setattr("app.checkout.sandbox.ShipLogicSandboxClient", refuse)
    response = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert response.status_code == 422
    assert "couldn't load delivery options" in response.json()["detail"]
    assert "8500" not in response.text


def test_shiplogic_error_does_not_fall_back_to_a_simulated_rate(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)

    class Broken:
        def __init__(self, **kwargs):
            pass

        def quote(self, **kwargs):
            from app.shipping.shiplogic import ShipLogicUnavailableError

            raise ShipLogicUnavailableError("down")

    monkeypatch.setattr("app.checkout.sandbox.ShipLogicSandboxClient", Broken)
    response = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert response.status_code == 503
    assert "couldn't load delivery options" in response.json()["detail"]
    assert "simulated" not in response.json()["detail"].lower()


def test_missing_notify_url_rejects_the_order_before_a_delivery_quote(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    monkeypatch.setenv("PAYFAST_NOTIFY_URL", "")
    get_settings.cache_clear()

    def refuse(**kwargs):
        raise AssertionError("ShipLogic was called")

    monkeypatch.setattr("app.checkout.sandbox.ShipLogicSandboxClient", refuse)
    response = client.post(
        "/api/v1/checkout/orders",
        headers={"X-CSRF-Token": token},
        json=_order("ECO", 8500),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Payment is temporarily unavailable."
    assert "notify" not in response.text.lower()


def test_order_rechecks_the_amount_and_payfast_redirect_uses_the_saved_total(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    _install_shiplogic(monkeypatch)
    quoted = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    ).json()["quotes"][0]
    mismatch = client.post(
        "/api/v1/checkout/orders",
        headers={"X-CSRF-Token": token},
        json=_order(quoted["service_code"], 1),
    )
    assert mismatch.status_code == 422
    created = client.post(
        "/api/v1/checkout/orders",
        headers={"X-CSRF-Token": token},
        json=_order(quoted["service_code"], quoted["shipping_cents"]),
    )
    assert created.status_code == 200
    order = created.json()
    current = client.get(f"/api/v1/checkout/orders/{order['id']}")
    assert current.status_code == 200
    assert current.json()["payment_status"] == "pending"
    assert current.json()["order_number"] == order["order_number"]
    assert "customer_email" not in current.json()
    assert order["simulation"] is False
    assert order["total_cents"] == 158500
    assert order["shipping_provider"] == "shiplogic"
    assert order["payment_status"] == "pending"
    redirect = client.post(f"/api/v1/checkout/orders/{order['id']}/payfast", headers={"X-CSRF-Token": token})
    assert redirect.status_code == 200
    body = redirect.json()
    assert body["action"] == "https://sandbox.payfast.co.za/eng/process"
    assert body["fields"]["amount"] == "1585.00"
    assert body["fields"]["m_payment_id"] == order["order_number"]
    assert "passphrase" not in body["fields"]
    assert "sandbox-pass" not in redirect.text
    assert "sandbox-merchant-key" in body["fields"]["merchant_key"]


def test_itn_confirms_payment_once_and_rejects_bad_notifications(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    _install_shiplogic(monkeypatch)
    quoted = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _delivery(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    ).json()["quotes"][0]
    order = client.post(
        "/api/v1/checkout/orders",
        headers={"X-CSRF-Token": token},
        json=_order(quoted["service_code"], quoted["shipping_cents"]),
    ).json()
    monkeypatch.setattr("app.checkout.sandbox.validate_with_payfast", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.checkout.sandbox.ip_is_payfast", lambda value: value == "197.97.145.144")

    def post_itn(amount: str, status: str, reference: str = "1089250", merchant: str = "10000100"):
        pairs = [
            ("m_payment_id", order["order_number"]),
            ("pf_payment_id", reference),
            ("payment_status", status),
            ("amount_gross", amount),
            ("merchant_id", merchant),
        ]
        parameter_string = itn_parameter_string(pairs)
        signed = hashlib.md5((parameter_string + "&passphrase=" + payfast_encode("sandbox-pass")).encode()).hexdigest()
        payload = {name: value for name, value in pairs}
        payload["signature"] = signed
        return client.post("/api/v1/payments/payfast/itn", data=payload, headers={"X-Forwarded-For": "197.97.145.144"})

    monkeypatch.setattr("app.api.v1.checkout.source_ip", lambda *args, **kwargs: "197.97.145.144")
    unsigned = client.post(
        "/api/v1/payments/payfast/itn",
        data={"m_payment_id": order["order_number"], "payment_status": "COMPLETE", "amount_gross": "1585.00", "signature": "not-a-signature"},
    )
    assert unsigned.status_code == 200
    assert unsigned.json()["status"] == "ignored"
    wrong_merchant = post_itn("1585.00", "COMPLETE", reference="1089247", merchant="99999999")
    assert wrong_merchant.status_code == 200
    assert wrong_merchant.json()["status"] == "ignored"
    monkeypatch.setattr("app.checkout.sandbox.validate_with_payfast", lambda *args, **kwargs: False)
    unconfirmed = post_itn("1585.00", "COMPLETE", reference="1089248")
    assert unconfirmed.status_code == 503
    monkeypatch.setattr("app.checkout.sandbox.validate_with_payfast", lambda *args, **kwargs: True)
    unknown = client.post(
        "/api/v1/payments/payfast/itn",
        data={
            "m_payment_id": "AV-DOES-NOT-EXIST",
            "pf_payment_id": "1089246",
            "payment_status": "COMPLETE",
            "amount_gross": "1585.00",
            "merchant_id": "10000100",
            "signature": hashlib.md5(
                (itn_parameter_string([
                    ("m_payment_id", "AV-DOES-NOT-EXIST"),
                    ("pf_payment_id", "1089246"),
                    ("payment_status", "COMPLETE"),
                    ("amount_gross", "1585.00"),
                    ("merchant_id", "10000100"),
                ]) + "&passphrase=" + payfast_encode("sandbox-pass")).encode()
            ).hexdigest(),
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "ignored"
    wrong_amount = post_itn("1.00", "COMPLETE")
    assert wrong_amount.status_code == 200
    assert wrong_amount.json()["status"] == "ignored"
    failed = post_itn("1585.00", "FAILED", reference="1089249")
    assert failed.status_code == 200
    cancelled = post_itn("1585.00", "CANCELLED", reference="1089251")
    assert cancelled.status_code == 200
    pending = post_itn("1585.00", "PENDING", reference="1089252")
    assert pending.status_code == 200
    confirmed = post_itn("1585.00", "COMPLETE", reference="1089253")
    assert confirmed.status_code == 200
    again = post_itn("1585.00", "COMPLETE", reference="1089253")
    assert again.status_code == 200

    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        stored = session.scalar(select(Order).where(Order.order_number == order["order_number"]))
        emails = session.scalars(select(EmailNotification).where(EmailNotification.order_id == stored.id)).all()
        shipments = session.scalars(select(Shipment).where(Shipment.order_id == stored.id)).all()
        assert stored.payment_status == "paid"
        failed_payment = session.scalar(select(Payment).where(Payment.provider_reference == "1089249"))
        assert failed_payment is not None
        assert failed_payment.status == "failed"
        assert stored.total_cents == 158500
        assert stored.fulfilment_status == "unfulfilled"
        assert len(emails) == 1
        assert "does not book a courier shipment" in emails[0].text_body.lower()
        assert shipments == []
        paid = session.scalar(select(func.count()).select_from(Payment).where(Payment.status == "paid"))
        assert paid == 1
    engine.dispose()


def test_production_rejects_sandbox_settings(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("EMAIL_FROM", "orders@example.test")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    monkeypatch.setenv("COURIER_PROVIDER", "shiplogic")
    monkeypatch.setenv("PAYMENT_PROVIDER", "payfast")
    monkeypatch.setenv("PAYFAST_MODE", "sandbox")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()


def _order(service_code: str, shipping_cents: int) -> dict:
    return {
        "idempotency_key": uuid.uuid4().hex + uuid.uuid4().hex[:8],
        "customer_name": "Sandbox Buyer",
        "customer_email": "sandbox@example.com",
        "customer_phone": "0820000000",
        "delivery": _delivery(),
        "lines": [{"product_id": str(PRICED_ID), "quantity": 1}],
        "service_code": service_code,
        "expected_shipping_cents": shipping_cents,
        "accept_terms": True,
        "terms_version": "v1.0-draft",
    }
