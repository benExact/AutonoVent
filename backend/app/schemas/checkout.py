"""Public simulated checkout. The browser cannot set prices or payment status."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class CheckoutLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=20)


class CheckoutAddressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=4, max_length=4, pattern=r"^[0-9]{4}$")
    country: str = Field(min_length=2, max_length=2)


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: CheckoutAddressInput
    lines: list[CheckoutLineInput] = Field(min_length=1, max_length=20)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=16, max_length=80)
    customer_name: str = Field(min_length=1, max_length=160)
    customer_email: str = Field(min_length=3, max_length=254)
    customer_phone: str | None = Field(default=None, max_length=40)
    delivery: CheckoutAddressInput
    lines: list[CheckoutLineInput] = Field(min_length=1, max_length=20)
    service_code: str = Field(min_length=1, max_length=32)
    expected_shipping_cents: int | None = Field(default=None, ge=0)


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=16, max_length=80)


class QuotedLineView(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class QuoteOptionView(BaseModel):
    provider: str
    service_code: str
    service_name: str
    shipping_cents: int
    total_cents: int
    quote_reference: str
    label: str


class QuoteResponse(BaseModel):
    simulation: bool
    provider: str
    label: str
    currency: str
    subtotal_cents: int
    lines: list[QuotedLineView]
    quotes: list[QuoteOptionView]


class CheckoutStatus(BaseModel):
    simulation_enabled: bool


class CheckoutOrderView(BaseModel):
    simulation: bool
    label: str
    payment_label: str
    id: uuid.UUID
    order_number: str
    currency: str
    subtotal_cents: int
    shipping_cents: int
    total_cents: int
    payment_status: str
    fulfilment_status: str
    payment_provider: str | None
    payment_reference: str | None
    shipping_provider: str | None
    shipping_service_code: str | None
    shipping_quote_reference: str | None
