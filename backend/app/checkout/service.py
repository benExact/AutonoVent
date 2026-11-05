"""Simulated checkout. Prices, delivery amounts, and payment status are decided here."""

import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.order import Order, OrderStatusEvent
from app.models.payment import Payment
from app.models.product import Product
from app.legal import TERMS_VERSION
from app.notifications.service import queue_payment_confirmation, release_notifications
from app.orders.service import (
    DeliveryAddress,
    IdempotencyConflict,
    OrderDraft,
    OrderLine,
    OrderValidationError,
    create_order,
)
from app.shipping.simulated import (
    SIMULATED_LABEL,
    SimulatedConfigurationError,
    SimulatedCourier,
    SimulatedRate,
    canonical_province,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^[0-9+() \-]{6,40}$")
PAYMENT_PROVIDER = "simulated"
PAYMENT_LABEL = "Simulated payment. This is not a PayFast payment."
OUTCOMES = {
    "success": "paid",
    "failure": "failed",
    "cancel": "cancelled",
}


class CheckoutError(Exception):
    """A simulated checkout step could not be completed."""


class CheckoutValidationError(CheckoutError):
    """The checkout request is incomplete or inconsistent."""


class CheckoutConflict(CheckoutError):
    """The same request was repeated with different details, or payment is already complete."""


class CheckoutNotFound(CheckoutError):
    """The order does not exist."""


class CheckoutUnavailable(CheckoutError):
    """A checkout provider could not be reached. No price or payment was invented."""


@dataclass(frozen=True)
class QuotedLine:
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    price_is_demo: bool = False


@dataclass(frozen=True)
class QuoteResult:
    currency: str
    subtotal_cents: int
    lines: list[QuotedLine]
    rates: list[SimulatedRate]
    label: str = SIMULATED_LABEL


@dataclass(frozen=True)
class CheckoutResult:
    order: Order
    payment_provider: str | None
    payment_reference: str | None
    label: str = "Simulated test order"
    payment_label: str = PAYMENT_LABEL


def quote_delivery(
    session: Session,
    settings: Settings,
    *,
    delivery: DeliveryAddress,
    lines: list[OrderLine],
) -> QuoteResult:
    province = _province(delivery)
    priced = _priced_lines(session, settings, lines)
    subtotal = sum(line.line_total_cents for line in priced)
    if _uses_shiplogic_quotes(settings):
        from app.checkout.sandbox import _fresh_rates, quote_label

        rates = _fresh_rates(settings, delivery, province, priced, subtotal)
        return QuoteResult(
            currency="ZAR",
            subtotal_cents=subtotal,
            lines=priced,
            rates=rates,
            label=quote_label(settings),
        )
    rates = _courier(settings).quote(region=province)
    return QuoteResult(currency="ZAR", subtotal_cents=subtotal, lines=priced, rates=rates)


def place_simulated_order(
    session: Session,
    settings: Settings,
    *,
    idempotency_key: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    delivery: DeliveryAddress,
    lines: list[OrderLine],
    service_code: str,
    expected_shipping_cents: int | None,
    accept_terms: bool,
    terms_version: str,
) -> CheckoutResult:
    province = _province(delivery)
    email = _email(customer_email)
    phone = _phone(customer_phone, required=True)
    _require_text(customer_name, "customer name")
    if accept_terms is not True or terms_version.strip() != TERMS_VERSION:
        raise CheckoutValidationError("Accept the current Terms and Conditions before payment.")
    quoted = _priced_lines(session, settings, lines)
    subtotal = sum(line.line_total_cents for line in quoted)
    if _uses_shiplogic_quotes(settings):
        from app.checkout.sandbox import _match_rate

        selected = _match_rate(settings, delivery, province, quoted, subtotal, service_code, expected_shipping_cents)
    else:
        selected = _selected_rate(settings, province, service_code)
        if expected_shipping_cents is not None and expected_shipping_cents != selected.shipping_cents:
            raise CheckoutValidationError("The delivery amount does not match the simulated quote.")
    draft = OrderDraft(
        idempotency_key=idempotency_key,
        customer_name=customer_name,
        customer_email=email,
        customer_phone=phone,
        delivery=DeliveryAddress(
            name=delivery.name,
            line1=delivery.line1,
            line2=delivery.line2,
            city=delivery.city,
            region=province,
            postal_code=delivery.postal_code.strip(),
            suburb=delivery.suburb,
            country="ZA",
        ),
        lines=[
            OrderLine(product_id=item.product_id, quantity=item.quantity, unit_price_cents=item.unit_price_cents)
            for item in quoted
        ],
        shipping_cents=selected.shipping_cents,
        is_simulation=True,
        shipping_provider=selected.provider,
        shipping_service_code=selected.service_code,
        shipping_quote_reference=selected.quote_reference,
        terms_version=TERMS_VERSION,
    )
    try:
        order = create_order(session, draft)
    except IdempotencyConflict as exc:
        raise CheckoutConflict(str(exc)) from None
    except OrderValidationError as exc:
        raise CheckoutValidationError(str(exc)) from None
    del quoted
    return _result(session, order)


def record_simulated_payment(
    session: Session,
    *,
    order_id: uuid.UUID,
    outcome: str,
    idempotency_key: str,
) -> CheckoutResult:
    status = OUTCOMES.get(outcome)
    if status is None:
        raise CheckoutValidationError("Choose a successful, failed, or cancelled simulated payment.")
    key = idempotency_key.strip()
    if len(key) < 16 or len(key) > 80:
        raise CheckoutValidationError("An idempotency key is required.")
    try:
        with _begin(session):
            order = session.get(Order, order_id)
            if order is None or not order.is_simulation:
                raise CheckoutNotFound("The simulated order does not exist.")
            if order.terms_accepted is not True or not order.terms_version or order.terms_accepted_at is None:
                raise CheckoutValidationError("Accept the current Terms and Conditions before payment.")
            existing = session.scalar(select(Payment).where(Payment.idempotency_key == key))
            if existing is not None:
                _replay(existing, order, outcome)
                order_id = order.id
            else:
                if order.payment_status == "paid":
                    raise CheckoutConflict("This simulated order is already paid.")
                previous = order.payment_status
                payment = Payment(
                    order_id=order.id,
                    provider=PAYMENT_PROVIDER,
                    provider_reference=_payment_reference(),
                    idempotency_key=key,
                    status=status,
                    amount_cents=order.total_cents,
                    currency=order.currency,
                    notification={"simulation": True, "outcome": outcome},
                )
                session.add(payment)
                if previous != status:
                    order.payment_status = status
                    session.add(
                        OrderStatusEvent(
                            order_id=order.id,
                            field_name="payment_status",
                            from_status=previous,
                            to_status=status,
                            actor="simulated-payment",
                        )
                    )
                    if status == "paid":
                        queue_payment_confirmation(session, order, get_settings())
                session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Payment).where(Payment.idempotency_key == key))
        order = session.get(Order, order_id)
        if existing is None or order is None:
            raise
        _replay(existing, order, outcome)
    stored = session.get(Order, order_id)
    if stored is None or not stored.is_simulation:
        raise CheckoutNotFound("The simulated order does not exist.")
    if session.in_transaction():
        session.commit()
    release_notifications(session)
    return _result(session, stored)


