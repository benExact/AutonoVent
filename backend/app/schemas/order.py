"""Private order views. Internal identifiers and secrets stay out of these models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrderItemView(BaseModel):
    product_name: str
    sku: str | None
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class StatusEventView(BaseModel):
    field_name: str
    from_status: str | None
    to_status: str
    actor: str | None
    created_at: datetime


class OrderListItem(BaseModel):
    id: uuid.UUID
    order_number: str
    created_at: datetime
    customer_name: str
    customer_email: str
    fulfilment_status: str
    payment_status: str
    currency: str
    total_cents: int


class OrderListResponse(BaseModel):
    orders: list[OrderListItem]
    total: int
    limit: int
    offset: int


class OrderDetail(OrderListItem):
    customer_phone: str | None
    subtotal_cents: int
    shipping_cents: int
    delivery_name: str | None
    delivery_line1: str | None
    delivery_line2: str | None
    delivery_city: str | None
    delivery_region: str | None
    delivery_postal_code: str | None
    delivery_country: str | None
    payment_reference: str | None
    items: list[OrderItemView]
    status_events: list[StatusEventView]
    allowed_fulfilment_statuses: list[str]


class OrderSummary(BaseModel):
    orders: int
    payment: dict[str, int]
    fulfilment: dict[str, int]


class FulfilmentUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)
