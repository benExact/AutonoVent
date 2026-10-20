"""Order recording tests use fixture rows in the isolated database only."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.order import Order, OrderItem, OrderStatusEvent
from app.orders.service import (
    DeliveryAddress,
    IdempotencyConflict,
    OrderDraft,
    OrderLine,
    OrderValidationError,
    create_order,
    update_fulfilment_status,
)

client = TestClient(app)
PRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
UNPRICED_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


def _engine(database_url: str):
    return create_engine(database_url)


def _prepare(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_engine()
    engine = _engine(database_url)
    with engine.begin() as connection:
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
                VALUES
                  (:priced, 'fixture-priced', 'Order fixture', 'Automated test row. Not a commercial product.', NULL, 2500, 'ZAR', true),
                  (:unpriced, 'fixture-unpriced', 'Unpriced fixture', 'Automated test row. Not a commercial product.', NULL, NULL, 'ZAR', true)
                """
            ),
            {"priced": PRICED_ID, "unpriced": UNPRICED_ID},
        )
    engine.dispose()


def _draft(
    product_id: uuid.UUID,
    quantity: int = 2,
    shipping_cents: int = 1234,
    key: str = "fixture-idempotency-key",
) -> OrderDraft:
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
        lines=[OrderLine(product_id=product_id, quantity=quantity)],
        shipping_cents=shipping_cents,
    )


def test_order_is_priced_from_the_database_and_an_unavailable_item_rolls_back(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    engine = _engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(session, _draft(PRICED_ID))
        assert order.subtotal_cents == 5000
        assert order.shipping_cents == 1234
        assert order.total_cents == 6234
        assert order.payment_status == "pending"
        item = session.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
        assert item is not None
        assert item.product_name == "Order fixture"
        assert item.unit_price_cents == 2500
        assert item.line_total_cents == 5000
        events = session.scalars(select(OrderStatusEvent).where(OrderStatusEvent.order_id == order.id)).all()
        assert {event.field_name for event in events} == {"payment_status", "fulfilment_status"}
        assert all(event.created_at is not None for event in events)

    with Session(engine, expire_on_commit=False) as session:
        with pytest.raises(OrderValidationError):
            create_order(session, _draft(UNPRICED_ID, quantity=1, key="fixture-idempotency-key-2"))
        assert session.scalar(select(func.count()).select_from(Order)) == 1
    engine.dispose()


def test_repeated_submission_does_not_duplicate_the_order(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    engine = _engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        first = create_order(session, _draft(PRICED_ID))
        second = create_order(session, _draft(PRICED_ID))
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        with pytest.raises(IdempotencyConflict):
            create_order(session, _draft(PRICED_ID, quantity=3))
        assert session.scalar(select(func.count()).select_from(Order)) == 1
    engine.dispose()


def test_fulfilment_history_does_not_mark_payment(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    engine = _engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(session, _draft(PRICED_ID))
        updated = update_fulfilment_status(session, order.id, "processing", "owner")
        assert updated.payment_status == "pending"
        assert updated.fulfilment_status == "processing"
        change = session.scalar(
            select(OrderStatusEvent).where(
                OrderStatusEvent.order_id == order.id,
                OrderStatusEvent.field_name == "fulfilment_status",
                OrderStatusEvent.to_status == "processing",
            )
        )
        assert change is not None
        assert change.from_status == "unfulfilled"
        assert change.actor == "owner"
        assert change.created_at is not None
    engine.dispose()


def test_orders_are_not_public(monkeypatch, isolated_database_url: str) -> None:
    _prepare(monkeypatch, isolated_database_url)
    assert client.get("/api/v1/orders").status_code == 401
    assert client.post("/api/v1/orders", json={"idempotency_key": "fixture-idempotency-key"}).status_code == 405
    reset_engine()
    get_settings.cache_clear()