def _result(session: Session, order: Order) -> CheckoutResult:
    payment = session.scalar(
        select(Payment)
        .where(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(1)
    )
    provider = payment.provider if payment is not None else None
    reference = (payment.provider_reference or None) if payment is not None else None
    return CheckoutResult(order=order, payment_provider=provider, payment_reference=reference)


def _replay(existing: Payment, order: Order, outcome: str) -> None:
    recorded = (existing.notification or {}).get("outcome")
    if existing.order_id != order.id or existing.provider != PAYMENT_PROVIDER or recorded != outcome:
        raise CheckoutConflict("This idempotency key was already used for a different payment.")


def _selected_rate(settings: Settings, province: str, service_code: str) -> SimulatedRate:
    cleaned = service_code.strip()
    for rate in _courier(settings).quote(region=province):
        if rate.service_code == cleaned:
            return rate
    raise CheckoutValidationError("That simulated delivery option is not available.")


def applicable_price(product: Product, settings: Settings) -> tuple[int, bool] | None:
    if not product.active or product.archived_at is not None:
        return None
    if product.unit_price_cents is not None:
        return product.unit_price_cents, False
    if settings.checkout_simulation_active and settings.checkout_simulation_demo_unit_price_cents is not None:
        return settings.checkout_simulation_demo_unit_price_cents, True
    return None


def _priced_lines(session: Session, settings: Settings, lines: list[OrderLine]) -> list[QuotedLine]:
    if not lines:
        raise CheckoutValidationError("An order needs at least one item.")
    priced: list[QuotedLine] = []
    for line in lines:
        if not isinstance(line.quantity, int) or isinstance(line.quantity, bool) or line.quantity <= 0 or line.quantity > 20:
            raise CheckoutValidationError("Quantity must be a positive integer.")
        product = session.get(Product, line.product_id)
        resolved = applicable_price(product, settings) if product is not None else None
        if product is None or resolved is None:
            raise CheckoutValidationError("An item is not available at a confirmed price.")
        unit_price, price_is_demo = resolved
        if unit_price > 2_000_000_000 // line.quantity:
            raise CheckoutValidationError("The line total is too large.")
        priced.append(
            QuotedLine(
                product_id=product.id,
                product_name=product.name,
                quantity=line.quantity,
                unit_price_cents=unit_price,
                line_total_cents=line.quantity * unit_price,
                price_is_demo=price_is_demo,
            )
        )
    return priced


def _uses_shiplogic_quotes(settings: Settings) -> bool:
    from app.checkout.sandbox import shiplogic_quotes_configured

    return settings.checkout_simulation_active and shiplogic_quotes_configured(settings)


def _courier(settings: Settings) -> SimulatedCourier:
    try:
        return SimulatedCourier(
            rates=settings.checkout_simulation_rates,
            region_extras=settings.checkout_simulation_region_extras,
        )
    except SimulatedConfigurationError as exc:
        raise CheckoutValidationError("Simulated delivery rates are not configured.") from exc


def _province(delivery: DeliveryAddress) -> str:
    if delivery.country.strip().upper() != "ZA":
        raise CheckoutValidationError("Delivery is limited to South Africa.")
    _require_text(delivery.name, "delivery name")
    _require_text(delivery.line1, "delivery address")
    _require_text(delivery.suburb, "suburb")
    _require_text(delivery.city, "delivery city")
    postal = delivery.postal_code.strip()
    if not re.fullmatch(r"[0-9]{4}", postal):
        raise CheckoutValidationError("Enter a South African postal code.")
    try:
        return canonical_province(delivery.region)
    except SimulatedConfigurationError as exc:
        raise CheckoutValidationError("Delivery is limited to a South African province.") from exc


def _email(value: str) -> str:
    email = _require_text(value, "customer email").lower()
    if len(email) > 254 or EMAIL_PATTERN.fullmatch(email) is None:
        raise CheckoutValidationError("Enter a valid email address.")
    return email


def _phone(value: str | None, *, required: bool = False) -> str | None:
    if value is None or not value.strip():
        if required:
            raise CheckoutValidationError("A contact number is required.")
        return None
    phone = value.strip()
    if PHONE_PATTERN.fullmatch(phone) is None:
        raise CheckoutValidationError("Enter a phone number using digits and spaces.")
    return phone


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckoutValidationError(f"A {label} is required.")
    return value.strip()


def _payment_reference() -> str:
    return "sim-" + secrets.token_hex(12)


def _begin(session: Session):
    if session.in_transaction():
        return session.begin_nested()
    return session.begin()


def address_from_parts(
    *,
    name: str,
    line1: str,
    city: str,
    region: str,
    postal_code: str,
    line2: str | None,
    suburb: str,
    country: str,
) -> DeliveryAddress:
    return DeliveryAddress(
        name=name,
        line1=line1,
        line2=line2,
        suburb=suburb,
        city=city,
        region=region,
        postal_code=postal_code,
        country=country,
    )
