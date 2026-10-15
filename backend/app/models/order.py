"""Orders, item snapshots, and status history."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

PAYMENT_STATUSES = ("pending", "paid", "failed", "cancelled")
FULFILMENT_STATUSES = ("unfulfilled", "processing", "shipped", "delivered", "cancelled")
FULFILMENT_TRANSITIONS = {
    "unfulfilled": frozenset({"processing", "cancelled"}),
    "processing": frozenset({"shipped", "cancelled"}),
    "shipped": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal_cents >= 0", name="ck_orders_subtotal_nonnegative"),
        CheckConstraint("shipping_cents >= 0", name="ck_orders_shipping_nonnegative"),
        CheckConstraint("total_cents >= 0", name="ck_orders_total_nonnegative"),
        CheckConstraint("total_cents = subtotal_cents + shipping_cents", name="ck_orders_total_matches_parts"),
        CheckConstraint(
            "payment_status IN ('pending', 'paid', 'failed', 'cancelled')",
            name="ck_orders_payment_status",
        ),
        CheckConstraint(
            "fulfilment_status IN ('unfulfilled', 'processing', 'shipped', 'delivered', 'cancelled')",
            name="ck_orders_fulfilment_status",
        ),
        CheckConstraint(
            "(idempotency_key IS NULL AND idempotency_fingerprint IS NULL) OR (idempotency_key IS NOT NULL AND idempotency_fingerprint IS NOT NULL)",
            name="ck_orders_idempotency_pair",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending", index=True)
    fulfilment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unfulfilled", server_default="unfulfilled", index=True
    )
    delivery_name: Mapped[str | None] = mapped_column(String(160))
    delivery_line1: Mapped[str | None] = mapped_column(String(200))
    delivery_line2: Mapped[str | None] = mapped_column(String(200))
    delivery_city: Mapped[str | None] = mapped_column(String(120))
    delivery_region: Mapped[str | None] = mapped_column(String(120))
    delivery_postal_code: Mapped[str | None] = mapped_column(String(20))
    delivery_country: Mapped[str | None] = mapped_column(String(2))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    status_events: Mapped[list["OrderStatusEvent"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price_cents >= 0", name="ck_order_items_price_nonnegative"),
        CheckConstraint("line_total_cents = quantity * unit_price_cents", name="ck_order_items_line_total"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"))
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusEvent(Base):
    __tablename__ = "order_status_events"
    __table_args__ = (
        CheckConstraint(
            "field_name IN ('payment_status', 'fulfilment_status')",
            name="ck_order_status_events_field",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    order: Mapped[Order] = relationship(back_populates="status_events")
