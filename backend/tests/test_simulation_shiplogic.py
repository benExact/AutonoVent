"""Simulated payment with ShipLogic sandbox rates. The courier client is mocked."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.shipping.shiplogic import ShippingQuote, ShippingRate

client = TestClient(app)
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000051")


def _prepare(monkeypatch, database_url: str) -> str:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("CHECKOUT_SIMULATION_RATES", "standard:8500")
    monkeypatch.setenv("CHECKOUT_SIMULATION_REGION_EXTRAS", "")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    monkeypatch.setenv("COURIER_PROVIDER", "")
    monkeypatch.setenv("PAYMENT_PROVIDER", "")
    monkeypatch.setenv("SHIPLOGIC_MODE", "sandbox")
    monkeypatch.setenv("SHIPLOGIC_API_TOKEN", "sandbox-token")
    monkeypatch.setenv("COLLECTION_STREET_ADDRESS", "87 Piet Rautenbach St")
    monkeypatch.setenv("COLLECTION_LOCAL_AREA", "Rosslyn")
    monkeypatch.setenv("COLLECTION_CITY", "Akasia")
    monkeypatch.setenv("COLLECTION_ZONE", "Gauteng")
    monkeypatch.setenv("COLLECTION_POSTAL_CODE", "0200")
    monkeypatch.setenv("PACKED_PARCEL_DESCRIPTION", "AutonoVent canopy vent")
    monkeypatch.setenv("PACKED_PARCEL_LENGTH_MM", "187")
    monkeypatch.setenv("PACKED_PARCEL_WIDTH_MM", "150")
    monkeypatch.setenv("PACKED_PARCEL_HEIGHT_MM", "41")
    monkeypatch.setenv("PACKED_PARCEL_WEIGHT_GRAMS", "2000")
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM products WHERE slug = 'fixture-sim-ship'"))
        connection.execute(
            text(
                """
                INSERT INTO products (id, slug, name, description, sku, unit_price_cents, currency, active)
                VALUES (:priced, 'fixture-sim-ship', 'Simulation fixture', 'Automated test row.', NULL, 150000, 'ZAR', true)
                """
            ),
            {"priced": PRICED_ID},
        )
    engine.dispose()
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    client.cookies.set("autonovent_csrf", token)
    return token


def _address(postal_code: str = "2196") -> dict:
    return {
        "name": "Fixture Buyer",
        "line1": "4 Arum Avenue",
        "line2": None,
        "local_area": "Morningside Manor",
        "city": "Sandton",
        "region": "Gauteng",
        "postal_code": postal_code,
        "country": "ZA",
    }


def _rate(code: str, name: str, rate_id: str, cents: int) -> ShippingRate:
    return ShippingRate(
        provider_slug="shiplogic",
        service_level_code=code,
        service_name=name,
        total_price_cents=cents,
        rate_id=rate_id,
        collection_cut_off="2026-10-21T14:00:00+02:00",
        delivery_from="2026-10-21T16:00:00+02:00",
        delivery_to="2026-10-22T15:00:00+02:00",
    )


def _install(monkeypatch, responses: list[list[ShippingRate]]):
    seen = []

    class FakeClient:
        def __init__(self, **kwargs):
            seen.append({"base": kwargs["base_url"], "token": kwargs["api_token"]})

        def quote(self, **kwargs):
            seen.append({"delivery": kwargs["delivery"], "declared": kwargs.get("declared_value")})
            rates = responses.pop(0)
            return ShippingQuote(rates=rates)

    monkeypatch.setattr("app.checkout.sandbox.ShipLogicSandboxClient", FakeClient)
    return seen


def _order(service_code: str, cents: int, postal_code: str = "2196") -> dict:
    return {
        "idempotency_key": "fixture-sim-shiplogic-01",
        "customer_name": "Fixture Buyer",
        "customer_email": "buyer@example.com",
        "customer_phone": "0820000000",
        "delivery": _address(postal_code),
        "lines": [{"product_id": str(PRICED_ID), "quantity": 1}],
        "service_code": service_code,
        "expected_shipping_cents": cents,
        "accept_terms": True,
        "terms_version": "v1.0-draft",
    }


def test_simulation_quotes_use_vat_inclusive_shiplogic_rates(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    seen = _install(monkeypatch, [[_rate("LOF", "Local Overnight Flyer", "212573", 8625), _rate("ECO", "Economy", "212570", 9500)]])
    response = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _address(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["simulation"] is True
    assert body["provider"] == "shiplogic"
    assert "product specifications" in body["label"]
    assert "have not been confirmed" in body["label"]
    assert "187" in body["label"]
    assert [(item["service_code"], item["shipping_cents"], item["total_cents"]) for item in body["quotes"]] == [
        ("LOF", 8625, 158625),
        ("ECO", 9500, 159500),
    ]
    assert "VAT-inclusive" in body["quotes"][0]["label"]
    assert body["quotes"][0]["delivery_from"] == "2026-10-21T16:00:00+02:00"
    assert body["quotes"][0]["delivery_to"] == "2026-10-22T15:00:00+02:00"
    assert body["quotes"][0]["total_cents"] == body["subtotal_cents"] + body["quotes"][0]["shipping_cents"]
    assert seen[0]["token"] == "sandbox-token"
    assert seen[1]["declared"] is None
    assert "8500" not in response.text


def test_a_changed_address_requests_a_fresh_quote(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    seen = _install(
        monkeypatch,
        [
            [_rate("ECO", "Economy", "1", 9500)],
            [_rate("ECO", "Economy", "2", 11000)],
        ],
    )
    first = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _address("2196"), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    second = client.post(
        "/api/v1/checkout/quotes",
        headers={"X-CSRF-Token": token},
        json={"delivery": _address("0002"), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert first.json()["quotes"][0]["shipping_cents"] == 9500
    assert second.json()["quotes"][0]["shipping_cents"] == 11000
    assert seen[1]["delivery"].postal_code == "2196"
    assert seen[3]["delivery"].postal_code == "0002"


def test_order_rejects_tampering_and_stores_the_fresh_service_id(monkeypatch, isolated_database_url: str) -> None:
    token = _prepare(monkeypatch, isolated_database_url)
    _install(
        monkeypatch,
        [
            [_rate("ECO", "Economy", "old-id", 9500)],
            [_rate("ECO", "Economy", "fresh-id", 9500)],
            [_rate("ECO", "Economy", "fresh-id", 9500)],
        ],
    )
    tampered = client.post("/api/v1/checkout/orders", headers={"X-CSRF-Token": token}, json=_order("ECO", 1))
    assert tampered.status_code == 422
    assert "does not match" in tampered.json()["detail"]
    missing = client.post("/api/v1/checkout/orders", headers={"X-CSRF-Token": token}, json=_order("LSF", 9500))
    assert missing.status_code == 422
    assert "no longer available" in missing.json()["detail"]
    created = client.post("/api/v1/checkout/orders", headers={"X-CSRF-Token": token}, json=_order("ECO", 9500))
    assert created.status_code == 200
    body = created.json()
    assert body["simulation"] is True
    assert body["shipping_provider"] == "shiplogic"
    assert body["shipping_service_code"] == "ECO"
    assert body["shipping_quote_reference"] == "fresh-id"
    assert body["shipping_cents"] == 9500
    assert body["total_cents"] == 159500
    assert body["payment_status"] == "pending"


def test_unavailable_shiplogic_does_not_fall_back_to_simulated_prices(monkeypatch, isolated_database_url: str) -> None:
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
        json={"delivery": _address(), "lines": [{"product_id": str(PRICED_ID), "quantity": 1}]},
    )
    assert response.status_code == 503
    assert "8500" not in response.text
    assert "simulated" not in response.json()["detail"].lower()
